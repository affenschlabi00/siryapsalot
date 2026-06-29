"""Phase 1 acceptance: the harness handles known-good, real compiler output.

We compile a minimal (-nostdlib) program with MinGW that uses only the APIs the emulator
implements, then validate / run / trace it. Skipped automatically when MinGW is absent.
"""
import shutil
import subprocess

import pytest

from bytewright import harness

MINGW = shutil.which("x86_64-w64-mingw32-gcc")
pytestmark = pytest.mark.skipif(MINGW is None, reason="MinGW-w64 not installed")

SRC = r'''
#include <windows.h>
void start(void) {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD written;
    const char *msg = "Hello from MinGW!\n";
    WriteFile(h, msg, 18, &written, 0);
    ExitProcess(7);
}
'''


@pytest.fixture(scope="module")
def mingw_exe(tmp_path_factory):
    d = tmp_path_factory.mktemp("mingw")
    c = d / "hello.c"
    c.write_text(SRC)
    exe = d / "hello.exe"
    subprocess.run([MINGW, "-nostdlib", "-nostartfiles", "-e", "start", "-O2",
                    "-o", str(exe), str(c), "-lkernel32"], check=True)
    return str(exe)


def test_validate_compiler_pe(mingw_exe):
    vp = harness.validate_pe(mingw_exe)
    assert vp["ok"] and vp["headers"]["magic"] == "PE32+"


def test_run_compiler_pe(mingw_exe):
    r = harness.run(mingw_exe)
    assert r["stdout"] == "Hello from MinGW!\n"
    assert r["exit_code"] == 7
    assert not r["crashed"]


def test_trace_compiler_pe(mingw_exe):
    t = harness.trace(mingw_exe)
    api = [s["api_call"]["name"] for s in t["steps"] if s["api_call"]]
    assert api == ["GetStdHandle", "WriteFile", "ExitProcess"]
