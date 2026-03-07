from __future__ import annotations

import re
import struct
import zlib
from typing import Dict, List, Optional, Tuple

from gcode_lib._constants import (
    _BGCODE_MAGIC, _BLK_FILE_METADATA, _BLK_GCODE,
    _BLK_SLICER_METADATA, _BLK_PRINTER_METADATA,
    _BLK_PRINT_METADATA, _BLK_THUMBNAIL,
    _COMP_NONE, _COMP_DEFLATE, _COMP_HEATSHRINK_11_4,
    _COMP_HEATSHRINK_12_4,
    _ENC_RAW, _ENC_MEATPACK, _ENC_MEATPACK_COMMENTS,
    _IMG_PNG,
    _BGCODE_VERSION, _BGCODE_CHECKSUM_CRC32, _BGCODE_FILE_HDR_V2,
)
from gcode_lib._types import GCodeFile, Thumbnail
from gcode_lib._parsing import parse_lines


# ---------------------------------------------------------------------------
# File detection
# ---------------------------------------------------------------------------

def _is_bgcode_file(path: str) -> bool:
    """Return True if *path* starts with the ``GCDE`` magic bytes."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == _BGCODE_MAGIC
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Heatshrink decompression (pure-Python LZSS decoder)
# ---------------------------------------------------------------------------

def _heatshrink_decompress(
    data: bytes, window_sz2: int, lookahead_sz2: int, expected_size: int,
) -> bytes:
    """Decompress *data* using the Heatshrink LZSS algorithm.

    Parameters match the libbgcode convention:

    * ``window_sz2``   -- log2 of the sliding-window size (11 or 12).
    * ``lookahead_sz2`` -- log2 of the lookahead size (typically 4).
    * ``expected_size`` -- exact number of uncompressed bytes to produce.

    The decoder reads bits MSB-first.  A tag bit of **1** introduces an
    8-bit literal; **0** introduces a back-reference of *window_sz2* index
    bits followed by *lookahead_sz2* count bits.
    """
    if expected_size == 0:
        return b""

    window_size = 1 << window_sz2
    mask = window_size - 1
    window = bytearray(window_size)
    head = 0

    output = bytearray(expected_size)
    out_pos = 0

    # -- bit reader state --
    input_len = len(data)
    byte_pos = 0
    bit_buf = 0       # current byte being consumed
    bits_left = 0     # bits remaining in bit_buf (0-8)

    def _get_bits(count: int) -> int:
        """Read *count* bits MSB-first and return as an integer."""
        nonlocal byte_pos, bit_buf, bits_left
        result = 0
        remaining = count
        while remaining > 0:
            if bits_left == 0:
                bit_buf = data[byte_pos] if byte_pos < input_len else 0
                byte_pos += 1
                bits_left = 8
            take = min(remaining, bits_left)
            # Extract the top *take* bits from bit_buf.
            result = (result << take) | (bit_buf >> (bits_left - take))
            bit_buf &= (1 << (bits_left - take)) - 1
            bits_left -= take
            remaining -= take
        return result

    while out_pos < expected_size:
        tag = _get_bits(1)
        if tag:
            # Literal byte
            byte_val = _get_bits(8)
            output[out_pos] = byte_val
            window[head & mask] = byte_val
            head += 1
            out_pos += 1
        else:
            # Back-reference
            index = _get_bits(window_sz2)
            count = _get_bits(lookahead_sz2) + 1
            neg_offset = index + 1
            for _ in range(count):
                if out_pos >= expected_size:
                    break
                c = window[(head - neg_offset) & mask]
                output[out_pos] = c
                window[head & mask] = c
                head += 1
                out_pos += 1

    return bytes(output)


# ---------------------------------------------------------------------------
# MeatPack decoding
# ---------------------------------------------------------------------------

# 4-bit nibble -> character lookup (standard mode)
_MP_CHAR_TABLE: str = "0123456789. \nGX"
# Index 0xF (15) is the escape sentinel -- not a real character.

# Command bytes sent after the 0xFF 0xFF signal prefix.
_MP_CMD_ENABLE_PACKING      = 251
_MP_CMD_DISABLE_PACKING     = 250
_MP_CMD_RESET_ALL           = 249
_MP_CMD_ENABLE_NO_SPACES    = 247
_MP_CMD_DISABLE_NO_SPACES   = 246

_MP_SPACE_RE = re.compile(r"(?<=[0-9.])(?=[A-Z])")
"""Insert whitespace before an uppercase axis/command letter that immediately
follows a digit or period.  MeatPack *no-spaces* mode strips inter-word
spaces; this regex restores them so that downstream ``parse_line()`` works."""


def _meatpack_decode(data: bytes) -> str:
    """Decode MeatPack / MeatPackComments encoded *data* to a string.

    MeatPack packs two common G-code characters into a single byte using
    4-bit nibbles.  Nibble value 0xF is an escape: the *next* full byte
    is a raw character.  The scheme is toggled on/off by a ``0xFF 0xFF
    <cmd>`` signal sequence embedded in the stream.

    Signal detection uses a one-byte lookahead: when a ``0xFF`` is seen,
    peek at the next byte.  If it is also ``0xFF`` the pair is a signal
    prefix and the following byte is a command.  Otherwise the ``0xFF``
    is normal data (a packed byte with both nibbles = escape when packing
    is enabled, or a raw ``0xFF`` when it is not).
    """
    out: list[str] = []
    table = list(_MP_CHAR_TABLE)
    packing = False
    # Number of pending full-char bytes to pass through raw.
    pending_raw = 0
    # Character held from unpacking the second nibble when the first
    # nibble was an escape.
    held_char: str | None = None

    i = 0
    n = len(data)

    while i < n:
        b = data[i]
        i += 1

        # -- signal detection (0xFF 0xFF <cmd>) --
        if b == 0xFF:
            if i < n and data[i] == 0xFF:
                # Confirmed signal prefix -- consume the second 0xFF.
                i += 1
                if i < n:
                    cmd = data[i]
                    i += 1
                    if cmd == _MP_CMD_ENABLE_PACKING:
                        packing = True
                    elif cmd == _MP_CMD_DISABLE_PACKING:
                        packing = False
                    elif cmd == _MP_CMD_RESET_ALL:
                        packing = False
                        table = list(_MP_CHAR_TABLE)
                    elif cmd == _MP_CMD_ENABLE_NO_SPACES:
                        table = list(_MP_CHAR_TABLE)
                        table[11] = "E"   # space slot becomes 'E'
                    elif cmd == _MP_CMD_DISABLE_NO_SPACES:
                        table = list(_MP_CHAR_TABLE)
                continue
            # Single 0xFF (next byte is not 0xFF) -- fall through and
            # process it as normal data below.

        # -- pending raw bytes (from a previous escape nibble) --
        if pending_raw > 0:
            pending_raw -= 1
            # The raw byte is always the escaped character (came first in
            # the pair), so it must be emitted *before* any held second
            # nibble character.
            out.append(chr(b))
            if pending_raw == 0 and held_char is not None:
                out.append(held_char)
                held_char = None
            continue

        # -- raw mode (packing disabled) --
        if not packing:
            out.append(chr(b))
            continue

        # -- packing mode -- unpack two nibbles --
        # MeatPack convention: low nibble is the FIRST character,
        # high nibble is the SECOND character.
        lo = b & 0x0F          # first character
        hi = (b >> 4) & 0x0F   # second character

        if lo == 0x0F and hi == 0x0F:
            # Both nibbles are escapes -> next 2 bytes are raw chars.
            pending_raw = 2
        elif lo == 0x0F:
            # First char (lo) is escape -> next byte is a raw char.
            # Hold the second char (hi) until after the raw byte.
            pending_raw = 1
            held_char = table[hi]
        elif hi == 0x0F:
            # Second char (hi) is escape -> output first char now,
            # next byte is raw.
            out.append(table[lo])
            pending_raw = 1
        else:
            # Both nibbles are valid packed characters.
            out.append(table[lo])
            out.append(table[hi])

    # Flush any held character that was never followed by a raw byte
    # (shouldn't happen in well-formed data, but be safe).
    if held_char is not None:
        out.append(held_char)

    text = "".join(out)

    # MeatPack no-spaces mode strips whitespace between G-code words.
    # Re-insert spaces so that "G1X10Y20" becomes "G1 X10 Y20" and
    # parse_line() can split the command from its axes.
    return _MP_SPACE_RE.sub(" ", text)


# ---------------------------------------------------------------------------
# Binary block parsing
# ---------------------------------------------------------------------------

def _bgcode_split(
    data: bytes,
) -> Tuple[bytes, List[bytes], List[Thumbnail], str]:
    """Parse a .bgcode byte string into its components.

    Returns
    -------
    file_hdr
        10-byte file prefix (magic + version + checksum_type).
    nongcode_blocks
        Raw bytes of every non-GCode block in original order.  These are
        suitable for verbatim re-embedding on reassembly and include
        thumbnail blocks.
    thumbnails
        Parsed :class:`Thumbnail` objects (subset of nongcode_blocks).
    gcode_text
        Concatenated UTF-8 G-code text from all GCode blocks.

    Raises :class:`ValueError` for invalid, truncated, or unsupported files.
    """
    if len(data) < 10:
        raise ValueError(f"Data too short ({len(data)} bytes) to be a .bgcode file")
    if data[:4] != _BGCODE_MAGIC:
        raise ValueError(
            f"Not a .bgcode file: expected magic {_BGCODE_MAGIC!r}, got {data[:4]!r}"
        )

    file_hdr = data[:10]
    pos = 10
    gcode_parts: List[str] = []
    nongcode_raws: List[bytes] = []
    thumbnails: List[Thumbnail] = []

    while pos < len(data):
        block_start = pos
        if pos + 8 > len(data):
            raise ValueError(f"Truncated block header at offset {pos}")

        btype, comp = struct.unpack_from("<HH", data, pos)
        uncomp_size, = struct.unpack_from("<I", data, pos + 4)

        if comp == _COMP_NONE:
            comp_size = uncomp_size
            hdr_len = 8
        elif comp in (_COMP_DEFLATE, _COMP_HEATSHRINK_11_4, _COMP_HEATSHRINK_12_4):
            if pos + 12 > len(data):
                raise ValueError(f"Truncated compressed block header at offset {pos}")
            comp_size, = struct.unpack_from("<I", data, pos + 8)
            hdr_len = 12
        else:
            raise ValueError(f"Unknown compression type {comp} at offset {pos}")

        params_len = 6 if btype == _BLK_THUMBNAIL else 2
        params_start = pos + hdr_len
        payload_start = params_start + params_len
        payload_end = payload_start + comp_size

        if payload_end + 4 > len(data):
            raise ValueError(
                f"Truncated block payload at offset {pos}: "
                f"need {payload_end + 4 - len(data)} more bytes"
            )

        stored_crc, = struct.unpack_from("<I", data, payload_end)
        computed_crc = zlib.crc32(data[pos:payload_end]) & 0xFFFFFFFF
        if computed_crc != stored_crc:
            raise ValueError(
                f"CRC32 mismatch in block type {btype} at offset {pos}: "
                f"computed {computed_crc:#010x}, stored {stored_crc:#010x}"
            )

        block_end = payload_end + 4
        raw_block = data[block_start:block_end]
        payload = data[payload_start:payload_end]

        if btype == _BLK_GCODE:
            enc, = struct.unpack_from("<H", data, params_start)
            if comp == _COMP_NONE:
                raw_payload = payload
            elif comp == _COMP_DEFLATE:
                try:
                    raw_payload = zlib.decompress(payload)
                except zlib.error as exc:
                    raise ValueError(
                        f"DEFLATE decompression failed at offset {pos}: {exc}"
                    ) from exc
            elif comp == _COMP_HEATSHRINK_11_4:
                raw_payload = _heatshrink_decompress(payload, 11, 4, uncomp_size)
            elif comp == _COMP_HEATSHRINK_12_4:
                raw_payload = _heatshrink_decompress(payload, 12, 4, uncomp_size)
            else:
                raise ValueError(
                    f"Unsupported GCode block compression {comp} at offset {pos}"
                )
            if enc == _ENC_RAW:
                gcode_parts.append(raw_payload.decode("utf-8"))
            elif enc in (_ENC_MEATPACK, _ENC_MEATPACK_COMMENTS):
                gcode_parts.append(_meatpack_decode(raw_payload))
            else:
                raise ValueError(
                    f"Unsupported GCode block encoding {enc} at offset {pos}"
                )

        elif btype == _BLK_THUMBNAIL:
            params_bytes = data[params_start:payload_start]
            if comp == _COMP_NONE:
                img_data = payload
            elif comp == _COMP_DEFLATE:
                try:
                    img_data = zlib.decompress(payload)
                except zlib.error as exc:
                    raise ValueError(
                        f"DEFLATE decompression of thumbnail failed at offset {pos}: {exc}"
                    ) from exc
            elif comp == _COMP_HEATSHRINK_11_4:
                img_data = _heatshrink_decompress(payload, 11, 4, uncomp_size)
            elif comp == _COMP_HEATSHRINK_12_4:
                img_data = _heatshrink_decompress(payload, 12, 4, uncomp_size)
            else:
                img_data = payload  # store as-is for unknown compression
            thumbnails.append(Thumbnail(params=params_bytes, data=img_data, _raw_block=raw_block))
            nongcode_raws.append(raw_block)

        else:
            nongcode_raws.append(raw_block)

        pos = block_end

    if not gcode_parts:
        raise ValueError("No GCode blocks found in .bgcode data")

    return file_hdr, nongcode_raws, thumbnails, "".join(gcode_parts)


# ---------------------------------------------------------------------------
# Binary reassembly
# ---------------------------------------------------------------------------

def _bgcode_reassemble(
    file_hdr: bytes,
    nongcode_blocks: List[bytes],
    gcode_text: str,
) -> bytes:
    """Rebuild a .bgcode byte string from its components.

    A single new GCode block (COMP_NONE, ENC_RAW) is appended after all
    non-GCode blocks, matching the libbgcode convention (metadata before
    G-code).
    """
    payload = gcode_text.encode("utf-8")
    hdr    = struct.pack("<HHI", _BLK_GCODE, _COMP_NONE, len(payload))
    params = struct.pack("<H", _ENC_RAW)
    cksum  = zlib.crc32(hdr) & 0xFFFFFFFF
    cksum  = zlib.crc32(params, cksum) & 0xFFFFFFFF
    cksum  = zlib.crc32(payload, cksum) & 0xFFFFFFFF
    gcode_block = hdr + params + payload + struct.pack("<I", cksum)
    return file_hdr + b"".join(nongcode_blocks) + gcode_block


# ---------------------------------------------------------------------------
# Load helper
# ---------------------------------------------------------------------------

def _load_bgcode(data: bytes) -> GCodeFile:
    """Create a :class:`GCodeFile` from raw .bgcode bytes."""
    file_hdr, nongcode_blocks, thumbnails, gcode_text = _bgcode_split(data)
    return GCodeFile(
        lines=parse_lines(gcode_text),
        thumbnails=thumbnails,
        source_format="bgcode",
        _bgcode_file_hdr=file_hdr,
        _bgcode_nongcode_blocks=nongcode_blocks,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_bgcode(data: bytes) -> "GCodeFile":
    """Load a :class:`GCodeFile` from raw Prusa ``.bgcode`` bytes.

    Equivalent to :func:`load` for binary data already in memory.

    Raises :class:`ValueError` for invalid, truncated, or unsupported files.
    """
    return _load_bgcode(data)


def write_bgcode(
    ascii_gcode: str,
    thumbnails: Optional[List[Thumbnail]] = None,
) -> bytes:
    """Serialise ASCII G-code (and optional thumbnails) to ``.bgcode`` bytes.

    Creates a minimal but spec-compliant Prusa BGCode v2 file.  Thumbnail
    blocks are written before the GCode block, matching the layout produced
    by PrusaSlicer.

    Parameters
    ----------
    ascii_gcode: Plain G-code text to embed.
    thumbnails:  Optional list of :class:`Thumbnail` objects.  Thumbnails
                 that have a ``_raw_block`` (i.e. from a previously loaded
                 ``.bgcode`` file) are embedded verbatim for lossless
                 round-trips; others are serialised as uncompressed blocks.

    Returns
    -------
    bytes
        Raw ``.bgcode`` file data that can be written directly to disk.
    """
    thumb_blocks: List[bytes] = []
    for thumb in (thumbnails or []):
        if thumb._raw_block:
            # Verbatim re-embed (lossless round-trip).
            thumb_blocks.append(thumb._raw_block)
        else:
            # Build a fresh uncompressed thumbnail block.
            payload = thumb.data
            params  = thumb.params   # 6 bytes: width, height, fmt
            hdr     = struct.pack("<HHI", _BLK_THUMBNAIL, _COMP_NONE, len(payload))
            cksum   = zlib.crc32(hdr)    & 0xFFFFFFFF
            cksum   = zlib.crc32(params, cksum) & 0xFFFFFFFF
            cksum   = zlib.crc32(payload, cksum) & 0xFFFFFFFF
            thumb_blocks.append(hdr + params + payload + struct.pack("<I", cksum))

    return _bgcode_reassemble(_BGCODE_FILE_HDR_V2, thumb_blocks, ascii_gcode)
