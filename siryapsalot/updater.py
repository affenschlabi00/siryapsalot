"""Self-update: pull the newest code from the (public) git repo and switch branches.

Powers the "Update" button in the web UI and the `siryapsalot update` command. Works when the
package is run from a git checkout (install with `pip install -e .` from a clone). All git work is
shelled out to the local `git`; the repo is public so no credentials are needed.
"""
from __future__ import annotations

import os
import subprocess


def repo_root() -> str | None:
    """Find the git checkout containing this package (or the current directory)."""
    starts = [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.getcwd()]
    for start in starts:
        d = start
        while True:
            if os.path.isdir(os.path.join(d, ".git")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def available() -> bool:
    return repo_root() is not None


def _git(*args, timeout: int = 120) -> subprocess.CompletedProcess:
    root = repo_root()
    if not root:
        raise RuntimeError("not a git checkout — install with `pip install -e .` from a clone "
                           "to enable updates.")
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError as e:                     # git not installed / not on PATH (common on Windows)
        return subprocess.CompletedProcess(args, 127, stdout="", stderr=f"git not found: {e}")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, stdout="", stderr="git timed out")
    except OSError as e:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(e))


def current_branch() -> str | None:
    r = _git("rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def current_commit() -> str | None:
    r = _git("rev-parse", "--short", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def list_branches() -> list[str]:
    """Branch names on the public remote (read-only; falls back to local branches)."""
    try:
        r = _git("ls-remote", "--heads", "origin", timeout=20)
        names = [ln.split("refs/heads/")[-1] for ln in r.stdout.splitlines() if "refs/heads/" in ln]
        if names:
            return sorted(set(names))
    except Exception:
        pass
    r = _git("branch", "--format=%(refname:short)")
    return sorted(b.strip() for b in r.stdout.splitlines() if b.strip())


def status() -> dict:
    if not available():
        return {"available": False, "reason": "not a git checkout (use `pip install -e .`)"}
    branch = current_branch()
    if branch is None:                                 # .git present but git unusable (not on PATH)
        return {"available": False, "reason": "git not found on PATH"}
    return {"available": True, "branch": branch, "commit": current_commit(),
            "branches": list_branches()}


def update(branch: str | None = None) -> dict:
    """Fetch, optionally switch to `branch`, then fast-forward pull. Returns a result dict."""
    if not available():
        return {"ok": False, "message": "Updates need a git checkout — reinstall with "
                                        "`pip install -e .` from a clone of the repo."}
    f = _git("fetch", "origin")
    if f.returncode != 0:
        return {"ok": False, "message": (f.stderr or "git fetch failed").strip()}

    if branch and branch != current_branch():
        sw = _git("checkout", branch)
        if sw.returncode != 0:
            return {"ok": False, "message": (sw.stderr or f"could not switch to {branch}").strip()}

    br = current_branch()
    pull = _git("pull", "--ff-only", "origin", br)
    ok = pull.returncode == 0
    msg = (pull.stdout + pull.stderr).strip()
    return {"ok": ok, "branch": br, "commit": current_commit(), "message": msg,
            "note": "Restart siryapsalot to load the updated code." if ok else
            "Update failed (local changes? commit/stash them, or pick the right branch)."}
