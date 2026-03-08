"""Tests for gcode_lib I/O: from_text, to_text, load, save, bgcode roundtrip."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gcode_lib as gl


# ---------------------------------------------------------------------------
# Helpers: build minimal valid .bgcode bytes (no dependency on gcode_lib internals)
# ---------------------------------------------------------------------------

def _make_bgcode(gcode_text: str, extra_blocks: list[bytes] = ()) -> bytes:
    MAGIC       = b"GCDE"
    BLK_GCODE   = 1
    COMP_NONE   = 0
    ENC_RAW     = 0

    file_hdr = MAGIC + struct.pack("<IH", 1, 1)
    payload  = gcode_text.encode("utf-8")
    hdr      = struct.pack("<HHI", BLK_GCODE, COMP_NONE, len(payload))
    params   = struct.pack("<H", ENC_RAW)
    cksum    = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum    = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum    = zlib.crc32(payload, cksum) & 0xFFFFFFFF
    gcode_block = hdr + params + payload + struct.pack("<I", cksum)
    return file_hdr + b"".join(extra_blocks) + gcode_block


def _make_meta_block(btype: int, content: bytes) -> bytes:
    COMP_NONE = 0
    ENC_INI   = 0
    hdr    = struct.pack("<HHI", btype, COMP_NONE, len(content))
    params = struct.pack("<H", ENC_INI)
    cksum  = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum  = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum  = zlib.crc32(content, cksum) & 0xFFFFFFFF
    return hdr + params + content + struct.pack("<I", cksum)


def _make_thumbnail_block(img_data: bytes, width: int = 16, height: int = 16, fmt: int = 0) -> bytes:
    BLK_THUMBNAIL = 5
    COMP_NONE     = 0
    hdr    = struct.pack("<HHI", BLK_THUMBNAIL, COMP_NONE, len(img_data))
    params = struct.pack("<HHH", width, height, fmt)
    cksum  = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum  = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum  = zlib.crc32(img_data, cksum) & 0xFFFFFFFF
    return hdr + params + img_data + struct.pack("<I", cksum)


# ---------------------------------------------------------------------------
# from_text / to_text
# ---------------------------------------------------------------------------

def test_from_text_returns_gcode_file():
    gf = gl.from_text("G90\nG1 X10 Y20\n")
    assert isinstance(gf, gl.GCodeFile)
    assert gf.source_format == "text"
    assert len(gf.lines) == 2


def test_from_text_empty():
    gf = gl.from_text("")
    assert gf.lines == []


def test_to_text_roundtrip():
    text = "G90\nM82\nG1 X10 Y20 E1.0\n"
    gf   = gl.from_text(text)
    out  = gl.to_text(gf)
    # Lines should be the same; to_text adds a trailing newline
    assert out == text


def test_to_text_trailing_newline():
    gf  = gl.from_text("G1 X10")
    out = gl.to_text(gf)
    assert out.endswith("\n")


def test_to_text_preserves_comments():
    text = "G1 X10 ; comment here\n"
    assert gl.to_text(gl.from_text(text)) == text


def test_to_text_empty_stays_empty():
    gf = gl.from_text("")
    assert gl.to_text(gf) == ""


# ---------------------------------------------------------------------------
# load — text files
# ---------------------------------------------------------------------------

def test_load_text_file(tmp_path):
    p = tmp_path / "test.gcode"
    p.write_text("G90\nG1 X10 Y20\n", encoding="utf-8")
    gf = gl.load(str(p))
    assert gf.source_format == "text"
    assert len(gf.lines) == 2


def test_load_text_file_line_content(tmp_path):
    p = tmp_path / "test.gcode"
    p.write_text("G1 X5 Y10 E0.5\n", encoding="utf-8")
    gf = gl.load(str(p))
    assert gf.lines[0].command == "G1"
    assert gf.lines[0].words["X"] == pytest.approx(5.0)


def test_load_rejects_binary_non_bgcode(tmp_path):
    p = tmp_path / "bad.bin"
    p.write_bytes(b"\x00\x01\x02\x03binary data")
    with pytest.raises(ValueError, match="binary"):
        gl.load(str(p))


# ---------------------------------------------------------------------------
# load — bgcode files
# ---------------------------------------------------------------------------

def test_load_bgcode_file(tmp_path):
    p = tmp_path / "test.bgcode"
    p.write_bytes(_make_bgcode("G90\nG1 X10\n"))
    gf = gl.load(str(p))
    assert gf.source_format == "bgcode"
    assert any(ln.command == "G1" for ln in gf.lines)


def test_load_bgcode_thumbnails_extracted(tmp_path):
    img = b"\xff\xd8\xff\xe0" + b"\x00" * 60   # fake JPEG-ish bytes
    thumb_block = _make_thumbnail_block(img, width=16, height=16, fmt=1)
    p = tmp_path / "test.bgcode"
    p.write_bytes(_make_bgcode("G1 X1\n", extra_blocks=[thumb_block]))
    gf = gl.load(str(p))
    assert len(gf.thumbnails) == 1
    assert gf.thumbnails[0].width == 16
    assert gf.thumbnails[0].height == 16
    assert gf.thumbnails[0].data == img


def test_load_bgcode_no_thumbnails(tmp_path):
    p = tmp_path / "test.bgcode"
    p.write_bytes(_make_bgcode("G1 X1\n"))
    gf = gl.load(str(p))
    assert gf.thumbnails == []


# ---------------------------------------------------------------------------
# save — text files
# ---------------------------------------------------------------------------

def test_save_text_file_roundtrip(tmp_path):
    text = "G90\nM82\nG1 X10 Y20 E1.0\n"
    gf   = gl.from_text(text)
    p    = tmp_path / "out.gcode"
    gl.save(gf, str(p))
    assert p.read_text(encoding="utf-8") == text


def test_save_text_creates_file(tmp_path):
    gf = gl.from_text("G1 X5\n")
    p  = tmp_path / "new.gcode"
    gl.save(gf, str(p))
    assert p.exists()


def test_save_text_is_atomic(tmp_path):
    """save() should not leave a .tmp file behind."""
    gf = gl.from_text("G1 X5\n")
    p  = tmp_path / "out.gcode"
    gl.save(gf, str(p))
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


# ---------------------------------------------------------------------------
# save — bgcode files
# ---------------------------------------------------------------------------

def test_save_bgcode_produces_valid_bgcode(tmp_path):
    raw = _make_bgcode("G90\nG1 X10 Y20\n")
    gf  = gl._load_bgcode(raw)
    p   = tmp_path / "out.bgcode"
    gl.save(gf, str(p))
    out = p.read_bytes()
    assert out[:4] == b"GCDE"


def test_save_bgcode_roundtrip_gcode_text(tmp_path):
    text = "G90\nM82\nG1 X10 Y20 E1.0\n"
    raw  = _make_bgcode(text)
    gf   = gl._load_bgcode(raw)
    p    = tmp_path / "out.bgcode"
    gl.save(gf, str(p))
    # Re-load and verify G-code content
    gf2 = gl.load(str(p))
    assert gf2.source_format == "bgcode"
    assert any(ln.command == "G1" for ln in gf2.lines)


def test_save_bgcode_preserves_meta_blocks(tmp_path):
    BLK_SLICER_META = 2
    meta = _make_meta_block(BLK_SLICER_META, b"key=value\n")
    raw  = _make_bgcode("G1 X5\n", extra_blocks=[meta])
    gf   = gl._load_bgcode(raw)
    p    = tmp_path / "out.bgcode"
    gl.save(gf, str(p))
    # Re-split and verify non-gcode blocks intact
    _, nongcode, _, _ = gl._bgcode_split(p.read_bytes())
    assert len(nongcode) == 1
    assert nongcode[0] == meta


def test_save_bgcode_preserves_thumbnail(tmp_path):
    img   = b"\x89PNG\r\n" + b"\x00" * 50
    tblk  = _make_thumbnail_block(img, width=32, height=32, fmt=0)
    raw   = _make_bgcode("G1 X1\n", extra_blocks=[tblk])
    gf    = gl._load_bgcode(raw)
    p     = tmp_path / "out.bgcode"
    gl.save(gf, str(p))
    _, nongcode, thumbs, _ = gl._bgcode_split(p.read_bytes())
    assert len(thumbs) == 1
    assert thumbs[0].data == img
    assert thumbs[0].width == 32


def test_save_bgcode_with_thumbnails_is_idempotent(tmp_path):
    """Repeated save/load must not inject text thumbnail markers into bgcode G-code."""
    img = b"\x89PNG\r\n" + b"\x00" * 32
    tblk = _make_thumbnail_block(img, width=16, height=16, fmt=0)
    raw = _make_bgcode("G90\nG1 X1 Y1\n", extra_blocks=[tblk])
    p = tmp_path / "roundtrip.bgcode"

    gf = gl._load_bgcode(raw)
    gl.save(gf, str(p))
    gf1 = gl.load(str(p))

    assert len(gf1.thumbnails) == 1
    assert all("thumbnail" not in ln.raw.lower() for ln in gf1.lines)
    first_len = len(gf1.lines)

    gl.save(gf1, str(p))
    gf2 = gl.load(str(p))

    assert len(gf2.thumbnails) == 1
    assert all("thumbnail" not in ln.raw.lower() for ln in gf2.lines)
    assert len(gf2.lines) == first_len


# ---------------------------------------------------------------------------
# _bgcode_split — error handling
# ---------------------------------------------------------------------------

def test_bgcode_split_bad_magic():
    with pytest.raises(ValueError, match="Not a .bgcode"):
        gl._bgcode_split(b"NOTGCDE" + b"\x00" * 20)


def test_bgcode_split_too_short():
    with pytest.raises(ValueError, match="too short"):
        gl._bgcode_split(b"GCDE\x01")


def test_bgcode_split_crc_mismatch():
    data = bytearray(_make_bgcode("G1 X1\n"))
    data[20] ^= 0xFF
    with pytest.raises(ValueError, match="CRC32 mismatch"):
        gl._bgcode_split(bytes(data))


def test_bgcode_split_no_gcode_block():
    MAGIC    = b"GCDE"
    file_hdr = MAGIC + struct.pack("<IH", 1, 1)
    meta     = _make_meta_block(2, b"key=val\n")
    with pytest.raises(ValueError, match="No GCode blocks"):
        gl._bgcode_split(file_hdr + meta)


# ---------------------------------------------------------------------------
# _is_bgcode_file
# ---------------------------------------------------------------------------

def test_is_bgcode_file_true(tmp_path):
    p = tmp_path / "t.bgcode"
    p.write_bytes(_make_bgcode("G1 X1\n"))
    assert gl._is_bgcode_file(str(p)) is True


def test_is_bgcode_file_false(tmp_path):
    p = tmp_path / "t.gcode"
    p.write_text("G1 X1\n", encoding="utf-8")
    assert gl._is_bgcode_file(str(p)) is False


def test_is_bgcode_file_missing(tmp_path):
    assert gl._is_bgcode_file(str(tmp_path / "nonexistent.bgcode")) is False


# ---------------------------------------------------------------------------
# Heatshrink decompression unit tests
# ---------------------------------------------------------------------------

def _hs_bitstream(*bit_strings: str) -> bytes:
    """Build a bytearray from '0'/'1' bit strings (MSB-first, zero-padded)."""
    bits = "".join(bit_strings)
    # Pad to multiple of 8.
    while len(bits) % 8:
        bits += "0"
    out = bytearray()
    for i in range(0, len(bits), 8):
        out.append(int(bits[i:i + 8], 2))
    return bytes(out)


class TestHeatshrinkDecompress:
    def test_empty_expected_size(self):
        assert gl._heatshrink_decompress(b"\x00", 11, 4, 0) == b""

    def test_single_literal(self):
        # Tag=1, then 8 bits for 'A' (0x41 = 01000001)
        data = _hs_bitstream("1", "01000001")
        result = gl._heatshrink_decompress(data, 8, 4, 1)
        assert result == b"A"

    def test_two_literals(self):
        # Tag=1, 'A', Tag=1, 'B'
        data = _hs_bitstream("1", "01000001", "1", "01000010")
        result = gl._heatshrink_decompress(data, 8, 4, 2)
        assert result == b"AB"

    def test_literal_then_backref(self):
        # window_sz2=8 (window=256), lookahead_sz2=4
        # Literal 'A', then backref index=0 (neg_offset=1), count=0 (copy 1 byte)
        # → should output 'AA'
        data = _hs_bitstream(
            "1", "01000001",            # literal 'A'
            "0", "00000000", "0000",    # backref: index=0 (8 bits), count=0 (4 bits)
        )
        result = gl._heatshrink_decompress(data, 8, 4, 2)
        assert result == b"AA"

    def test_backref_copies_multiple(self):
        # Literal 'X', then backref index=0, count=3 → copy 4 bytes → 'XXXXX'
        data = _hs_bitstream(
            "1", "01011000",            # literal 'X' (0x58)
            "0", "00000000", "0011",    # backref: index=0, count=3 → 4 copies
        )
        result = gl._heatshrink_decompress(data, 8, 4, 5)
        assert result == b"XXXXX"

    def test_window_12_lookahead_4(self):
        # window_sz2=12 (4096), lookahead_sz2=4
        # Literal 'Z' (0x5A), then backref index=0 (12 bits), count=1 (4 bits) → 'ZZZ'
        data = _hs_bitstream(
            "1", "01011010",            # literal 'Z'
            "0", "000000000000", "0001",  # backref: 12-bit index=0, count=1 → 2 copies
        )
        result = gl._heatshrink_decompress(data, 12, 4, 3)
        assert result == b"ZZZ"

    def test_multiple_literals_and_backref(self):
        # 'A' 'B' then backref to copy both → 'ABAB'
        # window_sz2=8, lookahead_sz2=4
        data = _hs_bitstream(
            "1", "01000001",            # literal 'A'
            "1", "01000010",            # literal 'B'
            "0", "00000001", "0001",    # backref: index=1 (offset=2), count=1 (copy 2)
        )
        result = gl._heatshrink_decompress(data, 8, 4, 4)
        assert result == b"ABAB"


# ---------------------------------------------------------------------------
# MeatPack decoding unit tests
# ---------------------------------------------------------------------------

class TestMeatpackDecode:
    # Signal prefix to enable packing.
    ENABLE = bytes([0xFF, 0xFF, 251])
    # Signal prefix to enable no-spaces mode.
    ENABLE_NOSPACE = bytes([0xFF, 0xFF, 247])
    # Signal prefix to disable packing.
    DISABLE = bytes([0xFF, 0xFF, 250])

    def test_raw_passthrough_before_enable(self):
        """Before EnablePacking signal, bytes pass through as raw."""
        data = b"G1 X10\n"
        assert gl._meatpack_decode(data) == "G1 X10\n"

    def test_packed_digits(self):
        """Two packed digits decode correctly."""
        # '1' = nibble 1, '2' = nibble 2 → byte = (2 << 4) | 1 = 0x21
        data = self.ENABLE + bytes([0x21])
        assert gl._meatpack_decode(data) == "12"

    def test_packed_g_and_digit(self):
        """'G' = nibble 13, '1' = nibble 1 → byte = (1 << 4) | 13 = 0x1D."""
        data = self.ENABLE + bytes([0x1D])
        result = gl._meatpack_decode(data)
        assert result == "G1"

    def test_escape_first_nibble(self):
        """First nibble (lo) is escape → next raw byte is first char."""
        # 'M' not in table → lo=0xF, hi=7 → byte = (7 << 4) | 0xF = 0x7F
        # Then raw byte 0x4D = 'M'
        data = self.ENABLE + bytes([0x7F, 0x4D])
        result = gl._meatpack_decode(data)
        assert result == "M7"  # raw 'M' first, then packed '7'

    def test_escape_second_nibble(self):
        """Second nibble (hi) is escape → next raw byte is second char.

        The space normalization inserts whitespace between a digit and an
        uppercase letter (``3P`` → ``3 P``)."""
        # '3' in table = nibble 3, escape = 0xF
        # lo=3, hi=0xF → byte = (0xF << 4) | 3 = 0xF3
        # Then raw byte 0x50 = 'P'
        data = self.ENABLE + bytes([0xF3, 0x50])
        result = gl._meatpack_decode(data)
        assert result == "3 P"  # packed '3' first, then raw 'P' (space inserted)

    def test_both_escape(self):
        """Both nibbles are escapes → next 2 bytes are raw."""
        # byte = 0xFF (lo=0xF, hi=0xF)
        # But 0xFF triggers signal detection — we need it not to be followed by 0xFF.
        # Actually, 0xFF as packed data: lo=0xF, hi=0xF → both escapes
        # If next byte is NOT 0xFF, the 0xFF is processed as packed data.
        data = self.ENABLE + bytes([0xFF, 0x41, 0x42])
        # 0xFF: single 0xFF (next byte 0x41 != 0xFF) → packed byte
        # lo=0xF, hi=0xF → pending_raw=2
        # 0x41 = 'A' → first raw char
        # 0x42 = 'B' → second raw char
        result = gl._meatpack_decode(data)
        assert result == "AB"

    def test_nospace_mode_e_in_table(self):
        """In no-spaces mode, nibble 11 decodes as 'E' instead of space."""
        # Enable + NoSpace, then pack 'E' and '1':
        # 'E' = nibble 11, '1' = nibble 1 → byte = (1 << 4) | 11 = 0x1B
        data = self.ENABLE + self.ENABLE_NOSPACE + bytes([0x1B])
        result = gl._meatpack_decode(data)
        assert result == "E1"

    def test_disable_packing_switches_to_raw(self):
        data = self.ENABLE + bytes([0x21]) + self.DISABLE + b"raw"
        result = gl._meatpack_decode(data)
        assert result == "12raw"

    def test_space_normalization(self):
        """Space is re-inserted between digit and uppercase letter."""
        # Encode "G1X10\n" in packed format
        # G=13,1=1 → (1<<4)|13 = 0x1D
        # X=14,1=1 → (1<<4)|14 = 0x1E
        # 0=0, newline=12 → (12<<4)|0 = 0xC0
        data = self.ENABLE + bytes([0x1D, 0x1E, 0xC0])
        result = gl._meatpack_decode(data)
        assert result == "G1 X10\n"

    def test_empty_data(self):
        assert gl._meatpack_decode(b"") == ""

    def test_m73_decoding(self):
        """Decode packed 'M73 P0 R15\\n' — realistic G-code command."""
        # 'M'→esc, '7'=7: lo=0xF, hi=7 → 0x7F, raw 0x4D
        # '3'=3, ' '=11: lo=3, hi=11 → 0xB3
        # 'P'→esc, '0'=0: lo=0xF, hi=0 → 0x0F, raw 0x50
        # ' '=11, 'R'→esc: lo=11, hi=0xF → 0xFB, raw 0x52
        # '1'=1, '5'=5: lo=1, hi=5 → 0x51
        # '\n'=12, pad 0: lo=12, hi=0 → 0x0C
        data = (
            self.ENABLE
            + bytes([0x7F, 0x4D, 0xB3, 0x0F, 0x50, 0xFB, 0x52, 0x51, 0x0C])
        )
        result = gl._meatpack_decode(data)
        assert result == "M73 P0 R15\n0"  # trailing '0' from pad nibble


# ---------------------------------------------------------------------------
# bgcode with heatshrink-compressed block
# ---------------------------------------------------------------------------

def _make_hs_bgcode(gcode_text: str) -> bytes:
    """Build a .bgcode with Heatshrink_12_4 compressed + MeatPack encoded GCode."""
    # For testing, we just use uncompressed raw encoding to keep it simple.
    # The real heatshrink test is via the integration test with the real file.
    # This helper just tests that the _bgcode_split path dispatches correctly.
    MAGIC        = b"GCDE"
    BLK_GCODE    = 1
    COMP_NONE    = 0
    ENC_RAW      = 0

    file_hdr = MAGIC + struct.pack("<IH", 1, 1)
    payload  = gcode_text.encode("utf-8")
    hdr      = struct.pack("<HHI", BLK_GCODE, COMP_NONE, len(payload))
    params   = struct.pack("<H", ENC_RAW)
    cksum    = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum    = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum    = zlib.crc32(payload, cksum) & 0xFFFFFFFF
    gcode_block = hdr + params + payload + struct.pack("<I", cksum)
    return file_hdr + gcode_block
