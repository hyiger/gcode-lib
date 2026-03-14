from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from gcode_lib._constants import _MOVE_RE, _ARC_RE


@dataclass
class ModalState:
    """G-code modal state, updated line-by-line during parsing.

    Tracks coordinate mode, extrusion mode, arc-centre mode, and the
    current absolute tool position.
    """
    abs_xy: bool = True          # True = G90 (absolute), False = G91 (relative)
    abs_e: bool = True           # True = M82 (absolute E), False = M83 (relative E)
    ij_relative: bool = True     # True = G91.1 (relative IJ), False = G90.1 (absolute IJ)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    e: float = 0.0
    f: Optional[float] = None

    def copy(self) -> "ModalState":
        """Return an independent copy of this state."""
        return ModalState(
            abs_xy=self.abs_xy,
            abs_e=self.abs_e,
            ij_relative=self.ij_relative,
            x=self.x, y=self.y, z=self.z,
            e=self.e, f=self.f,
        )


@dataclass
class GCodeLine:
    """A single parsed G-code line.

    Attributes
    ----------
    raw:     Original line text (trailing newline stripped).
    command: Uppercased command token (e.g. ``"G1"``, ``"M82"``), or ``""``
             for blank / comment-only lines.
    words:   Axis-word dict parsed from the code portion, e.g.
             ``{"X": 10.0, "Y": 20.0, "E": 1.5}``.
    comment: Comment portion including the leading ``";"``, or ``""``.
    """
    raw: str
    command: str
    words: Dict[str, float]
    comment: str

    @property
    def is_move(self) -> bool:
        """True if this is a G0 or G1 command."""
        return bool(_MOVE_RE.match(self.command))

    @property
    def is_arc(self) -> bool:
        """True if this is a G2 or G3 command."""
        return bool(_ARC_RE.match(self.command))

    @property
    def is_blank(self) -> bool:
        """True if the line carries no command and no meaningful comment."""
        return not self.command and not self.comment.strip("; \t")


@dataclass
class Thumbnail:
    """An image thumbnail from a G-code file (text or binary).

    ``params`` holds a 6-byte block (format uint16, width uint16, height
    uint16) following the libbgcode spec.  For thumbnails parsed from
    plain-text files the format code is inferred from the keyword
    (``thumbnail_JPG`` / ``thumbnail_QOI``) or from the decoded image magic
    bytes.  ``_raw_block`` is set only for .bgcode sources; it carries the
    verbatim block bytes used for lossless binary round-trips.
    """
    params: bytes        # 6-byte block params (fmt_code, width, height)
    data: bytes          # Decompressed / decoded image bytes
    _raw_block: bytes    # Full bgcode block bytes (b"" for text sources)

    @property
    def format_code(self) -> int:
        """Raw format code from the bgcode thumbnail block params."""
        return struct.unpack_from("<H", self.params, 0)[0]

    @property
    def width(self) -> int:
        """Image width in pixels."""
        return struct.unpack_from("<H", self.params, 2)[0]

    @property
    def height(self) -> int:
        """Image height in pixels."""
        return struct.unpack_from("<H", self.params, 4)[0]


@dataclass
class GCodeFile:
    """Parsed G-code file -- top-level container for this library.

    Attributes
    ----------
    lines:         All G-code lines in source order.
    thumbnails:    Thumbnail images (populated only for .bgcode sources).
    source_format: ``"text"`` or ``"bgcode"``.
    """
    lines: List[GCodeLine]
    thumbnails: List[Thumbnail]
    source_format: str                               # "text" | "bgcode"
    _bgcode_file_hdr: Optional[bytes] = field(default=None, repr=False)
    _bgcode_nongcode_blocks: Optional[List[bytes]] = field(default=None, repr=False)


@dataclass
class Bounds:
    """Axis-aligned bounding box computed from G-code move endpoints.

    Starts at +/-inf; call ``expand(x, y)`` to include points.  Check
    ``valid`` before reading coordinates when the input may be empty.
    """
    x_min: float = float("inf")
    x_max: float = float("-inf")
    y_min: float = float("inf")
    y_max: float = float("-inf")
    z_min: float = float("inf")
    z_max: float = float("-inf")

    @property
    def valid(self) -> bool:
        """True if at least one XY point has been added."""
        return self.x_min != float("inf")

    def expand(self, x: float, y: float) -> None:
        """Expand the XY box to include ``(x, y)``."""
        if x < self.x_min: self.x_min = x
        if x > self.x_max: self.x_max = x
        if y < self.y_min: self.y_min = y
        if y > self.y_max: self.y_max = y

    def expand_z(self, z: float) -> None:
        """Expand the Z range to include ``z``."""
        if z < self.z_min: self.z_min = z
        if z > self.z_max: self.z_max = z

    @property
    def width(self) -> float:
        """X extent ``(x_max - x_min)``, or 0.0 if not valid."""
        return self.x_max - self.x_min if self.valid else 0.0

    @property
    def height(self) -> float:
        """Y extent ``(y_max - y_min)``, or 0.0 if not valid."""
        return self.y_max - self.y_min if self.valid else 0.0

    @property
    def center_x(self) -> float:
        """X midpoint, or 0.0 if not valid."""
        return 0.5 * (self.x_min + self.x_max) if self.valid else 0.0

    @property
    def center_y(self) -> float:
        """Y midpoint, or 0.0 if not valid."""
        return 0.5 * (self.y_min + self.y_max) if self.valid else 0.0


@dataclass
class GCodeStats:
    """Statistical summary of a G-code line sequence."""
    total_lines: int = 0
    blank_lines: int = 0
    comment_only_lines: int = 0
    move_count: int = 0          # G0 + G1 total
    arc_count: int = 0           # G2 + G3 total
    travel_count: int = 0        # non-extruding moves
    extrude_count: int = 0       # moves with positive extrusion delta
    retract_count: int = 0       # moves with negative extrusion delta
    total_extrusion: float = 0.0
    bounds: Bounds = field(default_factory=Bounds)
    z_heights: List[float] = field(default_factory=list)   # unique Z values, in order
    feedrates: List[float] = field(default_factory=list)   # unique F values, in order

    @property
    def layer_count(self) -> int:
        """Approximate layer count (number of unique Z heights seen)."""
        return len(self.z_heights)


@dataclass
class PrintEstimate:
    """Estimated print time and filament usage.

    Attributes
    ----------
    time_seconds:      Estimated total print time in seconds.
    filament_length_m: Total filament consumed in metres.
    filament_weight_g: Total filament consumed in grams.
    """
    time_seconds: float = 0.0
    filament_length_m: float = 0.0
    filament_weight_g: float = 0.0

    @property
    def time_hms(self) -> str:
        """Format *time_seconds* as ``'XhYmZs'`` (e.g. ``'5h20m17s'``)."""
        total = int(self.time_seconds)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h{m}m{s}s"
        if m:
            return f"{m}m{s}s"
        return f"{s}s"


@dataclass
class OOBHit:
    """A move endpoint that lies outside the allowed bed polygon.

    Attributes
    ----------
    line_number:      0-based index of the offending line in the input list.
    x, y:             Absolute coordinates of the out-of-bounds point.
    distance_outside: Distance (mm) from the point to the nearest polygon edge.
    """
    line_number: int
    x: float
    y: float
    distance_outside: float
