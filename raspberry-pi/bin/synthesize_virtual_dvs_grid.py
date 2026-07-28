#!/usr/bin/env python3
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

BASE = Path("/home/philip")
SNAP_DIR = BASE / "camera_snapshots"
PERSON_DIR = BASE / "person_snapshots"
SYNTH_DIR = BASE / "synthetic_frames"
STATE_DIR = BASE / ".local/state/camera-snapshots"
LOG_PATH = STATE_DIR / "synthetic-events.log"

OUTPUT_FRAMES = 60
MAX_EVENTS = 200
MAX_FRAME_WIDTH = 640
JPEG_QUALITY = 84
VIDEO_FPS = 20
DVS_CHUNK_US = 20000.0
DVS_VALID_X0 = 28.0
DVS_VALID_Y0 = 87.0
DVS_MAX_EVENTS_PER_CHUNK = 140000


def now_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def newest_jpgs(path, limit=6):
    if not path.exists():
        return []
    return sorted(path.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def resize_keep(img, max_width):
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    nh = max(1, int(h * max_width / w))
    return cv2.resize(img, (max_width, nh), interpolation=cv2.INTER_AREA)


def align_images(images):
    h = min(img.shape[0] for img in images)
    w = min(img.shape[1] for img in images)
    return [img[:h, :w] for img in images]


def make_virtual_event_mask(before, after):
    g0 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(g0, g1)
    blur = cv2.GaussianBlur(diff, (5, 5), 0)
    _, raw = cv2.threshold(blur, 14, 255, cv2.THRESH_BINARY)

    # Make the virtual DVS grid follow the moving person's silhouette instead
    # of filling random background changes. This stays lightweight: no model
    # inference, only contour filtering and morphology.
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    raw = cv2.dilate(raw, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(raw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = raw.shape[:2]
    min_area = max(180, int(h * w * 0.002))
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        aspect = bh / max(1, bw)
        if aspect < 0.8 or aspect > 5.5:
            continue
        candidates.append((area, c))

    mask = np.zeros_like(raw)
    if candidates:
        # Keep the strongest one or two moving blobs, which usually correspond
        # to the person body and a moving arm/leg.
        for _, contour in sorted(candidates, key=lambda item: item[0], reverse=True)[:2]:
            hull = cv2.convexHull(contour)
            cv2.drawContours(mask, [hull], -1, 255, -1)
    else:
        mask = raw

    mask = cv2.GaussianBlur(mask, (7, 7), 0)
    _, mask = cv2.threshold(mask, 40, 255, cv2.THRESH_BINARY)
    return mask


def estimate_shift(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) < 50:
        return 0.0, 0.0
    h, w = mask.shape[:2]
    cx = float(np.mean(xs))
    cy = float(np.mean(ys))
    dx = (cx - w / 2.0) * 0.035
    dy = (cy - h / 2.0) * 0.020
    return max(-14.0, min(14.0, dx)), max(-10.0, min(10.0, dy))


def translate(img, dx, dy):
    h, w = img.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

def translate_mask(mask, dx, dy):
    h, w = mask.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(mask, m, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def person_shape_mask(mask):
    shaped = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8))
    shaped = cv2.dilate(shaped, np.ones((13, 9), np.uint8), iterations=2)
    contours, _ = cv2.findContours(shaped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    if contours:
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:2]
        for contour in contours:
            if cv2.contourArea(contour) < 120:
                continue
            hull = cv2.convexHull(contour)
            cv2.drawContours(out, [hull], -1, 255, -1)
    if np.count_nonzero(out) < 80:
        out = shaped
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, np.ones((21, 15), np.uint8))
    return out


def intermediate_person_mask(mask, t, dx, dy):
    shaped = person_shape_mask(mask)
    a = translate_mask(shaped, -dx * (0.5 - t), -dy * (0.5 - t))
    b = translate_mask(shaped, dx * (t - 0.5), dy * (t - 0.5))
    mixed = cv2.bitwise_or(a, b)
    mixed = cv2.GaussianBlur(mixed, (9, 9), 0)
    _, mixed = cv2.threshold(mixed, 36, 255, cv2.THRESH_BINARY)
    mixed = cv2.morphologyEx(mixed, cv2.MORPH_CLOSE, np.ones((15, 11), np.uint8))
    return mixed


def remove_people_from_context(before, after, motion_mask, dx=0.0, dy=0.0):
    # Build a static scene context, then aggressively remove the real person
    # locations and the path between them. This prevents DVS from being drawn
    # on top of visible person ghosts in the intermediate frames.
    context = cv2.addWeighted(before, 0.50, after, 0.50, 0)
    base = person_shape_mask(motion_mask)
    erase = np.zeros_like(base)
    path_dx = float(np.clip(dx * 3.2, -46.0, 46.0))
    path_dy = float(np.clip(dy * 3.2, -34.0, 34.0))
    for phase in np.linspace(-0.70, 0.70, 9):
        shifted = translate_mask(base, path_dx * phase, path_dy * phase)
        erase = cv2.bitwise_or(erase, shifted)
    erase = cv2.morphologyEx(erase, cv2.MORPH_CLOSE, np.ones((33, 25), np.uint8))
    erase = cv2.dilate(erase, np.ones((45, 31), np.uint8), iterations=2)

    # Add a broad difference mask as a fallback for limbs or blur that the
    # contour hull missed.
    diff = cv2.absdiff(
        cv2.cvtColor(before, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(after, cv2.COLOR_BGR2GRAY),
    )
    _, diff_mask = cv2.threshold(cv2.GaussianBlur(diff, (9, 9), 0), 9, 255, cv2.THRESH_BINARY)
    diff_mask = cv2.dilate(diff_mask, np.ones((25, 25), np.uint8), iterations=1)
    erase = cv2.bitwise_or(erase, diff_mask)

    try:
        context = cv2.inpaint(context, erase, 7, cv2.INPAINT_TELEA)
    except Exception:
        blur = cv2.GaussianBlur(context, (41, 41), 0)
        context[erase > 0] = blur[erase > 0]
    return context, erase


def constrain_heat_to_path(heat, person_shape):
    if person_shape is None or np.count_nonzero(person_shape) == 0:
        return heat
    allowed = cv2.dilate(person_shape, np.ones((9, 9), np.uint8), iterations=1)
    out = np.zeros_like(heat)
    out[allowed > 0] = heat[allowed > 0]
    return out


def track_gap_mask(base_mask, t, dx, dy):
    # Cooperative-stereo inspired interpretation for our monocular fallback:
    # treat the event cluster as a target track and render only the unobserved
    # target position between two real CIS observations. Start/end positions
    # are explicitly removed so DVS never lands on the real person frames.
    base = person_shape_mask(base_mask)
    path_dx = float(np.clip(dx * 3.4, -56.0, 56.0))
    path_dy = float(np.clip(dy * 3.4, -42.0, 42.0))
    start = translate_mask(base, -path_dx * 0.50, -path_dy * 0.50)
    end = translate_mask(base, path_dx * 0.50, path_dy * 0.50)
    mid = translate_mask(base, path_dx * (t - 0.50), path_dy * (t - 0.50))

    observed = cv2.bitwise_or(start, end)
    observed = cv2.dilate(observed, np.ones((37, 29), np.uint8), iterations=2)
    gap = cv2.bitwise_and(mid, cv2.bitwise_not(observed))

    if np.count_nonzero(gap) < 100:
        # If the estimated displacement is small, create a narrow bridge
        # between centroids and use it as the unobserved path support.
        bridge = np.zeros_like(base)
        c0 = mask_centroid(start)
        c1 = mask_centroid(end)
        cv2.line(
            bridge,
            (int(c0[0]), int(c0[1])),
            (int(c1[0]), int(c1[1])),
            255,
            max(15, min(base.shape[:2]) // 22),
        )
        bridge = cv2.bitwise_and(bridge, cv2.dilate(base, np.ones((45, 31), np.uint8), iterations=2))
        gap = cv2.bitwise_and(bridge, cv2.bitwise_not(observed))

    gap = cv2.morphologyEx(gap, cv2.MORPH_CLOSE, np.ones((13, 9), np.uint8))
    gap = cv2.GaussianBlur(gap, (7, 7), 0)
    _, gap = cv2.threshold(gap, 32, 255, cv2.THRESH_BINARY)
    return gap



def mask_centroid(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) < 20:
        h, w = mask.shape[:2]
        return w / 2.0, h / 2.0
    return float(np.mean(xs)), float(np.mean(ys))


def make_virtual_dvs_npz(before, after, out_path, pair_idx, width_scale):
    g0 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY).astype(np.int16)
    g1 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.int16)
    delta = g1 - g0
    base_mask = make_virtual_event_mask(before, after)
    strength = np.abs(delta)
    event_mask = (base_mask > 0) & (strength >= 10)
    ys, xs = np.where(event_mask)
    if len(xs) == 0:
        ys, xs = np.where(base_mask > 0)
    if len(xs) == 0:
        np.savez_compressed(
            str(out_path),
            x=np.array([], dtype=np.float32),
            y=np.array([], dtype=np.float32),
            t=np.array([], dtype=np.float32),
            p=np.array([], dtype=np.uint8),
        )
        return 0, base_mask

    if len(xs) > DVS_MAX_EVENTS_PER_CHUNK:
        idx = np.linspace(0, len(xs) - 1, DVS_MAX_EVENTS_PER_CHUNK).astype(np.int64)
        xs = xs[idx]
        ys = ys[idx]

    cx, cy = mask_centroid(base_mask)
    dx, dy = estimate_shift(base_mask)
    # Amplify the path estimate so DVS events occupy the missing trajectory
    # between sparse CIS captures instead of staying on one static difference
    # blob. This is still deterministic and lightweight.
    path_dx = float(np.clip(dx * 2.2, -32.0, 32.0))
    path_dy = float(np.clip(dy * 2.2, -24.0, 24.0))
    if abs(path_dx) + abs(path_dy) < 3.0:
        h, w = base_mask.shape[:2]
        path_dx = float(np.clip((cx - w / 2.0) * 0.08, -20.0, 20.0))
        path_dy = float(np.clip((cy - h / 2.0) * 0.05, -16.0, 16.0))

    local_strength = np.maximum(1.0, strength[ys, xs].astype(np.float32))
    polarity = (delta[ys, xs] >= 0).astype(np.uint8)

    phase = np.linspace(0.0, 1.0, len(xs), dtype=np.float32)
    wave = np.sin(phase * math.pi).astype(np.float32)
    traj_x = xs.astype(np.float32) + (phase - 0.5) * path_dx
    traj_y = ys.astype(np.float32) + (phase - 0.5) * path_dy + wave * path_dy * 0.18

    h, w = base_mask.shape[:2]
    good = (traj_x >= 0) & (traj_x < w) & (traj_y >= 0) & (traj_y < h)
    traj_x = traj_x[good]
    traj_y = traj_y[good]
    polarity = polarity[good]
    local_strength = local_strength[good]
    phase = phase[good]

    # Stronger changes fire slightly earlier, but the dominant component is
    # phase along the estimated person path. Later rendering windows therefore
    # reveal the event silhouette moving through the gap between photos.
    strength_phase = 1.0 - np.minimum(local_strength / 255.0, 1.0)
    t_local = (0.86 * phase + 0.14 * strength_phase) * (DVS_CHUNK_US - 1.0)

    x_raw = traj_x / max(width_scale, 1e-6) + DVS_VALID_X0
    y_raw = traj_y / max(width_scale, 1e-6) + DVS_VALID_Y0
    t_raw = pair_idx * DVS_CHUNK_US + t_local
    np.savez_compressed(
        str(out_path),
        x=x_raw.astype(np.float32),
        y=y_raw.astype(np.float32),
        t=t_raw.astype(np.float32),
        p=polarity.astype(np.uint8),
    )
    return int(len(x_raw)), base_mask


def rasterize_dvs_npz(npz_path, shape, width_scale):
    h, w = shape[:2]
    heat = np.zeros((h, w, 3), dtype=np.uint8)
    try:
        data = np.load(str(npz_path))
        xs = ((data["x"].astype(np.float32) - DVS_VALID_X0) * width_scale).astype(np.int32)
        ys = ((data["y"].astype(np.float32) - DVS_VALID_Y0) * width_scale).astype(np.int32)
        ps = data["p"].astype(np.uint8)
    except Exception:
        return heat, 0
    good = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    xs = xs[good]
    ys = ys[good]
    ps = ps[good]
    if len(xs) == 0:
        return heat, 0
    pos = ps > 0
    heat[ys[pos], xs[pos], 1] = 255
    heat[ys[pos], xs[pos], 2] = 90
    heat[ys[~pos], xs[~pos], 0] = 255
    heat[ys[~pos], xs[~pos], 2] = 160
    heat = cv2.dilate(heat, np.ones((2, 2), np.uint8), iterations=1)
    return heat, int(len(xs))


def draw_dvs_grid_background(shape):
    h, w = shape[:2]
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :, :] = (10, 12, 16)
    step = max(24, min(h, w) // 18)
    for x in range(0, w, step):
        cv2.line(frame, (x, 0), (x, h - 1), (30, 34, 42), 1)
    for y in range(0, h, step):
        cv2.line(frame, (0, y), (w - 1, y), (30, 34, 42), 1)
    return frame


def draw_white_dvs_plane(shape):
    h, w = shape[:2]
    frame = np.full((h, w, 3), 255, dtype=np.uint8)
    return frame


def window_dvs_npz(npz_path, shape, width_scale, t, window=0.32, person_mask=None):
    h, w = shape[:2]
    heat = np.zeros((h, w, 3), dtype=np.uint8)
    try:
        data = np.load(str(npz_path))
        xs = ((data["x"].astype(np.float32) - DVS_VALID_X0) * width_scale).astype(np.int32)
        ys = ((data["y"].astype(np.float32) - DVS_VALID_Y0) * width_scale).astype(np.int32)
        ts = data["t"].astype(np.float32)
        ps = data["p"].astype(np.uint8)
    except Exception:
        return heat, 0
    if len(xs) == 0:
        return heat, 0
    t0 = float(np.min(ts))
    t1 = float(np.max(ts))
    span = max(1.0, t1 - t0)
    center = t0 + t * span
    half = span * window * 0.5
    selected = (ts >= center - half) & (ts <= center + half)
    if np.count_nonzero(selected) < 120:
        selected = np.ones_like(ts, dtype=bool)
    xs = xs[selected]
    ys = ys[selected]
    ps = ps[selected]
    good = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    xs = xs[good]
    ys = ys[good]
    ps = ps[good]
    if len(xs):
        pos = ps > 0
        heat[ys[pos], xs[pos], 1] = 255
        heat[ys[pos], xs[pos], 2] = 80
        heat[ys[~pos], xs[~pos], 0] = 255
        heat[ys[~pos], xs[~pos], 2] = 185

    if person_mask is not None and np.count_nonzero(person_mask) > 0:
        edge = cv2.Canny(person_mask, 40, 120)
        fill = cv2.erode(person_mask, np.ones((5, 5), np.uint8), iterations=1)
        heat[fill > 0, 1] = np.maximum(heat[fill > 0, 1], 82)
        heat[fill > 0, 2] = np.maximum(heat[fill > 0, 2], 42)
        heat[edge > 0, 1] = 255
        heat[edge > 0, 2] = 130

        # Add deterministic scanline-like event samples inside the body shape.
        ys2, xs2 = np.where(fill > 0)
        if len(xs2):
            keep = ((xs2 + ys2 + int(t * 100)) % 7) == 0
            xs2 = xs2[keep]
            ys2 = ys2[keep]
            heat[ys2, xs2, 0] = 110
            heat[ys2, xs2, 1] = 230
            heat[ys2, xs2, 2] = 210

    heat = cv2.dilate(heat, np.ones((2, 2), np.uint8), iterations=1)
    heat = cv2.GaussianBlur(heat, (3, 3), 0)
    return heat, int(len(xs) + (np.count_nonzero(person_mask) if person_mask is not None else 0))


def synth_between(before, after, t, dvs_npz=None, mask=None, width_scale=1.0):
    if mask is None:
        mask = make_virtual_event_mask(before, after)
    dx, dy = estimate_shift(mask)

    if dvs_npz is not None:
        # Real photo frames stay untouched. Between them, remove the visible
        # people from the context and draw DVS only at the estimated missing
        # person path.
        _, erased_people = remove_people_from_context(before, after, mask, dx, dy)
        frame = draw_white_dvs_plane(before.shape)
        person_shape = track_gap_mask(mask, t, dx, dy)
        # Draw only the estimated gap events on a DVS plane. This matches the
        # reference style: real RGB frames stay intact, while inserted frames
        # are pure red/blue event views.
        person_shape = cv2.bitwise_and(person_shape, erased_people)
        heat, event_count = window_dvs_npz(dvs_npz, before.shape, width_scale, t, window=0.40, person_mask=person_shape)
        heat = constrain_heat_to_path(heat, person_shape)
        event_pixels = np.any(heat > 0, axis=2)
        frame[event_pixels] = heat[event_pixels]
        cv2.rectangle(frame, (10, before.shape[0] - 34), (346, before.shape[0] - 10), (0, 0, 0), -1)
        cv2.putText(
            frame,
            f"DVS fills missing person path {event_count}",
            (18, before.shape[0] - 17),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (147, 197, 253),
            1,
            cv2.LINE_AA,
        )
        return frame, event_count, dx, dy

    frame = draw_dvs_grid_background(before.shape)
    heat = np.zeros_like(frame)
    heat[:, :, 1] = (mask * (1.0 - t)).astype(np.uint8)
    heat[:, :, 2] = (mask * t).astype(np.uint8)
    event_count = int(np.count_nonzero(mask))
    frame = cv2.addWeighted(frame, 1.0, heat, 0.95, 0)
    return frame, event_count, dx, dy


def label_frame(frame, text, real=False):
    color = (92, 200, 167) if real else (217, 189, 112)
    cv2.rectangle(frame, (8, 8), (230, 35), (0, 0, 0), -1)
    cv2.putText(frame, text, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
    return frame


def make_video(out_dir, event_id):
    list_path = out_dir / "frames.txt"
    ordered = sorted(out_dir.glob(f"{event_id}_*.jpg"))
    list_path.write_text("".join(f"file '{p.name}'\n" for p in ordered), encoding="utf-8")
    video = out_dir / f"{event_id}.mp4"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-r", str(VIDEO_FPS),
        "-vf", "format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "27",
        "-movflags", "+faststart",
        str(video),
    ]
    try:
        subprocess.run(cmd, check=True, cwd=str(out_dir), timeout=12)
        return video.name
    except Exception:
        return None


def prune_old():
    dirs = [p for p in SYNTH_DIR.iterdir() if p.is_dir()] if SYNTH_DIR.exists() else []
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for d in dirs[MAX_EVENTS:]:
        for f in d.glob("*"):
            f.unlink(missing_ok=True)
        d.rmdir()


def target_plan(source_count):
    # More grid frames make the motion look smoother. With the current 0.1s
    # person burst, a typical 6-photo sequence becomes 32 frames:
    # photo - 5/6 grids - photo - 5/6 grids ...
    source_count = max(2, min(source_count, OUTPUT_FRAMES))
    intervals = source_count - 1
    synthetic_total = OUTPUT_FRAMES - source_count
    base = synthetic_total // intervals
    extra = synthetic_total % intervals
    return [base + (1 if i < extra else 0) for i in range(intervals)]


def synthesize_sequence(paths):
    loaded = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is not None:
            loaded.append((p, resize_keep(img, MAX_FRAME_WIDTH)))
    if len(loaded) < 2:
        raise RuntimeError("need at least two readable images")

    paths = [p for p, _ in loaded]
    original_width = max(1, loaded[0][1].shape[1])
    images = align_images([img for _, img in loaded])
    width_scale = images[0].shape[1] / float(original_width)
    event_id = now_id()
    out_dir = SYNTH_DIR / event_id
    out_dir.mkdir(parents=True, exist_ok=True)
    dvs_dir = out_dir / "virtual_dvs"
    dvs_dir.mkdir(parents=True, exist_ok=True)

    per_interval = target_plan(len(images))
    frames = []
    event_pixels = 0
    shifts = []
    idx = 0

    for pair_idx, synth_count in enumerate(per_interval):
        before = images[pair_idx]
        after = images[pair_idx + 1]
        real = before.copy()
        name = f"{event_id}_{idx:02d}.jpg"
        cv2.imwrite(str(out_dir / name), real, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        frames.append(name)
        idx += 1

        dvs_name = f"{event_id}_pair{pair_idx:02d}.npz"
        dvs_path = dvs_dir / dvs_name
        raw_events, pair_mask = make_virtual_dvs_npz(before, after, dvs_path, pair_idx, width_scale)
        for j in range(synth_count):
            t = (j + 1) / (synth_count + 1)
            frame, pixels, dx, dy = synth_between(before, after, t, dvs_path, pair_mask, width_scale)
            event_pixels += pixels
            shifts.append((dx, dy))
            label_frame(frame, f"dvs {pair_idx + 1}.{j + 1} raw={raw_events}", False)
            name = f"{event_id}_{idx:02d}.jpg"
            cv2.imwrite(str(out_dir / name), frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            frames.append(name)
            idx += 1

    real = images[-1].copy()
    name = f"{event_id}_{idx:02d}.jpg"
    cv2.imwrite(str(out_dir / name), real, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    frames.append(name)

    if len(frames) > OUTPUT_FRAMES:
        frames = frames[:OUTPUT_FRAMES]

    video_name = make_video(out_dir, event_id)
    avg_shift = {
        "dx": round(sum(x for x, _ in shifts) / len(shifts), 2) if shifts else 0,
        "dy": round(sum(y for _, y in shifts) / len(shifts), 2) if shifts else 0,
    }
    meta = {
        "id": event_id,
        "video": video_name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "mode": "rgb_photo_white_plane_cooperative_dvs_events",
        "source_images": [p.name for p in paths],
        "source_before": paths[0].name,
        "source_after": paths[-1].name,
        "output_frames": len(frames),
        "shape_mask": "white_dvs_plane_gap_events_between_rgb_people",
        "video_fps": VIDEO_FPS,
        "grid_distribution": per_interval,
        "estimated_shift": avg_shift,
        "event_pixels": event_pixels,
        "virtual_dvs_format": "npz:x(float32),y(float32),t(float32),p(uint8)",
        "virtual_dvs_chunks": [p.name for p in sorted(dvs_dir.glob("*.npz"))],
        "virtual_dvs_chunk_us": DVS_CHUNK_US,
        "frames": frames,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    prune_old()
    return meta


def main():
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    args = [Path(p) for p in sys.argv[1:]]
    if len(args) >= 2:
        paths = args
    else:
        paths = list(reversed(newest_jpgs(PERSON_DIR, 2) or newest_jpgs(SNAP_DIR, 6)))
    if len(paths) < 2:
        raise RuntimeError("need at least two jpgs")
    print(json.dumps(synthesize_sequence(paths), ensure_ascii=False))


if __name__ == "__main__":
    main()
