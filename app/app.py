"""echo-ms-explorer Shiny app.

Run with:
    shiny run --reload app/app.py
or:
    uv run shiny run app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from shiny import App, Inputs, Outputs, Session, reactive, render, ui
from shinywidgets import output_widget, render_widget

from echo_ms_explorer import (
    assign_peaks_to_replicates_clustered,
    detect_injections,
    expand_with_replicates,
    extract_spectrum_at_rt,
    extract_xic,
    load_mzml,
    parse_well_range_text,
    serpentine_order_over_selection,
    well_replicate_id,
)
from echo_ms_explorer.extract import (
    average_spectrum_over_window,
    downsample_for_display,
)
from echo_ms_explorer.plate import ROW_LETTERS

# ---------- Plate constants ----------
PLATE_FORMATS = {
    "384 (16 × 24)": (16, 24),
    "96 (8 × 12)": (8, 12),
    "1536 (32 × 48)": (32, 48),
}

# ---------- Colour palette — Bootswatch Sandstone ----------
TIC_COLOR = "#3e3f3a"                            # $dark / $body-color
PEAK_WINDOW_COLOR = "rgba(50, 93, 136, 0.20)"   # $primary tint
PEAK_APEX_COLOR = "#325d88"                      # $primary
RT_GUIDE_COLOR = "#325d88"                       # $primary
BASELINE_COLOR = "#8e8c84"                       # $secondary

MIN_DISPLAY_WIDTH_MIN = 0.005  # min visual width for peak bands (minutes)

# 12 distinguishable colours for replicate-boundary lines.
REPLICATE_COLORS = [
    "#325d88",  # primary
    "#93c54b",  # success / green
    "#d9534f",  # danger / red
    "#29abe0",  # info / cyan
    "#f47c3c",  # warning / orange
    "#6f42c1",  # purple
    "#8e8c84",  # secondary
    "#20c997",  # teal
    "#e83e8c",  # pink
    "#6610f2",  # indigo
    "#495057",  # gray-700
    "#ffc107",  # yellow
]

INK = "#3e3f3a"           # Sandstone $dark
INK_SOFT = "#8e8c84"      # Sandstone $secondary
PAPER_SOFT = "#f8f5f0"    # Sandstone $light
BORDER = "#dfd7ca"        # Sandstone $gray-300


HOVER_BG = "#93c54b"   # Sandstone $success green
HOVER_FG = "#fff"

def _plotly_theme(fig: go.Figure, *, height: int = 320) -> go.Figure:
    fig.update_layout(
        font=dict(family="Inter, -apple-system, sans-serif", size=12, color=INK),
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=height,
        margin=dict(l=50, r=20, t=30, b=45),
        hoverlabel=dict(bgcolor=HOVER_BG, font_color=HOVER_FG, font_size=12),
        xaxis=dict(
            gridcolor=PAPER_SOFT,
            zerolinecolor=BORDER,
            linecolor=BORDER,
            tickcolor=BORDER,
            tickfont=dict(color=INK_SOFT),
        ),
        yaxis=dict(
            gridcolor=PAPER_SOFT,
            zerolinecolor=BORDER,
            linecolor=BORDER,
            tickcolor=BORDER,
            tickfont=dict(color=INK_SOFT),
        ),
        showlegend=False,
    )
    return fig


# ---------- Build the plate grid HTML ----------
def build_plate_grid_html(n_rows: int, n_cols: int) -> ui.Tag:
    cells: list[ui.Tag] = []
    cells.append(ui.tags.div("", class_="plate-label"))
    for c in range(n_cols):
        cells.append(ui.tags.div(str(c + 1), class_="plate-label"))
    for r in range(n_rows):
        cells.append(ui.tags.div(ROW_LETTERS[r], class_="plate-label"))
        for c in range(n_cols):
            well_id = f"{ROW_LETTERS[r]}{c + 1}"
            cells.append(
                ui.tags.div(
                    "",
                    class_="plate-cell",
                    **{"data-well": well_id, "title": well_id},
                )
            )
    grid = ui.tags.div(
        *cells,
        class_="plate-grid",
        style=f"--n-cols: {n_cols};",
    )
    # Wrap in a scrollable container so large plates (1536) don't overflow
    return ui.tags.div(grid, class_="plate-grid-wrapper")


# ---------- UI definition ----------
app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.link(rel="stylesheet", href="styles.css"),
        ui.tags.script(src="plate.js"),
        ui.tags.title("echo-ms-explorer"),
    ),
    ui.tags.div(
        ui.tags.h1("echo-ms-explorer"),
        ui.tags.p(
            "Interactive viewer for SCIEX Echo MS acoustic ejection data. "
            "Pre-convert .wiff/.wiff2 files to mzML using SCIEX MS Data Converter or msconvert.",
            class_="app-subtitle",
        ),

        ui.navset_tab(
            ui.nav_panel(
                "Analysis",

        # Top: file upload + status
        ui.tags.div(
            ui.row(
                ui.column(
                    7,
                    ui.input_file(
                        "mzml_file",
                        "mzML file",
                        accept=[".mzML", ".mzml"],
                        button_label="Choose file",
                        placeholder="No file selected",
                    ),
                ),
                ui.column(
                    3,
                    ui.input_select("ms_level", "MS level", choices=["1", "2"], selected="1"),
                ),
                ui.column(2, ui.output_ui("file_status")),
            ),
            class_="panel",
        ),

        # Plate selection
        ui.tags.div(
            ui.tags.h2("Plate"),
            ui.row(
                ui.column(
                    3,
                    ui.input_select(
                        "plate_format",
                        "Plate format",
                        choices=list(PLATE_FORMATS.keys()),
                        selected="384 (16 × 24)",
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "n_replicates",
                        "Replicates per well",
                        value=1,
                        min=1,
                        max=20,
                        step=1,
                    ),
                ),
                ui.column(
                    3,
                    ui.input_radio_buttons(
                        "replicate_pattern",
                        "Replicate pattern",
                        choices={
                            "grouped": "Grouped (A1, A1, A1, A2, A2, A2...)",
                            "interleaved": "Interleaved (A1, A2, A3... x N passes)",
                        },
                        selected="grouped",
                    ),
                ),
                ui.column(
                    4,
                    ui.tags.div(
                        ui.input_action_button("clear_selection", "Clear", class_="btn-primary"),
                        " ",
                        ui.input_action_button("select_all", "Select all", class_="btn-primary"),
                        " ",
                        ui.input_action_button(
                            "apply_range_text", "Apply text", class_="btn-primary"
                        ),
                        style="margin-top: 1.45rem; display: flex; gap: 0.4rem; flex-wrap: wrap;",
                    ),
                ),
            ),
            ui.tags.p(
                "Click wells to toggle. Shift-click for ranges.",
                class_="text-muted",
                style="font-size: 0.78rem; margin: 0.25rem 0 0.5rem;",
            ),
            ui.output_ui("plate_grid_ui"),
            ui.tags.div(
                ui.tags.h3("Or paste well list"),
                ui.input_text_area(
                    "range_text",
                    None,
                    placeholder="e.g. A1-A5, A6-A12, B1-B12",
                    rows=2,
                    width="100%",
                ),
                style="margin-top: 1rem;",
            ),
            ui.output_ui("selection_summary"),
            class_="panel",
        ),

        # Peak Selection
        ui.tags.div(
            ui.tags.h2("Peak Selection"),
            ui.tags.p(
                "Set the RT window to the region containing injections, "
                "then set the baseline just above noise. "
                "Hover the TIC to read exact RT values. "
                "Shaded bands show each peak's integration window.",
                class_="text-muted",
                style="font-size: 0.82rem; margin: 0 0 0.5rem;",
            ),
            ui.row(
                ui.column(
                    2,
                    ui.input_numeric(
                        "rt_start_min",
                        "RT start (min)",
                        value=0.0,
                        min=0.0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "rt_end_min",
                        "RT end (min)",
                        value=0.0,
                        min=0.0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "baseline_threshold",
                        "Baseline (cps)",
                        value=0.0,
                        min=0.0,
                        step=1e5,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "peak_width_sec",
                        "Expected width (s)",
                        value=0.3,
                        min=0.05,
                        max=5.0,
                        step=0.05,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "min_distance_sec",
                        "Min spacing (s)",
                        value=3.0,
                        min=0.5,
                        max=60.0,
                        step=0.5,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "min_prominence_pct",
                        "Signal threshold (%)",
                        value=5.0,
                        min=0.0,
                        max=50.0,
                        step=0.5,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    3,
                    ui.input_checkbox(
                        "auto_count",
                        "Match expected count from selection",
                        value=True,
                    ),
                ),
                ui.column(
                    3,
                    ui.input_checkbox(
                        "split_wide_peaks",
                        "Split wide multi-modal peaks",
                        value=True,
                    ),
                ),
                ui.column(
                    2,
                    ui.input_numeric(
                        "max_neighbor_gap_sec",
                        "Max neighbor gap (s)",
                        value=60.0,
                        min=1.0,
                        max=600.0,
                        step=5.0,
                    ),
                ),
                ui.tags.div(
                    ui.input_action_button(
                        "recompute",
                        "Recompute",
                        class_="btn-primary",
                        style="width: 100%;",
                    ),
                    ui.output_ui("detection_status"),
                    class_="col-sm-2 offset-sm-2",
                    style="display: flex; flex-direction: column; gap: 0.4rem;",
                ),
            ),
            ui.tags.p(
                "Split wide peaks: catches two adjacent injections that "
                "merged into one bump on the TIC. Max neighbor gap: drops "
                "any peak whose nearest neighbor is farther away than "
                "this many seconds — a long gap between detected peaks "
                "almost always means carryover or noise rather than a "
                "real injection. Set very high (e.g. 9999) to disable.",
                class_="text-muted",
                style="font-size: 0.78rem; margin: 0.1rem 0 0.5rem;",
            ),
            output_widget("tic_plot"),
            class_="panel",
        ),

        # Extracted Ion Chromatogram
        ui.tags.div(
            ui.tags.h2("Extracted Ion Chromatogram"),
            ui.row(
                ui.column(
                    3,
                    ui.input_numeric(
                        "fullxic_mz", "XIC m/z target", value=200.0, step=0.1
                    ),
                ),
                ui.column(
                    3,
                    ui.input_numeric(
                        "fullxic_tol", "+/- m/z tolerance", value=0.02,
                        min=0.001, step=0.001,
                    ),
                ),
                ui.column(
                    3,
                    ui.input_checkbox(
                        "fullxic_show_markers",
                        "Overlay peak windows",
                        value=True,
                    ),
                    ui.input_action_button(
                        "xic_recompute",
                        "Recompute XIC",
                        class_="btn-primary",
                        style="width: 100%; margin-top: 0.5rem;",
                    ),
                ),
            ),
            output_widget("fullxic_plot"),
            class_="panel",
        ),

        # Per-well inspection
        ui.tags.div(
            ui.tags.h2("Per-well inspection"),
            ui.row(
                ui.column(
                    3,
                    ui.output_ui("well_picker_ui"),
                    ui.input_checkbox("avg_spectrum", "Average spectrum over peak window", value=True),
                ),
                ui.column(
                    9,
                    output_widget("spectrum_plot"),
                ),
            ),
            class_="panel",
        ),

        # Export
        ui.tags.div(
            ui.tags.div(
                ui.tags.h2("Export"),
                ui.tags.div(
                    ui.input_action_button(
                        "export_spectra_btn",
                        "Export mass spectra",
                        class_="btn-primary",
                    ),
                    ui.input_action_button(
                        "export_xic_btn",
                        "Export XIC",
                        class_="btn-primary",
                    ),
                    class_="panel-header-actions",
                ),
                class_="panel-header",
            ),
            ui.tags.div(
                ui.tags.span(
                    "Split by: ",
                    style="font-size: 0.85rem; color: var(--app-secondary, #8e8c84);",
                ),
                ui.input_radio_buttons(
                    "export_split",
                    None,
                    choices={
                        "well": "Per well",
                        "row": "Per row",
                        "all": "Single file",
                    },
                    selected="well",
                    inline=True,
                ),
                style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem;",
            ),
            ui.output_ui("spectra_preview"),
            ui.output_ui("export_status"),
            class_="panel",
        ),

            ),  # end Analysis nav_panel

            ui.nav_panel(
                "Pivot Table",
                ui.tags.div(
                    ui.tags.h2("Pivot Table Export"),
                    ui.tags.p(
                        "Build a pivot table of XIC peak heights (cps) for "
                        "multiple compounds across all detected wells. "
                        "Select the polarity, define compounds below "
                        "(one per line: Name, m/z), then click Generate. "
                        "Peak detection must be completed in the Analysis "
                        "tab first.",
                        class_="text-muted",
                        style="font-size: 0.82rem; margin: 0 0 0.5rem;",
                    ),
                    ui.row(
                        ui.column(
                            6,
                            ui.input_text_area(
                                "pivot_compounds",
                                "Compounds (Name, m/z — one per line)",
                                placeholder="Caffeine, 195.0877",
                                rows=8,
                                width="100%",
                            ),
                        ),
                        ui.column(
                            6,
                            ui.input_text_area(
                                "pivot_sample_names",
                                "Sample names (Well, Sample Name — one per "
                                "line, optional)",
                                placeholder=(
                                    "A1, Sample 1\n"
                                    "A2, Sample 2\n"
                                    "A3, Sample 3\n"
                                    "Wells with no entry keep their well ID."
                                    "  Replicate suffix added automatically."
                                ),
                                rows=8,
                                width="100%",
                            ),
                        ),
                    ),
                    ui.row(
                        ui.column(
                            3,
                            ui.input_numeric(
                                "pivot_mz_tol",
                                "m/z tolerance (+/-)",
                                value=0.02,
                                min=0.001,
                                step=0.001,
                            ),
                        ),
                        ui.column(
                            3,
                            ui.input_numeric(
                                "pivot_rt_window_sec",
                                "Peak window (s)",
                                value=2.0,
                                min=0.1,
                                max=30.0,
                                step=0.1,
                            ),
                        ),
                        ui.column(
                            3,
                            ui.input_select(
                                "pivot_polarity",
                                "Polarity",
                                choices=["Positive", "Negative"],
                                selected="Positive",
                            ),
                        ),
                        ui.column(
                            3,
                            ui.tags.div(
                                ui.input_action_button(
                                    "pivot_generate",
                                    "Generate",
                                    class_="btn-primary",
                                    style="width: 100%;",
                                ),
                                ui.input_action_button(
                                    "pivot_export_csv",
                                    "Export CSV",
                                    class_="btn-primary",
                                    style="width: 100%; margin-top: 0.5rem;",
                                ),
                                style="margin-top: 1.45rem;",
                            ),
                        ),
                    ),
                    ui.output_ui("pivot_preview"),
                    ui.tags.div(
                        ui.tags.h3(
                            "XIC Preview",
                            style="margin-top: 1.25rem; "
                                  "font-size: 1rem; font-weight: 600; "
                                  "color: var(--app-dark);",
                        ),
                        ui.tags.p(
                            "Verify peak integration widths for any "
                            "compound from the pivot table. Shaded bands "
                            "show the RT window used to measure peak "
                            "height.",
                            class_="text-muted",
                            style="font-size: 0.82rem; margin: 0 0 0.5rem;",
                        ),
                        ui.row(
                            ui.column(
                                6,
                                ui.input_select(
                                    "pivot_xic_compound",
                                    "Compound",
                                    choices=[],
                                ),
                            ),
                        ),
                        output_widget("pivot_xic_plot"),
                        style="margin-top: 0.5rem;",
                    ),
                    ui.output_ui("pivot_status"),
                    class_="panel",
                ),
            ),  # end Pivot Table nav_panel
        ),  # end navset_tab

        class_="main-container",
    ),
    theme=ui.Theme(preset="sandstone"),
)


# ---------- Server ----------
def server(input: Inputs, output: Outputs, session: Session):

    plate_selection = reactive.Value[list[str]]([])
    parsed_data = reactive.Value(None)
    file_name = reactive.Value("")
    file_load_error = reactive.Value("")

    # --- File upload ---
    @reactive.Effect
    @reactive.event(input.mzml_file)
    def _load_file():
        import warnings as _warnings
        f = input.mzml_file()
        if not f:
            return
        uploaded = f[0]
        try:
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                data = load_mzml(uploaded["datapath"], ms_level=int(input.ms_level()))
                if caught:
                    for w in caught:
                        ui.notification_show(str(w.message), type="warning", duration=8)
            parsed_data.set(data)
            file_name.set(uploaded["name"])
            file_load_error.set("")
        except Exception as e:
            ui.notification_show(
                f"Failed to load {uploaded['name']}: {type(e).__name__}: {e}",
                type="error",
                duration=None,
            )
            file_load_error.set(f"{type(e).__name__}: {e}")
            parsed_data.set(None)

    @output
    @render.ui
    def file_status():
        if file_load_error():
            return ui.tags.span(
                f"Error: {file_load_error()}", class_="status-pill err"
            )
        data = parsed_data()
        if data is None:
            return ui.tags.span("Awaiting file", class_="status-pill")
        rt_min, rt_max = data.rt_min_max
        return ui.tags.div(
            ui.tags.span(f"{data.n_scans} scans", class_="status-pill"),
            ui.tags.span(
                f"RT {rt_min:.1f}-{rt_max:.1f}s",
                class_="status-pill",
                style="margin-left: 4px;",
            ),
            style="margin-top: 1.6rem;",
        )

    # --- Plate grid ---
    @output
    @render.ui
    def plate_grid_ui():
        n_rows, n_cols = PLATE_FORMATS[input.plate_format()]
        return build_plate_grid_html(n_rows, n_cols)

    @reactive.Effect
    @reactive.event(input.plate_selection)
    def _sync_selection_from_js():
        sel = input.plate_selection()
        if sel is not None:
            plate_selection.set(list(sel))

    @reactive.Effect
    @reactive.event(input.clear_selection)
    async def _clear():
        plate_selection.set([])
        await session.send_custom_message("plate_set_selection", {"wells": []})

    @reactive.Effect
    @reactive.event(input.select_all)
    async def _select_all():
        n_rows, n_cols = PLATE_FORMATS[input.plate_format()]
        all_wells = [f"{ROW_LETTERS[r]}{c + 1}" for r in range(n_rows) for c in range(n_cols)]
        plate_selection.set(all_wells)
        await session.send_custom_message("plate_set_selection", {"wells": all_wells})

    @reactive.Effect
    @reactive.event(input.apply_range_text)
    async def _apply_range_text():
        try:
            wells = parse_well_range_text(input.range_text() or "")
            plate_selection.set(wells)
            await session.send_custom_message("plate_set_selection", {"wells": wells})
        except ValueError as e:
            ui.notification_show(f"Invalid selection text: {e}", type="error", duration=5)

    @output
    @render.ui
    def selection_summary():
        sel = plate_selection()
        if not sel:
            return ui.tags.p(
                "No wells selected", class_="text-muted", style="font-size: 0.82rem; margin-top: 0.6rem;"
            )
        ordered = serpentine_order_over_selection(sel)
        n_reps = max(1, int(input.n_replicates() or 1))
        sequence = expand_with_replicates(ordered, n_replicates=n_reps,
                                          pattern=input.replicate_pattern())
        total = len(sequence)
        labels = [well_replicate_id(w, r, n_reps) for w, r in sequence[:6]]
        preview = ", ".join(labels)
        if total > 6:
            last = sequence[-1]
            preview += f", ... {well_replicate_id(last[0], last[1], n_reps)}"

        reps_note = f" x {n_reps} reps" if n_reps > 1 else ""
        return ui.tags.p(
            ui.tags.span(f"{len(ordered)} wells{reps_note} = {total} injections", class_="status-pill"),
            ui.tags.span(f"  Order: {preview}",
                         style="color: var(--ink-soft); margin-left: 0.5rem; font-size: 0.82rem;"),
            style="margin-top: 0.6rem;",
        )

    # --- Injection sequence ---
    @reactive.Calc
    def injection_sequence() -> list[tuple[str, int]]:
        wells = serpentine_order_over_selection(plate_selection())
        if not wells:
            return []
        n_reps = max(1, int(input.n_replicates() or 1))
        return expand_with_replicates(wells, n_replicates=n_reps,
                                      pattern=input.replicate_pattern())

    # --- Peak detection cache ---
    _events_cache = reactive.Value[list]([])
    _labels_cache = reactive.Value[list[str]]([])
    _assignment_cache = reactive.Value[dict](dict())
    _spectral_groups_cache = reactive.Value[list[list]]([])
    _offcount_spectral_groups_cache = reactive.Value[set[int]](set())
    _last_signature = reactive.Value[tuple | None](None)
    _last_n_reps_at_compute = reactive.Value[int](1)

    def _detection_signature() -> tuple:
        try:
            return (
                id(parsed_data()),
                tuple(plate_selection()),
                int(input.n_replicates() or 1),
                str(input.replicate_pattern()),
                bool(input.auto_count()),
                float(input.rt_start_min() or 0),
                float(input.rt_end_min() or 0),
                float(input.baseline_threshold() or 0),
                float(input.peak_width_sec() or 0.3),
                float(input.min_distance_sec() or 0),
                float(input.min_prominence_pct() or 0),
                bool(input.split_wide_peaks()),
                float(input.max_neighbor_gap_sec() or 60.0),
            )
        except Exception:
            return None

    def _run_detection_and_populate_cache():
        data = parsed_data()
        if data is None:
            _events_cache.set([])
            _labels_cache.set([])
            _assignment_cache.set({})
            return

        seq = injection_sequence()
        if not seq:
            _events_cache.set([])
            _labels_cache.set([])
            _assignment_cache.set({})
            return

        n_reps = max(1, int(input.n_replicates() or 1))

        rt_start = float(input.rt_start_min() or 0) * 60.0
        rt_end = float(input.rt_end_min() or 0) * 60.0
        rt_window = None
        if rt_end > rt_start > 0:
            rt_window = (rt_start, rt_end)

        baseline = float(input.baseline_threshold() or 0)
        peak_w = float(input.peak_width_sec() or 0.3)

        prom_pct = float(input.min_prominence_pct() or 0)
        prom = None
        if prom_pct > 0:
            tic_max = float(data.tic.max())
            if baseline > 0:
                tic_max = max(tic_max - baseline, 1.0)
            prom = (prom_pct / 100.0) * tic_max

        max_gap_sec = float(input.max_neighbor_gap_sec() or 60.0)
        split_wide = bool(input.split_wide_peaks())

        kwargs = dict(
            rt_window=rt_window,
            baseline_intensity=baseline,
            min_distance_sec=float(input.min_distance_sec() or 3.0),
            peak_width_sec=peak_w,
            split_wide_peaks=split_wide,
            max_neighbor_gap_sec=max_gap_sec,
        )

        if input.auto_count():
            kwargs["expected_count"] = len(seq)
        else:
            kwargs["min_prominence"] = prom

        events = detect_injections(data, **kwargs)

        # Spectral-group-aware assignment: detect RT gaps in the peak sequence and
        # restart the well sequence at the next clean pass/group boundary
        # so the first peak after each gap maps to "A1 of the next pass"
        # (interleaved) or the next well's rep 1 (grouped), instead of
        # continuing sequentially across the gap.
        pattern = str(input.replicate_pattern())
        serpentine_wells = serpentine_order_over_selection(plate_selection())
        n_unique_wells = len(serpentine_wells)
        # Map well_id -> 1-based position in the serpentine sample order.
        # Used in the hover label so the user can see "Position 7 of 20"
        # — i.e. which sample in the run this peak is.
        well_to_position = {w: i + 1 for i, w in enumerate(serpentine_wells)}
        asn, spectral_group_warnings, spectral_groups = assign_peaks_to_replicates_clustered(
            events,
            seq,
            n_wells=n_unique_wells,
            n_replicates=n_reps,
            pattern=pattern,
            max_gap_sec=max_gap_sec,
        )

        # Per-event spectral_group lookup (by object identity) for label formatting
        # and the off-count set for the TIC visual highlight.
        boundary = (
            max(1, n_unique_wells) if pattern == "interleaved"
            else max(1, n_reps)
        )
        event_spectral_group_idx: dict[int, int] = {}
        offcount_spectral_groups: set[int] = set()
        for b_idx, spectral_group in enumerate(spectral_groups):
            if len(spectral_group) % boundary != 0 and len(spectral_groups) > 1:
                offcount_spectral_groups.add(b_idx)
            for ev in spectral_group:
                event_spectral_group_idx[id(ev)] = b_idx
        n_spectral_groups = len(spectral_groups)

        event_to_label_key: dict[int, tuple[str, int]] = {
            id(evt): key for key, evt in asn.items()
        }
        labels: list[str] = []
        for e in events:
            lines: list[str] = [f"#{e.index + 1}"]
            key = event_to_label_key.get(id(e))
            if key is not None:
                w, r = key
                lines.append(well_replicate_id(w, r, n_reps))
                if n_unique_wells > 1:
                    pos = well_to_position.get(w)
                    if pos is not None:
                        lines.append(f"Position {pos} of {n_unique_wells}")
            else:
                lines.append("(unassigned — gap skip)")
            b_idx = event_spectral_group_idx.get(id(e))
            if b_idx is not None and n_spectral_groups > 1:
                marker = " (off count)" if b_idx in offcount_spectral_groups else ""
                lines.append(f"Spectral group {b_idx + 1} of {n_spectral_groups}{marker}")
            lines.append(f"RT {e.rt/60:.2f} min")
            lines.append(
                f"Window {e.rt_start/60:.3f}–{e.rt_end/60:.3f} min"
            )
            labels.append("<br>".join(lines))

        for msg in spectral_group_warnings:
            ui.notification_show(msg, type="warning", duration=10)

        _events_cache.set(events)
        _labels_cache.set(labels)
        _assignment_cache.set(asn)
        _spectral_groups_cache.set(spectral_groups)
        _offcount_spectral_groups_cache.set(offcount_spectral_groups)
        _last_signature.set(_detection_signature())
        _last_n_reps_at_compute.set(n_reps)

    @reactive.Effect
    @reactive.event(input.recompute)
    def _on_recompute_click():
        try:
            _run_detection_and_populate_cache()
        except Exception as e:
            print(f"Detection failed: {type(e).__name__}: {e}", file=sys.stderr)
            ui.notification_show(
                f"Peak detection failed: {type(e).__name__}: {e}",
                type="error", duration=8,
            )

    @reactive.Effect
    @reactive.event(parsed_data, ignore_init=True)
    def _on_file_load_autocompute():
        if parsed_data() is None or not plate_selection():
            return
        try:
            _run_detection_and_populate_cache()
        except Exception as e:
            print(f"Auto-detection failed: {type(e).__name__}: {e}", file=sys.stderr)

    @reactive.Calc
    def detected_events():
        return _events_cache()

    @reactive.Calc
    def detected_labels() -> list[str]:
        return _labels_cache()

    @reactive.Calc
    def detection_is_stale() -> bool:
        last = _last_signature()
        if last is None:
            return parsed_data() is not None and bool(plate_selection())
        return _detection_signature() != last

    @reactive.Calc
    def assignment() -> dict[tuple[str, int], "InjectionEvent"]:
        return _assignment_cache()

    @reactive.Calc
    def detected_spectral_groups() -> list[list]:
        return _spectral_groups_cache()

    @reactive.Calc
    def offcount_spectral_group_indices() -> set[int]:
        return _offcount_spectral_groups_cache()

    def _spectral_group_aware_separator_shapes() -> list[dict]:
        """Build dashed-line shapes that separate consecutive passes (or
        well-groups) on the TIC / XIC plots, with the counter resetting
        at every spectral_group boundary so the lines stay aligned with the
        spectral-group-aware "Position X of N" labels in the hover.
        """
        spectral_groups = detected_spectral_groups()
        try:
            pattern_local = str(input.replicate_pattern())
            n_reps_local = max(1, int(input.n_replicates() or 1))
            n_wells_local = len(
                serpentine_order_over_selection(plate_selection())
            )
        except Exception:
            return []

        unit = (
            n_wells_local if pattern_local == "interleaved"
            else n_reps_local
        )
        if not spectral_groups or unit <= 1 or n_reps_local <= 1:
            return []

        shapes: list[dict] = []
        line_count = 0
        for spectral_group in spectral_groups:
            for k in range(unit, len(spectral_group), unit):
                rt_before = spectral_group[k - 1].rt / 60.0
                rt_after = spectral_group[k].rt / 60.0
                x_line = (rt_before + rt_after) / 2.0
                color = REPLICATE_COLORS[
                    line_count % len(REPLICATE_COLORS)
                ]
                shapes.append(dict(
                    type="line",
                    x0=x_line, x1=x_line,
                    y0=0, y1=1,
                    yref="paper",
                    line=dict(color=color, width=1.5, dash="dot"),
                ))
                line_count += 1
        return shapes

    @output
    @render.ui
    def detection_status():
        seq = injection_sequence()
        events = detected_events()
        stale = detection_is_stale()

        if not seq:
            return ui.tags.div()

        if stale and not events:
            return ui.tags.span("Click Recompute", class_="status-pill warn")

        cls = "status-pill" if len(events) == len(seq) else "status-pill warn"
        pill = ui.tags.span(f"{len(events)} / {len(seq)} peaks", class_=cls)

        if stale:
            return ui.tags.div(
                pill,
                ui.tags.span(
                    "stale",
                    class_="status-pill warn",
                    style="margin-top: 0.2rem;",
                ),
                style="display: flex; flex-direction: column; gap: 0.2rem;",
            )
        return pill

    # --- TIC plot ---
    @render_widget
    def tic_plot():
        from shiny.types import SilentException

        data = parsed_data()
        if data is None:
            fig = go.Figure()
            fig.update_layout(
                xaxis_title="Retention time (min)",
                yaxis_title="Intensity (cps)",
                annotations=[dict(text="Upload an mzML file to view the TIC",
                                  showarrow=False, font=dict(size=12, color=INK_SOFT),
                                  x=0.5, y=0.5, xref="paper", yref="paper")],
            )
            return _plotly_theme(fig, height=300)

        fig = go.Figure()
        try:
            tic_x, tic_y = downsample_for_display(
                data.rt, data.tic, target_points=4000
            )
            tic_x_min = tic_x / 60.0
            fig.add_trace(
                go.Scattergl(
                    x=tic_x_min, y=tic_y, mode="lines",
                    line=dict(color=TIC_COLOR, width=1.2),
                    name="TIC",
                    hovertemplate="RT %{x:.3f} min<br>Intensity %{y:.2e} cps<extra></extra>",
                )
            )
        except SilentException:
            raise
        except Exception as e:
            print(f"TIC trace render error: {type(e).__name__}: {e}", file=sys.stderr)
            fig.add_annotation(
                text=f"Could not render TIC: {type(e).__name__}: {e}",
                showarrow=False, font=dict(size=12, color="#a44"),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )

        # RT window guide lines + baseline
        try:
            rt_s = float(input.rt_start_min() or 0)
            rt_e = float(input.rt_end_min() or 0)
            baseline_val = float(input.baseline_threshold() or 0)

            shapes = []
            if rt_s > 0:
                shapes.append(dict(
                    type="line", x0=rt_s, x1=rt_s, y0=0, y1=1,
                    yref="paper", line=dict(color=RT_GUIDE_COLOR, width=2, dash="dash"),
                ))
            if rt_e > 0:
                shapes.append(dict(
                    type="line", x0=rt_e, x1=rt_e, y0=0, y1=1,
                    yref="paper", line=dict(color=RT_GUIDE_COLOR, width=2, dash="dash"),
                ))
            if baseline_val > 0:
                shapes.append(dict(
                    type="line", x0=0, x1=1, y0=baseline_val, y1=baseline_val,
                    xref="paper", line=dict(color=BASELINE_COLOR, width=1.5, dash="dot"),
                ))
            if shapes:
                fig.update_layout(shapes=shapes)
        except Exception:
            pass

        # Peak windows as shaded rectangles + apex tick marks
        try:
            events = detected_events()
            labels = detected_labels()

            if events:
                # Shaded rectangles showing the exact integration window
                band_x: list[float | None] = []
                band_y: list[float | None] = []
                band_text: list[str | None] = []
                for idx, e in enumerate(events):
                    x0 = e.rt_start / 60.0
                    x1 = e.rt_end / 60.0
                    # Enforce minimum visual width so narrow windows stay visible
                    display_w = x1 - x0
                    if display_w < MIN_DISPLAY_WIDTH_MIN:
                        center = (x0 + x1) / 2.0
                        x0 = center - MIN_DISPLAY_WIDTH_MIN / 2.0
                        x1 = center + MIN_DISPLAY_WIDTH_MIN / 2.0
                    h = e.intensity
                    lbl = labels[idx] if idx < len(labels) else f"#{idx + 1}"
                    band_x += [x0, x0, x1, x1, None]
                    band_y += [0, h, h, 0, None]
                    band_text += [lbl, lbl, lbl, lbl, None]

                fig.add_trace(
                    go.Scatter(
                        x=band_x, y=band_y,
                        mode="lines",
                        line=dict(width=0),
                        fill="tozeroy",
                        fillcolor=PEAK_WINDOW_COLOR,
                        text=band_text,
                        hoverinfo="text",
                        showlegend=False,
                        name="Peak windows",
                    )
                )

                # Small apex tick at the top of each window for hover info.
                # Use go.Scatter (SVG) — Scattergl falls back to squares for
                # the "line-ns-open" symbol.
                fig.add_trace(
                    go.Scatter(
                        x=[e.rt / 60 for e in events],
                        y=[e.intensity for e in events],
                        mode="markers",
                        marker=dict(
                            color=PEAK_APEX_COLOR, size=10, symbol="line-ns-open",
                            line=dict(width=2, color=PEAK_APEX_COLOR),
                        ),
                        text=labels,
                        hoverinfo="text",
                        name="Detected peaks",
                    )
                )
        except SilentException:
            raise
        except Exception as e:
            print(f"Peak-marker overlay error: {type(e).__name__}: {e}", file=sys.stderr)
            ui.notification_show(
                f"Peak detection failed: {type(e).__name__}: {e}",
                type="warning", duration=6,
            )

        # --- Pass / well-group separator lines (spectral-group-aware) ---
        # Draw a dashed vertical line at every pass boundary INSIDE each
        # spectral_group — the counter resets at every spectral_group gap so the lines stay
        # aligned with the "Position X of N" labels in the hover.
        try:
            rep_shapes = _spectral_group_aware_separator_shapes()
            if rep_shapes:
                fig.update_layout(
                    shapes=list(fig.layout.shapes or []) + rep_shapes,
                )
        except Exception:
            pass

        # --- Spectral group highlight ---
        # When multiple spectral_groups are detected, lightly shade each one. Spectral groups
        # with an off-count (extra or missing peaks vs the expected pass /
        # well-group size) get a saturated cyan-blue tint AND a dashed
        # border + ⚠ marker, so the highlight is visible without relying
        # on red/orange (which fails for red-green colour vision).
        try:
            spectral_groups = detected_spectral_groups()
            offcount = offcount_spectral_group_indices()
            if len(spectral_groups) > 1:
                spectral_group_shapes = []
                spectral_group_annotations = []
                for i, spectral_group in enumerate(spectral_groups):
                    if not spectral_group:
                        continue
                    x0 = spectral_group[0].rt / 60.0
                    x1 = spectral_group[-1].rt / 60.0
                    is_bad = i in offcount
                    if is_bad:
                        fill = "rgba(41, 171, 224, 0.22)"   # info cyan tint
                        border = dict(
                            color="#1a8db8", width=1.5, dash="dot",
                        )
                    else:
                        fill = "rgba(50, 93, 136, 0.04)"    # very faint primary
                        border = dict(width=0)
                    spectral_group_shapes.append(dict(
                        type="rect",
                        xref="x", yref="paper",
                        x0=x0, x1=x1, y0=0, y1=1,
                        fillcolor=fill,
                        line=border,
                        layer="below",
                    ))
                    label_text = f"Spectral group {i + 1}: {len(spectral_group)} peaks"
                    if is_bad:
                        label_text += " ⚠"
                    spectral_group_annotations.append(dict(
                        xref="x", yref="paper",
                        x=(x0 + x1) / 2.0,
                        y=1.04,
                        text=label_text,
                        showarrow=False,
                        font=dict(
                            size=10,
                            color="#1a8db8" if is_bad else INK_SOFT,
                        ),
                    ))
                if spectral_group_shapes:
                    fig.update_layout(
                        shapes=list(fig.layout.shapes or []) + spectral_group_shapes,
                        annotations=(
                            list(fig.layout.annotations or [])
                            + spectral_group_annotations
                        ),
                        margin=dict(l=50, r=20, t=45, b=45),
                    )
        except Exception:
            pass

        fig.update_layout(
            xaxis_title="Retention time (min)",
            yaxis_title="Intensity (cps)",
            yaxis=dict(tickformat=".2e", exponentformat="e"),
        )
        return _plotly_theme(fig, height=300)

    # --- Per-well inspection ---
    @output
    @render.ui
    def well_picker_ui():
        a = assignment()
        if not a:
            return ui.input_select(
                "selected_well", "Well", choices=["(select wells and load file)"]
            )
        n_reps = max(1, int(_last_n_reps_at_compute()))
        choices = {f"{w}|{r}": well_replicate_id(w, r, n_reps) for (w, r) in a.keys()}
        return ui.input_select("selected_well", "Well", choices=choices)

    @reactive.Calc
    def current_event():
        a = assignment()
        try:
            key_str = input.selected_well()
        except Exception:
            return None
        if not a or not key_str or "|" not in str(key_str):
            return None
        well, rep_str = str(key_str).split("|", 1)
        try:
            rep = int(rep_str)
        except ValueError:
            return None
        return a.get((well, rep))

    # --- XIC cache: only recompute when user clicks the button ----------------
    _xic_cache = reactive.Value[dict | None](None)

    @reactive.Effect
    @reactive.event(input.xic_recompute)
    def _recompute_xic():
        data = parsed_data()
        if data is None:
            _xic_cache.set(None)
            return
        target_mz = float(input.fullxic_mz() or 0.0)
        tol = float(input.fullxic_tol() or 0.02)
        show_markers = bool(input.fullxic_show_markers())
        try:
            rt_xic, int_xic = extract_xic(
                data, target_mz=target_mz, mz_tolerance=tol, rt_window=None
            )
            _xic_cache.set({
                "rt": rt_xic, "int": int_xic,
                "mz": target_mz, "tol": tol,
                "show_markers": show_markers,
            })
        except Exception as e:
            _xic_cache.set({"error": str(e), "mz": target_mz, "tol": tol,
                            "show_markers": show_markers})

    @render_widget
    def fullxic_plot():
        from shiny.types import SilentException

        cache = _xic_cache()
        if cache is None:
            fig = go.Figure()
            fig.update_layout(
                xaxis_title="Retention time (min)",
                yaxis_title="Intensity (cps)",
                annotations=[dict(
                    text="Set m/z target and click Recompute XIC",
                    showarrow=False, font=dict(size=12, color=INK_SOFT),
                    x=0.5, y=0.5, xref="paper", yref="paper",
                )],
            )
            return _plotly_theme(fig, height=300)

        target_mz = cache["mz"]
        tol = cache["tol"]
        show_markers = cache.get("show_markers", True)
        fig = go.Figure()

        if "error" in cache:
            fig.add_annotation(
                text=f"Could not extract XIC: {cache['error']}",
                showarrow=False, font=dict(size=12, color="#a44"),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )
            return _plotly_theme(fig, height=300)

        rt_xic = cache["rt"]
        int_xic = cache["int"]

        if rt_xic.size == 0:
            fig.update_layout(
                annotations=[dict(
                    text=f"No data for m/z {target_mz:.3f} +/- {tol:.3f}",
                    showarrow=False, font=dict(size=12, color=INK_SOFT),
                    x=0.5, y=0.5, xref="paper", yref="paper",
                )],
            )
            return _plotly_theme(fig, height=300)

        if len(rt_xic) > 4000:
            rt_xic_d, int_xic_d = downsample_for_display(
                rt_xic, int_xic, target_points=4000,
            )
        else:
            rt_xic_d, int_xic_d = rt_xic, int_xic
        rt_min = rt_xic_d / 60.0
        fig.add_trace(
            go.Scattergl(
                x=rt_min, y=int_xic_d, mode="lines",
                line=dict(color=TIC_COLOR, width=1.2),
                name="XIC",
                hovertemplate="RT %{x:.3f} min<br>Intensity %{y:.2e} cps<extra></extra>",
            )
        )

        if show_markers:
            try:
                events = detected_events()
                labels = detected_labels()
                if events and rt_xic.size:
                    band_x: list[float | None] = []
                    band_y: list[float | None] = []
                    band_text: list[str | None] = []
                    for idx, e in enumerate(events):
                        x0 = e.rt_start / 60.0
                        x1 = e.rt_end / 60.0
                        display_w = x1 - x0
                        if display_w < MIN_DISPLAY_WIDTH_MIN:
                            center = (x0 + x1) / 2.0
                            x0 = center - MIN_DISPLAY_WIDTH_MIN / 2.0
                            x1 = center + MIN_DISPLAY_WIDTH_MIN / 2.0
                        int_at_apex = float(np.interp(e.rt, rt_xic, int_xic))
                        lbl = labels[idx] if idx < len(labels) else f"#{idx + 1}"
                        band_x += [x0, x0, x1, x1, None]
                        band_y += [0, int_at_apex, int_at_apex, 0, None]
                        band_text += [lbl, lbl, lbl, lbl, None]

                    fig.add_trace(
                        go.Scatter(
                            x=band_x, y=band_y,
                            mode="lines",
                            line=dict(width=0),
                            fill="tozeroy",
                            fillcolor=PEAK_WINDOW_COLOR,
                            text=band_text,
                            hoverinfo="text",
                            showlegend=False,
                        )
                    )

                    apex_rts = np.array([e.rt for e in events])
                    apex_int = np.interp(apex_rts, rt_xic, int_xic)
                    fig.add_trace(
                        go.Scatter(
                            x=apex_rts / 60.0, y=apex_int,
                            mode="markers",
                            marker=dict(
                                color=PEAK_APEX_COLOR, size=10, symbol="line-ns-open",
                                line=dict(width=2, color=PEAK_APEX_COLOR),
                            ),
                            text=labels, hoverinfo="text",
                            name="Detected peaks",
                        )
                    )
            except SilentException:
                raise
            except Exception as e:
                print(f"Marker overlay error: {type(e).__name__}: {e}", file=sys.stderr)

        # --- Pass / well-group separator lines (spectral-group-aware) ---
        try:
            rep_shapes = _spectral_group_aware_separator_shapes()
            if rep_shapes:
                fig.update_layout(
                    shapes=list(fig.layout.shapes or []) + rep_shapes,
                )
        except Exception:
            pass

        fig.update_layout(
            title=f"XIC m/z {target_mz:.3f} +/- {tol:.3f}",
            xaxis_title="Retention time (min)",
            yaxis_title="Intensity (cps)",
            yaxis=dict(tickformat=".2e", exponentformat="e"),
        )
        return _plotly_theme(fig, height=300)


    @render_widget
    def spectrum_plot():
        data = parsed_data()
        evt = current_event()
        fig = go.Figure()
        if data is None or evt is None:
            fig.update_layout(title="Mass spectrum -- select a well")
            return _plotly_theme(fig, height=280)

        if input.avg_spectrum():
            mz, intensity = average_spectrum_over_window(data, evt.rt_start, evt.rt_end)
            title = f"Averaged MS, RT {evt.rt/60:.3f} min"
        else:
            mz, intensity = extract_spectrum_at_rt(data, evt.rt)
            title = f"MS at apex, RT {evt.rt/60:.3f} min"

        if mz.size > 0:
            xs, ys = [], []
            for m, i in zip(mz, intensity):
                xs += [m, m, None]
                ys += [0, i, None]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                     line=dict(color=PEAK_APEX_COLOR, width=1)))

        fig.update_layout(
            title=title,
            xaxis_title="m/z",
            yaxis_title="Intensity (cps)",
            yaxis=dict(tickformat=".2e", exponentformat="e"),
        )
        return _plotly_theme(fig, height=280)

    # --- Export preview + handlers ---
    @output
    @render.ui
    def spectra_preview():
        asn = assignment()
        if not asn:
            return ui.tags.p(
                "No assignments yet — upload a file, select wells, and run peak selection.",
                class_="text-muted",
            )
        data = parsed_data()
        if data is None:
            return ui.tags.p("No data loaded.", class_="text-muted")

        n_reps = max(1, int(_last_n_reps_at_compute()))
        use_avg = bool(input.avg_spectrum())

        # Build a small preview from the first 3 entries
        preview_entries = list(asn.keys())[:3]
        df = _build_wide_df(preview_entries, asn, n_reps, use_avg, data)
        if df.empty:
            return ui.tags.p("No spectra extracted.", class_="text-muted")

        # Show first 8 m/z rows of the wide table
        n_show = min(len(df), 8)
        preview = df.head(n_show).copy()
        # Format numbers nicely
        for col in preview.columns:
            if col == "mz":
                preview[col] = preview[col].apply(lambda x: f"{x:.4f}")
            else:
                preview[col] = preview[col].apply(lambda x: f"{x:.1f}")
        html = preview.to_html(classes="dataframe table table-sm", index=False)
        n_total_cols = len(list(asn.keys()))
        note = (f'<p class="text-muted" style="font-size:0.82rem; margin-top:0.3rem;">'
                f'Preview: {n_show} of {len(df)} m/z bins, '
                f'showing {len(preview.columns)-1} of {n_total_cols} injections. '
                f'Export for the full dataset.</p>')
        return ui.HTML(html + note)

    def _export_dir() -> Path:
        """Return (and create) an exports folder next to the source file."""
        src = file_name()
        if src:
            d = Path(src).parent / "exports"
        else:
            d = Path.home() / "Desktop" / "echo_exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @reactive.Effect
    @reactive.event(input.export_xic_btn)
    def _export_xic():
        """Export the XIC as a wide-format CSV: rt_min column + one intensity column per injection."""
        cache = _xic_cache()
        asn = assignment()
        if cache is None or "error" in cache or not asn:
            ui.notification_show(
                "Compute an XIC first (set m/z target and click Recompute XIC), "
                "then run peak selection.",
                type="warning",
            )
            return
        rt_xic = cache["rt"]
        int_xic = cache["int"]
        target_mz = cache["mz"]
        tol = cache["tol"]
        if rt_xic.size == 0:
            ui.notification_show("XIC has no data — adjust m/z target.", type="warning")
            return

        n_reps = max(1, int(_last_n_reps_at_compute()))
        events = detected_events()
        seq = injection_sequence()

        # Build wide table: rt_min column, then one column per injection
        # with the XIC intensity at each scan
        rows_out = {"rt_min": rt_xic / 60.0}
        for evt in events:
            if evt.index < len(seq):
                w, r = seq[evt.index]
                label = well_replicate_id(w, r, n_reps)
            else:
                label = f"#{evt.index + 1}"
            # Extract XIC intensity within this peak's window
            mask = (rt_xic >= evt.rt_start) & (rt_xic <= evt.rt_end)
            col = np.zeros(len(rt_xic))
            col[mask] = int_xic[mask]
            rows_out[label] = col

        df = pd.DataFrame(rows_out)
        stem = Path(file_name() or "echo_run").stem
        out_path = _export_dir() / f"{stem}_XIC_mz{target_mz:.3f}.csv"
        df.to_csv(out_path, index=False)
        ui.notification_show(
            f"Saved: {out_path}  ({len(df)} scans, {len(df.columns)-1} injections)",
            type="message", duration=8,
        )

    def _extract_spectrum_pair(
        well_id: str, rep: int, evt, n_reps: int, use_avg: bool, data
    ) -> tuple[str, np.ndarray, np.ndarray]:
        """Return (label, mz_array, intensity_array) for one injection."""
        label = well_replicate_id(well_id, rep, n_reps)
        if use_avg:
            mz, intensity = average_spectrum_over_window(
                data, evt.rt_start, evt.rt_end
            )
        else:
            mz, intensity = extract_spectrum_at_rt(data, evt.rt)
        return label, mz, intensity

    def _build_wide_df(
        entries: list[tuple[str, int]], asn: dict, n_reps: int,
        use_avg: bool, data,
        mz_bin_width: float = 0.05,
    ) -> pd.DataFrame:
        """Build wide-format DataFrame: mz column + one intensity column per label.

        All spectra are binned into ``mz_bin_width`` Da bins (default 0.05)
        so that peaks from different injections align on a common m/z axis.
        Within each bin the intensities are summed.  Missing values are 0.0.
        """
        # Extract spectra for each injection
        spectra: list[tuple[str, pd.Series]] = []
        for (well_id, rep) in entries:
            evt = asn.get((well_id, rep))
            if evt is None:
                continue
            label, mz, intensity = _extract_spectrum_pair(
                well_id, rep, evt, n_reps, use_avg, data,
            )
            if mz.size == 0:
                continue
            # Bin m/z to the nearest mz_bin_width (e.g. 0.05 Da)
            mz_binned = np.round(mz / mz_bin_width) * mz_bin_width
            mz_binned = np.round(mz_binned, 4)  # clean float noise
            s = pd.Series(intensity.astype(float), index=mz_binned, name=label)
            # Sum intensities within the same bin
            s = s.groupby(level=0).sum()
            spectra.append((label, s))

        if not spectra:
            return pd.DataFrame({"mz": []})

        # Merge all onto a common m/z axis
        all_mz = sorted(set().union(*(s.index for _, s in spectra)))
        rows = {"mz": all_mz}
        for label, s in spectra:
            rows[label] = s.reindex(all_mz, fill_value=0.0).values
        return pd.DataFrame(rows)

    @reactive.Effect
    @reactive.event(input.export_spectra_btn)
    def _export_spectra():
        import zipfile

        data = parsed_data()
        asn = assignment()
        if data is None or not asn:
            ui.notification_show("No peak assignments — nothing to export.", type="warning")
            return

        n_reps = max(1, int(_last_n_reps_at_compute()))
        use_avg = bool(input.avg_spectrum())
        split_mode = input.export_split()
        stem = Path(file_name() or "echo_run").stem
        export_dir = _export_dir()
        all_entries = list(asn.keys())

        if split_mode == "all":
            df = _build_wide_df(all_entries, asn, n_reps, use_avg, data)
            out_path = export_dir / f"{stem}_spectra.csv"
            df.to_csv(out_path, index=False)
            ui.notification_show(f"Saved: {out_path}  ({len(df)} rows, {len(df.columns)-1} spectra)", type="message", duration=8)
            return

        # Per-well or per-row: group entries, build one wide CSV per group → ZIP
        groups: dict[str, list[tuple[str, int]]] = {}
        for (well_id, rep) in all_entries:
            if split_mode == "well":
                key = well_id
            else:
                key = well_id[0]
            groups.setdefault(key, []).append((well_id, rep))

        out_path = export_dir / f"{stem}_spectra.zip"
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for key in sorted(groups.keys()):
                df = _build_wide_df(groups[key], asn, n_reps, use_avg, data)
                csv_str = df.to_csv(index=False)
                if split_mode == "well":
                    fname = f"{stem}_{key}.csv"
                else:
                    fname = f"{stem}_row{key}.csv"
                zf.writestr(fname, csv_str)

        n_files = len(groups)
        ui.notification_show(f"Saved: {out_path}  ({n_files} files)", type="message", duration=8)

    @output
    @render.ui
    def export_status():
        """Show the export folder path."""
        src = file_name()
        if not src:
            return ui.tags.p()
        d = Path(src).parent / "exports"
        return ui.tags.p(
            f"Files saved to: {d}",
            style="font-size: 0.82rem; color: #666; margin-top: 0.4rem;",
        )

    # --- Pivot Table ---
    _pivot_cache = reactive.Value[pd.DataFrame | None](None)

    def _parse_compound_defs(text: str) -> list[tuple[str, float]]:
        compounds = []
        for line in text.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            name = parts[0]
            try:
                mz = float(parts[1])
            except ValueError:
                continue
            compounds.append((name, mz))
        return compounds

    def _parse_sample_names(text: str) -> dict[str, str]:
        """Parse 'WellID, Sample Name' lines into a {well: name} dict."""
        names: dict[str, str] = {}
        for line in text.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Split only on the first comma so sample names may contain commas
            parts = [p.strip() for p in line.split(",", 1)]
            if len(parts) < 2:
                continue
            well_id = parts[0].upper()
            sample_name = parts[1]
            if well_id and sample_name:
                names[well_id] = sample_name
        return names

    def _pivot_label(base: str, replicate_index: int, total_replicates: int) -> str:
        """Format a column label: 'Name' or 'Name (rep/total)'."""
        if total_replicates <= 1:
            return base
        return f"{base} ({replicate_index}/{total_replicates})"

    @reactive.Effect
    @reactive.event(input.pivot_generate)
    def _generate_pivot():
        data = parsed_data()
        events = detected_events()
        asn = assignment()

        if data is None or not events or not asn:
            ui.notification_show(
                "Load a file, select wells, and run peak detection "
                "in the Analysis tab first.",
                type="warning",
            )
            return

        text = input.pivot_compounds() or ""
        compounds = _parse_compound_defs(text)
        if not compounds:
            ui.notification_show(
                "No valid compounds. Format: Name, m/z",
                type="warning",
            )
            return

        polarity = input.pivot_polarity()
        tol = float(input.pivot_mz_tol() or 0.02)
        window_sec = float(input.pivot_rt_window_sec() or 2.0)
        half_window = window_sec / 2.0
        n_reps = max(1, int(_last_n_reps_at_compute()))

        # Sample-name overrides: {well_id: "Sample 1"}.  Wells not listed in
        # the mapping fall back to the well ID. The replicate suffix is
        # always appended automatically when n_reps > 1.
        sample_names = _parse_sample_names(
            input.pivot_sample_names() or ""
        )

        # Use the full injection sequence (serpentine + replicates) so columns
        # appear in actual sampling order. Wells without a detected peak get
        # an empty cell rather than being omitted from the table.
        seq = injection_sequence()
        if not seq:
            seq = list(asn.keys())
        well_labels = [
            _pivot_label(sample_names.get(w, w), r, n_reps)
            for (w, r) in seq
        ]

        rows = []
        for name, mz in compounds:
            rt_xic, int_xic = extract_xic(
                data, target_mz=mz, mz_tolerance=tol,
            )
            row: dict[str, object] = {
                "Compound": name, "Polarity": polarity,
            }
            for (w, r), label in zip(seq, well_labels):
                evt = asn.get((w, r))
                if evt is None:
                    row[label] = ""
                    continue
                if rt_xic.size == 0:
                    row[label] = 0.0
                    continue
                # Fixed-width window centered on the detected apex so every
                # well is measured with an identical RT window.
                rt_lo = evt.rt - half_window
                rt_hi = evt.rt + half_window
                mask = (rt_xic >= rt_lo) & (rt_xic <= rt_hi)
                if mask.any():
                    row[label] = float(int_xic[mask].max())
                else:
                    row[label] = 0.0
            rows.append(row)

        df = pd.DataFrame(
            rows, columns=["Compound", "Polarity"] + well_labels,
        )
        _pivot_cache.set(df)

        # Populate the XIC preview compound dropdown
        compound_names = [name for name, _ in compounds]
        ui.update_select(
            "pivot_xic_compound",
            choices=compound_names,
            selected=compound_names[0] if compound_names else None,
        )

        ui.notification_show(
            f"Pivot table: {len(compounds)} compounds "
            f"× {len(well_labels)} wells (serpentine order)",
            type="message",
            duration=5,
        )

    @output
    @render.ui
    def pivot_preview():
        df = _pivot_cache()
        if df is None:
            return ui.tags.p(
                "Define compounds and click Generate.",
                class_="text-muted",
            )
        if df.empty:
            return ui.tags.p("No data generated.", class_="text-muted")

        preview = df.copy()
        for col in preview.columns:
            if col not in ("Compound", "Polarity"):
                preview[col] = preview[col].apply(
                    lambda x: f"{x:.4f}"
                    if isinstance(x, (int, float))
                    else ""
                )

        html = preview.to_html(
            classes="dataframe table table-sm pivot-table",
            index=False,
            na_rep="",
        )
        n_wells = len(df.columns) - 2
        note = (
            f'<p class="text-muted" style="font-size:0.82rem;'
            f' margin-top:0.3rem;">'
            f"{len(df)} compounds × {n_wells} wells</p>"
        )
        return ui.HTML(
            f'<div style="overflow-x: auto;">{html}</div>{note}'
        )

    @render_widget
    def pivot_xic_plot():
        from shiny.types import SilentException

        fig = go.Figure()
        df = _pivot_cache()
        data = parsed_data()

        if df is None or data is None:
            fig.update_layout(
                annotations=[dict(
                    text="Generate pivot table to preview XIC",
                    showarrow=False,
                    font=dict(size=12, color=INK_SOFT),
                    x=0.5, y=0.5, xref="paper", yref="paper",
                )],
                xaxis_title="Retention time (min)",
                yaxis_title="Intensity (cps)",
            )
            return _plotly_theme(fig, height=280)

        try:
            compound_name = input.pivot_xic_compound()
        except Exception:
            compound_name = None

        if not compound_name:
            return _plotly_theme(fig, height=280)

        # Find m/z for the chosen compound
        text = input.pivot_compounds() or ""
        compounds = _parse_compound_defs(text)
        target_mz = next(
            (mz for name, mz in compounds if name == compound_name),
            None,
        )

        if target_mz is None:
            fig.add_annotation(
                text=f"Compound '{compound_name}' not in current list",
                showarrow=False, font=dict(size=12, color="#a44"),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )
            return _plotly_theme(fig, height=280)

        tol = float(input.pivot_mz_tol() or 0.02)

        try:
            rt_xic, int_xic = extract_xic(
                data, target_mz=target_mz, mz_tolerance=tol,
            )
        except SilentException:
            raise
        except Exception as e:
            fig.add_annotation(
                text=f"Could not extract XIC: {e}",
                showarrow=False, font=dict(size=12, color="#a44"),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )
            return _plotly_theme(fig, height=280)

        if rt_xic.size == 0:
            fig.add_annotation(
                text=f"No data for m/z {target_mz:.4f} +/- {tol:.4f}",
                showarrow=False, font=dict(size=12, color=INK_SOFT),
                x=0.5, y=0.5, xref="paper", yref="paper",
            )
            return _plotly_theme(fig, height=280)

        if len(rt_xic) > 4000:
            rt_xic_d, int_xic_d = downsample_for_display(
                rt_xic, int_xic, target_points=4000,
            )
        else:
            rt_xic_d, int_xic_d = rt_xic, int_xic

        fig.add_trace(
            go.Scattergl(
                x=rt_xic_d / 60.0, y=int_xic_d, mode="lines",
                line=dict(color=TIC_COLOR, width=1.2),
                name="XIC",
                hovertemplate=(
                    "RT %{x:.3f} min<br>"
                    "Intensity %{y:.2e} cps<extra></extra>"
                ),
            )
        )

        window_sec = float(input.pivot_rt_window_sec() or 2.0)
        half_window_sec = window_sec / 2.0
        half_window_min = half_window_sec / 60.0

        events = detected_events()
        # Build hover labels using sample-name overrides so the preview
        # matches what the user sees in the pivot table.
        sample_names = _parse_sample_names(
            input.pivot_sample_names() or ""
        )
        n_reps = max(1, int(_last_n_reps_at_compute()))
        seq = injection_sequence()
        labels: list[str] = []
        for idx, e in enumerate(events):
            if idx < len(seq):
                w, r = seq[idx]
                base = sample_names.get(w, w)
                pretty = _pivot_label(base, r, n_reps)
                labels.append(
                    f"#{idx + 1}<br>{pretty}<br>RT {e.rt/60:.2f} min"
                )
            else:
                labels.append(f"#{idx + 1}<br>RT {e.rt/60:.2f} min")
        if events:
            band_x: list[float | None] = []
            band_y: list[float | None] = []
            band_text: list[str | None] = []
            for idx, e in enumerate(events):
                apex_min = e.rt / 60.0
                # Uniform-width window centered on each apex — matches the
                # window used to compute the pivot table values.
                x0 = apex_min - half_window_min
                x1 = apex_min + half_window_min
                rt_lo = e.rt - half_window_sec
                rt_hi = e.rt + half_window_sec
                mask = (rt_xic >= rt_lo) & (rt_xic <= rt_hi)
                band_height = (
                    float(int_xic[mask].max()) if mask.any() else 0.0
                )
                lbl = labels[idx] if idx < len(labels) else f"#{idx + 1}"
                band_x += [x0, x0, x1, x1, None]
                band_y += [0, band_height, band_height, 0, None]
                band_text += [lbl, lbl, lbl, lbl, None]

            fig.add_trace(
                go.Scatter(
                    x=band_x, y=band_y,
                    mode="lines",
                    line=dict(width=0),
                    fill="tozeroy",
                    fillcolor=PEAK_WINDOW_COLOR,
                    text=band_text,
                    hoverinfo="text",
                    showlegend=False,
                )
            )

            apex_rts = np.array([e.rt for e in events])
            apex_int = np.interp(apex_rts, rt_xic, int_xic)
            fig.add_trace(
                go.Scatter(
                    x=apex_rts / 60.0, y=apex_int,
                    mode="markers",
                    marker=dict(
                        color=PEAK_APEX_COLOR, size=10,
                        symbol="line-ns-open",
                        line=dict(width=2, color=PEAK_APEX_COLOR),
                    ),
                    text=labels, hoverinfo="text",
                    name="Peak apex",
                )
            )

        fig.update_layout(
            title=(
                f"XIC: {compound_name} "
                f"(m/z {target_mz:.4f} +/- {tol:.4f}, "
                f"window {window_sec:.1f} s)"
            ),
            xaxis_title="Retention time (min)",
            yaxis_title="Intensity (cps)",
            yaxis=dict(tickformat=".2e", exponentformat="e"),
        )
        return _plotly_theme(fig, height=280)

    @reactive.Effect
    @reactive.event(input.pivot_export_csv)
    def _export_pivot_csv():
        df = _pivot_cache()
        if df is None or df.empty:
            ui.notification_show(
                "Generate the pivot table first.", type="warning",
            )
            return

        stem = Path(file_name() or "echo_run").stem
        out_path = _export_dir() / f"{stem}_pivot_table.csv"
        df.to_csv(out_path, index=False)
        ui.notification_show(
            f"Saved: {out_path}", type="message", duration=8,
        )

    @output
    @render.ui
    def pivot_status():
        src = file_name()
        if not src:
            return ui.tags.p()
        d = Path(src).parent / "exports"
        return ui.tags.p(
            f"CSV will be saved to: {d}",
            style="font-size: 0.82rem; color: #666; margin-top: 0.4rem;",
        )


# ---------- App ----------
www_dir = Path(__file__).parent / "www"
app = App(app_ui, server, static_assets=str(www_dir))
