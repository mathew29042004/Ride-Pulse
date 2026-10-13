#!/usr/bin/env python
"""Render the app icons (PNG) used by the PWA manifest, from the same shapes as favicon.svg.

Dependency-free (zlib + struct), so it runs anywhere Python does:

    python scripts/make_icons.py

Writes frontend/public/icons/icon-{192,512}.png, maskable-512.png and apple-touch-icon.png.
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"
INK = (11, 15, 25)
BRAND = (16, 185, 129)
# The pulse line from favicon.svg, on a 64x64 canvas.
PULSE = [(8, 34), (20, 34), (25, 22), (33, 44), (39, 29), (43, 34), (56, 34)]


def segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int, *, rounded: bool, inset: float = 0.0) -> bytes:
    """RGBA pixels. ``inset`` shrinks the artwork (maskable icons need a safe zone)."""
    scale = size / 64
    art = 1 - 2 * inset
    radius = 16 * scale if rounded else 0
    width = 5 * art / 2  # half the stroke, in 64-unit space
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # Background: a rounded square (or full bleed for maskable icons).
            alpha = 1.0
            if rounded:
                cx = min(max(x + 0.5, radius), size - radius)
                cy = min(max(y + 0.5, radius), size - radius)
                edge = radius - math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                alpha = max(0.0, min(1.0, edge + 0.5))
            # Pulse line, anti-aliased by distance to the polyline.
            u = ((x + 0.5) / scale - 32) / art + 32
            v = ((y + 0.5) / scale - 32) / art + 32
            d = min(segment_distance(u, v, *PULSE[i], *PULSE[i + 1]) for i in range(len(PULSE) - 1))
            cover = max(0.0, min(1.0, (width - d) * scale * art + 0.5))
            r, g, b = (round(INK[i] + (BRAND[i] - INK[i]) * cover) for i in range(3))
            row += bytes((r, g, b, round(alpha * 255)))
        rows.append(b"\x00" + bytes(row))
    return b"".join(rows)


def png(size: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {
        "icon-192.png": (192, True, 0.0),
        "icon-512.png": (512, True, 0.0),
        "maskable-512.png": (512, False, 0.12),
        "apple-touch-icon.png": (180, False, 0.06),
    }
    for name, (size, rounded, inset) in targets.items():
        (OUT / name).write_bytes(png(size, render(size, rounded=rounded, inset=inset)))
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
