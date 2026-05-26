# Fixes — 2026-05-12

## Round 1: TIC disappearing
Fixed `input.prominence_pct()` typo, removed duplicate panel, made tic_plot
resilient to peak-detection errors.

## Round 2: peak picking + full-run XIC + long-format spectra export
Top-N-by-prominence picking, apex refinement, 4000-point TIC display,
y-axis label "Intensity (cps)", full-run XIC, long-format spectra CSV.

## Round 3: manual Recompute + plot cache isolation
Gated peak detection behind a Recompute button; cached the full bundle
(events, labels, assignment, n_reps) so plots/tables read only from the cache
and never recompute on input changes.

## Round 4: picker hardening + UI additions
Post-refine deduplication, `min_apex_intensity` floor, exposed
`apex_refine_sec`, circle markers instead of triangles.

## Round 5: peak boundaries + MS averaging window + marker style
**Peak boundaries (the real issue for averaged MS):**
The old boundary code was *finding the argmin in a half-window, then walking
inward* — which collapsed the integration window to 1-2 scans. That meant
the "Average spectrum over peak" feature was averaging over almost nothing.

New boundaries walk **outward from the apex** until the signal drops below
`boundary_frac` × apex height (default 0.5 = FWHM-style). Bounded by the
midpoint to the neighbouring peaks, not by `min_distance_sec`.

**New input: Integration boundary (fraction of apex).** Default 0.5 gives
FWHM-style windows. Lower it (e.g. 0.1) for wider windows that capture the
shoulders/tails. Higher (e.g. 0.7) for tighter apex-only windows.

**Marker style:** small filled dots (size 4) right on the apex, plus a
subtle shaded band underneath each peak showing the exact integration window
that the averaged-MS export uses. The band is the visual proof of what
`rt_start → rt_end` resolves to.

**Spectrum-plot title** now displays the window width in seconds so you can
quickly sanity-check it.

## Not fixed (still flagged for later)
- `ROW_LETTERS = "ABCDEFGHIJKLMNOP"` covers 16 rows; UI offers 1536.
- `pywebview` in `pyproject.toml` appears unused.
