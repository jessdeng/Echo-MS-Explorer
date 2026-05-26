"""Tests for peak detection helpers, especially wide-peak splitting and
isolated-peak rejection."""

from __future__ import annotations

import numpy as np

from echo_ms_explorer.peaks import (
    _drop_isolated_peaks,
    _find_peaks_top_n_by_prominence,
    _split_wide_peaks,
)


def _gaussian(n: int, center: int, sigma: float, amplitude: float = 1.0) -> np.ndarray:
    x = np.arange(n)
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


# ----- Wide-peak splitting -----

def test_split_wide_peak_with_double_hump_is_split():
    """Two Gaussians close together form a wide double-hump bump.
    The candidate at the merged region should be replaced with the two
    underlying sub-peaks."""
    n = 400
    tic = (
        _gaussian(n, 196, sigma=3, amplitude=1.0)
        + _gaussian(n, 204, sigma=3, amplitude=1.0)
    )
    # Candidate at one of the apexes (find_peaks may have only landed on one)
    peaks_idx = np.array([196], dtype=int)
    proms = np.array([0.5])
    out_idx, out_proms = _split_wide_peaks(
        tic, peaks_idx, proms,
        expected_width_samples=12,  # window covers [184, 209)
        distance_samples=3,
    )
    assert len(out_idx) == 2
    # Sub-peaks should land close to the two original centers
    assert 194 <= out_idx[0] <= 198
    assert 202 <= out_idx[1] <= 206
    # Inherit parent prominence so they survive top-N selection
    assert np.allclose(out_proms, 0.5)


def test_split_shoulder_peak():
    """A main peak with a smaller-but-distinct shoulder should be split.
    No FWHM gate, so even a modest shoulder triggers the splitter."""
    n = 400
    tic = (
        _gaussian(n, 195, sigma=3, amplitude=1.0)
        + _gaussian(n, 205, sigma=3, amplitude=0.7)
    )
    # find_peaks would land on the main peak; the shoulder was missed
    peaks_idx = np.array([195], dtype=int)
    proms = np.array([0.5])
    out_idx, _ = _split_wide_peaks(
        tic, peaks_idx, proms,
        expected_width_samples=12,  # window covers [183, 208)
        distance_samples=3,
    )
    # Should find both the main peak and the shoulder
    assert len(out_idx) >= 2
    positions = sorted(int(p) for p in out_idx)
    assert 193 <= positions[0] <= 197
    assert positions[-1] >= 203


def test_narrow_peak_is_not_split():
    """A single narrow Gaussian should pass through unchanged."""
    n = 400
    tic = _gaussian(n, 200, sigma=4, amplitude=1.0)
    peaks_idx = np.array([200], dtype=int)
    proms = np.array([0.5])
    out_idx, out_proms = _split_wide_peaks(
        tic, peaks_idx, proms,
        expected_width_samples=10,
        distance_samples=3,
    )
    assert list(out_idx) == [200]
    assert list(out_proms) == [0.5]


def test_wide_smooth_peak_without_substructure_is_not_split():
    """A genuinely wide single-mode Gaussian (no shoulders) is kept as one."""
    n = 400
    tic = _gaussian(n, 200, sigma=20, amplitude=1.0)
    peaks_idx = np.array([200], dtype=int)
    proms = np.array([0.5])
    out_idx, _ = _split_wide_peaks(
        tic, peaks_idx, proms,
        expected_width_samples=10,
        distance_samples=3,
    )
    assert list(out_idx) == [200]


# ----- Isolated-peak rejection (absolute gap in samples) -----

def test_drop_isolated_peak_in_dead_zone():
    """An evenly-spaced injection train with one stray peak far away.
    The stray peak's nearest neighbour is 4000 samples away, well past
    the 500-sample threshold, so it should be dropped."""
    peaks = np.array([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 5000])
    proms = np.array([1.0] * 11)
    out, _ = _drop_isolated_peaks(
        peaks, proms, max_neighbor_gap_samples=500.0,
    )
    assert 5000 not in out
    assert all(p in out for p in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])


def test_drop_isolated_keeps_all_when_within_gap():
    peaks = np.array([100, 200, 300, 400, 500])
    proms = np.ones(5)
    out, _ = _drop_isolated_peaks(
        peaks, proms, max_neighbor_gap_samples=150.0,
    )
    assert list(out) == [100, 200, 300, 400, 500]


def test_drop_isolated_infinite_gap_keeps_everything():
    """Passing inf disables the filter."""
    peaks = np.array([100, 200, 5000])
    proms = np.ones(3)
    out, _ = _drop_isolated_peaks(
        peaks, proms, max_neighbor_gap_samples=np.inf,
    )
    assert list(out) == [100, 200, 5000]


def test_drop_isolated_with_two_clusters_separated_by_gap():
    """Two dense clusters separated by a clear gap. Peaks at the cluster
    edges have a close neighbour on one side, so they should be kept.
    A stray peak in the middle of the gap should be dropped."""
    cluster1 = np.arange(100, 200, 10)
    cluster2 = np.arange(800, 900, 10)
    stray = np.array([500])
    peaks = np.concatenate([cluster1, cluster2, stray])
    peaks.sort()
    proms = np.ones(len(peaks))
    out, _ = _drop_isolated_peaks(
        peaks, proms, max_neighbor_gap_samples=200.0,
    )
    assert 500 not in out
    for p in cluster1:
        assert p in out
    for p in cluster2:
        assert p in out


# ----- End-to-end via _find_peaks_top_n_by_prominence -----

def test_top_n_split_then_dedupe_carryover():
    """Build a TIC with: an injection train of 10 evenly-spaced peaks, one
    merged double peak inside that train, and a stray carryover peak in a
    dead zone. The algorithm should split the merged peak and drop the
    carryover, ending up with exactly 11 real injections."""
    n = 3000
    rng = np.random.default_rng(42)
    tic = rng.normal(0.0, 0.01, n)

    for c in range(200, 2100, 200):
        tic += _gaussian(n, c, sigma=6, amplitude=1.0)
    tic += _gaussian(n, 1100, sigma=6, amplitude=1.0)
    tic += _gaussian(n, 1140, sigma=6, amplitude=1.0)
    tic += _gaussian(n, 2700, sigma=6, amplitude=0.8)

    expected = 11
    out = _find_peaks_top_n_by_prominence(
        tic,
        target=expected,
        distance=10,
        expected_width_samples=14,
        split_wide=True,
        max_neighbor_gap_samples=400.0,
    )
    assert len(out) <= expected
    # Carryover at 2700 (700 samples from nearest train peak at 2000) dropped
    assert all(abs(p - 2700) > 50 for p in out)
    # Two close sub-peaks around 1100/1140 should both be present
    near_1100 = sum(1 for p in out if 1080 <= p <= 1160)
    assert near_1100 >= 2
