# Deploying the live demo to Hugging Face Spaces

This repo includes a single-command deploy script: `scripts/deploy_to_hf.py`.
You run it once, paste an access token when prompted, and it creates a
public Space and uploads the code. Subsequent deploys are a single
command with no prompts.

## What you'll end up with

A public URL like `https://huggingface.co/spaces/<your-hf-username>/echo-ms-explorer`
that anyone can click. The app boots empty; a "Load demo data" button in
the app populates it with synthetic data so reviewers can drive every
feature without uploading anything.

Cold-start time: ~30 s on the free CPU tier. After that the Space stays
warm for a few minutes between visits.

## One-time setup

### 1. Create a Hugging Face account
<https://huggingface.co/join> — free, no card required.

### 2. Create an access token
<https://huggingface.co/settings/tokens>

- Click **New token**
- Name it `deploy` (or anything)
- Role: **Write**
- Click **Generate token**
- Copy the long `hf_…` string somewhere safe — you'll paste it once.

### 3. Run the deploy script

From a terminal in this repo:

```bash
uv run python scripts/deploy_to_hf.py
```

What happens:

1. The script installs `huggingface_hub` if it's missing.
2. It asks for your access token (paste it — the terminal hides what
   you type). The token is cached at `~/.cache/huggingface/token`, so
   you won't be asked again.
3. It creates the Space named `echo-ms-explorer` under your account
   (Docker SDK, public, free CPU).
4. It uploads the repo contents (skipping `.venv`, caches, the GitHub
   README, this `scripts/` folder, and any local exports).
5. It uploads `docs/huggingface-space-readme.md` as the Space's
   `README.md` so the landing page gets the right title/emoji/port.
6. It prints the live URL and a link to the build logs.

The first build takes about 3–5 minutes. When the status badge on the
Space flips from "Building" to "Running", the demo is live.

### 4. Link the live demo URL from the GitHub README

The GitHub `README.md` has a placeholder `<LIVE_DEMO_URL>` in the
"Try it" section. Once the Space is up, replace it:

```bash
sed -i '' 's|<LIVE_DEMO_URL>|https://huggingface.co/spaces/<you>/echo-ms-explorer|g' README.md
git add README.md && git commit -m "Link the live demo URL" && git push
```

## Updating the deployment

Re-run the same command after any code change:

```bash
uv run python scripts/deploy_to_hf.py
```

It re-uses the cached token, pushes only changed files, and triggers
a rebuild of the Space.

## Resource limits on the free tier

- **RAM:** 16 GB on free CPU (generous — large mzMLs work fine)
- **Storage:** 50 GB ephemeral
- **Concurrent users:** ~3 before the Space queues
- **Sleeps:** ~48 h of no traffic puts the Space to sleep; next visit
  triggers a ~30 s cold start.

## Troubleshooting

**Script complains that the token didn't authenticate.**
Delete the cached token and try again:

```bash
rm ~/.cache/huggingface/token
uv run python scripts/deploy_to_hf.py
```

Make sure the token has the **Write** role, not just **Read**.

**Build fails on `uv sync`.**
The `Dockerfile` expects `uv.lock` to be committed and in sync with
`pyproject.toml`. Run `uv sync` locally first and commit any
`uv.lock` changes.

**App crashes on first load.**
Open the Space's "Logs" tab; tracebacks appear there. Most common
cause is a missing system lib for `lxml` — but the `Dockerfile`
already installs `libxml2` / `libxslt1.1`, so this should be rare.

**Demo button does nothing for ~1 second.**
That's expected: the synthetic dataset takes a moment to generate on
the first click. Subsequent clicks are instant.

**The Space loads but the app shows "Awaiting file".**
Click the "Load demo data" button in the app's top panel.
