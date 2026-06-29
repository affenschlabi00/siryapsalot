"""Unicorn-based Windows emulator (decision D1).

Loads a PE, maps memory (null page left unmapped so null derefs fault), points every IAT
slot at a Python-backed API hook, and runs with total deterministic observability:
single-step, full register/memory access, every API call intercepted, replayable. This one
engine powers run / trace / inspect / crash_analysis (Plan §6).
"""
from __future__ import annotations

import lief
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from unicorn import (Uc, UC_ARCH_X86, UC_MODE_64, UcError,
                     UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE,
                     UC_HOOK_MEM_UNMAPPED, UC_PROT_ALL, UC_PROT_READ, UC_PROT_WRITE,
                     UC_PROT_EXEC, UC_MEM_WRITE_UNMAPPED, UC_MEM_READ_UNMAPPED,
                     UC_MEM_FETCH_UNMAPPED)
from unicorn.x86_const import (
    UC_X86_REG_RAX, UC_X86_REG_RBX, UC_X86_REG_RCX, UC_X86_REG_RDX,
    UC_X86_REG_RSI, UC_X86_REG_RDI, UC_X86_REG_RBP, UC_X86_REG_RSP,
    UC_X86_REG_RIP, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_R10,
    UC_X86_REG_R11, UC_X86_REG_R12, UC_X86_REG_R13, UC_X86_REG_R14, UC_X86_REG_R15)

from . import apidb

STACK_BASE, STACK_SIZE = 0x00100000, 0x00200000
HEAP_BASE, HEAP_SIZE = 0x00600000, 0x00400000
HOOK_BASE, HOOK_SIZE = 0x7FFF0000, 0x00001000
SENTINEL = HOOK_BASE            # initial return address -> clean process exit

_GP = {
    "rax": UC_X86_REG_RAX, "rbx": UC_X86_REG_RBX, "rcx": UC_X86_REG_RCX,
    "rdx": UC_X86_REG_RDX, "rsi": UC_X86_REG_RSI, "rdi": UC_X86_REG_RDI,
    "rbp": UC_X86_REG_RBP, "rsp": UC_X86_REG_RSP, "rip": UC_X86_REG_RIP,
    "r8": UC_X86_REG_R8, "r9": UC_X86_REG_R9, "r10": UC_X86_REG_R10,
    "r11": UC_X86_REG_R11, "r12": UC_X86_REG_R12, "r13": UC_X86_REG_R13,
    "r14": UC_X86_REG_R14, "r15": UC_X86_REG_R15,
}


def _align(n, a=0x1000):
    return (n + a - 1) & ~(a - 1)


class VirtualConsole:
    """A screen-buffer model so positioned/colored console programs are observable (Plan §6).

    Plain WriteFile output advances the cursor like a terminal; SetConsoleCursorPosition /
    SetConsoleTextAttribute / FillConsoleOutputCharacter let a program draw at coordinates.
    render() returns the visible screen — what a game self-tests against.
    """

    def __init__(self, w: int = 80, h: int = 25):
        self.w, self.h = w, h
        self.grid = [[" "] * w for _ in range(h)]
        self.attr = [[7] * w for _ in range(h)]
        self.cx = self.cy = 0
        self.cur_attr = 7

    def _scroll(self):
        self.grid.pop(0)
        self.grid.append([" "] * self.w)
        self.attr.pop(0)
        self.attr.append([7] * self.w)
        self.cy = self.h - 1

    def set_cursor(self, x: int, y: int):
        self.cx = max(0, min(x, self.w - 1))
        self.cy = max(0, min(y, self.h - 1))

    def set_attr(self, a: int):
        self.cur_attr = a

    def write_text(self, data: bytes):
        for byte in data:
            ch = chr(byte)
            if ch == "\n":
                self.cx = 0
                self.cy += 1
            elif ch == "\r":
                self.cx = 0
            elif ch == "\t":
                self.cx = min(self.w - 1, (self.cx // 8 + 1) * 8)
            else:
                if self.cy >= self.h:
                    self._scroll()
                self.grid[self.cy][self.cx] = ch
                self.attr[self.cy][self.cx] = self.cur_attr
                self.cx += 1
                if self.cx >= self.w:
                    self.cx = 0
                    self.cy += 1
            if self.cy >= self.h:
                self._scroll()

    def fill_char(self, ch: str, count: int, x: int, y: int):
        for i in range(count):
            px, py = x + i, y
            if 0 <= py < self.h and 0 <= px < self.w:
                self.grid[py][px] = ch

    def render(self) -> str:
        rows = ["".join(r).rstrip() for r in self.grid]
        while rows and rows[-1] == "":
            rows.pop()
        return "\n".join(rows)


class EmuContext:
    """The handle API implementations use to read args, touch memory, and capture I/O."""

    def __init__(self, emu: "Emulator"):
        self.emu = emu
        self.mu = emu.mu
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.stdin = emu.stdin
        self.stdin_pos = 0
        self.vfs: dict[str, bytearray] = {}
        self.handles: dict[int, tuple[str, str]] = {}
        self.dialogs: list[dict] = []          # MessageBox calls (GUI)
        self.console = VirtualConsole()         # screen buffer for positioned drawing
        self._next_handle = 0x100
        self._heap = HEAP_BASE
        self.exit_code: int | None = None

    # argument access (Microsoft x64 calling convention)
    def arg(self, i: int) -> int:
        regs = (UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9)
        if 1 <= i <= 4:
            return self.mu.reg_read(regs[i - 1])
        rsp = self.mu.reg_read(UC_X86_REG_RSP)
        return int.from_bytes(self.mu.mem_read(rsp + 8 * i, 8), "little")

    def read_mem(self, addr: int, n: int) -> bytes:
        return bytes(self.mu.mem_read(addr, n)) if n else b""

    def write_mem(self, addr: int, data: bytes):
        self.mu.mem_write(addr, bytes(data))

    def write_u32(self, addr: int, val: int):
        self.mu.mem_write(addr, (val & 0xFFFFFFFF).to_bytes(4, "little"))

    def read_cstr(self, addr: int, limit: int = 4096) -> bytes:
        out = bytearray()
        while len(out) < limit:
            ch = self.mu.mem_read(addr + len(out), 1)[0]
            if ch == 0:
                break
            out.append(ch)
        return bytes(out)

    def new_handle(self, kind: str, name: str) -> int:
        h = self._next_handle
        self._next_handle += 4
        self.handles[h] = (kind, name)
        return h

    def alloc(self, n: int) -> int:
        addr = self._heap
        self._heap = _align(self._heap + max(n, 1), 16)
        return addr

    def stop(self, code: int):
        self.exit_code = code
        self.mu.emu_stop()


class Emulator:
    def __init__(self, path: str, stdin: bytes = b""):
        self.path = path
        self.stdin = stdin if isinstance(stdin, (bytes, bytearray)) else str(stdin).encode()
        self.bin = lief.parse(path)
        if self.bin is None:
            raise ValueError(f"could not parse PE: {path}")
        oh = self.bin.optional_header
        self.image_base = oh.imagebase
        self.entry = self.image_base + oh.addressof_entrypoint
        self.size_of_image = oh.sizeof_image
        self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        self.md = Cs(CS_ARCH_X86, CS_MODE_64)
        self.hookmap: dict[int, tuple[str, str]] = {}   # hook addr -> (dll, func)
        self.ctx = EmuContext(self)
        self._setup_memory()

    # ---- setup ----------------------------------------------------------
    def _setup_memory(self):
        self.mu.mem_map(self.image_base, _align(self.size_of_image), UC_PROT_ALL)
        for s in self.bin.sections:
            content = bytes(s.content)
            if content:
                self.mu.mem_write(self.image_base + s.virtual_address, content)

        self.mu.mem_map(STACK_BASE, STACK_SIZE, UC_PROT_READ | UC_PROT_WRITE)
        self.mu.mem_map(HEAP_BASE, HEAP_SIZE, UC_PROT_READ | UC_PROT_WRITE)
        self.mu.mem_map(HOOK_BASE, HOOK_SIZE, UC_PROT_READ | UC_PROT_EXEC)
        self.mu.mem_write(HOOK_BASE, b"\xc3" * HOOK_SIZE)  # each hook is a lone `ret`

        # point each IAT slot at a unique hook address
        next_hook = HOOK_BASE + 8
        for imp in self.bin.imports:
            for e in imp.entries:
                hook = next_hook
                next_hook += 8
                self.hookmap[hook] = (imp.name, e.name or f"ord{e.ordinal}")
                self.mu.mem_write(self.image_base + e.iat_address, hook.to_bytes(8, "little"))

        # stack: 16-align then push SENTINEL so a `ret` from entry exits cleanly
        top = (STACK_BASE + STACK_SIZE - 0x1000) & ~0xF
        self.mu.mem_write(top - 8, SENTINEL.to_bytes(8, "little"))
        self.mu.reg_write(UC_X86_REG_RSP, top - 8)
        self.mu.reg_write(UC_X86_REG_RIP, self.entry)

    # ---- helpers --------------------------------------------------------
    def regs(self) -> dict[str, int]:
        return {n: self.mu.reg_read(r) for n, r in _GP.items()}

    def _disasm_at(self, addr: int):
        code = bytes(self.mu.mem_read(addr, 15))
        for ins in self.md.disasm(code, addr):
            return ins.mnemonic, ins.op_str, code[:ins.size]
        return "(bad)", "", code[:1]

    def _dispatch_api(self, hook_addr: int):
        dll, func = self.hookmap[hook_addr]
        impl = apidb.IMPLS.get(func)
        before = [self.ctx.arg(i) for i in range(1, 5)]
        if impl is None:
            ret = 0  # unknown API: stub to 0 so emulation continues
        else:
            ret = impl(self.ctx)
        if self.ctx.exit_code is None and ret is not None:
            self.mu.reg_write(UC_X86_REG_RAX, ret & 0xFFFFFFFFFFFFFFFF)
        return {"name": func, "dll": dll, "args": before, "ret": ret}

    # ---- the one execution engine ---------------------------------------
    def execute(self, max_steps: int = 200_000, record: bool = False,
                stop_step: int | None = None, stop_bp: int | None = None):
        """Run the loaded program. Returns a result dict; `record` enables full tracing."""
        state = {
            "steps": [], "api_calls": [], "instr_count": 0, "crashed": False,
            "fault": None, "ended": None, "snapshot": None, "truncated": False,
        }
        pending = {"step": None}
        prev_regs = {"v": None}
        cur_mem: list = []

        def finalize(now_regs):
            st = pending["step"]
            if st is None:
                return
            if prev_regs["v"] is not None:
                st["reg_deltas"] = {k: f"{prev_regs['v'][k]:#x} -> {now_regs[k]:#x}"
                                    for k in now_regs if prev_regs["v"].get(k) != now_regs[k]}
            st["mem_accesses"] = list(cur_mem)
            state["steps"].append(st)

        def hook_code(mu, address, size, _):
            now = self.regs() if record else None
            if record:
                finalize(now)
            # stop conditions
            if address == SENTINEL:
                state["ended"] = f"ret-to-loader(eax={mu.reg_read(UC_X86_REG_RAX) & 0xFFFFFFFF})"
                if self.ctx.exit_code is None:
                    self.ctx.exit_code = mu.reg_read(UC_X86_REG_RAX) & 0xFFFFFFFF
                mu.emu_stop()
                pending["step"] = None
                return
            if state["instr_count"] >= max_steps:
                state["truncated"] = True
                mu.emu_stop()
                pending["step"] = None
                return

            idx = state["instr_count"]
            state["instr_count"] += 1

            api_info = None
            if address in self.hookmap:
                api_info = self._dispatch_api(address)
                api_info["ret"] = mu.reg_read(UC_X86_REG_RAX)
                state["api_calls"].append(api_info)
                if self.ctx.exit_code is not None:
                    state["ended"] = f"{api_info['name']}({api_info['args'][0]})"

            if record:
                mn, ops, raw = self._disasm_at(address)
                pending["step"] = {
                    "idx": idx, "addr": f"{address:#x}", "mnemonic": mn, "operands": ops,
                    "bytes": raw.hex(), "reg_deltas": {}, "mem_accesses": [],
                    "api_call": ({"name": api_info["name"], "args": api_info["args"],
                                  "ret": api_info["ret"]} if api_info else None),
                }
                prev_regs["v"] = now
                cur_mem.clear()

            if stop_step is not None and idx == stop_step:
                state["snapshot"] = self._snapshot()
                mu.emu_stop()
            if stop_bp is not None and address == stop_bp:
                state["snapshot"] = self._snapshot()
                mu.emu_stop()

        def hook_mem(mu, access, address, size, value, _):
            if record and pending["step"] is not None:
                cur_mem.append({"type": "write" if access == UC_HOOK_MEM_WRITE else "read",
                                "addr": f"{address:#x}", "size": size,
                                "value": f"{value:#x}" if access == UC_HOOK_MEM_WRITE else None})

        def hook_unmapped(mu, access, address, size, value, _):
            kind = {UC_MEM_WRITE_UNMAPPED: "write access violation",
                    UC_MEM_READ_UNMAPPED: "read access violation",
                    UC_MEM_FETCH_UNMAPPED: "execute access violation"}.get(access, "access violation")
            rip = mu.reg_read(UC_X86_REG_RIP)
            mn, ops, raw = self._disasm_at(rip)
            state["crashed"] = True
            state["fault"] = {
                "fault_addr": f"{rip:#x}", "access": kind, "target_addr": f"{address:#x}",
                "fault_instruction": {"mnemonic": mn, "operands": ops, "bytes": raw.hex()},
                "registers": {k: f"{v:#x}" for k, v in self.regs().items()},
            }
            return False  # do not retry -> emulation stops with UcError

        self.mu.hook_add(UC_HOOK_CODE, hook_code)
        if record:
            self.mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, hook_mem)
        self.mu.hook_add(UC_HOOK_MEM_UNMAPPED, hook_unmapped)

        try:
            self.mu.emu_start(self.entry, 0, count=0)
        except UcError as e:
            if not state["crashed"]:
                rip = self.mu.reg_read(UC_X86_REG_RIP)
                mn, ops, raw = self._disasm_at(rip)
                state["crashed"] = True
                state["fault"] = {
                    "fault_addr": f"{rip:#x}", "access": f"cpu error: {e}",
                    "fault_instruction": {"mnemonic": mn, "operands": ops, "bytes": raw.hex()},
                    "registers": {k: f"{v:#x}" for k, v in self.regs().items()},
                }
        if record and pending["step"] is not None:
            finalize(self.regs())

        state["exit_code"] = self.ctx.exit_code
        state["stdout"] = bytes(self.ctx.stdout)
        state["stderr"] = bytes(self.ctx.stderr)
        state["vfs"] = {k: bytes(v) for k, v in self.ctx.vfs.items()}
        state["dialogs"] = list(self.ctx.dialogs)
        state["screen"] = self.ctx.console.render()
        return state

    def _snapshot(self) -> dict:
        rsp = self.mu.reg_read(UC_X86_REG_RSP)
        stack = []
        for i in range(16):
            try:
                val = int.from_bytes(self.mu.mem_read(rsp + i * 8, 8), "little")
                stack.append({"addr": f"{rsp + i * 8:#x}", "value": f"{val:#x}"})
            except UcError:
                break
        return {"registers": {k: f"{v:#x}" for k, v in self.regs().items()}, "stack": stack}
