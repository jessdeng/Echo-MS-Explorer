"""Extract XICs and mass spectra at specified RTs or RT windows."""

from __future__ import annotations

import numpy as np

from echo_ms_explorer.parser import MzmlData


def extract_xic(
    data: MzmlData,
    target_mz: float,
    *,
    mz_tolerance: float = 0.02,
    rt_window: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract an XIC (extracted ion chromatogram) for a target m/z.

    Args:
        data: Parsed mzML data.
        target_mz: Target m/z value.
        mz_tolerance: Absolute m/z tolerance window (target ± tolerance).
        rt_window: Optional (rt_start, rt_end) in seconds to limit the trace.
            If None, returns the full run.

    Returns:
        Tuple of (rt_array, intensity_array).
    """
    mz_low = target_mz - mz_tolerance
    mz_high = target_mz + mz_tolerance

    if rt_window is None:
        scan_indices = np.arange(data.n_scans)
    else:
        scan_indices = np.where(
            (data.rt >= rt_window[0]) & (data.rt <= rt_window[1])
        )[0]

    if scan_indices.size == 0:
        return np.array([]), np.array([])

    # Prefetch all scans in the window in one pass (much faster than
    # individual lazy hits when reading from the source mzML)
    data.prefetch_scans(scan_indices.tolist())

    rts = data.rt[scan_indices]
    intensities = np.zeros(scan_indices.size, dtype=np.float64)

    for j, i in enumerate(scan_indices):
        mz = data.mz_arrays[i]
        if mz.size == 0:
            continue
        # m/z arrays from msconvert peak-picked SCIEX data are sorted;
        # use searchsorted for O(log n) range lookup
        if mz[0] <= mz[-1]:  # sorted ascending (typical)
            lo = np.searchsorted(mz, mz_low, side="left")
            hi = np.searchsorted(mz, mz_high, side="right")
            if hi > lo:
                intensities[j] = data.intensity_arrays[i][lo:hi].sum()
        else:
            # Fallback for unsorted arrays
            mask = (mz >= mz_low) & (mz <= mz_high)
            if mask.any():
                intensities[j] = data.intensity_arrays[i][mask].sum()

    return rts, intensities


def extract_spectrum_at_rt(
    data: MzmlData,
    rt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the mass spectrum (m/z, intensity arrays) from the scan nearest to `rt`.

    Args:
        data: Parsed mzML data.
        rt: Target retention time (seconds).

    Returns:
        Tuple of (mz_array, intensity_array) for the closest scan.
    """
    idx = int(np.argmin(np.abs(data.rt - rt)))
    return data.mz_arrays[idx], data.intensity_arrays[idx]


def downsample_for_display(
    x: np.ndarray, y: np.ndarray, target_points: int = 2000
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample a long 1D trace for plotting while preserving peak shape.

    Uses min/max binning: each output bin emits both the min and max y-value
    within that bin. This preserves spikes that simple averaging would erase,
    which is essential for our use case where every TIC peak corresponds to
    an injection event.

    Returns:
        (x_out, y_out) with len ~ 2 * (target_points / 2) = target_points.
        Returns the input unchanged if it's already short enough.
    """
    n = len(x)
    if n <= target_points:
        return x, y

    # Each bin produces 2 points (min and max), so use half the target as bin count
    n_bins = target_points // 2
    bin_size = n // n_bins

    # Reshape into (n_bins, bin_size); drop trailing samples that don't fill a bin
    trimmed = n_bins * bin_size
    y_b = y[:trimmed].reshape(n_bins, bin_size)
    x_b = x[:trimmed].reshape(n_bins, bin_size)

    # For each bin, emit the (x, min_y) and (x, max_y) at the *position* of each extremum
    min_idx = y_b.argmin(axis=1)
    max_idx = y_b.argmax(axis=1)
    row_idx = np.arange(n_bins)

    x_min = x_b[row_idx, min_idx]
    y_min = y_b[row_idx, min_idx]
    x_max = x_b[row_idx, max_idx]
    y_max = y_b[row_idx, max_idx]

    # Interleave by x-position so the line draws correctly in order
    pairs_x = np.column_stack([x_min, x_max])
    pairs_y = np.column_stack([y_min, y_max])
    # Sort each pair by x so the line connects chronologically
    swap = pairs_x[:, 0] > pairs_x[:, 1]
    pairs_x[swap] = pairs_x[swap][:, ::-1]
    pairs_y[swap] = pairs_y[swap][:, ::-1]

    x_out = pairs_x.flatten()
    y_out = pairs_y.flatten()

    # Append any trailing samples we trimmed
    if trimmed < n:
        x_out = np.concatenate([x_out, x[trimmed:]])
        y_out = np.concatenate([y_out, y[trimmed:]])

    return x_out, y_out


def average_spectrum_over_window(
    data: MzmlData,
    rt_start: float,
    rt_end: float,
    *,
    mz_bin: float = 0.05,  
) -> tuple[np.ndarray, np.ndarray]:
    """Average the mass spectra across scans within an RT window."""
    scan_mask = (data.rt >= rt_start) & (data.rt <= rt_end)
    scan_indices = np.where(scan_mask)[0]

    if len(scan_indices) == 0:
        return np.array([]), np.array([])

    
    data.prefetch_scans(scan_indices.tolist())

    all_mz = np.concatenate([data.mz_arrays[i] for i in scan_indices])
    if all_mz.size == 0:
        return np.array([]), np.array([])

    mz_min, mz_max = float(all_mz.min()), float(all_mz.max())
    grid = np.arange(mz_min, mz_max + mz_bin, mz_bin)
    summed = np.zeros_like(grid)

    for i in scan_indices:
        mz = data.mz_arrays[i]
        intensity = data.intensity_arrays[i]
        if mz.size == 0:
            continue
        bin_idx = np.clip(((mz - mz_min) / mz_bin).astype(int), 0, len(grid) - 1)
        np.add.at(summed, bin_idx, intensity)

    mean_intensity = summed / len(scan_indices)

    max_int = mean_intensity.max() if mean_intensity.size > 0 else 0
    if max_int > 0:
        sig_mask = mean_intensity > 0.001 * max_int  # keep peaks > 0.1% of max
        grid = grid[sig_mask]
        mean_intensity = mean_intensity[sig_mask]

    return grid, mean_intensity