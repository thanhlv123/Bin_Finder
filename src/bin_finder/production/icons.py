"""Small dependency-free RGBA subscribe button with a drawn bell."""
from pathlib import Path
import struct
import zlib


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def write_subscribe_icon(output: Path) -> None:
    """Write button backgrounds and a bell; FFmpeg adds the two labels."""
    width = 620
    height = 110
    rows = []
    for vertical in range(height):
        row = bytearray(b"\0")
        for horizontal in range(width):
            color = (0, 0, 0, 0)
            for left, right, button_color in ((5, 185, (45, 95, 170, 255)), (200, 525, (210, 30, 40, 255))):
                nearest_horizontal = min(max(horizontal, left + 18), right - 19)
                nearest_vertical = min(max(vertical, 23), 86)
                if (horizontal - nearest_horizontal) ** 2 + (vertical - nearest_vertical) ** 2 <= 18 ** 2:
                    color = button_color
            bell_body = 24 <= vertical <= 60 and abs(horizontal - 575) <= 10 + (vertical - 24) * 0.4
            bell_rim = 60 <= vertical <= 67 and 545 <= horizontal <= 605
            bell_top = (horizontal - 575) ** 2 + (vertical - 23) ** 2 <= 36
            bell_clapper = (horizontal - 575) ** 2 + (vertical - 74) ** 2 <= 25
            if bell_body or bell_rim or bell_top or bell_clapper:
                color = (255, 255, 255, 255)
            row.extend(color)
        rows.append(bytes(row))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    output.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) +
                       _chunk(b"IDAT", zlib.compress(b"".join(rows))) + _chunk(b"IEND", b""))
