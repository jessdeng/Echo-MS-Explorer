"""Peak detection on the TIC to identify acoustic ejection injection events.

Echo MS acoustic injections produce narrow, regular peaks in the TIC. This
module crops to a user-defined RT window, subtracts a flat baseline, finds
candidates on a lightly smoothed signal, then refines apex positions and
boundaries on the raw signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from echo_ms_explorer.parser import MzmlData


@dataclass
class InjectionEvent:
    """A single detected injection peak in the TIC.

    Attributes:
        index: Sequential injection number (0-based, in chronological order).
        rt: Retention time at the peak apex (seconds).
        scan_idx: Index into MzmlData.rt / .tic / .mz_arrays for the apex scan.
        intensity: TIC value at the apex (original, before baseline subtraction).
        rt_start: Estimated start of the peak (seconds).
        rt_end: Estimated end of the peak (seconds).
    """

    index: int
    rt: float
    scan_idx: int
    intensity: float
    rt_start: float
    rt_end: float


def detect_injections(
    data: MzmlData,
    *,
    rt_window: tuple[float, float] | None = None,
    baseline_intensity: float = 0.0,
    min_prominence: float | None = None,
    min_distance_sec: float = 3.0,
    peak_width_sec: float = 0.3,
    expected_count: int | None = None,
    split_wide_peaks: bool = True,
    max_neighbor_gap_sec: float = 60.0,
) -> list[InjectionEvent]:
    """Detect injection events from the TIC.

    Pipeline:
      1. Crop to ``rt_window``.
      2. Subtract ``baseline_intensity``.
      3. Light 3-point smoothing for candidate finding only.
      4. find_peaks on smoothed signal (no width constraint -- just distance
         and prominence so narrow peaks aren't rejected).
      5. If ``expected_count``: optionally split wide multi-modal peaks
         into sub-peaks (so two merged injections aren't undercounted),
         drop peaks isolated by more than ``max_neighbor_gap_sec`` from
         their nearest neighbour (carryover in dead zones), then keep
         top-N by prominence.
      6. Snap each candidate to true local max on RAW signal within
         +/- half ``peak_width_sec``.
      7. Deduplicate by min-distance (keep higher intensity).
      8. Fixed-width window = ``peak_width_sec`` centered on each apex.
         Every injection window is identical. If two windows would overlap,
         both are truncated at the midpoint between their apices.

    Args:
        split_wide_peaks: If True (default), every candidate peak is
            inspected for multi-modal substructure within a window of
            +/- ``peak_width_sec``. If 2+ sub-peaks are present (each at
            least 8% of the local max), the candidate is replaced with
            those sub-peaks — catching merged adjacent injections.
        max_neighbor_gap_sec: Drop any peak whose nearest neighbour is
            farther than this many seconds. Echo MS injections come in
            tight trains, so a peak with a multi-minute gap to its
            neighbours is almost certainly carryover or a stray
            detection in a dead zone. Default 60s. Set to ``inf`` to
            disable.
    """
    rt = data.rt
    tic = data.tic

    # --- 1. Crop to RT window ------------------------------------------------
    if rt_window is not None:
        mask = (rt >= rt_window[0]) & (rt <= rt_window[1])
        if not mask.any():
            return []
        win_idx = np.where(mask)[0]
        rt_w = rt[win_idx]
        tic_w = tic[win_idx]
    else:
        win_idx = np.arange(len(rt))
        rt_w = rt
        tic_w = tic

    # --- 2. Subtract flat baseline -------------------------------------------
    if baseline_intensity > 0:
        tic_c = np.maximum(tic_w - baseline_intensity, 0.0)
    else:
        tic_c = tic_w.copy()

    if tic_c.max() == 0:
        return []

    median_dt = float(np.median(np.diff(rt_w))) if len(rt_w) > 1 else 1.0

    # When expected_count is set, auto-floor min_distance to 50% of expected
    # spacing so double-picks are impossible regardless of the UI default.
    effective_distance = min_distance_sec
    if expected_count is not None and expected_count > 1:
        rt_span = float(rt_w[-1] - rt_w[0])
        expected_spacing = rt_span / expected_count
        auto_floor = 0.5 * expected_spacing
        effective_distance = max(min_distance_sec, auto_floor)

    distance_samples = max(1, int(round(effective_distance / median_dt)))

    # --- 3. Minimal smoothing for candidate finding --------------------------
    # Fixed 3-point moving average -- just enough to suppress single-scan
    # noise spikes without blurring narrow injection peaks.
    tic_smooth = uniform_filter1d(tic_c, size=3)

    # --- 4. Find candidates on smoothed signal -------------------------------
    # NO width constraint here -- Echo MS peaks vary in width and a tight
    # width filter rejects real peaks. Distance + prominence are sufficient.
    expected_width_samples = max(1, int(round(peak_width_sec / median_dt)))
    max_gap_samples = (
        max_neighbor_gap_sec / median_dt
        if np.isfinite(max_neighbor_gap_sec)
        else np.inf
    )
    if expected_count is not None:
        peaks_idx = _find_peaks_top_n_by_prominence(
            tic_smooth,
            target=expected_count,
            distance=distance_samples,
            expected_width_samples=expected_width_samples,
            split_wide=split_wide_peaks,
            max_neighbor_gap_samples=max_gap_samples,
        )
    else:
        prom = min_prominence if min_prominence is not None else 0.02 * float(tic_smooth.max())
        peaks_idx, _ = find_peaks(
            tic_smooth,
            prominence=prom,
            distance=distance_samples,
        )

    if peaks_idx.size == 0:
        return []

    # --- 5. Apex refinement on RAW signal ------------------------------------
    # Snap each candidate to the true local max within +/- half the expected
    # peak width. Wide enough to escape a shoulder, narrow enough not to jump
    # to a neighboring peak.
    refine_half = max(1, int(round((peak_width_sec / 2.0) / median_dt)))
    refined = []
    for p_idx in peaks_idx:
        lo = max(0, p_idx - refine_half)
        hi = min(len(tic_c), p_idx + refine_half + 1)
        local_max = lo + int(np.argmax(tic_c[lo:hi]))
        refined.append(local_max)
    refined = np.array(refined, dtype=int)

    # --- 6. Re-enforce min-distance after refinement -------------------------
    order = np.argsort(tic_c[refined])[::-1]
    accepted_idx: list[int] = []
    accepted_set: set[int] = set()
    accepted_arr = np.array([], dtype=int)
    for rank in order:
        candidate = int(refined[rank])
        if candidate in accepted_set:
            continue
        if accepted_arr.size == 0:
            accepted_idx.append(candidate)
            accepted_set.add(candidate)
            accepted_arr = np.array([candidate])
            continue
        if np.min(np.abs(accepted_arr - candidate)) >= distance_samples:
            accepted_idx.append(candidate)
            accepted_set.add(candidate)
            accepted_arr = np.append(accepted_arr, candidate)
    peaks_idx = np.array(sorted(accepted_idx), dtype=int)

    # --- 7. Fixed-width windows ------------------------------------------------
    # Every Echo MS injection is the same acoustic ejection, so every
    # integration window should be the same width = peak_width_sec, centered
    # on the apex. If two windows would overlap, truncate both at the midpoint
    # between their apices so no scan is double-counted.
    half_width = peak_width_sec / 2.0
    events: list[InjectionEvent] = []
    n_peaks = len(peaks_idx)
    apex_rts = np.array([float(rt_w[int(p)]) for p in peaks_idx])

    for i, p_idx in enumerate(peaks_idx):
        p_idx = int(p_idx)
        apex_rt = apex_rts[i]

        left_rt = apex_rt - half_width
        right_rt = apex_rt + half_width

        # Truncate at midpoint to neighbors if windows would overlap
        if i > 0:
            mid_left = (apex_rts[i - 1] + apex_rt) / 2.0
            left_rt = max(left_rt, mid_left)
        if i < n_peaks - 1:
            mid_right = (apex_rt + apex_rts[i + 1]) / 2.0
            right_rt = min(right_rt, mid_right)

        # Clamp to the RT window edges
        left_rt = max(left_rt, float(rt_w[0]))
        right_rt = min(right_rt, float(rt_w[-1]))

        g_apex = int(win_idx[p_idx])

        events.append(
            InjectionEvent(
                index=i,
                rt=float(rt[g_apex]),
                scan_idx=g_apex,
                intensity=float(tic[g_apex]),
                rt_start=left_rt,
                rt_end=right_rt,
            )
        )

    return events


def _find_peaks_top_n_by_prominence(
    tic: np.ndarray,
    *,
    target: int,
    distance: int,
    expected_width_samples: int = 1,
    split_wide: bool = True,
    max_neighbor_gap_samples: float = np.inf,
) -> np.ndarray:
    """Find candidate peaks at a low prominence floor, optionally split wide
    multi-modal peaks and drop isolated carryover peaks, then keep top-N
    by prominence.
    """
    if target <= 0:
        return np.array([], dtype=int)

    floor = 0.001 * float(tic.max())
    peaks_idx, props = find_peaks(tic, prominence=floor, distance=distance)
    proms = props["prominences"]

    if peaks_idx.size == 0:
        return peaks_idx

    # Step 1: split wide / multi-modal peaks (adds candidates in dense
    # regions where adjacent injections merged into a single bump).
    if split_wide and expected_width_samples >= 2:
        peaks_idx, proms = _split_wide_peaks(
            tic, peaks_idx, proms,
            expected_width_samples=expected_width_samples,
            distance_samples=distance,
        )

    # Step 2: narrow down to a slightly larger pool than the target by
    # prominence so low-prominence noise doesn't pollute the isolation
    # filter or the final selection.
    if len(peaks_idx) > target and target > 0:
        pool_size = min(
            len(peaks_idx),
            max(target + 5, int(target * 1.3)),
        )
        top_idx = np.argpartition(proms, -pool_size)[-pool_size:]
        peaks_idx = peaks_idx[top_idx]
        proms = proms[top_idx]
        order = np.argsort(peaks_idx)
        peaks_idx = peaks_idx[order]
        proms = proms[order]

    # Step 3: drop peaks whose nearest neighbour is farther than the
    # absolute "max neighbour gap" — these are stray detections in dead
    # zones between injection trains (carryover, noise spikes, etc.).
    if np.isfinite(max_neighbor_gap_samples) and len(peaks_idx) >= 2:
        peaks_idx, proms = _drop_isolated_peaks(
            peaks_idx, proms,
            max_neighbor_gap_samples=max_neighbor_gap_samples,
        )

    # Step 4: final top-N selection.
    if len(peaks_idx) > target:
        top_n = np.argpartition(proms, -target)[-target:]
        chosen = peaks_idx[top_n]
        chosen.sort()
        return chosen

    if len(peaks_idx) > 0:
        order = np.argsort(peaks_idx)
        return peaks_idx[order]

    return peaks_idx


def _split_wide_peaks(
    tic: np.ndarray,
    peaks_idx: np.ndarray,
    proms: np.ndarray,
    *,
    expected_width_samples: int,
    distance_samples: int,
    sub_prominence_ratio: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Detect multi-modal peaks (merged adjacent injections) and split them.

    For every candidate peak, scan a window of +/- ``expected_width_samples``
    around the apex and re-run ``find_peaks`` with a tighter distance
    constraint. If two or more sub-peaks are found, each above
    ``sub_prominence_ratio`` of the local max, the original candidate is
    replaced with those sub-peaks. Otherwise the candidate passes through
    unchanged.

    There is no FWHM gate — even a peak with a small shoulder gets split
    if the shoulder is prominent enough on its own. Split sub-peaks
    inherit the parent's global prominence so they are not unfairly
    dropped by the downstream top-N selection.
    """
    if peaks_idx.size == 0:
        return peaks_idx, proms

    new_peaks: list[int] = []
    new_proms: list[float] = []

    # Sub-peaks within one merged event sit closer than the global
    # min-distance (otherwise find_peaks would already have split them).
    # Use ~1/4 of the expected peak width as the floor — two real
    # injections won't be closer than that.
    sub_distance = max(2, expected_width_samples // 4)
    # Look one expected-width on either side of the apex — enough to see
    # both halves of a merged double peak without leaking into neighbours.
    window_radius = max(expected_width_samples, 3)

    for i in range(len(peaks_idx)):
        p = int(peaks_idx[i])
        prom = float(proms[i])

        lo = max(0, p - window_radius)
        hi = min(len(tic), p + window_radius + 1)
        local = tic[lo:hi]

        if len(local) < 5:
            new_peaks.append(p)
            new_proms.append(prom)
            continue

        local_max = float(local.max())
        if local_max <= 0:
            new_peaks.append(p)
            new_proms.append(prom)
            continue

        sub_peaks, _ = find_peaks(
            local,
            distance=sub_distance,
            prominence=sub_prominence_ratio * local_max,
        )

        if len(sub_peaks) >= 2:
            for sp in sub_peaks:
                new_peaks.append(lo + int(sp))
                new_proms.append(prom)
        else:
            new_peaks.append(p)
            new_proms.append(prom)

    order = np.argsort(new_peaks)
    return (
        np.array(new_peaks, dtype=int)[order],
        np.array(new_proms, dtype=float)[order],
    )


def _drop_isolated_peaks(
    peaks_idx: np.ndarray,
    proms: np.ndarray,
    *,
    max_neighbor_gap_samples: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Remove peaks whose nearest neighbor is farther than
    ``max_neighbor_gap_samples`` away.

    Echo MS injections come in regularly-spaced trains. A peak with no
    close neighbours — for example a single bump in the middle of a
    minute-long dead zone — is almost certainly carryover or a noise
    spike rather than a real injection.

    First and last peaks each have only one neighbour; they are dropped
    only if that single neighbour is also beyond the threshold.
    """
    n = len(peaks_idx)
    if n < 2 or not np.isfinite(max_neighbor_gap_samples):
        return peaks_idx, proms

    order = np.argsort(peaks_idx)
    sorted_peaks = peaks_idx[order].astype(float)
    sorted_proms = proms[order]

    keep = np.ones(n, dtype=bool)
    for i in range(n):
        left = np.inf if i == 0 else (sorted_peaks[i] - sorted_peaks[i - 1])
        right = (
            np.inf
            if i == n - 1
            else (sorted_peaks[i + 1] - sorted_peaks[i])
        )
        if min(left, right) > max_neighbor_gap_samples:
            keep[i] = False

    return sorted_peaks[keep].astype(int), sorted_proms[keep]
