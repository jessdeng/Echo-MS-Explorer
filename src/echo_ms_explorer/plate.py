"""Plate layout + assignment of detected injection peaks to wells.

Echo MS samples in serpentine (boustrophedon / S-pattern) order. This module
generates the well sequence given a user-configured layout and maps detected
peaks to wells by chronological order.
"""

from __future__ import annotations

from dataclasses import dataclass

from echo_ms_explorer.peaks import InjectionEvent

# Row labels for plates up to 1536-well (32 rows).
# 384-well uses A-P (16), 1536-well uses A-AF (32).
ROW_LETTERS = [
    "A", "B", "C", "D", "E", "F", "G", "H",
    "I", "J", "K", "L", "M", "N", "O", "P",
    "Q", "R", "S", "T", "U", "V", "W", "X",
    "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF",
]


@dataclass
class PlateLayout:
    """User-configured plate layout for assigning peaks to wells.

    Attributes:
        n_rows: Number of rows in use (typically 16 for 384-well, 8 for 96-well).
        n_cols: Number of columns in use (typically 24 for 384-well, 12 for 96-well).
        start_well: First well injected, e.g. 'A1'.
        serpentine: If True, alternate row direction (S-pattern). If False, raster (always left→right).
        row_major: If True, iterate columns within a row before moving to the next row.
            If False, iterate rows within a column (column-major). Echo MS is typically row-major.
        used_wells: Optional explicit list of wells in injection order. If provided, overrides
            n_rows/n_cols/start_well/serpentine/row_major. Use this for sparse plates where
            not all wells were injected.
    """

    n_rows: int = 16
    n_cols: int = 24
    start_well: str = "A1"
    serpentine: bool = True
    row_major: bool = True
    used_wells: list[str] | None = None

    def injection_sequence(self) -> list[str]:
        """Return the ordered list of wells in injection order."""
        if self.used_wells is not None:
            return list(self.used_wells)

        start_row, start_col = well_id_to_rowcol(self.start_well)
        if start_row >= self.n_rows or start_col >= self.n_cols:
            raise ValueError(
                f"start_well {self.start_well} is outside the configured "
                f"{self.n_rows}x{self.n_cols} plate."
            )

        wells: list[str] = []

        if self.row_major:
            for r_offset in range(self.n_rows):
                r = start_row + r_offset
                if r >= self.n_rows:
                    break
                # Serpentine: even-offset rows go forward, odd-offset rows go backward
                cols = (
                    range(self.n_cols)
                    if (not self.serpentine or r_offset % 2 == 0)
                    else range(self.n_cols - 1, -1, -1)
                )
                for c in cols:
                    wells.append(_rowcol_to_well_id(r, c))
        else:
            for c_offset in range(self.n_cols):
                c = start_col + c_offset
                if c >= self.n_cols:
                    break
                rows = (
                    range(self.n_rows)
                    if (not self.serpentine or c_offset % 2 == 0)
                    else range(self.n_rows - 1, -1, -1)
                )
                for r in rows:
                    wells.append(_rowcol_to_well_id(r, c))

        return wells


def well_id_to_rowcol(well_id: str) -> tuple[int, int]:
    """Convert a well ID like 'A1', 'P24', or 'AA1' to (row_index, col_index), both 0-based."""
    well_id = well_id.strip().upper()
    if len(well_id) < 2 or not well_id[0].isalpha():
        raise ValueError(f"Invalid well ID: {well_id!r}")
    # Split into alphabetic row prefix and numeric column suffix
    i = 0
    while i < len(well_id) and well_id[i].isalpha():
        i += 1
    row_letter = well_id[:i]
    col_str = well_id[i:]
    if row_letter not in ROW_LETTERS:
        raise ValueError(f"Row letter {row_letter!r} not supported (must be A–AF).")
    try:
        col_num = int(col_str)
    except ValueError as e:
        raise ValueError(f"Invalid column in well ID: {well_id!r}") from e
    return ROW_LETTERS.index(row_letter), col_num - 1


def _rowcol_to_well_id(row: int, col: int) -> str:
    return f"{ROW_LETTERS[row]}{col + 1}"


def serpentine_order_over_selection(
    selected_wells: list[str] | set[str],
    *,
    row_major: bool = True,
) -> list[str]:
    """Sort an arbitrary set of selected wells into Echo serpentine injection order.

    The Echo serpentines its path *within* whatever wells were chosen — it doesn't
    require contiguous rows. For example, given A1, A2, A3, B1, B2, B5, the
    injection order is A1, A2, A3, B5, B2, B1 (row A forward, row B reversed
    because it's the second row encountered, regardless of column gaps).

    Args:
        selected_wells: Iterable of well IDs (e.g. {"A1", "A5", "B12"}).
        row_major: If True, sweep across columns within each row. If False,
            sweep down rows within each column.

    Returns:
        Ordered list of well IDs in serpentine injection order.
    """
    if not selected_wells:
        return []

    # Parse into (row, col) tuples
    coords = [(well_id_to_rowcol(w), w) for w in selected_wells]

    if row_major:
        # Group by row, sort columns within each row, alternate direction
        rows_present = sorted({rc[0] for rc, _ in coords})
        ordered: list[str] = []
        for offset, r in enumerate(rows_present):
            wells_in_row = sorted(
                [(rc[1], w) for rc, w in coords if rc[0] == r],
                reverse=(offset % 2 == 1),
            )
            ordered.extend(w for _, w in wells_in_row)
        return ordered
    else:
        # Column-major: group by col, sort rows within each col, alternate
        cols_present = sorted({rc[1] for rc, _ in coords})
        ordered = []
        for offset, c in enumerate(cols_present):
            wells_in_col = sorted(
                [(rc[0], w) for rc, w in coords if rc[1] == c],
                reverse=(offset % 2 == 1),
            )
            ordered.extend(w for _, w in wells_in_col)
        return ordered


def parse_well_range_text(text: str) -> list[str]:
    """Parse a free-text well selection like 'A1-A5, A6-A12, B3, C1-C24'.

    Ranges are inclusive and expanded left-to-right within a row. Both single
    wells and ranges may be mixed, separated by commas, semicolons, or whitespace.

    Returns:
        Deduplicated list of well IDs in the order they were encountered.
    """
    if not text or not text.strip():
        return []

    # Normalize separators: commas, semicolons, newlines, and whitespace all split tokens
    import re
    tokens = [t for t in re.split(r"[,;\s]+", text) if t]

    result: list[str] = []
    seen: set[str] = set()

    for token in tokens:
        token = token.upper()
        if "-" in token:
            start, end = token.split("-", 1)
            r1, c1 = well_id_to_rowcol(start)
            r2, c2 = well_id_to_rowcol(end)
            if r1 != r2:
                raise ValueError(f"Range {token!r} must span a single row.")
            if c1 > c2:
                c1, c2 = c2, c1
            for c in range(c1, c2 + 1):
                w = _rowcol_to_well_id(r1, c)
                if w not in seen:
                    seen.add(w)
                    result.append(w)
        else:
            r, c = well_id_to_rowcol(token)
            w = _rowcol_to_well_id(r, c)
            if w not in seen:
                seen.add(w)
                result.append(w)

    return result


def expand_with_replicates(
    wells: list[str],
    *,
    n_replicates: int = 1,
    pattern: str = "grouped",
) -> list[tuple[str, int]]:
    """Expand a well sequence to account for replicate injections.

    Args:
        wells: Ordered list of well IDs (typically the output of
            `serpentine_order_over_selection`).
        n_replicates: How many times each well was injected.
        pattern: One of:
            - "grouped":   A1, A1, A1, A2, A2, A2, ...
              (each well injected N times in a row before moving on)
            - "interleaved": A1, A2, A3, ..., A1, A2, A3, ...
              (full pass repeated N times)

    Returns:
        List of (well_id, replicate_index) tuples in injection order. The
        replicate_index is 1-based.
    """
    if n_replicates < 1:
        raise ValueError("n_replicates must be >= 1")
    if pattern not in ("grouped", "interleaved"):
        raise ValueError(f"Unknown replicate pattern: {pattern!r}")
    if not wells:
        return []

    if pattern == "grouped":
        return [(w, rep + 1) for w in wells for rep in range(n_replicates)]
    else:  # interleaved
        return [(w, rep + 1) for rep in range(n_replicates) for w in wells]


def well_replicate_id(well_id: str, replicate_index: int, total_replicates: int) -> str:
    """Format a well + replicate index as a human-readable label.

    When total_replicates is 1, just returns the well_id unchanged.
    Otherwise returns e.g. 'A1 (1/3)'.
    """
    if total_replicates <= 1:
        return well_id
    return f"{well_id} ({replicate_index}/{total_replicates})"


def assign_peaks_to_wells(
    events: list[InjectionEvent],
    layout: PlateLayout,
) -> dict[str, InjectionEvent]:
    """Map detected injection events to wells by chronological order.

    Args:
        events: List of detected peaks, sorted by retention time.
        layout: Plate layout describing the injection sequence.

    Returns:
        Dict mapping well_id -> InjectionEvent. If fewer peaks were detected
        than expected wells, only the first N wells get an assignment. If more
        peaks were detected than wells, extra peaks are ignored.
    """
    sequence = layout.injection_sequence()
    n = min(len(events), len(sequence))
    return {sequence[i]: events[i] for i in range(n)}


def assign_peaks_to_replicates(
    events: list[InjectionEvent],
    injection_sequence: list[tuple[str, int]],
) -> dict[tuple[str, int], InjectionEvent]:
    """Map detected peaks to (well_id, replicate_index) pairs by chronological order.

    Args:
        events: List of detected peaks, sorted by retention time.
        injection_sequence: Output of `expand_with_replicates` — ordered list
            of (well_id, replicate_index) tuples representing the expected
            injection order.

    Returns:
        Dict mapping (well_id, replicate_index) -> InjectionEvent.
    """
    n = min(len(events), len(injection_sequence))
    return {injection_sequence[i]: events[i] for i in range(n)}


def split_events_into_spectral_groups(
    events: list["InjectionEvent"],
    *,
    max_gap_sec: float = 30.0,
) -> list[list["InjectionEvent"]]:
    """Group chronologically-ordered events into spectral_groups.

    A "spectral_group" is a continuous run of injections — Echo MS dispenses
    samples back-to-back, so a long RT gap means the operator paused or
    swapped plates. Any two consecutive events farther apart than
    ``max_gap_sec`` seconds start a new spectral_group.
    """
    if not events:
        return []
    spectral_groups: list[list["InjectionEvent"]] = [[events[0]]]
    for e in events[1:]:
        if e.rt - spectral_groups[-1][-1].rt > max_gap_sec:
            spectral_groups.append([e])
        else:
            spectral_groups[-1].append(e)
    return spectral_groups


def assign_peaks_to_replicates_clustered(
    events: list["InjectionEvent"],
    injection_sequence: list[tuple[str, int]],
    *,
    n_wells: int,
    n_replicates: int,
    pattern: str = "grouped",
    max_gap_sec: float = 30.0,
) -> tuple[
    dict[tuple[str, int], "InjectionEvent"],
    list[str],
    list[list["InjectionEvent"]],
]:
    """Assign peaks to wells with spectral-group-aware alignment.

    Detected peaks are grouped into "spectral_groups" — continuous runs of Echo
    MS injections separated by RT gaps larger than ``max_gap_sec``
    seconds. After each spectral_group, the well sequence is advanced to the
    next clean pass (interleaved) or well-group (grouped) boundary so
    the first peak after a gap maps to the start of the next pass
    instead of continuing sequentially across the gap.

    For interleaved replicates each pass injects every well exactly
    once, so a spectral_group's size should be a multiple of ``n_wells``. For
    grouped replicates each well is injected ``n_replicates`` times
    back-to-back, so a spectral_group's size should be a multiple of
    ``n_replicates``. Any spectral_group whose count does not divide cleanly is
    recorded as a warning string.

    Args:
        events: Chronologically ordered detected peaks.
        injection_sequence: Expected (well_id, replicate_index) order
            from ``expand_with_replicates``.
        n_wells: Number of unique selected wells.
        n_replicates: Number of replicate injections per well.
        pattern: "interleaved" or "grouped".
        max_gap_sec: Two consecutive peaks farther apart than this are
            treated as belonging to different spectral_groups.

    Returns:
        ``(assignments, warnings, spectral_groups)``:
          * ``assignments`` — maps ``(well_id, replicate_index)`` to its
            ``InjectionEvent``.
          * ``warnings`` — human-readable strings describing spectral_groups
            whose size did not match the expected boundary.
          * ``spectral_groups`` — list of spectral_groups, each a list of events in the
            order they were detected.
    """
    if pattern not in ("grouped", "interleaved"):
        raise ValueError(f"Unknown replicate pattern: {pattern!r}")

    if not events or not injection_sequence:
        return {}, [], []

    spectral_groups = split_events_into_spectral_groups(events, max_gap_sec=max_gap_sec)

    # Boundary unit: how many peaks make up one "natural" round.
    if pattern == "interleaved":
        boundary = max(1, n_wells)
        round_word = "pass"
    else:
        boundary = max(1, n_replicates)
        round_word = "well group"

    assignments: dict[tuple[str, int], "InjectionEvent"] = {}
    seq_idx = 0
    warnings: list[str] = []

    for sg_i, spectral_group in enumerate(spectral_groups):
        sg_size = len(spectral_group)
        remainder = sg_size % boundary
        if remainder != 0 and len(spectral_groups) > 1:
            rt_start = spectral_group[0].rt / 60.0
            rt_end = spectral_group[-1].rt / 60.0
            short_by = boundary - remainder
            warnings.append(
                f"Spectral group {sg_i + 1} (RT {rt_start:.2f}–{rt_end:.2f} "
                f"min) has {sg_size} peaks — expected a multiple "
                f"of {boundary} ({round_word} size). Either {remainder} "
                f"extra peak(s) in this spectral_group, or {short_by} missing; "
                f"check the highlighted region on the TIC."
            )

        for e in spectral_group:
            if seq_idx < len(injection_sequence):
                assignments[injection_sequence[seq_idx]] = e
            seq_idx += 1

        # After this spectral_group, snap the sequence pointer up to the next
        # clean boundary so the next spectral_group starts on a fresh round.
        if seq_idx % boundary != 0:
            seq_idx = ((seq_idx // boundary) + 1) * boundary

    return assignments, warnings, spectral_groups
