# echo-ms-explorer

Interactive viewer for SCIEX Echo MS acoustic ejection data. Detects TIC peaks, assigns them to wells using an interactive plate selector (handles the serpentine S-pattern over arbitrary subsets), and lets you inspect TIC, XIC, and mass spectra per well.

Runs as a **native desktop window** on Mac and Windows. No browser tab, no Terminal in daily use.

## Try it

**[→ Live demo on Hugging Face Spaces](https://huggingface.co/spaces/jess-deng/echo-ms-explorer)** (loads in ~30 s on first visit). Click **"Load demo data"** inside the app — a synthetic 60-injection Echo MS run loads, wells A1–A20 are pre-selected with 3 interleaved replicates and 2 spectral groups separated by a ~70 s gap, and peak detection runs automatically. From there you can drive the XIC and Pivot Table tabs to see every feature working without uploading anything.

> No real proprietary data is shipped with the repo or the demo. Everything reviewers see in the live demo is generated in-memory from `src/echo_ms_explorer/demo.py`.

## Screenshots

| Plate + peak detection | Pivot table export |
|---|---|
| ![Plate selection + TIC with detected peaks](docs/screenshots/plate-and-tic.png) | ![Pivot table with XIC preview](docs/screenshots/pivot-table.png) |

## Why

Echo MS produces hundreds of acoustic injections per plate. Manually figuring out which TIC peak corresponds to which well — and then digging into m/z data for each — is the bottleneck on a workflow that's supposed to be high-throughput. This tool does the well assignment automatically and gives you a clickable plate map.

## First-time setup

You only need to do this once. After setup, daily use is a single double-click.

### 1. Pre-convert your .wiff/.wiff2 to mzML

This tool reads **mzML** files, not native SCIEX `.wiff`/`.wiff2`. Convert your data first using either:

- **SCIEX MS Data Converter** (Windows) — free from SCIEX
- **ProteoWizard `msconvert`** (Windows, or Docker on Mac/Linux) — https://proteowizard.sourceforge.io/

Basic msconvert command:
```
msconvert YourFile.wiff --mzML --64 --zlib --filter "peakPicking true 1-"
```

### 2. Install `uv` (one-time, Python package manager)

**Mac** — open Terminal and run:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows** — open PowerShell and run:
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. Get this project

Clone or download this repo to a folder you'll keep (e.g. `~/Documents/echo-ms-explorer`).

## Daily use: just double-click

- **Mac:** double-click `echo-ms-explorer.command`
- **Windows:** double-click `echo-ms-explorer.bat`

A small Terminal/Command Prompt window flashes up briefly while it starts (you can ignore or minimize it), then the app opens in its own native window.

**Pin it to your Dock / Taskbar for one-click launch:**

- **Mac:** drag `echo-ms-explorer.command` to your Dock. (If macOS won't let you drag it directly, right-click → Make Alias, drag the alias to Dock.) You can also change its icon by selecting it, pressing Cmd+I, and pasting a new image over the small icon at the top of the Info panel.
- **Windows:** right-click `echo-ms-explorer.bat` → Send to → Desktop (create shortcut). Then right-click the shortcut → Pin to taskbar.

**First launch is slower** — `uv` quietly downloads and installs all Python dependencies the first time. Subsequent launches are instant.

## How to use

1. **Upload mzML** at the top.
2. **Choose your plate format** (96, 384, 1536), then **click wells** in the grid to mark which ones were injected.
   - **Click** to toggle a well on/off.
   - **Shift-click** to fill a range from the last clicked well (within the same row, or rectangular across rows).
   - Numbers on selected wells show the auto-computed serpentine injection order.
   - Or paste a text list like `A1-A5, A6-A12, B1-B12` and click "Apply text selection".
3. **Set replicates** if you injected each well more than once:
   - **Replicates per well:** how many times each well was injected (default 1).
   - **Grouped** pattern: A1, A1, A1, A2, A2, A2, … (each well in a row).
   - **Interleaved** pattern: A1, A2, A3, …, A1, A2, A3, … (full plate pass repeated).
4. **Tune peak detection** — "Match expected count" auto-tunes the prominence threshold to find exactly as many peaks as injections you expect (wells × replicates). Or set prominence manually.
   - **Split wide multi-modal peaks** (on by default) — when two adjacent injections merge into one wider bump on the TIC, the algorithm finds the sub-peaks and splits them. Without this, dense regions get under-counted and stray peaks elsewhere get picked instead.
   - **Max neighbor gap (s)** (default 60s) — drops any peak whose nearest neighbour is farther than this many seconds away. Echo MS injects continuously, so a multi-minute gap to neighbours almost always means carryover or noise rather than a real injection.
5. **Inspect** — pick a well from the dropdown to see its XIC at a target m/z and the full mass spectrum. With replicates, each gets its own entry like `A1 (1/3)`.
   - **Spectral groups** — the TIC plot shades each continuous run of injections separated by a gap. Groups whose peak count doesn't match the expected pass size (interleaved) or well-group size (grouped) are highlighted cyan-blue with a ⚠ marker and a notification, so you can see at a glance where the detection is off.
   - **Per-peak hover** shows `#N` (chronological detection index), the assigned well + replicate, position within the well sequence (e.g. `Position 7 of 20`), and which spectral group it belongs to.
6. **Export** —
   - *Per-well spectra* (existing): well-summary CSV with `well`, `replicate`, `label` columns.
   - *Pivot table* (new tab): define multiple compounds by name and m/z, pick a polarity and integration window, and export a CSV of peak heights (cps) — rows = compounds, columns = wells with their replicate suffix (`A1 (3/12)`), in true serpentine sampling order. Built-in XIC preview shows the integration window for any selected compound so you can verify peak widths visually.

## Project layout

```
echo-ms-explorer/
├── echo-ms-explorer.command     # Mac double-click launcher
├── echo-ms-explorer.bat         # Windows double-click launcher
├── launch.py                    # Native-window launcher (used by the above)
├── app/
│   ├── app.py                   # Shiny app
│   └── www/
│       ├── styles.css           # Inter font + green palette
│       └── plate.js             # Clickable plate grid logic
├── src/echo_ms_explorer/
│   ├── parser.py                # mzML loader (pymzml)
│   ├── peaks.py                 # TIC peak detection
│   ├── plate.py                 # Plate layout + serpentine over arbitrary subsets
│   ├── extract.py               # XIC and spectrum extraction
│   └── demo.py                  # Synthetic data for the live demo
├── tests/                       # pytest suite (43 tests)
├── Dockerfile                   # Container build for the Hugging Face Spaces demo
├── docs/
│   ├── DEPLOY.md                # Step-by-step Hugging Face Spaces deploy guide
│   ├── huggingface-space-readme.md   # YAML config for the Space landing page
│   └── screenshots/             # PNGs referenced from the README
├── pyproject.toml
└── README.md
```

The core library (`src/echo_ms_explorer/`) is UI-agnostic and can be used directly:

```python
from echo_ms_explorer import (
    load_mzml,
    detect_injections,
    PlateLayout,
    assign_peaks_to_wells,
    serpentine_order_over_selection,
    extract_xic,
)

data = load_mzml("plate1.mzML")
wells = serpentine_order_over_selection({"A1", "A2", "A3", "B1", "B2", "B3"})
events = detect_injections(data, expected_count=len(wells))
assignment = assign_peaks_to_wells(events, PlateLayout(used_wells=wells))
```

## Power-user: run from terminal

If you want to bypass the double-click launcher (e.g. for development):

```bash
uv sync                              # install/update dependencies
uv run python launch.py              # native window
uv run shiny run --reload app/app.py # browser mode + auto-reload, for development
```

## Design notes

- **UI framework:** Shiny for Python, wrapped in a pywebview native window. The native window uses the system's webview (WKWebView on Mac, Edge WebView2 on Windows) — no Chrome dependency.
- **Theme:** Inter font, deep forest green (`#2e5c4e`) and sage (`#4a7c59`) on a warm off-white background.
- **Serpentine selection:** Echo serpentines its path *within* whatever wells you select, regardless of contiguity. The injection order is computed row-by-row: forward on the first row with selections, reversed on the second, alternating thereafter. See `serpentine_order_over_selection` in `src/echo_ms_explorer/plate.py` and the test cases in `tests/test_plate.py`.

## Known limitations

- Manual mzML conversion step (no native .wiff support — SCIEX's format isn't open).
- Single-file workflow; no batch processing yet.
- Assumes peaks appear in injection order with no major misfires. Missed/double injections will cause downstream wells to be misassigned; visually verify on the TIC plot — markers are labelled with their assigned well.

## License

MIT
