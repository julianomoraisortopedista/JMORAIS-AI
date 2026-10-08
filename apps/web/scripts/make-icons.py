"""Generate the app icons (PNG) with the standard library: navy-teal square with a white 'J'."""
import struct
import sys
import zlib
from pathlib import Path


def png(size: int) -> bytes:
    rows = []
    s = size / 512
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            t = (x + y) / (2 * size)
            r, g, b = int(11 + (14 - 11) * t), int(31 + (124 - 31) * t), int(54 + (134 - 54) * t)  # navy -> teal
            X, Y = x / s, y / s
            stem = 290 <= X <= 350 and 120 <= Y <= 330
            top = 220 <= X <= 390 and 120 <= Y <= 172
            hook = ((X - 245) ** 2 + (Y - 330) ** 2) <= 105 ** 2 and ((X - 245) ** 2 + (Y - 330) ** 2) >= 45 ** 2 and Y >= 330
            if stem or top or hook:
                r, g, b = 255, 255, 255
            row += bytes((r, g, b))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


out = Path(sys.argv[1] if len(sys.argv) > 1 else "public")
out.mkdir(parents=True, exist_ok=True)
for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
    (out / name).write_bytes(png(size))
print("icons written to", out)
