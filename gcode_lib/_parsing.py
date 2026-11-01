from __future__ import annotations

import re
from typing import Dict, List, Tuple

from gcode_lib._constants import _AXIS_RE
from gcode_lib._types import GCodeLine

_REPEATED_BLANKS_RE = re.compile(r"[ \t]{2,}")


def split_comment(line: str) -> Tuple[str, str]:
    """Split a G-code line into ``(code, comment)``.

    A ``';'`` outside parentheses starts a comment that runs to the end of the
    line.  ``(...)`` comments may nest, and an unclosed one runs to the end of
    the line; they are moved out of the code, wherever they appear, so that
    code handed to transforms only holds real words.  The comment string keeps
    each comment's delimiters.  Trailing whitespace is stripped from the code.

    >>> split_comment("G1 X10 Y20 ; move to start")
    ('G1 X10 Y20', '; move to start')
    >>> split_comment("G1 X10 Y20")
    ('G1 X10 Y20', '')
    >>> split_comment("G1 X10 (fast) Y20 ; move")
    ('G1 X10 Y20', '(fast) ; move')
    """
    if "(" not in line:
        if ";" in line:
            code, comment = line.split(";", 1)
            return code.rstrip(), ";" + comment
        return line.rstrip(), ""

    code_chars: List[str] = []
    comments: List[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(line):
        if depth == 0:
            if ch == ";":
                comments.append(line[i:])
                break
            if ch == "(":
                depth = 1
                start = i
                code_chars.append(" ")  # keeps the words either side of the comment apart
            else:
                code_chars.append(ch)
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                comments.append(line[start:i + 1])
    if depth > 0:
        comments.append(line[start:])

    code = _REPEATED_BLANKS_RE.sub(" ", "".join(code_chars)).strip()
    return code, " ".join(comments)


def parse_words(code: str) -> Dict[str, float]:
    """Parse axis words from a G-code command string.

    Returns a ``{axis: value}`` dict for every recognised axis letter
    (X/Y/Z/A/B/C/E/F/I/J/K/R) found in *code*.  Letter keys are always uppercase.

    >>> parse_words("G1 X10.5 Y-3 E0.1")
    {'X': 10.5, 'Y': -3.0, 'E': 0.1}
    """
    words_only, _ = split_comment(code)
    return {m.group(1).upper(): float(m.group(2)) for m in _AXIS_RE.finditer(words_only)}


def parse_line(raw_line: str) -> GCodeLine:
    """Parse one line of G-code text into a :class:`GCodeLine`.

    The trailing newline is stripped before processing.
    Both ``;`` and ``(…)`` comment styles are recognised.
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
