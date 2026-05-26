"""Synthetic demo data for showcasing the app without exposing real samples.

``generate_demo_data()`` returns an in-memory ``MzmlData`` that mimics a
small SCIEX Echo MS run:

* 7.5 minutes of acquisition at 50 Hz (22 500 MS1 scans)
* 60 acoustic injections = 20 wells x 3 replicates, interleaved
* Two spectral groups separated by a ~70 s gap (so the burst-aware
  assignment + warning logic has something to highlight)
* Four detectable compound peaks per injection in positive ion mode
  (caffeine, acetaminophen, theobromine, L-phenylalanine), with slightly
  different intensities per well so the pivot-table export shows real
  variation across columns

Every m/z + intensity array is pre-populated in the ``MzmlData`` cache,
so no file system or pyteomics reader is ever touched.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from echo_ms_explorer.parser import MzmlData

# (name, [M+H]+ m/z, relative intensity)
_DEMO_COMPOUNDS = (
    ("Caffeine", 195.0877, 1.00),
    ("Acetaminophen", 152.0706, 0.60),
    ("Theobromine", 181.0720, 0.45),
    ("L-Phenylalanine", 166.0863, 0.30),
)


def generate_demo_data(rng_seed: int = 42) -> MzmlData:
    """Build a synthetic ``MzmlData`` ready to plug into the app.

    The returned object behaves like a real loaded mzML for every read
    path in the app: TIC plot, peak detection, XIC extraction, per-scan
    spectrum lookup and pivot-table integration all work without any
    file I/O.
    """
    rng = np.random.default_rng(rng_seed)

    # --- Acquisition timeline ---------------------------------------------
    sample_rate_hz = 50.0
    rt_max_s = 450.0
    n_scans = int(rt_max_s * sample_rate_hz)
    rt = np.linspace(0.05, rt_max_s, n_scans, dtype=np.float64)

    # --- Injection schedule (60 peaks across 2 spectral groups) -----------
    # Group 1 = passes 1 + 2 (40 injections, 5 s apart, RT 30–225 s)
    # Group 2 = pass 3      (20 injections, 5 s apart, RT 300–395 s)
    group1_rts = np.arange(30.0, 226.0, 5.0)
    group2_rts = np.arange(300.0, 396.0, 5.0)
    inj_rts = np.concatenate([group1_rts, group2_rts])
    assert inj_rts.size == 60

    # Per-well intensity multipliers so the pivot table shows variation.
    well_factor = np.array([0.55 + 0.045 * (i % 7) for i in range(20)])

    # --- Build the TIC ----------------------------------------------------
    sigma_s = 0.15  # peak half-width
    peak_height = 1.5e7
    baseline = 5e5

    tic = np.full(n_scans, baseline, dtype=np.float64)
    tic += 1.0e5 * rng.standard_normal(n_scans).clip(-2.5, 2.5)

    for i, ir in enumerate(inj_rts):
        scale = float(well_factor[i % 20])
        tic += peak_height * scale * np.exp(
            -0.5 * ((rt - ir) / sigma_s) ** 2
        )

    # --- Per-scan m/z + intensity arrays ---------------------------------
    # Outside any injection window the spectrum is empty; inside (+/- 1 s)
    # we emit the four compound peaks (with sub-ppm jitter) plus a few
    # random background ions.
    mz_per_scan: list[np.ndarray] = [
        np.array([], dtype=np.float64) for _ in range(n_scans)
    ]
    int_per_scan: list[np.ndarray] = [
        np.array([], dtype=np.float64) for _ in range(n_scans)
    ]

    for i, ir in enumerate(inj_rts):
        scale = float(well_factor[i % 20])
        window_mask = (rt >= ir - 1.0) & (rt <= ir + 1.0)
        for si in np.where(window_mask)[0]:
            shape = float(
                np.exp(-0.5 * ((rt[si] - ir) / sigma_s) ** 2)
            )
            mzs: list[float] = []
            ints: list[float] = []
            for _name, mz_val, rel_int in _DEMO_COMPOUNDS:
                mzs.append(mz_val + 0.001 * float(rng.standard_normal()))
                ints.append(rel_int * scale * 1.0e6 * shape)
            # Background ions
            n_bg = int(rng.integers(2, 6))
            for _ in range(n_bg):
                mzs.append(100.0 + 400.0 * float(rng.random()))
                ints.append(
                    scale * 5.0e4 * shape * float(rng.random())
                )
            order = np.argsort(mzs)
            mz_per_scan[si] = np.array(mzs, dtype=np.float64)[order]
            int_per_scan[si] = np.array(ints, dtype=np.float64)[order]

    # --- Wrap into MzmlData with everything pre-cached --------------------
    data = MzmlData(
        rt=rt,
        tic=tic,
        ms_levels=np.ones(n_scans, dtype=np.int32),
        source_file=Path("demo_synthetic.mzML"),
        _scan_ids=[f"scan={i + 1}" for i in range(n_scans)],
        _cache_limit=n_scans + 100,
    )
    for i in range(n_scans):
        data._cache_mz[i] = mz_per_scan[i]
        data._cache_intensity[i] = int_per_scan[i]
    return data


# Recommended app settings for the demo so peak detection just works
DEMO_WELLS: list[str] = [f"A{i + 1}" for i in range(20)]
DEMO_N_REPLICATES: int = 3
DEMO_REPLICATE_PATTERN: str = "interleaved"
DEMO_RT_START_MIN: float = 0.4
DEMO_RT_END_MIN: float = 7.0
DEMO_BASELINE_CPS: float = 7.5e5
DEMO_PEAK_WIDTH_SEC: float = 0.5
DEMO_MIN_SPACING_SEC: float = 1.0
