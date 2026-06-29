"""Shared x86-64 tables and small helpers used across the backend.

Kept deliberately tiny and data-driven so the trusted floor is easy to audit.
"""
from __future__ import annotations

# Canonical 64-bit GP registers and their sub-registers, for operand classification.
REG64 = ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
         "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
REG32 = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi",
         "r8d", "r9d", "r10d", "r11d", "r12d", "r13d", "r14d", "r15d"]
REG16 = ["ax", "cx", "dx", "bx", "sp", "bp", "si", "di",
         "r8w", "r9w", "r10w", "r11w", "r12w", "r13w", "r14w", "r15w"]
REG8 = ["al", "cl", "dl", "bl", "spl", "bpl", "sil", "dil",
        "r8b", "r9b", "r10b", "r11b", "r12b", "r13b", "r14b", "r15b"]

ALL_REGS = set(REG64 + REG32 + REG16 + REG8 + ["rip"])

# Caller-saved (volatile): freely used by model code for args/scratch.
CALLER_SAVED = {"rax", "rcx", "rdx", "r8", "r9", "r10", "r11"}
# Callee-saved (non-volatile): the pool the register allocator binds %vN to.
# Order matters: lowest churn first. rbx/rsi/rdi/r12-r15 (rbp reserved as frame-ish, skipped).
CALLEE_SAVED_POOL = ["rbx", "rsi", "rdi", "r12", "r13", "r14", "r15"]

# Conditional-branch mnemonics -> the low nibble of the 0F 8x opcode.
JCC = {
    "jo": 0x0, "jno": 0x1, "jb": 0x2, "jc": 0x2, "jnae": 0x2,
    "jae": 0x3, "jnb": 0x3, "jnc": 0x3, "je": 0x4, "jz": 0x4,
    "jne": 0x5, "jnz": 0x5, "jbe": 0x6, "jna": 0x6, "ja": 0x7, "jnbe": 0x7,
    "js": 0x8, "jns": 0x9, "jp": 0xa, "jpe": 0xa, "jnp": 0xb, "jpo": 0xb,
    "jl": 0xc, "jnge": 0xc, "jge": 0xd, "jnl": 0xd,
    "jle": 0xe, "jng": 0xe, "jg": 0xf, "jnle": 0xf,
}
BRANCH_OPS = set(JCC) | {"jmp", "call"}

# Ops the model is forbidden from emitting: the backend owns the stack frame (decision D3).
FORBIDDEN_OPS = {"push", "pop", "pushf", "popf", "pushfq", "popfq",
                 "sub_rsp", "enter", "leave"}

# A conservative whitelist of non-symbolic mnemonics the backend will hand to keystone.
# (Anything here with no symbolic operand is encoded wholesale.) Expanded over time.
ALLOWED_OPS = {
    "mov", "movzx", "movsx", "movsxd", "lea", "xchg",
    "add", "sub", "imul", "mul", "idiv", "div", "inc", "dec", "neg",
    "and", "or", "xor", "not", "shl", "shr", "sar", "sal", "rol", "ror",
    "cmp", "test", "cdq", "cqo", "cwde", "cbw",
    "jmp", "call", "ret", "nop",
    "seto", "setno", "setb", "setae", "sete", "setz", "setne", "setnz",
    "setbe", "seta", "sets", "setns", "setl", "setge", "setle", "setg",
} | set(JCC)


def is_register(tok: str) -> bool:
    return tok.strip().lower() in ALL_REGS


def reg_index(name: str) -> int:
    """Return the 0-15 encoding index for a GP register of any width."""
    n = name.strip().lower()
    for table in (REG64, REG32, REG16, REG8):
        if n in table:
            return table.index(n)
    raise KeyError(f"not a GP register: {name}")
