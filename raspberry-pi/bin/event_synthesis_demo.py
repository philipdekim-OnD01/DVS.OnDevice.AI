#!/usr/bin/env python3
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np


BASE = Path("/home/philip/event_synthesis_demo")
DATA = BASE / "data"
IMAGES = DATA / "images"
EVENTS = DATA / "events"
OUTPUT = BASE / "output"
TARGET_WIDTH = int(os.environ.get("EVENT_DEMO_WIDTH", "960"))
OUT_FPS = int(os.environ.get("EVENT_DEMO_FPS", "60"))
OUT_VIDEO = OUTPUT / f"event_synthesis_5s_{TARGET_WIDTH}w_{OUT_FPS}fps.mp4"
METRICS = OUTPUT / f"metrics_{TARGET_WIDTH}w_{OUT_FPS}fps.json"

SECONDS = 5.0
SOURCE_WIDTH = 1920
SOURCE_HEIGHT = 1080
CONTRAST_GAIN = 4.8
EVENT_DECAY = 0.70
OVERLAY_GAIN = 0.45


def temp_c():
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(path.read_text().strip()) / 1000.0
    except Exception:
        return None


def read_cpu_stat():
    parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + vals[4]
    return idle, sum(vals)


def cpu_percent(before, after):
    idle0, total0 = before
    idle1, total1 = after
    dt = total1 - total0
    if dt <= 0:
        return 0.0
    return 100.0 * (1.0 - (idle1 - idle0) / dt)


def fit_width(img):
    h, w = img.shape[:2]
    if w == TARGET_WIDTH:
        return img
    out_h = max(1, round(h * TARGET_WIDTH / w))
    return cv2.resize(img, (TARGET_WIDTH, out_h), interpolation=cv2.INTER_AREA)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    timestamps = np.loadtxt(IMAGES / "timestamp.txt", dtype=np.float64)
    image_paths = sorted(IMAGES.glob("*.jpg"))
    event_paths = sorted(EVENTS.glob("*.npz"))
    if len(image_paths) < 2 or len(event_paths) < 1:
        raise RuntimeError("missing demo data")

    first = cv2.imread(str(image_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise RuntimeError(f"could not read {image_paths[0]}")
    first = fit_width(first)
    h, w = first.shape[:2]
    sx = w / SOURCE_WIDTH
    sy = h / SOURCE_HEIGHT
    writer = cv2.VideoWriter(str(OUT_VIDEO), cv2.VideoWriter_fourcc(*"mp4v"), OUT_FPS, (w, h))
    if not writer.isOpened():
        raise RuntimeError(f"could not create {OUT_VIDEO}")

    total_frames = int(round(SECONDS * OUT_FPS))
    event_memory = np.zeros((h, w), np.float32)
    current_interval = -1
    base = first.astype(np.float32)
    next_img = base.copy()
    xs = ys = ps = ts = None
    cursor = 0

    event_count_total = 0
    frames_written = 0
    slowest_frame_ms = 0.0
    frame_times = []
    temp_before = temp_c()
    cpu_before = read_cpu_stat()
    start = time.perf_counter()

    for out_idx in range(total_frames):
        frame_start = time.perf_counter()
        target_t = timestamps[0] + out_idx * 1_000_000.0 / OUT_FPS
        interval = int(np.searchsorted(timestamps, target_t, side="right") - 1)
        interval = max(0, min(interval, len(event_paths) - 1))

        if interval != current_interval:
            loaded = cv2.imread(str(image_paths[interval]), cv2.IMREAD_COLOR)
            loaded_next = cv2.imread(str(image_paths[interval + 1]), cv2.IMREAD_COLOR)
            if loaded is not None:
                base = fit_width(loaded).astype(np.float32)
            if loaded_next is not None:
                next_img = fit_width(loaded_next).astype(np.float32)
            z = np.load(event_paths[interval])
            xs = np.rint(z["x"] * sx).astype(np.int32)
            ys = np.rint(z["y"] * sy).astype(np.int32)
            ps = z["p"].astype(np.uint8)
            ts = z["t"].astype(np.float64)
            valid = (0 <= xs) & (xs < w) & (0 <= ys) & (ys < h)
            xs, ys, ps, ts = xs[valid], ys[valid], ps[valid], ts[valid]
            order = np.argsort(ts, kind="stable")
            xs, ys, ps, ts = xs[order], ys[order], ps[order], ts[order]
            cursor = 0
            event_memory.fill(0.0)
            current_interval = interval

        event_memory *= EVENT_DECAY
        stop = int(np.searchsorted(ts, target_t, side="right"))
        if stop > cursor:
            slice_x = xs[cursor:stop]
            slice_y = ys[cursor:stop]
            slice_p = ps[cursor:stop]
            pos = slice_p > 0
            np.add.at(event_memory, (slice_y[pos], slice_x[pos]), 1.0)
            np.add.at(event_memory, (slice_y[~pos], slice_x[~pos]), -1.0)
            event_count_total += stop - cursor
            cursor = stop

        t0 = timestamps[interval]
        t1 = timestamps[interval + 1]
        alpha = float(np.clip((target_t - t0) / max(t1 - t0, 1e-6), 0.0, 1.0))
        anchor = cv2.addWeighted(base, 1.0 - 0.12 * alpha, next_img, 0.12 * alpha, 0.0)

        signed = np.clip(event_memory, -10.0, 10.0)
        synth = np.clip(anchor + signed[:, :, None] * CONTRAST_GAIN, 0.0, 255.0)
        pos_map = event_memory > 0.5
        neg_map = event_memory < -0.5
        synth[pos_map] = synth[pos_map] * (1.0 - OVERLAY_GAIN) + np.array([20, 35, 255]) * OVERLAY_GAIN
        synth[neg_map] = synth[neg_map] * (1.0 - OVERLAY_GAIN) + np.array([255, 80, 20]) * OVERLAY_GAIN

        writer.write(synth.astype(np.uint8))
        frames_written += 1
        elapsed_ms = (time.perf_counter() - frame_start) * 1000.0
        frame_times.append(elapsed_ms)
        slowest_frame_ms = max(slowest_frame_ms, elapsed_ms)

    writer.release()
    elapsed = time.perf_counter() - start
    cpu_after = read_cpu_stat()
    temp_after = temp_c()

    metrics = {
        "device": os.uname().nodename,
        "resolution": f"{w}x{h}",
        "source_cis_fps": 50,
        "target_output_fps": OUT_FPS,
        "frames_written": frames_written,
        "source_seconds": SECONDS,
        "wall_seconds": elapsed,
        "achieved_fps": frames_written / elapsed if elapsed else 0.0,
        "realtime_factor": SECONDS / elapsed if elapsed else 0.0,
        "events_processed": event_count_total,
        "events_per_second_processed": event_count_total / elapsed if elapsed else 0.0,
        "mean_frame_ms": float(np.mean(frame_times)),
        "p95_frame_ms": float(np.percentile(frame_times, 95)),
        "slowest_frame_ms": slowest_frame_ms,
        "cpu_percent_during_run": cpu_percent(cpu_before, cpu_after),
        "temperature_c_before": temp_before,
        "temperature_c_after": temp_after,
        "video": OUT_VIDEO.name,
        "method": "CIS anchor plus accumulated DVS polarity events for missing output timestamps",
    }
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
