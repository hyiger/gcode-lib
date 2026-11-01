"""Tests for gcode_lib parsing utilities: split_comment, parse_words, parse_line, parse_lines."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ---------------------------------------------------------------------------
# split_comment
# ---------------------------------------------------------------------------

def test_split_comment_with_comment():
    code, comment = gl.split_comment("G1 X10 Y20 ; move")
    assert code == "G1 X10 Y20"
    assert comment == "; move"


def test_split_comment_no_comment():
    code, comment = gl.split_comment("G1 X10 Y20")
    assert code == "G1 X10 Y20"
    assert comment == ""


def test_split_comment_only_comment():
    code, comment = gl.split_comment("; this is a comment")
    assert code == ""
    assert comment == "; this is a comment"


def test_split_comment_multiple_semicolons():
    code, comment = gl.split_comment("G1 X10 ; first ; second")
    assert code == "G1 X10"
    assert comment == "; first ; second"


def test_split_comment_strips_trailing_space_from_code():
    code, _ = gl.split_comment("G1 X10   ; comment")
    assert code == "G1 X10"


def test_split_comment_empty_line():
    code, comment = gl.split_comment("")
    assert code == ""
    assert comment == ""


def test_split_comment_blank_line():
    code, comment = gl.split_comment("   ")
    assert code == ""
    assert comment == ""


# ---------------------------------------------------------------------------
# parse_words
# ---------------------------------------------------------------------------

def test_parse_words_basic():
    d = gl.parse_words("G1 X10.5 Y-3 E0.1")
    assert d["X"] == pytest.approx(10.5)
    assert d["Y"] == pytest.approx(-3.0)
    assert d["E"] == pytest.approx(0.1)


def test_parse_words_keys_are_uppercase():
    d = gl.parse_words("g1 x5 y10")
    assert "X" in d
    assert "Y" in d


def test_parse_words_scientific_notation():
    d = gl.parse_words("G1 E1.5e-3")
    assert d["E"] == pytest.approx(1.5e-3)


@pytest.mark.parametrize(
    "code, expected",
    [
        pytest.param("G1 X10E1", {"X": 10.0, "E": 1.0}, id="uppercase-e-is-a-word"),
        pytest.param("G1 X10E1.5", {"X": 10.0, "E": 1.5}, id="uppercase-e-decimal"),
        pytest.param("G1 X10e1.5", {"X": 10.0, "E": 1.5}, id="lowercase-e-decimal"),
        pytest.param("G1 X1e2", {"X": 100.0}, id="lowercase-exponent"),
        pytest.param("G1 X1e+2 Y2e-1", {"X": 100.0, "Y": 0.2}, id="signed-exponents"),
    ],
)
def test_parse_words_separates_e_word_from_exponent(code, expected):
    assert gl.parse_words(code) == pytest.approx(expected)


def test_parse_words_with_ij():
    d = gl.parse_words("G2 X10 Y0 I5 J0")
    assert d["I"] == pytest.approx(5.0)
    assert d["J"] == pytest.approx(0.0)


def test_parse_words_feedrate():
    d = gl.parse_words("G1 X10 F3000")
    assert d["F"] == pytest.approx(3000.0)


def test_parse_words_empty():
    assert gl.parse_words("") == {}
    assert gl.parse_words("; comment only") == {}


def test_parse_words_no_axis_words():
    assert gl.parse_words("G28") == {}


def test_parse_words_all_axes():
    d = gl.parse_words("G2 X1 Y2 Z3 E4 F5 I6 J7 K8 R9")
    for axis in ("X", "Y", "Z", "E", "F", "I", "J", "K", "R"):
        assert axis in d


def test_parse_words_rotational_axes():
    d = gl.parse_words("G1 X10 Y20 A30 B45 C60")
    assert d["A"] == pytest.approx(30.0)
    assert d["B"] == pytest.approx(45.0)
    assert d["C"] == pytest.approx(60.0)


def test_parse_words_rotational_words_outside_moves_do_not_break_commands():
    assert gl.parse_line("M862.1 P0.4 A0 F1").command == "M862.1"


def test_parse_words_mixed_with_rotational():
    d = gl.parse_words("G1 X10 Y20 Z0.3 A90 B180 C270 E0.1 F3000")
    assert d["A"] == pytest.approx(90.0)
    assert d["B"] == pytest.approx(180.0)
    assert d["C"] == pytest.approx(270.0)
    assert d["E"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# parse_line
# ---------------------------------------------------------------------------

def test_parse_line_move():
    line = gl.parse_line("G1 X10 Y20 E1.0 ; extrude")
    assert line.command == "G1"
    assert line.words["X"] == pytest.approx(10.0)
    assert line.words["Y"] == pytest.approx(20.0)
    assert line.words["E"] == pytest.approx(1.0)
    assert line.comment == "; extrude"
    assert line.raw == "G1 X10 Y20 E1.0 ; extrude"


def test_parse_line_arc():
    line = gl.parse_line("G2 X5 Y5 I2 J0")
    assert line.command == "G2"
    assert line.is_arc


def test_parse_line_modal():
    line = gl.parse_line("G90")
    assert line.command == "G90"
    assert not line.is_move
    assert not line.is_arc


def test_parse_line_lowercase_normalised():
    line = gl.parse_line("g1 x5 y10")
    assert line.command == "G1"
    assert line.is_move


def test_parse_line_blank():
    line = gl.parse_line("")
    assert line.command == ""
    assert line.words == {}
    assert line.comment == ""
    assert line.is_blank


def test_parse_line_comment_only():
    line = gl.parse_line("; just a comment")
    assert line.command == ""
    assert line.comment == "; just a comment"
    assert not line.is_blank


def test_is_blank_true_for_comment_without_text():
    assert gl.parse_line(";").is_blank
    assert gl.parse_line(" ;  ").is_blank


def test_is_blank_false_for_command():
    assert not gl.parse_line("G1 X1").is_blank


def test_parse_line_strips_trailing_newline():
    line = gl.parse_line("G1 X10\n")
    assert line.raw == "G1 X10"


def test_parse_line_is_move_g0():
    assert gl.parse_line("G0 X10 Y20").is_move


def test_parse_line_is_move_g1():
    assert gl.parse_line("G1 X10 Y20 E0.5").is_move


def test_parse_line_is_arc_g2():
    assert gl.parse_line("G2 X5 Y5 I2 J0").is_arc


def test_parse_line_is_arc_g3():
    assert gl.parse_line("G3 X5 Y5 I-2 J0").is_arc


def test_parse_line_is_not_move_arc():
    assert not gl.parse_line("G2 X5 Y5 I2 J0").is_move
    assert not gl.parse_line("G1 X5 Y5").is_arc


# ---------------------------------------------------------------------------
# Parenthesised comments (RS-274)
# ---------------------------------------------------------------------------

def test_parse_paren_comment_only_has_no_command():
    line = gl.parse_line("(Exported by FreeCAD)")
    assert line.command == ""
    assert line.words == {}


def test_parse_paren_comment_does_not_leak_words():
    """Text inside parens like 'Surface006' must not produce a false E word."""
    line = gl.parse_line("(Begin operation: Surface006)")
    assert "E" not in line.words


def test_parse_paren_inline_ignored():
    line = gl.parse_line("G17 G90 (set absolute mode)")
    assert line.command == "G17"
    assert "E" not in line.words


def test_parse_paren_with_semicolon():
    line = gl.parse_line("G1 X10 (inline comment) F300 ; end")
    assert line.command == "G1"
    assert line.words["X"] == pytest.approx(10.0)
    assert line.words["F"] == pytest.approx(300.0)
    assert "E" not in line.words
    assert line.comment == "(inline comment) ; end"


def test_parse_paren_preserves_raw():
    line = gl.parse_line("(Begin operation: Surface006)")
    assert line.raw == "(Begin operation: Surface006)"


@pytest.mark.parametrize(
    "line, code, comment",
    [
        pytest.param("(Surface006)", "", "(Surface006)", id="whole-line"),
        pytest.param("G1 X10 (fast) Y20", "G1 X10 Y20", "(fast)", id="inline"),
        pytest.param("(a) G1 X1", "G1 X1", "(a)", id="leading"),
        pytest.param("G1 (a) X1 (b) Y2", "G1 X1 Y2", "(a) (b)", id="several"),
        pytest.param("(a ; b) G1 X1", "G1 X1", "(a ; b)", id="semicolon-inside"),
        pytest.param("G1 X1 (a) ; b (c", "G1 X1", "(a) ; b (c", id="paren-after-semicolon"),
        pytest.param("((E5)) G1 X1", "G1 X1", "((E5))", id="nested"),
        pytest.param("G1 X1 (open E5", "G1 X1", "(open E5", id="unclosed"),
        pytest.param("G1 X1 ) Y2 (c)", "G1 X1 ) Y2", "(c)", id="stray-close"),
        pytest.param("G1 X10(note)E1 Y20", "G1 X10 E1 Y20", "(note)", id="between-words"),
        pytest.param("G1(a)X1(b)(c)Y2", "G1 X1 Y2", "(a) (b) (c)", id="no-spaces-around"),
    ],
)
def test_split_comment_parentheses(line, code, comment):
    assert gl.split_comment(line) == (code, comment)


def test_split_comment_without_parens_keeps_spacing():
    assert gl.split_comment("  G1  X10 ; c") == ("  G1  X10", "; c")


@pytest.mark.parametrize(
    "line, command, words",
    [
        ("G1 X10 (move E5) Y20", "G1", {"X": 10.0, "Y": 20.0}),
        ("(a ; b) G1 X1", "G1", {"X": 1.0}),
        ("((E5)) G1 X1", "G1", {"X": 1.0}),
        ("G1 X1 (open E5", "G1", {"X": 1.0}),
        ("M117 Done (E9)", "M117", {}),
        ("G1 X10(note)E1 Y20", "G1", {"X": 10.0, "E": 1.0, "Y": 20.0}),
        ("G1(a)X1", "G1", {"X": 1.0}),
    ],
)
def test_parse_line_paren_comments_add_no_words(line, command, words):
    parsed = gl.parse_line(line)
    assert parsed.command == command
    assert parsed.words == words


def test_parse_words_ignores_comments():
    assert gl.parse_words("(Surface006)") == {}
    assert gl.parse_words("G1 X1 (E5) ; Y2") == {"X": 1.0}


def test_paren_comment_line_is_a_comment_not_blank():
    line = gl.parse_line("(Exported by FreeCAD)")
    assert line.comment == "(Exported by FreeCAD)"
    assert not line.is_blank


def test_paren_comment_counts_as_comment_only_line():
    stats = gl.compute_stats(gl.parse_lines("(Exported by FreeCAD)\nG1 X1 Y1"))
    assert stats.comment_only_lines == 1
    assert stats.blank_lines == 0


def test_paren_comment_survives_text_round_trip():
    text = "(header)\nG1 X1 (note) Y2 ; end\n"
    assert gl.to_text(gl.from_text(text)) == text


def test_translate_does_not_rewrite_word_inside_paren_comment():
    lines = gl.parse_lines("G90\nG1 (X5) X10 Y10")
    assert gl.translate_xy(lines, 100.0, 0.0)[1].raw == "G1 X110 Y10 (X5)"


def test_translate_rewrites_move_after_leading_paren_comment():
    lines = gl.parse_lines("G90\n(move from X0 Y0) G1 X10 Y20")
    moved = gl.translate_xy(lines, 5.0, 5.0)[1]
    assert moved.raw == "G1 X15 Y25 (move from X0 Y0)"


def test_translate_keeps_extrusion_when_comment_separates_words():
    lines = gl.parse_lines("G90\nG1 X10(note)E1 Y20")
    moved = gl.translate_xy(lines, 5.0, 5.0)[1]
    assert moved.raw == "G1 X15 E1 Y25 (note)"


def test_translate_writes_omitted_axis_outside_paren_comment():
    lines = gl.parse_lines("G90\nG1 X1 Y1\nG1 Y20 (from X5)")
    moved = gl.translate_xy(lines, 100.0, 0.0)[2]
    assert moved.raw.endswith("(from X5)")
    assert gl.parse_line(moved.raw).words["X"] == pytest.approx(101.0)


def test_translate_allow_arcs_does_not_rewrite_paren_comment():
    lines = gl.parse_lines("G90\nG1 X1 Y1\nG3 (X5) X0 Y10 I-10 J0")
    arc = next(ln for ln in gl.translate_xy_allow_arcs(lines, 100.0, 0.0) if ln.is_arc)
    assert arc.raw == "G3 X100 Y10 I-10 J0 (X5)"


def test_rotate_does_not_rewrite_paren_comment():
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 (I5) X0 Y10 I-10 J0")
    result = gl.rotate_xy(lines, 90.0, pivot_x=0.0, pivot_y=0.0)
    arc = gl.parse_line(next(ln for ln in result if ln.is_arc).raw)
    assert arc.comment == "(I5)"
    assert arc.words["I"] == pytest.approx(0.0, abs=1e-3)
    assert arc.words["J"] == pytest.approx(-10.0, abs=1e-3)


def test_to_absolute_does_not_rewrite_paren_comment():
    result = gl.to_absolute_xy(gl.parse_lines("G91\nG1 (X5) X1\nG1 (X5) X1"))
    assert result[2].raw == "G1 X2 (X5)"


def test_by_layer_does_not_rewrite_paren_comment():
    lines = gl.parse_lines("G90\nG1 (X5) X10 Y10")
    result = gl.apply_xy_transform_by_layer(lines, lambda x, y: (x + 100.0, y))
    assert result[1].raw == "G1 X110 Y10 (X5)"


def test_linearize_arcs_keeps_paren_comment_on_first_segment():
    lines = gl.parse_lines("G90\nG1 X10 Y0\nG3 X0 Y10 I-10 J0 (turn)")
    result = gl.linearize_arcs(lines)
    assert result[2].raw.endswith("(turn)")
    assert not any("(turn)" in line.raw for line in result[3:])


# ---------------------------------------------------------------------------
# parse_lines
# ---------------------------------------------------------------------------

def test_parse_lines_count():
    text = "G90\nM82\nG1 X10 Y20 E1.0\n"
    lines = gl.parse_lines(text)
    assert len(lines) == 3


def test_parse_lines_empty_string():
    assert gl.parse_lines("") == []


def test_parse_lines_preserves_order():
    text = "G90\nM82\nG1 X10\nG1 X20"
    lines = gl.parse_lines(text)
    assert lines[0].command == "G90"
    assert lines[1].command == "M82"
    assert lines[2].command == "G1"
    assert lines[3].command == "G1"
    assert lines[2].words["X"] == pytest.approx(10.0)
    assert lines[3].words["X"] == pytest.approx(20.0)


def test_parse_lines_blank_lines_preserved():
    text = "G90\n\nG1 X10"
    lines = gl.parse_lines(text)
    assert len(lines) == 3
    assert lines[1].is_blank
