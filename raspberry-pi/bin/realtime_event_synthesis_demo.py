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

TARGET_WIDTH = int(os.environ.get("EVENT_DEMO_WIDTH", "480"))
TARGET_OUTPUT_FPS = int(os.environ.get("EVENT_DEMO_TARGET_FPS", "60"))
WALL_SECONDS = float(os.environ.get("EVENT_DEMO_WALL_SECONDS", "5"))
PLAYBACK_FPS = int(os.environ.get("EVENT_DEMO_PLAYBACK_FPS", "30"))
DRAW_OVERLAY = os.environ.get("EVENT_DEMO_DRAW_OVERLAY", "0") == "1"

SOURCE_WIDTH = 1920
SOURCE_HEIGHT = 1080
CONTRAST_GAIN = 4.8
EVENT_DECAY = 0.70
OVERLAY_GAIN = 0.45

OUT_VIDEO = OUTPUT / f"realtime_synthesis_{TARGET_WIDTH}w_target{TARGET_OUTPUT_FPS}fps.mp4"
METRICS = OUTPUT / f"realtime_metrics_{TARGET_WIDTH}w_target{TARGET_OUTPUT_FPS}fps.json"


def read_mem():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            values[key] = int(rest.strip().split()[0])
    except Exception:
        return 0, 0, 0.0
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    pct = used / total * 100.0 if total else 0.0
    return used // 1024, total // 1024, pct


def temp_c():
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
    except Exception:
        return None


def cpu_stat():
    parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    return vals[3] + vals[4], sum(vals)


def cpu_pct(prev, current):
    idle0, total0 = prev
    idle1, total1 = current
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


def draw_overlay(frame, stats):
    h, w = frame.shape[:2]
    panel_h = 82
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, panel_h), (8, 10, 13), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    lines = [
        f"Realtime synthesis: {stats['resolution']} target {stats['target_fps']} FPS",
        f"elapsed {stats['elapsed']:.2f}s / {stats['wall_seconds']:.1f}s   generated {stats['frames']} frames   achieved {stats['achieved_fps']:.1f} FPS",
        f"CPU {stats['cpu']:.1f}%   Memory {stats['mem_used']} / {stats['mem_total']} MB ({stats['mem_pct']:.1f}%)   Temp {stats['temp']}",
    ]
    y = 22
    for idx, line in enumerate(lines):
        color = (230, 242, 248) if idx == 0 else (188, 205, 214)
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        y += 24


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    timestamps = np.loadtxt(IMAGES / "timestamp.txt", dtype=np.float64)
    image_paths = sorted(IMAGES.glob("*.jpg"))
    event_paths = sorted(EVENTS.glob("*.npz"))
    first = cv2.imread(str(image_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise RuntimeError("missing first image")
    first = fit_width(first)
    h, w = first.shape[:2]
    sx = w / SOURCE_WIDTH
    sy = h / SOURCE_HEIGHT

    writer = cv2.VideoWriter(str(OUT_VIDEO), cv2.VideoWriter_fourcc(*"mp4v"), PLAYBACK_FPS, (w, h))
    if not writer.isOpened():
        raise RuntimeError(f"could not create {OUT_VIDEO}")

    event_memory = np.zeros((h, w), np.float32)
    current_interval = -1
    base = first.astype(np.float32)
    next_img = base.copy()
    xs = ys = ps = ts = None
    cursor = 0
    frame_count = 0
    event_count = 0

    start = time.perf_counter()
    cpu_prev = cpu_stat()
    cpu_now = 0.0
    cpu_samples = []
    temp_samples = []
    mem_samples = []

    while True:
        now = time.perf_counter()
        elapsed = now - start
        if elapsed >= WALL_SECONDS:
            break

        target_t = timestamps[0] + frame_count * 1_000_000.0 / TARGET_OUTPUT_FPS
        if target_t >= timestamps[-1]:
            break
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
            event_count += stop - cursor
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

        if frame_count == 0 or frame_count % max(1, PLAYBACK_FPS // 2) == 0:
            cpu_current = cpu_stat()
            cpu_now = cpu_pct(cpu_prev, cpu_current)
            cpu_prev = cpu_current
        mem_used, mem_total, mem_pct_value = read_mem()
        current_temp = temp_c()
        cpu_samples.append(cpu_now)
        mem_samples.append(mem_pct_value)
        if current_temp is not None:
            temp_samples.append(current_temp)

        frame = synth.astype(np.uint8)
        if DRAW_OVERLAY:
            draw_overlay(
                frame,
                {
                    "resolution": f"{w}x{h}",
                    "target_fps": TARGET_OUTPUT_FPS,
                    "elapsed": elapsed,
                    "wall_seconds": WALL_SECONDS,
                    "frames": frame_count + 1,
                    "achieved_fps": (frame_count + 1) / max(elapsed, 1e-6),
                    "cpu": cpu_now,
                    "mem_used": mem_used,
                    "mem_total": mem_total,
                    "mem_pct": mem_pct_value,
                    "temp": f"{current_temp:.1f}C" if current_temp is not None else "n/a",
                },
            )
        writer.write(frame)
        frame_count += 1

    writer.release()
    elapsed = time.perf_counter() - start
    metrics = {
        "device": os.uname().nodename,
        "mode": "wall_clock_realtime",
        "resolution": f"{w}x{h}",
        "target_output_fps": TARGET_OUTPUT_FPS,
        "wall_seconds": WALL_SECONDS,
        "frames_written": frame_count,
        "achieved_fps": frame_count / elapsed if elapsed else 0.0,
        "realtime_factor": (frame_count / elapsed / TARGET_OUTPUT_FPS) if elapsed and TARGET_OUTPUT_FPS else 0.0,
        "events_processed": event_count,
        "events_per_second_processed": event_count / elapsed if elapsed else 0.0,
        "cpu_percent_mean": float(np.mean(cpu_samples)) if cpu_samples else 0.0,
        "cpu_percent_max": float(np.max(cpu_samples)) if cpu_samples else 0.0,
        "mem_percent_mean": float(np.mean(mem_samples)) if mem_samples else 0.0,
        "temperature_c_mean": float(np.mean(temp_samples)) if temp_samples else None,
        "temperature_c_max": float(np.max(temp_samples)) if temp_samples else None,
        "video": OUT_VIDEO.name,
    }
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
