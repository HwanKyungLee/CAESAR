"""tools/build_vigil_usb.py — Vigil-only source folder for an offline measurement PC (USB).

The measurement PC runs Vigil only, so it gets only what Vigil imports: vigil/** plus the core/,
gui/ and tools/ modules reachable from it (static import closure, function-level imports included),
the data files they read (icons, fonts, tools/channel_map.json, one scenario json), the launcher and
a requirements file with just the modules Vigil needs. Files come from the committed tree (git HEAD),
never from the working copy, and core/_build_version.py is stamped so results written on a PC without
git still carry the commit (core/provenance.py).

Usage:
    python tools/build_vigil_usb.py --out <folder>            # builds, then self-checks
Python installer + wheels + install.bat live next to that folder on the USB (see its README).
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKGS = ("vigil", "core", "gui", "tools")
# Read at run time by modules in the closure (theme fonts, window/splash icons, optimize_params
# channel map loaded at import, residual_compare default scenario) and the Vigil launcher.
DATA = ["icons", "fonts", "tools/channel_map.json",
        "scenarios/Doctor_Scenario_Cold_ROI1_ROI2.json", "Vigil_실행.bat"]


def _git(*args) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def head_files() -> dict:
    """{repo-relative posix path: bytes} for every file in HEAD."""
    tar = tarfile.open(fileobj=io.BytesIO(_git("archive", "--format=tar", "HEAD")))
    return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


def closure(files: dict):
    """(repo .py paths Vigil needs, third-party top-level modules) from vigil/**."""
    def mod_path(mod):
        parts = mod.split(".")
        if parts[0] not in PKGS:
            return None
        base = "/".join(parts)
        for cand in (base + ".py", base + "/__init__.py"):
            if cand in files:
                return cand
        return None

    seen, third = set(), set()
    todo = [p for p in files if p.startswith("vigil/") and p.endswith(".py")]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        pkg = p.rsplit("/", 1)[0].split("/")
        for n in ast.walk(ast.parse(files[p].decode("utf-8-sig"))):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = (pkg[: len(pkg) - n.level + 1] if n.level else [])
                mod = ".".join(base + ([n.module] if n.module else []))
                mods = [mod] + [f"{mod}.{a.name}" for a in n.names]   # "from pkg import submodule"
            for m in mods:
                top = m.split(".")[0]
                if top in PKGS:
                    for k in range(1, len(m.split(".")) + 1):          # parent packages too
                        q = mod_path(".".join(m.split(".")[:k]))
                        if q and q not in seen:
                            todo.append(q)
                elif top and top not in sys.stdlib_module_names:
                    third.add(top)
    return seen, third


def build(out: str) -> list:
    files = head_files()
    py, third = closure(files)
    keep = set(py) | {p for p in files if p.startswith("vigil/")}
    for d in DATA:
        keep |= {p for p in files if p == d or p.startswith(d + "/")}
    for p in sorted(keep):
        dst = os.path.join(out, *p.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(files[p])
    short = _git("rev-parse", "--short", "HEAD").decode().strip()
    with open(os.path.join(out, "core", "_build_version.py"), "w", encoding="utf-8") as fh:
        fh.write('"""빌드 시점에 자동 생성됨 — 손으로 고치지 말 것 (tools/build_vigil_usb.py)."""\n')
        fh.write(f'CODE_VERSION = "g{short}"\n')
    # Pinned lines of requirements.txt for the third-party modules Vigil imports (jsonschema is optional).
    req = [ln for ln in files["requirements.txt"].decode("utf-8").splitlines()
           if ln.split("==")[0].strip().lower() in {t.lower() for t in third}]
    with open(os.path.join(out, "requirements-vigil.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(req) + "\n")
    return sorted(keep)


def check(out: str) -> None:
    """The built folder alone (not this repo) must import Vigil and report the stamped commit."""
    code = ("import sys, os; sys.modules.setdefault('_wmi', None); import vigil.run_vigil, vigil.dashboard.dashboard_window;"
            "import vigil.monitors.conc_monitor, vigil.monitors.r_monitor;"
            "from core.provenance import code_version; import vigil;"
            "assert os.path.abspath(vigil.__file__).startswith(os.path.abspath('.')), vigil.__file__;"
            "print(code_version())")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH="", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", code], cwd=out, env=env, capture_output=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(f"[check] Vigil does not import from {out}:\n{r.stderr[-2000:]}")
    print(f"[check] Vigil imports from the built folder alone, code {r.stdout.strip().splitlines()[-1]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output folder (created; existing files are overwritten)")
    args = ap.parse_args()
    kept = build(args.out)
    print(f"[build] {len(kept)} files -> {args.out}")
    check(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
