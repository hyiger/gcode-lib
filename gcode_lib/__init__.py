"""gcode_lib — general-purpose G-code manipulation library.

Re-exports all public and test-accessed private symbols for backward
compatibility.  ``import gcode_lib as gl`` continues to work exactly as
before.
"""

from __future__ import annotations

# stdlib modules re-exported for backward-compat with mock.patch targets
import os  # noqa: F401  (tests patch gcode_lib.os.path.isfile)
import platform  # noqa: F401  (tests patch gcode_lib.platform)
import shutil  # noqa: F401  (tests patch gcode_lib.shutil.which)
import subprocess  # noqa: F401  (tests patch gcode_lib.subprocess.run)
from urllib.request import urlopen  # noqa: F401  (tests patch gcode_lib.urlopen)

# --- version ---------------------------------------------------------------
from gcode_lib._constants import __version__

# --- constants (public) ----------------------------------------------------
from gcode_lib._constants import (
    DEFAULT_ARC_MAX_DEG,
    DEFAULT_ARC_SEG_MM,
    DEFAULT_OTHER_DECIMALS,
    DEFAULT_XY_DECIMALS,
    EPS,
)

# --- constants (private, used by tests / integration) ----------------------
from gcode_lib._constants import (
    _ARC_RE,
    _AXIS_RE,
    _BGCODE_CHECKSUM_CRC32,
    _BGCODE_FILE_HDR_V2,
    _BGCODE_MAGIC,
    _BGCODE_VERSION,
    _BLK_FILE_METADATA,
    _BLK_GCODE,
    _BLK_PRINT_METADATA,
    _BLK_PRINTER_METADATA,
    _BLK_SLICER_METADATA,
    _BLK_THUMBNAIL,
    _COMP_DEFLATE,
    _COMP_HEATSHRINK_11_4,
    _COMP_HEATSHRINK_12_4,
    _COMP_NONE,
    _ENC_MEATPACK,
    _ENC_MEATPACK_COMMENTS,
    _ENC_RAW,
    _IMG_JPG,
    _IMG_MAGIC,
    _IMG_PNG,
    _IMG_QOI,
    _MOVE_RE,
    _NUM_RE,
    _THUMB_B64_LINE_LEN,
    _THUMB_BEGIN_RE,
    _THUMB_END_RE,
    _THUMB_FMT_KEYWORD,
    _THUMB_KEYWORD_FMT,
)

# --- data classes / types --------------------------------------------------
from gcode_lib._types import (
    Bounds,
    GCodeFile,
    GCodeLine,
    GCodeStats,
    ModalState,
    Thumbnail,
)

# --- parsing ---------------------------------------------------------------
from gcode_lib._parsing import parse_line, parse_lines, parse_words, split_comment

# --- state / formatting / arc geometry -------------------------------------
from gcode_lib._state import (
    advance_state,
    fmt_axis,
    fmt_float,
    is_extrusion_move,
    iter_arcs,
    iter_extruding,
    iter_moves,
    iter_with_state,
    linearize_arc_points,
    replace_or_append,
)
# Private arc helpers used internally
from gcode_lib._state import _arc_center, _arc_end_abs, _sweep_angle

# --- transforms, stats, OOB, layers ---------------------------------------
from gcode_lib._transforms import (
    OOBHit,
    analyze_xy_transform,
    apply_skew,
    apply_xy_transform,
    apply_xy_transform_by_layer,
    compute_bounds,
    compute_stats,
    find_oob_moves,
    iter_layers,
    linearize_arcs,
    max_oob_distance,
    recenter_to_bed,
    rotate_xy,
    to_absolute_xy,
    translate_xy,
    translate_xy_allow_arcs,
)
# Private OOB helpers used by tests
from gcode_lib._transforms import (
    _dist_to_segment,
    _min_dist_to_polygon_boundary,
    _point_in_polygon,
)

# --- bgcode ----------------------------------------------------------------
from gcode_lib._bgcode import (
    read_bgcode,
    write_bgcode,
)
# Private bgcode helpers used by tests
from gcode_lib._bgcode import (
    _bgcode_reassemble,
    _bgcode_split,
    _heatshrink_decompress,
    _is_bgcode_file,
    _load_bgcode,
    _meatpack_decode,
)

# --- I/O -------------------------------------------------------------------
from gcode_lib._io import (
    encode_thumbnail_comment_block,
    from_text,
    load,
    render_template,
    save,
    to_text,
)
# Private I/O helpers
from gcode_lib._io import _parse_text_thumbnails, _render_text_thumbnails

# --- PrusaSlicer CLI + INI -------------------------------------------------
from gcode_lib._prusaslicer import (
    PrusaSlicerCapabilities,
    RunResult,
    SliceRequest,
    find_prusaslicer_executable,
    inject_pa_into_start_gcode,
    pa_command,
    parse_prusaslicer_ini,
    probe_prusaslicer_capabilities,
    replace_ini_value,
    run_prusaslicer,
    slice_batch,
    slice_model,
)
# Private INI helpers used by tests
from gcode_lib._prusaslicer import (
    _ini_first_value,
    _ini_parse_bed_shape,
    _ini_parse_extrusion_width,
    _ini_parse_float,
    _ini_parse_int,
)

# --- PrusaLink API ---------------------------------------------------------
from gcode_lib._prusalink import (
    PrusaLinkError,
    PrusaLinkInfo,
    PrusaLinkJob,
    PrusaLinkStatus,
    prusalink_get_job,
    prusalink_get_status,
    prusalink_get_version,
    prusalink_upload,
)
# Private PrusaLink helpers used by tests
from gcode_lib._prusalink import _build_multipart, _prusalink_request

# --- presets, templates, thumbnails, slicer helpers, filename utils ---------
from gcode_lib._presets import (
    FILAMENT_PRESETS,
    KNOWN_PRINTERS,
    MBL_TEMP,
    PRINTER_PRESETS,
    PrinterGCode,
    ThumbnailSpec,
    build_thumbnail_block,
    compute_bed_center,
    compute_bed_shape,
    compute_m555,
    derive_slicer_dimensions,
    detect_print_volume,
    detect_printer_preset,
    flow_to_feedrate,
    gcode_ext,
    inject_thumbnails,
    parse_thumbnail_specs,
    patch_slicer_metadata,
    render_end_gcode,
    render_start_gcode,
    render_stl_to_png,
    resolve_filament_preset,
    resolve_printer,
    safe_filename_part,
    unique_suffix,
)
# Private presets helpers used by tests
from gcode_lib._presets import (
    _fallback_png,
    _find_slicer_meta_index,
    _find_thumbnail_insert_pos,
    _needs_subprocess_render,
    _rebuild_slicer_meta_block,
)
