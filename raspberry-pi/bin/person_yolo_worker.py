#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import time

BASE = Path("/home/philip/.local/state/camera-snapshots")
QUEUE = BASE / "detect-queue"
SYNTH_QUEUE = BASE / "synthesis-queue"
LOG = BASE / "person-yolo-worker.log"
MAX_QUEUE = 120


def log(message):
    BASE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")


def trim_queue():
    items = sorted(QUEUE.glob("*.queue"), key=lambda p: p.stat().st_mtime)
    for old in items[:-MAX_QUEUE]:
        try:
            old.unlink()
            log(f"drop old detect queue {old.name}")
        except OSError:
            pass


def enqueue_synthesis(source_name):
    SYNTH_QUEUE.mkdir(parents=True, exist_ok=True)
    event_id = time.strftime("%Y%m%d_%H%M%S")
    tmp = SYNTH_QUEUE / f".{event_id}.tmp"
    final = SYNTH_QUEUE / f"{event_id}.queue"
    tmp.write_text(source_name + "\n", encoding="utf-8")
    tmp.replace(final)


def process_one(path):
    try:
        image_path = Path(path.read_text(encoding="utf-8").strip())
    except Exception as exc:
        log(f"bad queue {path.name}: {exc}")
        return
    if not image_path.is_file():
        log(f"missing image from queue {path.name}: {image_path}")
        return
    log(f"detect start {image_path.name}")
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "/home/philip/bin/person_detect.py", str(image_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=75,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log(f"detect timeout {image_path.name}")
        return
    output = (result.stdout or "").strip().replace("\n", " | ")
    log(f"detect exit={result.returncode} {image_path.name} {output}")
    if result.returncode == 0:
        enqueue_synthesis(image_path.name)
        log(f"synthesis queued {image_path.name}")


def main():
    QUEUE.mkdir(parents=True, exist_ok=True)
    SYNTH_QUEUE.mkdir(parents=True, exist_ok=True)
    log("worker started")
    while True:
        trim_queue()
        items = sorted(QUEUE.glob("*.queue"), key=lambda p: p.stat().st_mtime)
        if not items:
            time.sleep(1.0)
            continue
        item = items[0]
        processing = item.with_suffix(".processing")
        try:
            item.rename(processing)
        except OSError:
            time.sleep(0.2)
            continue
        try:
            process_one(processing)
        finally:
            try:
                processing.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
