#!/usr/bin/env python3
"""One-command deploy of echo-ms-explorer to Hugging Face Spaces.

Usage:
    uv run python scripts/deploy_to_hf.py

What it does:
    1. Asks for a Hugging Face access token if you don't already have one
       cached (paste it once; the cache is reused on future runs).
    2. Creates the Space if it doesn't exist (Docker SDK, public, free CPU).
    3. Uploads the repo contents, swapping in docs/huggingface-space-readme.md
       as the Space's README.md so the HF landing page gets the right
       YAML config.
    4. Prints the live URL.

Tokens come from: https://huggingface.co/settings/tokens
Use a token with the **"Write"** role.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

# Where the script lives — used to find the repo root regardless of CWD
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

SPACE_NAME = "echo-ms-explorer"

# Files / dirs that should never end up on the Space
IGNORE = [
    ".git/*",
    ".venv/*",
    ".pytest_cache/*",
    "__pycache__/*",
    "**/__pycache__/*",
    "*.pyc",
    ".DS_Store",
    "exports/*",
    "**/exports/*",
    ".claude/*",
    ".server*",
    ".server-port*",
    "uv 2.lock",
    "FIXES.md",
    # We upload the HF-specific README separately as README.md, so skip
    # the GitHub README to avoid clobbering HF's YAML frontmatter.
    "README.md",
    # We also don't need the deploy script itself on the Space
    "scripts/*",
]


def ensure_huggingface_hub() -> None:
    """Install huggingface_hub into the active environment if missing."""
    try:
        import huggingface_hub  # noqa: F401
        return
    except ImportError:
        pass

    import subprocess
    print("Installing huggingface_hub (one-time)...")
    # Try uv first (this project's tool of choice), fall back to pip
    for cmd in (
        [sys.executable, "-m", "uv", "pip", "install", "huggingface_hub>=0.24"],
        [sys.executable, "-m", "pip", "install", "huggingface_hub>=0.24"],
    ):
        try:
            subprocess.run(cmd, check=True, cwd=REPO_ROOT)
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print(
        "ERROR: couldn't install huggingface_hub. Run manually:\n"
        "    uv pip install huggingface_hub",
        file=sys.stderr,
    )
    sys.exit(1)


def get_token() -> str:
    """Token resolution order:
    1. HF_TOKEN env var
    2. Cached token at ~/.cache/huggingface/token (huggingface_hub default)
    3. Prompt the user.
    """
    env = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env:
        return env.strip()

    from huggingface_hub import HfFolder
    cached = HfFolder.get_token()
    if cached:
        return cached.strip()

    print()
    print("=" * 70)
    print("Hugging Face access token needed.")
    print()
    print("  1. Open https://huggingface.co/settings/tokens")
    print("  2. Click 'New token' → name it 'deploy' → Role: Write")
    print("  3. Copy the long 'hf_...' string")
    print("  4. Paste it below (it's hidden as you type)")
    print("=" * 70)
    token = getpass.getpass("Token: ").strip()
    if not token:
        print("No token entered, aborting.", file=sys.stderr)
        sys.exit(1)

    # Cache for future runs
    from huggingface_hub import HfFolder as _HF
    _HF.save_token(token)
    print("Token cached at ~/.cache/huggingface/token")
    return token


def main() -> None:
    ensure_huggingface_hub()
    from huggingface_hub import HfApi, create_repo

    token = get_token()
    api = HfApi(token=token)

    try:
        user = api.whoami()
    except Exception as exc:
        print(
            f"ERROR: token didn't authenticate ({exc}).\n"
            "Delete ~/.cache/huggingface/token and re-run to enter a new one.",
            file=sys.stderr,
        )
        sys.exit(1)

    username = user["name"]
    repo_id = f"{username}/{SPACE_NAME}"
    print(f"\nLogged in as: {username}")
    print(f"Target Space: {repo_id}")

    print("\nCreating Space (or reusing existing)...")
    try:
        create_repo(
            repo_id=repo_id,
            token=token,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
        )
    except Exception as exc:
        print(f"WARNING: create_repo: {exc}", file=sys.stderr)

    # Push the Dockerfile + app code
    print(f"\nUploading repo contents from {REPO_ROOT} ...")
    api.upload_folder(
        folder_path=str(REPO_ROOT),
        repo_id=repo_id,
        repo_type="space",
        ignore_patterns=IGNORE,
        commit_message="Deploy echo-ms-explorer",
    )

    # Drop the HF-specific README at the root so the Space landing page
    # picks up the YAML frontmatter (title, emoji, port, SDK, etc.)
    hf_readme = REPO_ROOT / "docs" / "huggingface-space-readme.md"
    if hf_readme.exists():
        print("Uploading HF-side README.md (with YAML frontmatter)...")
        api.upload_file(
            path_or_fileobj=str(hf_readme),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="space",
            commit_message="Set Space landing page",
        )

    url = f"https://huggingface.co/spaces/{repo_id}"
    print()
    print("=" * 70)
    print("Deployed.")
    print(f"  Space:           {url}")
    print(f"  Build progress:  {url}?logs=build")
    print()
    print("The first build takes 3-5 minutes. Watch the Logs tab.")
    print("Once the badge flips to 'Running', the demo is live.")
    print("=" * 70)


if __name__ == "__main__":
    main()
