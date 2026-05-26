#!/usr/bin/env python3
"""One-shot setup script for echo-ms-explorer.

Run this once after unzipping the app, or any time the .command launcher
fails. It will:

  1. Restore the executable bit on the .command file (Mac)
  2. Check that uv is installed and on PATH
  3. Run `uv sync` to install all Python dependencies
  4. Print clear instructions for next steps

Usage:
    python3 setup.py
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def info(msg: str) -> None:
    print(f"  • {msg}")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


def restore_executable_bits(root: Path) -> None:
    section("1. Restoring file permissions")
    for name in ("echo-ms-explorer.command", "setup.py"):
        target = root / name
        if not target.exists():
            continue
        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ok(f"executable: {name}")


def check_uv(root: Path) -> str | None:
    section("2. Checking uv (Python package manager)")
    # Augment PATH with the common uv install locations
    extra_paths = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.cargo/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    current = os.environ.get("PATH", "")
    augmented = os.pathsep.join(extra_paths + [current])
    uv = shutil.which("uv", path=augmented)
    if uv:
        ok(f"uv found at: {uv}")
        return uv

    fail("uv is not installed.")
    print()
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        print("  Install it with this command in Terminal:")
        print()
        print("    curl -LsSf https://astral.sh/uv/install.sh | sh")
    else:
        print("  Install it with this command in PowerShell:")
        print()
        print('    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
    print()
    print("  Then re-run this script: python3 setup.py")
    return None


def run_uv_sync(uv: str, root: Path) -> bool:
    section("3. Installing dependencies (uv sync)")
    info("This may take a minute on first run…")
    try:
        result = subprocess.run(
            [uv, "sync"],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        fail(f"Could not run uv: {e}")
        return False

    if result.returncode != 0:
        fail("uv sync failed:")
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return False

    ok("All dependencies installed.")
    return True


def print_next_steps(root: Path) -> None:
    section("Setup complete")
    print()
    if sys.platform == "darwin":
        print("  To launch the app, double-click:")
        print(f"    {root / 'echo-ms-explorer.command'}")
        print()
        print("  Or run from Terminal:")
        print(f"    cd '{root}'")
        print("    ./echo-ms-explorer.command")
    elif sys.platform == "win32":
        print("  To launch the app, double-click:")
        print(f"    {root / 'echo-ms-explorer.bat'}")
    else:
        print("  To launch the app, run:")
        print(f"    cd '{root}'")
        print("    uv run python launch.py")
    print()


def main() -> int:
    root = Path(__file__).resolve().parent
    print(f"Setting up echo-ms-explorer in: {root}")

    restore_executable_bits(root)
    uv = check_uv(root)
    if uv is None:
        return 1
    if not run_uv_sync(uv, root):
        return 1
    print_next_steps(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
