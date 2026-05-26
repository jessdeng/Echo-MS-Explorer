"""mzML parsing with lazy m/z loading and a metadata cache.

This module loads only the per-scan metadata (RT + TIC + ms_level) up front,
which is fast even for very large mzML files. The m/z and intensity arrays
for any given scan are decoded lazily on first access and cached in memory.

A small index file is written next to the source mzML on first load
(``<file>.mzML.idx.npz``). Subsequent loads of the same file skip the
metadata pass entirely and read the index in milliseconds. The index is
invalidated automatically if the source file changes (size or mtime).

Public API:
    load_mzml(path) -> MzmlData
    MzmlData.rt              # np.ndarray of retention times in seconds
    MzmlData.tic             # np.ndarray of TIC per scan
    MzmlData.ms_levels       # np.ndarray of MS levels
    MzmlData.mz_arrays[i]    # lazy: triggers decode of scan i's m/z array
    MzmlData.intensity_arrays[i]  # lazy: same for intensity
    MzmlData.n_scans
    MzmlData.rt_min_max
"""

from __future__ import annotations

import base64
import json
import warnings
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pyteomics import mzml

# Numpress decoders — optional (only used if file has Numpress-compressed arrays)
try:
    import pynumpress
    _HAS_NUMPRESS = True
except ImportError:
    _HAS_NUMPRESS = False


# CV accession → decoder hint
_NUMPRESS_ACCESSIONS = {
    "MS:1002312",  # linear prediction
    "MS:1002313",  # positive integer
    "MS:1002314",  # short logged float
    "MS:1002746",  # linear + zlib
    "MS:1002747",  # positive integer + zlib
    "MS:1002748",  # short logged float + zlib
}


# ----- Index file (sidecar) versioning -----
_INDEX_VERSION = 2


# ============================================================================
# Lazy array views
# ============================================================================
class _LazyArrayList:
    """List-like object that decodes spectrum arrays on demand.

    Indexing this list (e.g. ``mz_arrays[i]``) calls back into the parent
    MzmlData to decode and cache scan ``i``'s m/z (or intensity) array.

    Iteration is supported but will trigger decode of every scan, so avoid
    iterating over this when possible.
    """

    __slots__ = ("_parent", "_kind")

    def __init__(self, parent: "MzmlData", kind: str):
        self._parent = parent
        self._kind = kind  # "mz" or "intensity"

    def __len__(self) -> int:
        return self._parent.n_scans

    def __getitem__(self, i: int) -> np.ndarray:
        return self._parent._get_array(i, self._kind)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


# ============================================================================
# MzmlData
# ============================================================================
@dataclass
class MzmlData:
    """Parsed mzML data with lazy spectrum access.

    Attributes (eager, loaded immediately):
        rt: Retention times in seconds.
        tic: Total ion current per scan.
        ms_levels: MS level per scan.
        source_file: Path to the source mzML file.

    Properties (lazy, decoded on first access):
        mz_arrays[i]: m/z array for scan i.
        intensity_arrays[i]: intensity array for scan i.
    """

    rt: np.ndarray
    tic: np.ndarray
    ms_levels: np.ndarray
    source_file: Path
    # Internal: per-scan offsets into the source mzML to find the spectrum element
    _scan_offsets: np.ndarray = field(repr=False, default_factory=lambda: np.array([]))
    _scan_ids: list[str] = field(repr=False, default_factory=list)
    _cache_mz: dict[int, np.ndarray] = field(repr=False, default_factory=dict)
    _cache_intensity: dict[int, np.ndarray] = field(repr=False, default_factory=dict)
    # Bounded cache size (per-array kind). Old entries evicted in FIFO order.
    _cache_limit: int = field(repr=False, default=2000)
    # Persistent pyteomics reader for fast random scan access (lazy-initialized)
    _reader: Any = field(repr=False, default=None)

    @property
    def n_scans(self) -> int:
        return len(self.rt)

    @property
    def rt_min_max(self) -> tuple[float, float]:
        if self.n_scans == 0:
            return 0.0, 0.0
        return float(self.rt[0]), float(self.rt[-1])

    @property
    def mz_arrays(self) -> _LazyArrayList:
        return _LazyArrayList(self, "mz")

    @property
    def intensity_arrays(self) -> _LazyArrayList:
        return _LazyArrayList(self, "intensity")

    def _get_reader(self):
        """Lazy-initialize and cache the pyteomics reader for fast random access."""
        if self._reader is None:
            # Build the reader once; it parses the offset index on construction.
            # All subsequent get_by_id calls reuse this index.
            self._reader = mzml.read(str(self.source_file), use_index=True)
        return self._reader

    def close(self) -> None:
        """Release the pyteomics reader and clear caches. Idempotent."""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
        self._cache_mz.clear()
        self._cache_intensity.clear()

    def _get_array(self, scan_idx: int, kind: str) -> np.ndarray:
        """Decode and cache the m/z or intensity array for one scan."""
        cache = self._cache_mz if kind == "mz" else self._cache_intensity
        if scan_idx in cache:
            return cache[scan_idx]

        reader = self._get_reader()
        scan_id = self._scan_ids[scan_idx]
        try:
            spectrum = reader.get_by_id(scan_id)
        except KeyError:
            empty = np.array([], dtype=np.float64)
            self._cache_mz[scan_idx] = empty
            self._cache_intensity[scan_idx] = empty
            return empty

        mz = _safe_get_array(spectrum, "m/z array")
        intensity = _safe_get_array(spectrum, "intensity array")

        # Cache both arrays since they come together for free
        self._evict_if_full(self._cache_mz)
        self._evict_if_full(self._cache_intensity)
        self._cache_mz[scan_idx] = mz
        self._cache_intensity[scan_idx] = intensity

        return mz if kind == "mz" else intensity

    def _evict_if_full(self, cache: dict) -> None:
        while len(cache) >= self._cache_limit:
            # Drop the oldest entry (Python 3.7+ dicts preserve insertion order)
            oldest = next(iter(cache))
            del cache[oldest]

    def prefetch_scans(self, scan_indices: list[int]) -> None:
        """Decode and cache a batch of scans up front (e.g. for an inspection window).

        Cheaper than calling mz_arrays[i] individually because we reuse the
        same pyteomics reader and its offset index.
        """
        wanted = [i for i in scan_indices if i not in self._cache_mz]
        if not wanted:
            return
        reader = self._get_reader()
        for scan_idx in wanted:
            try:
                spectrum = reader.get_by_id(self._scan_ids[scan_idx])
                mz = _safe_get_array(spectrum, "m/z array")
                intensity = _safe_get_array(spectrum, "intensity array")
                self._evict_if_full(self._cache_mz)
                self._evict_if_full(self._cache_intensity)
                self._cache_mz[scan_idx] = mz
                self._cache_intensity[scan_idx] = intensity
            except KeyError:
                continue


# ============================================================================
# Index file helpers (cache the metadata pass)
# ============================================================================
def _index_path_for(mzml_path: Path) -> Path:
    return mzml_path.with_suffix(mzml_path.suffix + ".idx.npz")


def _load_index(index_path: Path, source_path: Path) -> dict[str, Any] | None:
    """Return cached index if it exists and matches the source file, else None."""
    if not index_path.exists():
        return None
    try:
        with np.load(str(index_path), allow_pickle=False) as npz:
            meta = json.loads(str(npz["meta_json"]))
            if meta.get("version") != _INDEX_VERSION:
                return None
            if meta.get("source_size") != source_path.stat().st_size:
                return None
            if abs(meta.get("source_mtime", 0) - source_path.stat().st_mtime) > 1:
                return None
            return {
                "rt": npz["rt"],
                "tic": npz["tic"],
                "ms_levels": npz["ms_levels"],
                "scan_ids": meta["scan_ids"],
            }
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _write_index(index_path: Path, source_path: Path, data: dict[str, Any]) -> None:
    """Persist the metadata pass next to the source mzML."""
    meta = {
        "version": _INDEX_VERSION,
        "source_size": source_path.stat().st_size,
        "source_mtime": source_path.stat().st_mtime,
        "source_name": source_path.name,
        "scan_ids": data["scan_ids"],
    }
    try:
        np.savez_compressed(
            str(index_path),
            rt=data["rt"],
            tic=data["tic"],
            ms_levels=data["ms_levels"],
            meta_json=np.array(json.dumps(meta), dtype=str),
        )
    except OSError as e:
        # Cache is an optimization — failure to write should not break loading
        warnings.warn(f"Could not write index file {index_path.name}: {e}", stacklevel=2)


# ============================================================================
# Public loader
# ============================================================================
def load_mzml(path: str | Path, ms_level: int = 1) -> MzmlData:
    """Load an mzML file with lazy spectrum access.

    Args:
        path: Path to the .mzML file.
        ms_level: Which MS level to keep (default 1 for MS1 scans only).

    Returns:
        MzmlData with retention times, TIC, and on-demand m/z / intensity arrays.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"mzML file not found: {path}")

    index_path = _index_path_for(path)
    cached = _load_index(index_path, path)

    if cached is not None:
        # Fast path — index file is valid
        return MzmlData(
            rt=cached["rt"],
            tic=cached["tic"],
            ms_levels=cached["ms_levels"],
            source_file=path,
            _scan_offsets=np.array([]),  # unused, kept for backward compat
            _scan_ids=cached["scan_ids"],
        )

    # Slow path — first time loading this file, do the metadata pass
    rt, tic, ms_levels, scan_ids = _metadata_pass(path, ms_level=ms_level)

    if len(rt) == 0:
        raise ValueError(
            f"No MS{ms_level} scans found in {path.name}. "
            f"The file may be empty, use a different MS level, or be malformed."
        )

    data_dict = {
        "rt": rt,
        "tic": tic,
        "ms_levels": ms_levels,
        "scan_ids": scan_ids,
    }
    _write_index(index_path, path, data_dict)

    return MzmlData(
        rt=rt,
        tic=tic,
        ms_levels=ms_levels,
        source_file=path,
        _scan_offsets=np.array([]),
        _scan_ids=scan_ids,
    )


# ============================================================================
# Metadata pass — stream once, skip binary arrays
# ============================================================================
def _metadata_pass(
    path: Path, ms_level: int = 1
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Fast first pass: read RT, TIC, ms_level, and the scan ID for every scan.

    Skips binary array decoding entirely. We tell pyteomics not to decode the
    binary arrays (decode_binary=False), which is the main speedup.
    """
    rts: list[float] = []
    tics: list[float] = []
    levels: list[int] = []
    ids: list[str] = []

    skipped = 0

    with mzml.read(str(path), decode_binary=False) as reader:
        for spectrum in reader:
            try:
                level = int(spectrum.get("ms level", 1))
                if level != ms_level:
                    continue

                scan_time = _get_scan_time_seconds(spectrum)
                if scan_time is None:
                    skipped += 1
                    continue

                # TIC — usually present as a CV param
                tic_val = spectrum.get("total ion current")
                if tic_val is None:
                    # Without binary decoding, fall back to base peak intensity
                    # (better than nothing for peak detection)
                    tic_val = spectrum.get("base peak intensity", 0.0)
                tic_val = float(tic_val)

                rts.append(scan_time)
                tics.append(tic_val)
                levels.append(level)
                ids.append(str(spectrum.get("id", f"scan={len(ids) + 1}")))
            except Exception:
                skipped += 1
                continue

    if skipped:
        warnings.warn(
            f"Skipped {skipped} unparseable scan(s) during metadata pass.",
            stacklevel=2,
        )

    return (
        np.array(rts, dtype=np.float64),
        np.array(tics, dtype=np.float64),
        np.array(levels, dtype=np.int32),
        ids,
    )


# ============================================================================
# Binary array helpers
# ============================================================================
def _safe_get_array(spectrum: dict, key: str) -> np.ndarray:
    """Retrieve a binary array from a pyteomics spectrum, with fallbacks for
    SCIEX mzML quirks (Numpress, missing precision tags).
    """
    # Trust pyteomics first
    try:
        if key in spectrum:
            arr = spectrum[key]
            if isinstance(arr, np.ndarray) and arr.dtype.kind == "f":
                return arr.astype(np.float64, copy=False)
            if hasattr(arr, "__len__") and len(arr) > 0:
                return np.asarray(arr, dtype=np.float64)
    except (ValueError, TypeError):
        pass

    # Manual fallback: find the relevant binaryDataArray entry
    bda_list = _get_binary_data_array_list(spectrum)
    for bda in bda_list:
        if key not in bda:
            continue
        return _decode_binary_array(bda, spectrum)

    return np.array([], dtype=np.float64)


def _get_binary_data_array_list(spectrum: dict) -> list[dict]:
    bda = spectrum.get("binaryDataArrayList", {})
    if isinstance(bda, dict):
        inner = bda.get("binaryDataArray", [])
        return inner if isinstance(inner, list) else [inner]
    return []


def _decode_binary_array(bda: dict, spectrum: dict) -> np.ndarray:
    """Decode a single binaryDataArray dict, handling zlib + Numpress + precision."""
    raw_b64 = bda.get("binary")
    if not raw_b64:
        return np.array([], dtype=np.float64)
    if isinstance(raw_b64, bytes):
        raw_b64 = raw_b64.decode("ascii", errors="ignore")
    try:
        raw = base64.b64decode(raw_b64)
    except Exception:
        return np.array([], dtype=np.float64)

    # zlib decompression (separate from Numpress; some files do both)
    if "zlib compression" in bda and "MS-Numpress" not in str(bda):
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            return np.array([], dtype=np.float64)

    # Numpress
    if _HAS_NUMPRESS:
        if "MS-Numpress linear prediction compression followed by zlib compression" in bda:
            try:
                raw = zlib.decompress(raw)
                return np.asarray(pynumpress.decode_linear(raw), dtype=np.float64)
            except Exception:
                pass
        if "MS-Numpress positive integer compression followed by zlib compression" in bda:
            try:
                raw = zlib.decompress(raw)
                return np.asarray(pynumpress.decode_pic(raw), dtype=np.float64)
            except Exception:
                pass
        if "MS-Numpress short logged float compression followed by zlib compression" in bda:
            try:
                raw = zlib.decompress(raw)
                return np.asarray(pynumpress.decode_slof(raw), dtype=np.float64)
            except Exception:
                pass
        if "MS-Numpress linear prediction compression" in bda:
            try:
                return np.asarray(pynumpress.decode_linear(raw), dtype=np.float64)
            except Exception:
                pass
        if "MS-Numpress positive integer compression" in bda:
            try:
                return np.asarray(pynumpress.decode_pic(raw), dtype=np.float64)
            except Exception:
                pass
        if "MS-Numpress short logged float compression" in bda:
            try:
                return np.asarray(pynumpress.decode_slof(raw), dtype=np.float64)
            except Exception:
                pass

    # Plain precision-tagged float array
    expected_n = spectrum.get("defaultArrayLength")
    for precision_key, dtype, size in (
        ("64-bit float", np.float64, 8),
        ("32-bit float", np.float32, 4),
    ):
        if precision_key in bda and len(raw) % size == 0:
            return np.frombuffer(raw, dtype=dtype).astype(np.float64, copy=False)

    # Unknown precision: try by length match
    for dtype, size in ((np.float32, 4), (np.float64, 8)):
        if len(raw) % size != 0:
            continue
        n = len(raw) // size
        if expected_n is not None and n == int(expected_n):
            return np.frombuffer(raw, dtype=dtype).astype(np.float64, copy=False)

    return np.array([], dtype=np.float64)


def _get_scan_time_seconds(spectrum: dict) -> float | None:
    """Extract scan time from a pyteomics spectrum dict, returning seconds."""
    try:
        scan = spectrum["scanList"]["scan"][0]
    except (KeyError, IndexError):
        return None

    t = scan.get("scan start time")
    if t is None:
        return None

    unit = getattr(t, "unit_info", None) or ""
    val = float(t)
    if "minute" in unit.lower() or unit.lower() in ("min", "minutes"):
        return val * 60.0
    if "second" in unit.lower() or unit.lower() in ("s", "sec", "seconds"):
        return val
    return val * 60.0 if val < 60 else val
