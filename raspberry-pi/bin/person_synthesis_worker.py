#!/usr/bin/env python3
from pathlib import Path
import subprocess
import time

BASE = Path("/home/philip/.local/state/camera-snapshots")
QUEUE = BASE / "synthesis-queue"
LOG = BASE / "person-synthesis-worker.log"


def log(message):
    BASE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")


def coalesce_queue():
    items = sorted(QUEUE.glob("*.queue"), key=lambda p: p.stat().st_mtime)
    if not items:
        return None
    latest = items[-1]
    for item in items[:-1]:
        try:
            item.unlink()
        except OSError:
            pass
    return latest


def main():
    QUEUE.mkdir(parents=True, exist_ok=True)
    log("worker started")
    while True:
        item = coalesce_queue()
        if item is None:
            time.sleep(1.5)
            continue
        processing = item.with_suffix(".processing")
        try:
            item.rename(processing)
        except OSError:
            time.sleep(0.5)
            continue
        log(f"synthesis start {processing.name}")
        try:
            result = subprocess.run(
                ["/usr/bin/python3", "/home/philip/bin/trigger_person_synthesis.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=70,
                check=False,
            )
            output = (result.stdout or "").strip().replace("\n", " | ")
            log(f"synthesis exit={result.returncode} {output}")
        except subprocess.TimeoutExpired:
            log("synthesis timeout")
        finally:
            try:
                processing.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
