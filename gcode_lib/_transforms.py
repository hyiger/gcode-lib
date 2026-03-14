"""Transforms, statistics, OOB detection, and layer iteration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from gcode_lib._constants import (
    DEFAULT_ARC_MAX_DEG,
    DEFAULT_ARC_SEG_MM,
    DEFAULT_OTHER_DECIMALS,
    DEFAULT_XY_DECIMALS,
    EPS,
)
from gcode_lib._types import Bounds, GCodeLine, GCodeStats, ModalState, PrintEstimate
from gcode_lib._parsing import parse_line, split_comment
from gcode_lib._state import (
    advance_state,
    fmt_axis,
    linearize_arc_points,
    replace_or_append,
)


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def linearize_arcs(
    lines: List[GCodeLine],
    seg_mm: float = DEFAULT_ARC_SEG_MM,
    max_deg: float = DEFAULT_ARC_MAX_DEG,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
) -> List[GCodeLine]:
    """Replace all G2/G3 arcs with equivalent G1 segments."""
    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()

    for line in lines:
        if not line.is_arc:
            result.append(line)
            advance_state(state, line)
            continue

        words = line.words
        cw  = (line.command.upper() == "G2")
        pts = linearize_arc_points(state, words, cw, seg_mm, max_deg)
        n   = len(pts)

        has_e = "E" in words
        e0    = state.e
        if has_e:
            if state.abs_e:
                e_end = words["E"]
                dE    = e_end - e0
            else:
                dE    = words["E"]
                e_end = e0 + dE
        else:
            dE    = 0.0
            e_end = e0

        has_f  = "F" in words
        f_word = words.get("F")
        has_z  = "Z" in words
        z_word = words.get("Z")

        e_accum = 0.0
        per_e   = round(dE / n, other_decimals) if (has_e and not state.abs_e and n > 0) else 0.0

        for i, (xi, yi) in enumerate(pts, start=1):
            parts = [
                "G1",
                f"X{fmt_axis('X', xi, xy_decimals, other_decimals)}",
                f"Y{fmt_axis('Y', yi, xy_decimals, other_decimals)}",
            ]

            if has_e:
                if state.abs_e:
                    t  = i / n
                    ei = (e0 + dE * t) if i < n else e_end
                else:
                    if i < n:
                        ei       = per_e
                        e_accum += ei
                    else:
                        ei = round(dE - e_accum, other_decimals)
                parts.append(f"E{fmt_axis('E', ei, xy_decimals, other_decimals)}")

            if has_z and z_word is not None and i == 1:
                parts.append(f"Z{fmt_axis('Z', z_word, xy_decimals, other_decimals)}")
            if has_f and f_word is not None and i == 1:
                parts.append(f"F{fmt_axis('F', f_word, xy_decimals, other_decimals)}")

            raw = " ".join(parts)
            seg_comment = (line.comment if i == 1 else "")
            if seg_comment:
                raw += " " + seg_comment.lstrip()

            new_words: Dict[str, float] = {"X": xi, "Y": yi}
            if has_e:
                new_words["E"] = ei  # type: ignore[possibly-undefined]
            if has_z and z_word is not None and i == 1:
                new_words["Z"] = z_word
            if has_f and f_word is not None and i == 1:
                new_words["F"] = f_word

            result.append(GCodeLine(
                raw=raw,
                command="G1",
                words=new_words,
                comment=seg_comment,
            ))

        # Advance state to arc endpoint
        if state.abs_xy:
            state.x = words.get("X", state.x)
            state.y = words.get("Y", state.y)
            state.z = words.get("Z", state.z)
        else:
            state.x += words.get("X", 0.0)
            state.y += words.get("Y", 0.0)
            state.z += words.get("Z", 0.0)
        if has_e:
            state.e = e_end
        if has_f and f_word is not None:
            state.f = f_word

    return result


def apply_xy_transform(
    lines: List[GCodeLine],
    fn: Callable[[float, float], Tuple[float, float]],
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Apply an arbitrary XY transform to all G0/G1 move endpoints."""
    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()

    for line in lines:
        if line.is_move and ("X" in line.words or "Y" in line.words):
            if not state.abs_xy:
                raise ValueError(
                    "apply_xy_transform: relative XY (G91) is not supported. "
                    "Ensure G90 is active or pre-process with to_absolute_xy()."
                )
            x_t = line.words.get("X", state.x)
            y_t = line.words.get("Y", state.y)

            if skip_negative_y and y_t < 0:
                result.append(line)
                advance_state(state, line)
                continue
            xs, ys = fn(x_t, y_t)

            code, comment = split_comment(line.raw)
            new_code = replace_or_append(code, "X", xs, xy_decimals, other_decimals)
            new_code = replace_or_append(new_code, "Y", ys, xy_decimals, other_decimals)
            for ax in ("Z", "E", "F"):
                if ax in line.words:
                    new_code = replace_or_append(
                        new_code, ax, line.words[ax], xy_decimals, other_decimals
                    )

            new_raw = new_code.rstrip() + ("" if not comment else " " + comment.lstrip())
            new_words = dict(line.words)
            new_words["X"] = xs
            new_words["Y"] = ys

            result.append(GCodeLine(
                raw=new_raw,
                command=line.command,
                words=new_words,
                comment=comment,
            ))

            state.x = x_t
            state.y = y_t
            if "Z" in line.words:
                state.z = line.words["Z"]
            if "E" in line.words:
                state.e = (line.words["E"] if state.abs_e
                           else state.e + line.words["E"])
            if "F" in line.words:
                state.f = line.words["F"]
        else:
            result.append(line)
            advance_state(state, line)

    return result


def apply_skew(
    lines: List[GCodeLine],
    skew_deg: float,
    y_ref: float = 0.0,
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Apply XY skew correction to all G0/G1 move endpoints."""
    k = math.tan(math.radians(skew_deg))
    return apply_xy_transform(
        lines,
        lambda x, y: (x + (y - y_ref) * k, y),
        xy_decimals=xy_decimals,
        other_decimals=other_decimals,
        initial_state=initial_state,
        skip_negative_y=skip_negative_y,
    )


def translate_xy(
    lines: List[GCodeLine],
    dx: float,
    dy: float,
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Translate all G0/G1 XY move endpoints by ``(dx, dy)``."""
    return apply_xy_transform(
        lines,
        lambda x, y: (x + dx, y + dy),
        xy_decimals=xy_decimals,
        other_decimals=other_decimals,
        initial_state=initial_state,
        skip_negative_y=skip_negative_y,
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_bounds(
    lines: List[GCodeLine],
    *,
    extruding_only: bool = False,
    include_arcs: bool = True,
    skip_negative_y: bool = False,
    arc_seg_mm: float = DEFAULT_ARC_SEG_MM,
    arc_max_deg: float = DEFAULT_ARC_MAX_DEG,
    initial_state: Optional[ModalState] = None,
) -> Bounds:
    """Compute XY/Z bounding box from a sequence of G-code lines."""
    bounds = Bounds()
    state  = initial_state.copy() if initial_state else ModalState()

    for line in lines:
        if line.is_move:
            if state.abs_xy:
                x1 = line.words.get("X", state.x)
                y1 = line.words.get("Y", state.y)
                z1 = line.words.get("Z", state.z)
            else:
                x1 = state.x + line.words.get("X", 0.0)
                y1 = state.y + line.words.get("Y", 0.0)
                z1 = state.z + line.words.get("Z", 0.0)

            if "X" in line.words or "Y" in line.words:
                is_ext = False
                if "E" in line.words:
                    e_w    = line.words["E"]
                    is_ext = (e_w > state.e) if state.abs_e else (e_w > 0.0)
                skip_y = skip_negative_y and y1 < 0
                if (not extruding_only or is_ext) and not skip_y:
                    bounds.expand(x1, y1)

            if "Z" in line.words:
                bounds.expand_z(z1)

            advance_state(state, line)

        elif line.is_arc and include_arcs:
            words  = line.words
            cw     = (line.command.upper() == "G2")
            pts    = linearize_arc_points(state, words, cw, arc_seg_mm, arc_max_deg)
            is_ext = False
            if "E" in words:
                e_w    = words["E"]
                is_ext = (e_w > state.e) if state.abs_e else (e_w > 0.0)
            if not extruding_only or is_ext:
                for xi, yi in pts:
                    if not (skip_negative_y and yi < 0):
                        bounds.expand(xi, yi)
            advance_state(state, line)

        else:
            advance_state(state, line)

    return bounds


def compute_stats(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> GCodeStats:
    """Compute a statistical summary of a G-code line sequence."""
    stats    = GCodeStats()
    state    = initial_state.copy() if initial_state else ModalState()
    seen_z:  List[float] = []
    seen_f:  List[float] = []
    seen_f_set: set = set()
    last_z:  Optional[float] = None

    for line in lines:
        stats.total_lines += 1

        if line.is_blank:
            stats.blank_lines += 1
            advance_state(state, line)
            continue

        if not line.command and line.comment:
            stats.comment_only_lines += 1
            advance_state(state, line)
            continue

        if line.is_move:
            stats.move_count += 1
            words = line.words

            if state.abs_xy:
                x1 = words.get("X", state.x)
                y1 = words.get("Y", state.y)
                z1 = words.get("Z", state.z)
            else:
                x1 = state.x + words.get("X", 0.0)
                y1 = state.y + words.get("Y", 0.0)
                z1 = state.z + words.get("Z", 0.0)

            if "X" in words or "Y" in words:
                stats.bounds.expand(x1, y1)

            if "Z" in words:
                stats.bounds.expand_z(z1)
                if last_z is None or abs(z1 - last_z) > EPS:
                    seen_z.append(z1)
                    last_z = z1

            if "F" in words:
                f = words["F"]
                if f not in seen_f_set:
                    seen_f.append(f)
                    seen_f_set.add(f)

            is_ext = False
            if "E" in words:
                e_word = words["E"]
                if state.abs_e:
                    dE     = e_word - state.e
                    is_ext = dE > 0
                    if is_ext:
                        stats.total_extrusion += dE
                    elif dE < -EPS:
                        stats.retract_count += 1
                else:
                    is_ext = e_word > 0.0
                    if is_ext:
                        stats.total_extrusion += e_word
                    elif e_word < -EPS:
                        stats.retract_count += 1

            if is_ext:
                stats.extrude_count += 1
            else:
                stats.travel_count += 1

        elif line.is_arc:
            stats.arc_count += 1
            words = line.words
            cw    = (line.command.upper() == "G2")
            pts   = linearize_arc_points(state, words, cw)

            for xi, yi in pts:
                stats.bounds.expand(xi, yi)

            if "Z" in words:
                if state.abs_xy:
                    z1 = words["Z"]
                else:
                    z1 = state.z + words["Z"]
                stats.bounds.expand_z(z1)
                if last_z is None or abs(z1 - last_z) > EPS:
                    seen_z.append(z1)
                    last_z = z1

            if "F" in words:
                f = words["F"]
                if f not in seen_f_set:
                    seen_f.append(f)
                    seen_f_set.add(f)

            is_ext = False
            if "E" in words:
                e_word = words["E"]
                if state.abs_e:
                    dE     = e_word - state.e
                    is_ext = dE > 0
                    if is_ext:
                        stats.total_extrusion += dE
                    elif dE < -EPS:
                        stats.retract_count += 1
                else:
                    is_ext = e_word > 0.0
                    if is_ext:
                        stats.total_extrusion += e_word
                    elif e_word < -EPS:
                        stats.retract_count += 1

            if is_ext:
                stats.extrude_count += 1
            else:
                stats.travel_count += 1

        advance_state(state, line)

    stats.z_heights = seen_z
    stats.feedrates  = seen_f
    return stats


_DEFAULT_FILAMENT_DENSITY = 1.24  # PLA, g/cm³


def estimate_print(
    lines: List[GCodeLine],
    filament_type: str = "PLA",
    filament_diameter: float = 1.75,
    filament_density: Optional[float] = None,
    initial_state: Optional[ModalState] = None,
) -> PrintEstimate:
    """Estimate print time and filament usage from a G-code line sequence.

    Parameters
    ----------
    lines:             Parsed G-code lines.
    filament_type:     Filament preset name for density lookup (default ``"PLA"``).
    filament_diameter: Filament diameter in mm (default 1.75).
    filament_density:  Explicit density in g/cm³; overrides *filament_type* lookup.
    initial_state:     Optional starting modal state.

    Returns
    -------
    PrintEstimate
        Estimated time (seconds), filament length (metres), and weight (grams).
    """
    # Resolve density: explicit > preset lookup > PLA default
    if filament_density is not None:
        density = filament_density
    else:
        from gcode_lib._presets import FILAMENT_PRESETS
        preset = FILAMENT_PRESETS.get(filament_type.upper())
        density = float(preset["density"]) if preset and "density" in preset else _DEFAULT_FILAMENT_DENSITY

    state = initial_state.copy() if initial_state else ModalState()
    total_time_min = 0.0
    total_extrusion_mm = 0.0

    for line in lines:
        if line.is_move:
            words = line.words

            # Resolve target position
            if state.abs_xy:
                x1 = words.get("X", state.x)
                y1 = words.get("Y", state.y)
                z1 = words.get("Z", state.z)
            else:
                x1 = state.x + words.get("X", 0.0)
                y1 = state.y + words.get("Y", 0.0)
                z1 = state.z + words.get("Z", 0.0)

            # Feedrate: use word if present, else last modal feedrate
            f = words.get("F", state.f)

            # 3D distance
            dist = math.sqrt(
                (x1 - state.x) ** 2 + (y1 - state.y) ** 2 + (z1 - state.z) ** 2
            )

            # Accumulate time (F is mm/min)
            if f is not None and f > 0 and dist > 0:
                total_time_min += dist / f

            # Accumulate extrusion
            if "E" in words:
                e_word = words["E"]
                if state.abs_e:
                    dE = e_word - state.e
                else:
                    dE = e_word
                if dE > 0:
                    total_extrusion_mm += dE

        elif line.is_arc:
            words = line.words
            cw = line.command.upper() == "G2"
            pts = linearize_arc_points(state, words, cw)

            # Feedrate for arc
            f = words.get("F", state.f)

            # Sum segment distances through linearised arc points
            prev_x, prev_y = state.x, state.y
            arc_dist = 0.0
            for xi, yi in pts:
                arc_dist += math.sqrt((xi - prev_x) ** 2 + (yi - prev_y) ** 2)
                prev_x, prev_y = xi, yi

            # Add Z component if present
            if "Z" in words:
                if state.abs_xy:
                    dz = words["Z"] - state.z
                else:
                    dz = words.get("Z", 0.0)
                arc_dist = math.sqrt(arc_dist ** 2 + dz ** 2)

            if f is not None and f > 0 and arc_dist > 0:
                total_time_min += arc_dist / f

            # Accumulate extrusion
            if "E" in words:
                e_word = words["E"]
                if state.abs_e:
                    dE = e_word - state.e
                else:
                    dE = e_word
                if dE > 0:
                    total_extrusion_mm += dE

        advance_state(state, line)

    # Convert units
    filament_length_m = total_extrusion_mm / 1000.0

    # Weight: length(mm) * cross-section area(mm²) * density(g/cm³) * (1 cm³ / 1000 mm³)
    radius_mm = filament_diameter / 2.0
    cross_section_mm2 = math.pi * radius_mm ** 2
    # density is g/cm³ = g/1000mm³, so weight = length_mm * area_mm² * density / 1000
    filament_weight_g = total_extrusion_mm * cross_section_mm2 * density / 1000.0

    return PrintEstimate(
        time_seconds=total_time_min * 60.0,
        filament_length_m=filament_length_m,
        filament_weight_g=filament_weight_g,
    )


# ---------------------------------------------------------------------------
# §4.1 — to_absolute_xy: G91 → G90 normalisation
# ---------------------------------------------------------------------------

def to_absolute_xy(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
) -> List[GCodeLine]:
    """Convert all G91 (relative XY) motion to absolute G90 equivalents."""
    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()
    found_g91 = False

    for line in lines:
        cmd = line.command

        if cmd == "G91":
            found_g91 = True
            advance_state(state, line)
            continue

        if (line.is_move or line.is_arc) and not state.abs_xy:
            words = line.words
            x_abs = state.x + words.get("X", 0.0)
            y_abs = state.y + words.get("Y", 0.0)
            z_abs = state.z + words.get("Z", 0.0)

            code, comment = split_comment(line.raw)
            new_code = code
            if "X" in words:
                new_code = replace_or_append(new_code, "X", x_abs, xy_decimals, other_decimals)
            if "Y" in words:
                new_code = replace_or_append(new_code, "Y", y_abs, xy_decimals, other_decimals)
            if "Z" in words:
                new_code = replace_or_append(new_code, "Z", z_abs, xy_decimals, other_decimals)

            new_raw = new_code.rstrip() + ("" if not comment else " " + comment.lstrip())
            new_words = dict(words)
            if "X" in words: new_words["X"] = x_abs
            if "Y" in words: new_words["Y"] = y_abs
            if "Z" in words: new_words["Z"] = z_abs

            result.append(GCodeLine(raw=new_raw, command=cmd, words=new_words, comment=comment))

            state.x = x_abs
            state.y = y_abs
            state.z = z_abs
            if "E" in words:
                state.e = words["E"] if state.abs_e else state.e + words["E"]
            if "F" in words:
                state.f = words["F"]
        else:
            result.append(line)
            advance_state(state, line)

    if found_g91:
        result.insert(0, parse_line("G90"))

    return result


# ---------------------------------------------------------------------------
# §4.2 — translate_xy_allow_arcs
# ---------------------------------------------------------------------------

def translate_xy_allow_arcs(
    lines: List[GCodeLine],
    dx: float,
    dy: float,
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Translate XY by ``(dx, dy)``, handling G2/G3 arcs natively."""
    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()

    for line in lines:
        words = line.words
        has_xy = "X" in words or "Y" in words

        if (line.is_move or line.is_arc) and has_xy:
            if not state.abs_xy:
                raise ValueError(
                    "translate_xy_allow_arcs: relative XY (G91) is not supported. "
                    "Call to_absolute_xy() first."
                )

            y_eff = words.get("Y", state.y)
            if skip_negative_y and y_eff < 0:
                result.append(line)
                advance_state(state, line)
                continue

            code, comment = split_comment(line.raw)
            new_code = code

            if "X" in words:
                new_code = replace_or_append(
                    new_code, "X", words["X"] + dx, xy_decimals, other_decimals
                )
            if "Y" in words:
                new_code = replace_or_append(
                    new_code, "Y", words["Y"] + dy, xy_decimals, other_decimals
                )

            new_words = dict(words)
            if "X" in words: new_words["X"] = words["X"] + dx
            if "Y" in words: new_words["Y"] = words["Y"] + dy

            if line.is_arc and not state.ij_relative:
                if "I" in words:
                    new_words["I"] = words["I"] + dx
                    new_code = replace_or_append(
                        new_code, "I", new_words["I"], xy_decimals, other_decimals
                    )
                if "J" in words:
                    new_words["J"] = words["J"] + dy
                    new_code = replace_or_append(
                        new_code, "J", new_words["J"], xy_decimals, other_decimals
                    )

            new_raw = new_code.rstrip() + ("" if not comment else " " + comment.lstrip())

            result.append(GCodeLine(
                raw=new_raw, command=line.command, words=new_words, comment=comment
            ))
        else:
            result.append(line)

        advance_state(state, line)

    return result


# ---------------------------------------------------------------------------
# §4.2b — rotate_xy
# ---------------------------------------------------------------------------

def rotate_xy(
    lines: List[GCodeLine],
    angle_deg: float,
    *,
    pivot_x: Optional[float] = None,
    pivot_y: Optional[float] = None,
    bed_min_x: Optional[float] = None,
    bed_max_x: Optional[float] = None,
    bed_min_y: Optional[float] = None,
    bed_max_y: Optional[float] = None,
    margin: float = 0.0,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Rotate XY coordinates by *angle_deg* degrees (counter-clockwise positive)."""
    theta = math.radians(angle_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    if pivot_x is None or pivot_y is None:
        bounds = compute_bounds(
            lines, skip_negative_y=skip_negative_y,
            initial_state=initial_state,
        )
        if not bounds.valid:
            return list(lines)
        if pivot_x is None:
            pivot_x = bounds.center_x
        if pivot_y is None:
            pivot_y = bounds.center_y

    def _rot(x: float, y: float) -> Tuple[float, float]:
        dx = x - pivot_x
        dy = y - pivot_y
        return (pivot_x + dx * cos_t - dy * sin_t,
                pivot_y + dx * sin_t + dy * cos_t)

    def _rot_vec(i: float, j: float) -> Tuple[float, float]:
        return (i * cos_t - j * sin_t,
                i * sin_t + j * cos_t)

    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()

    for line in lines:
        words = line.words
        has_xy = "X" in words or "Y" in words

        if (line.is_move or line.is_arc) and has_xy:
            if not state.abs_xy:
                raise ValueError(
                    "rotate_xy: relative XY (G91) is not supported. "
                    "Call to_absolute_xy() first."
                )

            x_abs = words.get("X", state.x)
            y_abs = words.get("Y", state.y)

            if skip_negative_y and y_abs < 0:
                result.append(line)
                advance_state(state, line)
                continue

            xr, yr = _rot(x_abs, y_abs)

            code, comment = split_comment(line.raw)
            new_code = code
            new_words = dict(words)

            if "X" in words:
                new_words["X"] = xr
                new_code = replace_or_append(new_code, "X", xr, xy_decimals, other_decimals)
            if "Y" in words:
                new_words["Y"] = yr
                new_code = replace_or_append(new_code, "Y", yr, xy_decimals, other_decimals)

            if line.is_arc and ("I" in words or "J" in words):
                i_val = words.get("I", 0.0)
                j_val = words.get("J", 0.0)
                if state.ij_relative:
                    ir, jr = _rot_vec(i_val, j_val)
                else:
                    ir, jr = _rot(i_val, j_val)
                if "I" in words:
                    new_words["I"] = ir
                    new_code = replace_or_append(new_code, "I", ir, xy_decimals, other_decimals)
                if "J" in words:
                    new_words["J"] = jr
                    new_code = replace_or_append(new_code, "J", jr, xy_decimals, other_decimals)

            new_raw = new_code.rstrip() + ("" if not comment else " " + comment.lstrip())
            result.append(GCodeLine(
                raw=new_raw, command=line.command, words=new_words, comment=comment
            ))
        else:
            result.append(line)

        advance_state(state, line)

    has_bed = (bed_min_x is not None and bed_max_x is not None
               and bed_min_y is not None and bed_max_y is not None)
    if has_bed:
        rb = compute_bounds(
            result,
            skip_negative_y=skip_negative_y,
            initial_state=initial_state,
        )
        if rb.valid:
            avail_x = (bed_max_x - bed_min_x) - 2 * margin
            avail_y = (bed_max_y - bed_min_y) - 2 * margin
            if rb.width > avail_x + EPS or rb.height > avail_y + EPS:
                raise ValueError(
                    f"rotate_xy: rotated print ({rb.width:.2f} x {rb.height:.2f} mm) "
                    f"exceeds available bed area ({avail_x:.2f} x {avail_y:.2f} mm)."
                )
            bed_cx = (bed_min_x + bed_max_x) / 2
            bed_cy = (bed_min_y + bed_max_y) / 2
            dx = bed_cx - rb.center_x
            dy = bed_cy - rb.center_y
            if abs(dx) > EPS or abs(dy) > EPS:
                result = translate_xy_allow_arcs(
                    result, dx, dy,
                    xy_decimals=xy_decimals,
                    other_decimals=other_decimals,
                    initial_state=initial_state,
                    skip_negative_y=skip_negative_y,
                )

    return result


# ---------------------------------------------------------------------------
# §4.3 — Out-of-bounds detection
# ---------------------------------------------------------------------------

@dataclass
class OOBHit:
    """A move endpoint that lies outside the allowed bed polygon."""
    line_number: int
    x: float
    y: float
    distance_outside: float


def _point_in_polygon(x: float, y: float, polygon: List[Tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (Jordan curve theorem)."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Treat points on polygon edges as in-bounds.
        dx = xj - xi
        dy = yj - yi
        cross = (x - xi) * dy - (y - yi) * dx
        if abs(cross) <= EPS:
            if (
                min(xi, xj) - EPS <= x <= max(xi, xj) + EPS and
                min(yi, yj) - EPS <= y <= max(yi, yj) + EPS
            ):
                return True
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _dist_to_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Minimum distance from point ``(px, py)`` to line segment ``(ax,ay)-(bx,by)``."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < EPS * EPS:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_dist_to_polygon_boundary(
    x: float, y: float, polygon: List[Tuple[float, float]]
) -> float:
    """Minimum distance from ``(x, y)`` to any edge of *polygon*."""
    n = len(polygon)
    min_d = float("inf")
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        d = _dist_to_segment(x, y, ax, ay, bx, by)
        if d < min_d:
            min_d = d
    return min_d


def find_oob_moves(
    lines: List[GCodeLine],
    bed_polygon: List[Tuple[float, float]],
    initial_state: Optional[ModalState] = None,
) -> List[OOBHit]:
    """Return all G0/G1 move endpoints that fall outside *bed_polygon*."""
    if len(bed_polygon) < 3:
        raise ValueError("bed_polygon must contain at least 3 points")

    hits: List[OOBHit] = []
    state = initial_state.copy() if initial_state else ModalState()

    for idx, line in enumerate(lines):
        if line.is_move and ("X" in line.words or "Y" in line.words):
            if state.abs_xy:
                x = line.words.get("X", state.x)
                y = line.words.get("Y", state.y)
            else:
                x = state.x + line.words.get("X", 0.0)
                y = state.y + line.words.get("Y", 0.0)

            if not _point_in_polygon(x, y, bed_polygon):
                dist = _min_dist_to_polygon_boundary(x, y, bed_polygon)
                hits.append(OOBHit(line_number=idx, x=x, y=y, distance_outside=dist))

        advance_state(state, line)

    return hits


def max_oob_distance(
    lines: List[GCodeLine],
    bed_polygon: List[Tuple[float, float]],
    initial_state: Optional[ModalState] = None,
) -> float:
    """Return the maximum out-of-bounds distance across all moves."""
    hits = find_oob_moves(lines, bed_polygon, initial_state)
    return max((h.distance_outside for h in hits), default=0.0)


# ---------------------------------------------------------------------------
# §4.4 — recenter_to_bed
# ---------------------------------------------------------------------------

def recenter_to_bed(
    lines: List[GCodeLine],
    bed_min_x: float,
    bed_max_x: float,
    bed_min_y: float,
    bed_max_y: float,
    margin: float = 0.0,
    mode: str = "center",
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Centre or scale a print to fit within the specified bed extents."""
    if mode not in ("center", "fit"):
        raise ValueError(f"recenter_to_bed: mode must be 'center' or 'fit', got {mode!r}")

    bounds = compute_bounds(
        lines, skip_negative_y=skip_negative_y, initial_state=initial_state,
    )
    if not bounds.valid:
        return list(lines)

    bed_cx = 0.5 * (bed_min_x + bed_max_x)
    bed_cy = 0.5 * (bed_min_y + bed_max_y)

    if mode == "center":
        dx = bed_cx - bounds.center_x
        dy = bed_cy - bounds.center_y
        return translate_xy_allow_arcs(
            lines, dx, dy,
            xy_decimals=xy_decimals,
            other_decimals=other_decimals,
            initial_state=initial_state,
            skip_negative_y=skip_negative_y,
        )

    # "fit" mode
    avail_x = (bed_max_x - bed_min_x) - 2.0 * margin
    avail_y = (bed_max_y - bed_min_y) - 2.0 * margin
    if avail_x <= 0 or avail_y <= 0:
        raise ValueError("recenter_to_bed: bed area after margin is zero or negative")
    if bounds.width < EPS or bounds.height < EPS:
        raise ValueError(
            "recenter_to_bed: print has zero width or height — cannot fit-scale"
        )

    scale = min(avail_x / bounds.width, avail_y / bounds.height)
    px_c, py_c = bounds.center_x, bounds.center_y

    def _scale_to_bed(x: float, y: float) -> Tuple[float, float]:
        xs = bed_cx + (x - px_c) * scale
        ys = bed_cy + (y - py_c) * scale
        return xs, ys

    lines_for_fit = (
        linearize_arcs(
            lines,
            xy_decimals=xy_decimals,
            other_decimals=other_decimals,
            initial_state=initial_state,
        )
        if any(line.is_arc for line in lines)
        else lines
    )

    return apply_xy_transform(
        lines_for_fit, _scale_to_bed,
        xy_decimals=xy_decimals,
        other_decimals=other_decimals,
        initial_state=initial_state,
        skip_negative_y=skip_negative_y,
    )


# ---------------------------------------------------------------------------
# §4.5 — analyze_xy_transform
# ---------------------------------------------------------------------------

def analyze_xy_transform(
    lines: List[GCodeLine],
    transform_fn: Callable[[float, float], Tuple[float, float]],
    initial_state: Optional[ModalState] = None,
) -> Dict[str, object]:
    """Analyse the effect of *transform_fn* without modifying any lines."""
    max_dx = 0.0
    max_dy = 0.0
    max_disp = 0.0
    worst_line = -1
    move_count = 0

    state = initial_state.copy() if initial_state else ModalState()

    for idx, line in enumerate(lines):
        if line.is_move and ("X" in line.words or "Y" in line.words) and state.abs_xy:
            x_orig = line.words.get("X", state.x)
            y_orig = line.words.get("Y", state.y)
            x_new, y_new = transform_fn(x_orig, y_orig)

            adx = abs(x_new - x_orig)
            ady = abs(y_new - y_orig)
            disp = math.hypot(adx, ady)
            move_count += 1

            if adx > max_dx: max_dx = adx
            if ady > max_dy: max_dy = ady
            if disp > max_disp:
                max_disp = disp
                worst_line = idx

        advance_state(state, line)

    return {
        "max_dx": max_dx,
        "max_dy": max_dy,
        "max_displacement": max_disp,
        "line_number": worst_line,
        "move_count": move_count,
    }


# ---------------------------------------------------------------------------
# §4.6 — Layer iterator and per-layer transform
# ---------------------------------------------------------------------------

def iter_layers(
    lines: List[GCodeLine],
    initial_state: Optional[ModalState] = None,
) -> Iterator[Tuple[float, List[GCodeLine]]]:
    """Yield ``(z_height, layer_lines)`` for each distinct Z level."""
    state = initial_state.copy() if initial_state else ModalState()
    current_z: float = state.z
    current_group: List[GCodeLine] = []

    for line in lines:
        z_changes = False
        next_z = current_z
        if (line.is_move or line.is_arc) and "Z" in line.words:
            next_z = line.words["Z"] if state.abs_xy else state.z + line.words["Z"]
            if abs(next_z - current_z) > EPS:
                z_changes = True

        if z_changes and current_group:
            yield (current_z, current_group)
            current_group = []
            current_z = next_z

        current_group.append(line)
        advance_state(state, line)

    if current_group:
        yield (current_z, current_group)


def apply_xy_transform_by_layer(
    lines: List[GCodeLine],
    transform_fn: Callable[[float, float], Tuple[float, float]],
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    *,
    xy_decimals: int = DEFAULT_XY_DECIMALS,
    other_decimals: int = DEFAULT_OTHER_DECIMALS,
    initial_state: Optional[ModalState] = None,
    skip_negative_y: bool = True,
) -> List[GCodeLine]:
    """Apply *transform_fn* only to layers within ``[z_min, z_max]``."""
    result: List[GCodeLine] = []
    state = initial_state.copy() if initial_state else ModalState()
    current_z: float = state.z

    for line in lines:
        in_range = (
            (z_min is None or current_z >= z_min - EPS) and
            (z_max is None or current_z <= z_max + EPS)
        )

        if in_range and line.is_move and ("X" in line.words or "Y" in line.words):
            if not state.abs_xy:
                raise ValueError(
                    "apply_xy_transform_by_layer: relative XY (G91) is not supported. "
                    "Call to_absolute_xy() first."
                )
            x_orig = line.words.get("X", state.x)
            y_orig = line.words.get("Y", state.y)

            if skip_negative_y and y_orig < 0:
                result.append(line)
                advance_state(state, line)
                if "Z" in line.words:
                    current_z = line.words["Z"]
                continue
            x_new, y_new = transform_fn(x_orig, y_orig)

            code, comment = split_comment(line.raw)
            new_code = replace_or_append(code, "X", x_new, xy_decimals, other_decimals)
            new_code = replace_or_append(new_code, "Y", y_new, xy_decimals, other_decimals)
            for ax in ("Z", "E", "F"):
                if ax in line.words:
                    new_code = replace_or_append(
                        new_code, ax, line.words[ax], xy_decimals, other_decimals
                    )

            new_raw = new_code.rstrip() + ("" if not comment else " " + comment.lstrip())
            new_words = dict(line.words)
            new_words["X"] = x_new
            new_words["Y"] = y_new
            result.append(GCodeLine(
                raw=new_raw, command=line.command, words=new_words, comment=comment
            ))

            state.x = x_orig
            state.y = y_orig
            if "Z" in line.words:
                state.z = line.words["Z"]
                current_z = state.z
            if "E" in line.words:
                state.e = line.words["E"] if state.abs_e else state.e + line.words["E"]
            if "F" in line.words:
                state.f = line.words["F"]
        else:
            result.append(line)
            prev_z = state.z
            advance_state(state, line)
            if abs(state.z - prev_z) > EPS:
                current_z = state.z

    return result
