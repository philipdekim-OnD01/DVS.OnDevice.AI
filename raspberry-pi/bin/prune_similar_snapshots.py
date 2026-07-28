#!/usr/bin/env python3
from pathlib import Path
import sys

from PIL import Image


MAX_IMAGES = 200
SIMILARITY_DISTANCE = 8


def dhash(path):
    try:
        image = Image.open(path).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    except Exception:
        return None

    pixels = list(image.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            left = pixels[y * 9 + x]
            right = pixels[y * 9 + x + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a, b):
    return (a ^ b).bit_count()


def prune(directory):
    root = Path(directory)
    items = []
    for path in root.glob("*.jpg"):
        try:
            st = path.stat()
        except OSError:
            continue
        value = dhash(path)
        if value is None:
            continue
        items.append({"path": path, "mtime": st.st_mtime, "hash": value})

    over = len(items) - MAX_IMAGES
    if over <= 0:
        return 0

    # Preserve a small newest window so the live gallery does not lose the latest frames.
    newest = sorted(items, key=lambda item: item["mtime"], reverse=True)
    protected = {item["path"] for item in newest[:20]}
    candidates = [item for item in items if item["path"] not in protected]

    for item in candidates:
        item["similar_count"] = 0
        item["nearest_distance"] = 64
        for other in items:
            if item is other:
                continue
            dist = hamming(item["hash"], other["hash"])
            item["nearest_distance"] = min(item["nearest_distance"], dist)
            if dist <= SIMILARITY_DISTANCE:
                item["similar_count"] += 1

    # Delete images in the densest similarity clusters first; for ties, delete older images.
    candidates.sort(
        key=lambda item: (
            item["similar_count"],
            -item["nearest_distance"],
            -item["mtime"],
        ),
        reverse=True,
    )

    deleted = 0
    for item in candidates:
        if deleted >= over:
            break
        try:
            item["path"].unlink()
            deleted += 1
        except OSError:
            pass

    return deleted


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/home/philip/camera_snapshots"
    count = prune(target)
    if count:
        print(f"pruned {count} similar snapshots from {target}")
