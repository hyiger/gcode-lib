from __future__ import annotations

import re
import struct
from typing import Dict, List, Tuple

__version__ = "1.1.1"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPS = 1e-9                    # Floating-point comparison tolerance
DEFAULT_ARC_SEG_MM = 0.20     # Max chord length (mm) per linearised arc segment
DEFAULT_ARC_MAX_DEG = 5.0     # Max sweep angle per linearised arc segment
DEFAULT_XY_DECIMALS = 3       # Output decimal places for X/Y axes
DEFAULT_OTHER_DECIMALS = 5    # Output decimal places for E/F/Z/I/J/K

# Pre-compiled regexes
_MOVE_RE = re.compile(r"^(G0|G1)\b", re.IGNORECASE)
_ARC_RE  = re.compile(r"^(G2|G3)\b", re.IGNORECASE)
_NUM_RE  = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_AXIS_RE = re.compile(rf"([XYZEFRIJK])\s*({_NUM_RE})", re.IGNORECASE)

# Binary .bgcode constants
_BGCODE_MAGIC = b"GCDE"
_BLK_FILE_METADATA    = 0
_BLK_GCODE            = 1
_BLK_SLICER_METADATA  = 2
_BLK_PRINTER_METADATA = 3
_BLK_PRINT_METADATA   = 4
_BLK_THUMBNAIL        = 5
_COMP_NONE              = 0
_COMP_DEFLATE           = 1
_COMP_HEATSHRINK_11_4   = 2   # window=2048 B, lookahead=16 B
_COMP_HEATSHRINK_12_4   = 3   # window=4096 B, lookahead=16 B
_ENC_RAW                = 0
_ENC_MEATPACK           = 1
_ENC_MEATPACK_COMMENTS  = 2

# Thumbnail image format codes (matching libbgcode EImageFormat)
_IMG_PNG = 0
_IMG_JPG = 1
_IMG_QOI = 2

# Map magic byte prefixes to format codes
_IMG_MAGIC: List[Tuple[bytes, int]] = [
    (b"\x89PNG", _IMG_PNG),
    (b"\xff\xd8", _IMG_JPG),
    (b"qoif",    _IMG_QOI),
]

# Map text keyword -> format code (case-insensitive match on keyword suffix)
_THUMB_KEYWORD_FMT: Dict[str, int] = {
    "thumbnail":     _IMG_PNG,
    "thumbnail_png": _IMG_PNG,
    "thumbnail_jpg": _IMG_JPG,
    "thumbnail_qoi": _IMG_QOI,
}
# Map format code -> keyword used when re-emitting plain-text thumbnails
_THUMB_FMT_KEYWORD: Dict[int, str] = {
    _IMG_PNG: "thumbnail",      # PrusaSlicer-compatible default for PNG
    _IMG_JPG: "thumbnail_JPG",
    _IMG_QOI: "thumbnail_QOI",
}
_THUMB_B64_LINE_LEN = 76        # base64 characters per comment line

# Regexes for plain-text thumbnail comment blocks
_THUMB_BEGIN_RE = re.compile(
    r"^;\s*(thumbnail(?:_\w+)?)\s+begin\s+(\d+)x(\d+)\s+(\d+)",
    re.IGNORECASE,
)
_THUMB_END_RE = re.compile(r"^;\s*thumbnail(?:_\w+)?\s+end\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Additional constants (bgcode write support)
# ---------------------------------------------------------------------------

# Minimal valid .bgcode v2 file header: magic + version(uint32) + checksum_type(uint16)
_BGCODE_VERSION = 2
_BGCODE_CHECKSUM_CRC32 = 1
_BGCODE_FILE_HDR_V2: bytes = (
    _BGCODE_MAGIC
    + struct.pack("<I", _BGCODE_VERSION)
    + struct.pack("<H", _BGCODE_CHECKSUM_CRC32)
)
