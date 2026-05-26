"""echo-ms-explorer — interactive viewer for SCIEX Echo MS acoustic ejection data."""

from echo_ms_explorer.parser import load_mzml, MzmlData
from echo_ms_explorer.peaks import detect_injections, InjectionEvent
from echo_ms_explorer.plate import (
    PlateLayout,
    assign_peaks_to_replicates,
    assign_peaks_to_replicates_clustered,
    assign_peaks_to_wells,
    expand_with_replicates,
    parse_well_range_text,
    serpentine_order_over_selection,
    split_events_into_spectral_groups,
    well_id_to_rowcol,
    well_replicate_id,
)
from echo_ms_explorer.extract import extract_xic, extract_spectrum_at_rt
from echo_ms_explorer.demo import generate_demo_data

__version__ = "0.1.0"

__all__ = [
    "load_mzml",
    "MzmlData",
    "detect_injections",
    "InjectionEvent",
    "PlateLayout",
    "assign_peaks_to_replicates",
    "assign_peaks_to_replicates_clustered",
    "assign_peaks_to_wells",
    "expand_with_replicates",
    "parse_well_range_text",
    "serpentine_order_over_selection",
    "split_events_into_spectral_groups",
    "well_id_to_rowcol",
    "well_replicate_id",
    "extract_xic",
    "extract_spectrum_at_rt",
    "generate_demo_data",
]
