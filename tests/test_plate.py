"""Tests for the plate layout sequence generator and well assignment."""

from __future__ import annotations

from echo_ms_explorer.peaks import InjectionEvent
from echo_ms_explorer.plate import (
    PlateLayout,
    assign_peaks_to_replicates,
    assign_peaks_to_replicates_clustered,
    assign_peaks_to_wells,
    expand_with_replicates,
    parse_well_range_text,
    serpentine_order_over_selection,
    well_id_to_rowcol,
    well_replicate_id,
)


def test_well_id_parsing():
    assert well_id_to_rowcol("A1") == (0, 0)
    assert well_id_to_rowcol("a1") == (0, 0)
    assert well_id_to_rowcol("P24") == (15, 23)
    assert well_id_to_rowcol("H12") == (7, 11)


def test_serpentine_row_major_384():
    """384-well plate, A1 start, serpentine, row-major.

    Expected:
      Row A: A1 → A24
      Row B: B24 → B1  (reversed)
      Row C: C1 → C24
      ...
    """
    layout = PlateLayout(n_rows=16, n_cols=24, start_well="A1", serpentine=True, row_major=True)
    seq = layout.injection_sequence()

    assert len(seq) == 384
    # First row forward
    assert seq[0] == "A1"
    assert seq[23] == "A24"
    # Second row reversed
    assert seq[24] == "B24"
    assert seq[47] == "B1"
    # Third row forward again
    assert seq[48] == "C1"
    assert seq[71] == "C24"
    # Last cell (row P, 16th row, 0-indexed offset 15 → odd → reversed)
    assert seq[-24] == "P24"
    assert seq[-1] == "P1"


def test_raster_row_major_96():
    """96-well plate, no serpentine — every row left-to-right."""
    layout = PlateLayout(n_rows=8, n_cols=12, start_well="A1", serpentine=False, row_major=True)
    seq = layout.injection_sequence()

    assert len(seq) == 96
    assert seq[0] == "A1"
    assert seq[11] == "A12"
    assert seq[12] == "B1"  # not reversed
    assert seq[-1] == "H12"


def test_serpentine_column_major():
    """Column-major serpentine: traverse rows within a column, snake across columns."""
    layout = PlateLayout(n_rows=8, n_cols=12, start_well="A1", serpentine=True, row_major=False)
    seq = layout.injection_sequence()

    assert len(seq) == 96
    # First column top → bottom
    assert seq[0] == "A1"
    assert seq[7] == "H1"
    # Second column bottom → top
    assert seq[8] == "H2"
    assert seq[15] == "A2"


def test_explicit_used_wells_overrides_layout():
    layout = PlateLayout(used_wells=["B2", "D5", "P24"])
    assert layout.injection_sequence() == ["B2", "D5", "P24"]


def test_assignment_basic():
    events = [
        InjectionEvent(index=0, rt=1.0, scan_idx=10, intensity=100, rt_start=0.9, rt_end=1.1),
        InjectionEvent(index=1, rt=2.0, scan_idx=20, intensity=200, rt_start=1.9, rt_end=2.1),
        InjectionEvent(index=2, rt=3.0, scan_idx=30, intensity=300, rt_start=2.9, rt_end=3.1),
    ]
    layout = PlateLayout(used_wells=["A1", "A2", "A3"])
    assignment = assign_peaks_to_wells(events, layout)
    assert assignment["A1"].rt == 1.0
    assert assignment["A2"].rt == 2.0
    assert assignment["A3"].rt == 3.0


def test_assignment_handles_fewer_peaks_than_wells():
    events = [
        InjectionEvent(index=0, rt=1.0, scan_idx=10, intensity=100, rt_start=0.9, rt_end=1.1),
    ]
    layout = PlateLayout(used_wells=["A1", "A2", "A3"])
    assignment = assign_peaks_to_wells(events, layout)
    assert set(assignment.keys()) == {"A1"}


# ----- Tests for serpentine_order_over_selection -----

def test_serpentine_selection_contiguous_two_rows():
    """A1-A5 + B1-B5 should yield A1..A5 then B5..B1."""
    selected = ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5"]
    order = serpentine_order_over_selection(selected)
    assert order == ["A1", "A2", "A3", "A4", "A5", "B5", "B4", "B3", "B2", "B1"]


def test_serpentine_selection_jess_example():
    """Jess's real-world case: A1-A5, then A6-A12, then B12 backwards."""
    selected = [f"A{c}" for c in range(1, 13)] + [f"B{c}" for c in range(1, 13)]
    order = serpentine_order_over_selection(selected)
    assert order[:12] == [f"A{c}" for c in range(1, 13)]
    assert order[12:] == [f"B{c}" for c in range(12, 0, -1)]


def test_serpentine_selection_sparse_row():
    """Sparse selection: A1, A5, A10, then B-row should still serpentine correctly."""
    selected = ["A1", "A5", "A10", "B2", "B7"]
    order = serpentine_order_over_selection(selected)
    # Row A forward (column order)
    # Row B reversed (because it's the 2nd row with selections)
    assert order == ["A1", "A5", "A10", "B7", "B2"]


def test_serpentine_selection_three_rows_skip():
    """Selection spans rows A, C, E (skipping B and D) — alternation is by
    order-of-appearance, not by absolute row index."""
    selected = ["A1", "A2", "C1", "C2", "E1", "E2"]
    order = serpentine_order_over_selection(selected)
    # A is offset 0 → forward, C is offset 1 → reversed, E is offset 2 → forward
    assert order == ["A1", "A2", "C2", "C1", "E1", "E2"]


def test_serpentine_selection_unordered_input():
    """Input order doesn't matter — selection is reordered by serpentine logic."""
    selected = ["B3", "A5", "A1", "B1", "A3"]
    order = serpentine_order_over_selection(selected)
    assert order == ["A1", "A3", "A5", "B3", "B1"]


def test_serpentine_selection_empty():
    assert serpentine_order_over_selection([]) == []
    assert serpentine_order_over_selection(set()) == []


# ----- Tests for parse_well_range_text -----

def test_parse_range_basic():
    assert parse_well_range_text("A1-A5") == ["A1", "A2", "A3", "A4", "A5"]


def test_parse_range_mixed():
    """Mixed singles and ranges."""
    result = parse_well_range_text("A1-A5, A6-A12, B3, C1-C3")
    assert result == [
        "A1", "A2", "A3", "A4", "A5",
        "A6", "A7", "A8", "A9", "A10", "A11", "A12",
        "B3",
        "C1", "C2", "C3",
    ]


def test_parse_range_handles_separators():
    """Commas, semicolons, newlines, spaces all work as separators."""
    result = parse_well_range_text("A1; A2\nA3 A4")
    # Each of these should be parsed as separate tokens
    assert "A1" in result and "A2" in result and "A3" in result and "A4" in result


def test_parse_range_deduplicates():
    """Duplicate wells are removed, first occurrence wins."""
    result = parse_well_range_text("A1-A3, A2")
    assert result == ["A1", "A2", "A3"]


def test_parse_range_reversed_range():
    """B12-B1 should expand the same as B1-B12 (range is direction-agnostic)."""
    result = parse_well_range_text("B12-B1")
    assert result == [f"B{c}" for c in range(1, 13)]


def test_parse_range_rejects_cross_row():
    """A1-B5 spans two rows and should error."""
    import pytest
    with pytest.raises(ValueError, match="single row"):
        parse_well_range_text("A1-B5")


def test_parse_range_empty():
    assert parse_well_range_text("") == []
    assert parse_well_range_text("   ") == []


# ----- Tests for expand_with_replicates -----

def test_expand_grouped_replicates():
    """Grouped: each well injected N times in a row before moving on."""
    wells = ["A1", "A2", "A3"]
    result = expand_with_replicates(wells, n_replicates=3, pattern="grouped")
    assert result == [
        ("A1", 1), ("A1", 2), ("A1", 3),
        ("A2", 1), ("A2", 2), ("A2", 3),
        ("A3", 1), ("A3", 2), ("A3", 3),
    ]


def test_expand_interleaved_replicates():
    """Interleaved: full pass repeated N times."""
    wells = ["A1", "A2", "A3"]
    result = expand_with_replicates(wells, n_replicates=3, pattern="interleaved")
    assert result == [
        ("A1", 1), ("A2", 1), ("A3", 1),
        ("A1", 2), ("A2", 2), ("A3", 2),
        ("A1", 3), ("A2", 3), ("A3", 3),
    ]


def test_expand_no_replicates_is_identity():
    """n_replicates=1 should give one entry per well, replicate index 1."""
    wells = ["A1", "B2"]
    grouped = expand_with_replicates(wells, n_replicates=1, pattern="grouped")
    interleaved = expand_with_replicates(wells, n_replicates=1, pattern="interleaved")
    assert grouped == interleaved == [("A1", 1), ("B2", 1)]


def test_expand_empty_wells():
    assert expand_with_replicates([], n_replicates=3) == []


def test_expand_rejects_invalid_n():
    import pytest
    with pytest.raises(ValueError):
        expand_with_replicates(["A1"], n_replicates=0)


def test_expand_rejects_invalid_pattern():
    import pytest
    with pytest.raises(ValueError, match="Unknown"):
        expand_with_replicates(["A1"], pattern="random")


def test_assign_to_replicates_grouped():
    """Verify peaks land on the right (well, rep) pairs in grouped order."""
    events = [
        InjectionEvent(index=i, rt=float(i), scan_idx=i, intensity=100,
                       rt_start=float(i) - 0.1, rt_end=float(i) + 0.1)
        for i in range(6)
    ]
    sequence = expand_with_replicates(["A1", "A2"], n_replicates=3, pattern="grouped")
    assignment = assign_peaks_to_replicates(events, sequence)
    # A1 reps 1, 2, 3 should be the first three peaks
    assert assignment[("A1", 1)].rt == 0.0
    assert assignment[("A1", 2)].rt == 1.0
    assert assignment[("A1", 3)].rt == 2.0
    # A2 reps 1, 2, 3 should be the next three
    assert assignment[("A2", 1)].rt == 3.0
    assert assignment[("A2", 3)].rt == 5.0


def test_well_replicate_id_formatting():
    # Single replicate — just well_id
    assert well_replicate_id("A1", 1, 1) == "A1"
    # Multiple replicates — annotated
    assert well_replicate_id("A1", 1, 3) == "A1 (1/3)"
    assert well_replicate_id("B12", 2, 3) == "B12 (2/3)"


# ----- Cluster-aware assignment -----


def _event(idx: int, rt: float) -> InjectionEvent:
    return InjectionEvent(
        index=idx, rt=rt, scan_idx=idx, intensity=100.0,
        rt_start=rt - 0.1, rt_end=rt + 0.1,
    )


def test_clustered_interleaved_restarts_at_next_pass_after_gap():
    """Interleaved: 2 wells, 3 reps = 6 expected peaks across passes.
    Pass 1 has only 1 peak (instead of 2), then a >gap, then 3 peaks.
    The 1-peak cluster should be flagged. The next cluster's first
    peak should restart at the next pass boundary — i.e., well A1
    rep 2, not continue with A2 rep 1."""
    wells = ["A1", "A2"]
    seq = expand_with_replicates(wells, n_replicates=3, pattern="interleaved")
    # Sequence: (A1,1), (A2,1), (A1,2), (A2,2), (A1,3), (A2,3)

    events = [
        _event(0, 10.0),  # cluster 1: only 1 peak
        # gap (>60s)
        _event(1, 200.0),  # cluster 2 starts here
        _event(2, 210.0),
        _event(3, 220.0),
    ]
    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        events, seq,
        n_wells=2, n_replicates=3, pattern="interleaved",
        max_gap_sec=30.0,
    )

    # First peak goes to (A1, 1)
    assert assignments[("A1", 1)].rt == 10.0
    # After the gap, sequence pointer should snap forward to next pass
    # boundary (index 2), so the next peak gets (A1, 2) — NOT (A2, 1).
    assert assignments[("A1", 2)].rt == 200.0
    assert assignments[("A2", 2)].rt == 210.0
    assert assignments[("A1", 3)].rt == 220.0
    # (A2, 1) and (A2, 3) should NOT be in assignments
    assert ("A2", 1) not in assignments

    # The 1-peak first cluster should produce a warning
    assert len(warnings) >= 1
    assert "Spectral group 1" in warnings[0]


def test_clustered_grouped_restarts_at_next_well_after_gap():
    """Grouped: 2 wells, 3 reps. First cluster has 2 peaks (incomplete
    well group), then a gap, then 3 peaks. Cluster 2's first peak
    should restart at the next *well group* boundary."""
    wells = ["A1", "A2"]
    seq = expand_with_replicates(wells, n_replicates=3, pattern="grouped")
    # Sequence: (A1,1), (A1,2), (A1,3), (A2,1), (A2,2), (A2,3)

    events = [
        _event(0, 10.0),
        _event(1, 11.0),  # only 2 peaks in cluster 1 (incomplete)
        # gap
        _event(2, 100.0),
        _event(3, 101.0),
        _event(4, 102.0),
    ]
    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        events, seq,
        n_wells=2, n_replicates=3, pattern="grouped",
        max_gap_sec=30.0,
    )

    # Cluster 1 → first 2 of A1's reps
    assert assignments[("A1", 1)].rt == 10.0
    assert assignments[("A1", 2)].rt == 11.0
    # After gap, sequence pointer snaps to next well boundary (index 3 = A2,1)
    assert assignments[("A2", 1)].rt == 100.0
    assert assignments[("A2", 2)].rt == 101.0
    assert assignments[("A2", 3)].rt == 102.0
    # A1 rep 3 should be skipped — never assigned
    assert ("A1", 3) not in assignments
    # Cluster 1 size 2 isn't a multiple of n_replicates=3 → warning
    assert any("Spectral group 1" in w for w in warnings)


def test_clustered_clean_clusters_no_warning():
    """If every cluster's size is a clean multiple of the boundary unit,
    no warnings are emitted."""
    wells = ["A1", "A2"]
    seq = expand_with_replicates(wells, n_replicates=3, pattern="interleaved")

    events = [
        _event(0, 10.0), _event(1, 11.0),       # pass 1 (cluster 1)
        _event(2, 12.0), _event(3, 13.0),       # pass 2 (cluster 1)
        # gap
        _event(4, 100.0), _event(5, 101.0),     # pass 3 (cluster 2)
    ]
    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        events, seq,
        n_wells=2, n_replicates=3, pattern="interleaved",
        max_gap_sec=30.0,
    )

    assert len(warnings) == 0
    assert assignments[("A1", 1)].rt == 10.0
    assert assignments[("A2", 1)].rt == 11.0
    assert assignments[("A1", 2)].rt == 12.0
    assert assignments[("A2", 2)].rt == 13.0
    # Cluster 2 starts on the next pass boundary (index 4)
    assert assignments[("A1", 3)].rt == 100.0
    assert assignments[("A2", 3)].rt == 101.0


def test_clustered_single_cluster_no_warning():
    """No gap → no clusters → no warning, behaves like the sequential
    assignment."""
    wells = ["A1", "A2"]
    seq = expand_with_replicates(wells, n_replicates=3, pattern="interleaved")
    events = [_event(i, 10.0 + i) for i in range(5)]  # 5 peaks, 1 less than 6

    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        events, seq,
        n_wells=2, n_replicates=3, pattern="interleaved",
        max_gap_sec=30.0,
    )
    # Single cluster, missing 1 peak — but no warning because there's
    # only one cluster (warning is only meaningful for multi-cluster runs)
    assert len(warnings) == 0
    assert len(assignments) == 5
    # Last expected (A2, 3) is missing
    assert ("A2", 3) not in assignments


def test_clustered_empty_inputs():
    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        [], [],
        n_wells=2, n_replicates=3, pattern="interleaved",
        max_gap_sec=30.0,
    )
    assert assignments == {}
    assert warnings == []


def test_clustered_realistic_240_peaks_off_by_one():
    """Realistic scenario mirroring the user's case: 20 wells × 12 reps
    interleaved, with cluster 1 having 79 peaks (1 short of 80) and
    cluster 2 having 161 peaks. After cluster 1, the sequence pointer
    snaps to index 80 so cluster 2's first peak gets (A1, rep 5), not
    (last well, rep 4)."""
    wells = [f"A{i+1}" for i in range(20)]
    seq = expand_with_replicates(wells, n_replicates=12, pattern="interleaved")
    assert len(seq) == 240

    cluster1 = [_event(i, 60.0 + i * 0.4) for i in range(79)]      # 79 peaks
    cluster2_start_rt = cluster1[-1].rt + 90.0                     # >60s gap
    cluster2 = [
        _event(79 + i, cluster2_start_rt + i * 0.4) for i in range(161)
    ]
    events = cluster1 + cluster2

    assignments, warnings, _spectral_groups = assign_peaks_to_replicates_clustered(
        events, seq,
        n_wells=20, n_replicates=12, pattern="interleaved",
        max_gap_sec=30.0,
    )

    # First peak of cluster 2 should now be (A1, rep 5), not (A20, rep 4)
    first_c2 = cluster2[0]
    # Find which key maps to this event
    matched_keys = [k for k, v in assignments.items() if v is first_c2]
    assert len(matched_keys) == 1
    assert matched_keys[0] == ("A1", 5)
    # Both clusters had off-by-one counts → 2 warnings
    assert len(warnings) == 2
