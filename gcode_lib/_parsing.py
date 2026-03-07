from __future__ import annotations

from typing import Dict, List, Tuple

from gcode_lib._constants import _AXIS_RE
from gcode_lib._types import GCodeLine


def split_comment(line: str) -> Tuple[str, str]:
    """Split a G-code line into ``(code, comment)`` at the first ``';'``.

    The comment string includes the leading ``";"`` if present.
    Trailing whitespace is stripped from the code portion.

    >>> split_comment("G1 X10 Y20 ; move to start")
    ('G1 X10 Y20', '; move to start')
    >>> split_comment("G1 X10 Y20")
    ('G1 X10 Y20', '')
    """
    if ";" in line:
        code, comment = line.split(";", 1)
        return code.rstrip(), ";" + comment
    return line.rstrip(), ""


def parse_words(code: str) -> Dict[str, float]:
    """Parse axis words from a G-code command string.

    Returns a ``{axis: value}`` dict for every recognised axis letter
    (X/Y/Z/E/F/I/J/K/R) found in *code*.  Letter keys are always uppercase.

    >>> parse_words("G1 X10.5 Y-3 E0.1")
    {'X': 10.5, 'Y': -3.0, 'E': 0.1}
    """
    return {m.group(1).upper(): float(m.group(2)) for m in _AXIS_RE.finditer(code)}


def parse_line(raw_line: str) -> GCodeLine:
    """Parse one line of G-code text into a :class:`GCodeLine`.

    The trailing newline is stripped before processing.
    """
    line = raw_line.rstrip("\n")
    code, comment = split_comment(line)
    s = code.strip()
    parts = s.split(None, 1)
    command = parts[0].upper() if parts else ""
    words = parse_words(code) if s else {}
    return GCodeLine(raw=line, command=command, words=words, comment=comment)


def parse_lines(text: str) -> List[GCodeLine]:
    """Parse a multi-line G-code string into a list of :class:`GCodeLine` objects."""
    return [parse_line(ln) for ln in text.splitlines()]
