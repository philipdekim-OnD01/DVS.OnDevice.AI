#!/usr/bin/env python3
import os
import shutil
from pathlib import Path
from datetime import datetime

BASE = Path("/home/philip")
STATE = BASE / ".local/state/camera-snapshots"
LOG = STATE / "disk-guard.log"
TARGET_USAGE = 70.0
CHECK_PATH = BASE

DELETE_ROOTS = [
    BASE / "camera_snapshots",
    STATE / "person-bursts",
    BASE / "synthetic_frames",
    BASE / "person_snapshots",
]

DELETE_SUFFIXES = {".jpg", ".jpeg", ".png", ".mp4", ".json", ".txt"}


def log(msg):
    STATE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


def usage_percent():
    total, used, free = shutil.disk_usage(CHECK_PATH)
    return used * 100.0 / total, total, used, free


def candidates():
    items = []
    for root in DELETE_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            try:
                if not p.is_file():
                    continue
                if p.suffix.lower() not in DELETE_SUFFIXES:
                    continue
                st = p.stat()
                items.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
    items.sort(key=lambda item: item[0])
    return items


def remove_empty_dirs():
    for root in [BASE / "synthetic_frames", STATE / "person-bursts"]:
        if not root.exists():
            continue
        for d in sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass


def main():
    before, total, used, free = usage_percent()
    if before <= TARGET_USAGE:
        log(f"ok usage={before:.1f}%")
        return 0

    deleted = 0
    bytes_deleted = 0
    for _, size, path in candidates():
        try:
            path.unlink()
            deleted += 1
            bytes_deleted += size
        except OSError as exc:
            log(f"delete_failed path={path} error={exc}")
            continue
        now, *_ = usage_percent()
        if now <= TARGET_USAGE:
            break

    remove_empty_dirs()
    after, *_ = usage_percent()
    log(
        f"cleanup before={before:.1f}% after={after:.1f}% "
        f"deleted={deleted} bytes={bytes_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
