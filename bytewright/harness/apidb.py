"""Win32 API surface for the emulator (Plan §6 `resolve_api` + the implementations).

Because the backend controls which APIs programs import, we implement a small, auditable
set directly in Python (decision D1) instead of needing a Windows rootfs. Each impl takes
an EmuContext and returns the value for RAX (or None if it stopped the process).

The API surface grows deliberately. Adding an API = add a SIGNATURE entry + an impl.
"""
from __future__ import annotations

# Pseudo-handles returned by GetStdHandle.
STD_INPUT, STD_OUTPUT, STD_ERROR = 0xF0000010, 0xF0000011, 0xF0000012

# Microsoft x64 signatures, for the resolve_api helper tool.
SIGNATURES: dict[str, dict] = {
    "GetStdHandle": {
        "dll": "kernel32.dll",
        "signature": "HANDLE GetStdHandle(DWORD nStdHandle)",
        "arg_registers": ["rcx"], "returns": "rax (HANDLE)",
    },
    "WriteFile": {
        "dll": "kernel32.dll",
        "signature": "BOOL WriteFile(HANDLE hFile, LPCVOID lpBuffer, DWORD nBytes, "
                     "LPDWORD lpWritten, LPOVERLAPPED lpOverlapped)",
        "arg_registers": ["rcx", "rdx", "r8", "r9", "stack+0x20"], "returns": "rax (BOOL)",
    },
    "ReadFile": {
        "dll": "kernel32.dll",
        "signature": "BOOL ReadFile(HANDLE hFile, LPVOID lpBuffer, DWORD nBytes, "
                     "LPDWORD lpRead, LPOVERLAPPED lpOverlapped)",
        "arg_registers": ["rcx", "rdx", "r8", "r9", "stack+0x20"], "returns": "rax (BOOL)",
    },
    "WriteConsoleA": {
        "dll": "kernel32.dll",
        "signature": "BOOL WriteConsoleA(HANDLE hConsoleOutput, const VOID* lpBuffer, "
                     "DWORD nChars, LPDWORD lpWritten, LPVOID lpReserved)",
        "arg_registers": ["rcx", "rdx", "r8", "r9", "stack+0x20"], "returns": "rax (BOOL)",
    },
    "ReadConsoleA": {
        "dll": "kernel32.dll",
        "signature": "BOOL ReadConsoleA(HANDLE hConsoleInput, LPVOID lpBuffer, DWORD nChars, "
                     "LPDWORD lpRead, PVOID pInputControl)",
        "arg_registers": ["rcx", "rdx", "r8", "r9", "stack+0x20"], "returns": "rax (BOOL)",
    },
    "ExitProcess": {
        "dll": "kernel32.dll",
        "signature": "VOID ExitProcess(UINT uExitCode)",
        "arg_registers": ["rcx"], "returns": "(does not return)",
    },
    "CreateFileA": {
        "dll": "kernel32.dll",
        "signature": "HANDLE CreateFileA(LPCSTR lpFileName, DWORD access, DWORD share, "
                     "LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags, HANDLE template)",
        "arg_registers": ["rcx", "rdx", "r8", "r9", "stack+0x20", "stack+0x28", "stack+0x30"],
        "returns": "rax (HANDLE)",
    },
    "CloseHandle": {
        "dll": "kernel32.dll",
        "signature": "BOOL CloseHandle(HANDLE hObject)",
        "arg_registers": ["rcx"], "returns": "rax (BOOL)",
    },
    "GetProcessHeap": {
        "dll": "kernel32.dll", "signature": "HANDLE GetProcessHeap(void)",
        "arg_registers": [], "returns": "rax (HANDLE)",
    },
    "HeapAlloc": {
        "dll": "kernel32.dll",
        "signature": "LPVOID HeapAlloc(HANDLE hHeap, DWORD flags, SIZE_T size)",
        "arg_registers": ["rcx", "rdx", "r8"], "returns": "rax (LPVOID)",
    },
    "GetLastError": {
        "dll": "kernel32.dll", "signature": "DWORD GetLastError(void)",
        "arg_registers": [], "returns": "rax (DWORD)",
    },
    "Sleep": {
        "dll": "kernel32.dll", "signature": "VOID Sleep(DWORD dwMilliseconds)",
        "arg_registers": ["rcx"], "returns": "(void)",
    },
    # --- user32: minimal GUI surface (Plan §6) ---
    "MessageBoxA": {
        "dll": "user32.dll",
        "signature": "int MessageBoxA(HWND hWnd, LPCSTR lpText, LPCSTR lpCaption, UINT uType)",
        "arg_registers": ["rcx", "rdx", "r8", "r9"], "returns": "rax (int; IDOK=1)",
    },
    # --- kernel32 console drawing (positioned/colored text — Plan §6) ---
    "SetConsoleCursorPosition": {
        "dll": "kernel32.dll",
        "signature": "BOOL SetConsoleCursorPosition(HANDLE hConsoleOutput, COORD dwCursorPosition)",
        "arg_registers": ["rcx", "rdx (packed COORD: X=low16, Y=high16)"], "returns": "rax (BOOL)",
    },
    "SetConsoleTextAttribute": {
        "dll": "kernel32.dll",
        "signature": "BOOL SetConsoleTextAttribute(HANDLE hConsoleOutput, WORD wAttributes)",
        "arg_registers": ["rcx", "rdx"], "returns": "rax (BOOL)",
    },
    "FillConsoleOutputCharacterA": {
        "dll": "kernel32.dll",
        "signature": ("BOOL FillConsoleOutputCharacterA(HANDLE h, CHAR c, DWORD nLength, "
                      "COORD dwWriteCoord, LPDWORD lpNumberOfCharsWritten)"),
        "arg_registers": ["rcx", "rdx", "r8", "r9 (packed COORD)", "stack+0x20"],
        "returns": "rax (BOOL)",
    },
}


def resolve_api(name: str) -> dict:
    """The `resolve_api` MCP tool: how to call a Win32 function correctly."""
    sig = SIGNATURES.get(name)
    if not sig:
        return {"name": name, "known": False,
                "note": "not in the v1 API surface; emulator will stub it (returns 0)."}
    return {"name": name, "known": True, "calling_convention": "win64", **sig}


# ---------------------------------------------------------------------------
# Implementations. Each returns the RAX value (or None after ctx.stop()).
# ---------------------------------------------------------------------------
def _signed32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _GetStdHandle(ctx):
    n = _signed32(ctx.arg(1))
    return {-10: STD_INPUT, -11: STD_OUTPUT, -12: STD_ERROR}.get(n, 0)


def _write_common(ctx, n_index):
    h = ctx.arg(1)
    buf = ctx.arg(2)
    n = ctx.arg(n_index) & 0xFFFFFFFF
    written_ptr = ctx.arg(4)
    data = ctx.read_mem(buf, n)
    if h == STD_OUTPUT:
        ctx.stdout.extend(data)
        ctx.console.write_text(data)
    elif h == STD_ERROR:
        ctx.stderr.extend(data)
    elif h in ctx.handles and ctx.handles[h][0] == "file":
        ctx.vfs[ctx.handles[h][1]].extend(data)
    else:
        ctx.stdout.extend(data)  # default: treat unknown handle as stdout
        ctx.console.write_text(data)
    if written_ptr:
        ctx.write_u32(written_ptr, n)
    return 1


def _WriteFile(ctx):
    return _write_common(ctx, 3)


def _WriteConsoleA(ctx):
    return _write_common(ctx, 3)


def _read_common(ctx):
    h = ctx.arg(1)
    buf = ctx.arg(2)
    n = ctx.arg(3) & 0xFFFFFFFF
    read_ptr = ctx.arg(4)
    if h == STD_INPUT or h not in ctx.handles:
        # console cooked mode: a read returns at most one line (through the newline),
        # so a program can read input line by line in an interactive loop.
        avail = ctx.stdin[ctx.stdin_pos:]
        nl = avail.find(b"\n")
        take = min(n, len(avail)) if nl == -1 else min(n, nl + 1)
        chunk = avail[:take]
        ctx.stdin_pos += len(chunk)
    else:
        # reading from a vfs file (rare for v1)
        name = ctx.handles[h][1]
        chunk = bytes(ctx.vfs.get(name, b""))[:n]
    ctx.write_mem(buf, chunk)
    if read_ptr:
        ctx.write_u32(read_ptr, len(chunk))
    return 1


def _ExitProcess(ctx):
    ctx.stop(ctx.arg(1) & 0xFFFFFFFF)
    return None


def _CreateFileA(ctx):
    name = ctx.read_cstr(ctx.arg(1)).decode("latin-1")
    h = ctx.new_handle("file", name)
    ctx.vfs.setdefault(name, bytearray())
    return h


def _CloseHandle(ctx):
    return 1


def _GetProcessHeap(ctx):
    return 0x00500000


def _HeapAlloc(ctx):
    return ctx.alloc(ctx.arg(3) & 0xFFFFFFFF)


def _GetLastError(ctx):
    return 0


def _Sleep(ctx):
    return 0


def _MessageBoxA(ctx):
    text = ctx.read_cstr(ctx.arg(2)).decode("latin-1")
    caption = ctx.read_cstr(ctx.arg(3)).decode("latin-1")
    ctx.dialogs.append({"text": text, "caption": caption, "type": ctx.arg(4) & 0xFFFFFFFF})
    return 1  # IDOK


def _SetConsoleCursorPosition(ctx):
    coord = ctx.arg(2)
    ctx.console.set_cursor(coord & 0xFFFF, (coord >> 16) & 0xFFFF)
    return 1


def _SetConsoleTextAttribute(ctx):
    ctx.console.set_attr(ctx.arg(2) & 0xFFFF)
    return 1


def _FillConsoleOutputCharacterA(ctx):
    ch = chr(ctx.arg(2) & 0xFF)
    count = ctx.arg(3) & 0xFFFFFFFF
    coord = ctx.arg(4)
    ctx.console.fill_char(ch, count, coord & 0xFFFF, (coord >> 16) & 0xFFFF)
    written = ctx.arg(5)
    if written:
        ctx.write_u32(written, count)
    return 1


IMPLS = {
    "GetStdHandle": _GetStdHandle,
    "WriteFile": _WriteFile,
    "WriteConsoleA": _WriteConsoleA,
    "ReadFile": _read_common,
    "ReadConsoleA": _read_common,
    "ExitProcess": _ExitProcess,
    "CreateFileA": _CreateFileA,
    "CloseHandle": _CloseHandle,
    "GetProcessHeap": _GetProcessHeap,
    "HeapAlloc": _HeapAlloc,
    "GetLastError": _GetLastError,
    "Sleep": _Sleep,
    "MessageBoxA": _MessageBoxA,
    "SetConsoleCursorPosition": _SetConsoleCursorPosition,
    "SetConsoleTextAttribute": _SetConsoleTextAttribute,
    "FillConsoleOutputCharacterA": _FillConsoleOutputCharacterA,
}
