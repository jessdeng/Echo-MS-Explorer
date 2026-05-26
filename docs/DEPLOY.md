# Deploying the live demo to Hugging Face Spaces

The repo includes everything needed to host a public live demo on
Hugging Face Spaces — a `Dockerfile` and the Space-side README config
(`docs/huggingface-space-readme.md`). This file documents the one-time
setup.

## What you'll get

A public URL like `https://huggingface.co/spaces/<your-hf-username>/echo-ms-explorer`
that anyone can click. The app boots empty; a "Load demo data" button
populates it with synthetic data so reviewers can explore every feature
without uploading anything.

Cold-start time: ~30 s on HF's free CPU tier. After that, the Space stays
warm for a few minutes per visit.

## One-time setup (~5 minutes)

### 1. Create a Hugging Face account
<https://huggingface.co/join> — free.

### 2. Create a new Space
- Go to <https://huggingface.co/new-space>
- **Owner:** your username
- **Space name:** `echo-ms-explorer` (or whatever)
- **License:** MIT
- **Select the Space SDK:** **Docker** → "Blank" template
- **Space hardware:** "CPU basic — Free"
- **Visibility:** Public

Click **Create Space**. Hugging Face gives you a git URL like
`https://huggingface.co/spaces/<you>/echo-ms-explorer`.

### 3. Push this repo's code to the Space

From a terminal in this repo:

```bash
# Add the Hugging Face Space as a second git remote
git remote add hf https://huggingface.co/spaces/<your-hf-username>/echo-ms-explorer

# Copy the Space-side README config to the repo root before pushing.
# (We keep it in docs/ so it doesn't clobber the GitHub README on main.)
cp docs/huggingface-space-readme.md README-hf.md

# Push to the Space (Hugging Face uses 'main' as the default branch)
git push hf main
```

When HF prompts for credentials, use your HF username and a write-scope
**access token** from <https://huggingface.co/settings/tokens>
(passwords aren't accepted for git over HTTPS).

> **Note on the README:** Hugging Face requires its YAML frontmatter at
> the top of the Space's `README.md`. We keep that frontmatter in
> `docs/huggingface-space-readme.md` so it doesn't disrupt the GitHub
> README. If you want HF to display a proper landing page, after the
> first push, rename `README-hf.md` to `README.md` *inside the Space's
> own git history only* (e.g. via the HF web UI's "Files" tab → edit
> README.md → paste the contents). The GitHub repo's README stays
> untouched.

### 4. Wait for the build

Hugging Face will see the `Dockerfile`, build the image (~3–5 min the
first time), and start the container. Watch progress on the Space's
"Logs" tab.

When the status flips to **Running**, the demo URL is live.

### 5. Add the demo URL to the GitHub README

Replace `<LIVE_DEMO_URL>` in the GitHub `README.md` badge with your
actual Space URL, then commit + push:

```bash
sed -i '' 's|<LIVE_DEMO_URL>|https://huggingface.co/spaces/<you>/echo-ms-explorer|g' README.md
git add README.md && git commit -m "Link live demo on Hugging Face Spaces"
git push origin main
```

## Updating the deployment

Every push to the `hf` remote rebuilds the Space:

```bash
git push hf main
```

If you want HF to auto-sync from GitHub on every push (so you only ever
have to `git push origin main`), enable "GitHub Sync" in your Space's
Settings → Repository.

## Resource limits on the free tier

- **RAM:** 16 GB on free CPU (generous — large mzMLs are fine)
- **Storage:** 50 GB ephemeral
- **Concurrent users:** ~3 before the Space queues
- **Sleeps:** the Space goes to sleep after ~48 h of no traffic. Next
  visit will trigger a ~30 s cold start.

## Troubleshooting

- **Build fails on `uv sync`** — check that `uv.lock` is committed and
  in sync with `pyproject.toml`. Run `uv sync` locally first.
- **App crashes on load** — open the Space's "Logs" tab; tracebacks
  appear there. Most common cause is a missing system lib for `lxml`;
  the `Dockerfile` already installs the necessary `libxml2` /
  `libxslt1.1` packages.
- **Demo button does nothing** — the synthetic dataset takes ~1 s to
  generate on first click; subsequent clicks are instant.
