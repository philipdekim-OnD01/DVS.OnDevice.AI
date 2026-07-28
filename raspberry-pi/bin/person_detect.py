#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np


MODEL_PATH = Path("/home/philip/models/yolov5n.onnx")
OUT_DIR = Path("/home/philip/person_snapshots")
LOG_FILE = Path("/home/philip/.local/state/camera-snapshots/person-events.log")
BURST_KEEP_DIR = Path("/home/philip/.local/state/camera-snapshots/person-bursts")
RETENTION_SECONDS = 24 * 60 * 60
BURST_FRAMES = 5
BURST_FPS = 7
INPUT_SIZE = 640
CONF_THRESHOLD = 0.60
NMS_THRESHOLD = 0.45


def log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")


def cleanup():
    cutoff = time.time() - RETENTION_SECONDS
    for path in OUT_DIR.glob("*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def load_net():
    net = cv2.dnn.readNetFromONNX(str(MODEL_PATH))
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def letterbox(image, size=INPUT_SIZE):
    h, w = image.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - nw) // 2
    pad_y = (size - nh) // 2
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    return canvas, scale, pad_x, pad_y


def detect_image(net, image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        return None

    input_image, scale, pad_x, pad_y = letterbox(image)
    blob = cv2.dnn.blobFromImage(input_image, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
    net.setInput(blob)
    output = net.forward()
    preds = np.squeeze(output)
    if preds.ndim == 1:
        preds = np.expand_dims(preds, axis=0)

    boxes = []
    confidences = []
    for row in preds:
        obj = float(row[4])
        person_prob = float(row[5])  # COCO class 0: person
        conf = obj * person_prob
        if conf < CONF_THRESHOLD:
            continue
        cx, cy, bw, bh = [float(v) for v in row[:4]]
        x = (cx - bw / 2 - pad_x) / scale
        y = (cy - bh / 2 - pad_y) / scale
        w = bw / scale
        h = bh / scale
        boxes.append([int(x), int(y), int(w), int(h)])
        confidences.append(conf)

    if not boxes:
        return None

    keep = cv2.dnn.NMSBoxes(boxes, confidences, CONF_THRESHOLD, NMS_THRESHOLD)
    if len(keep) == 0:
        return None

    detections = []
    ih, iw = image.shape[:2]
    for idx in np.array(keep).flatten():
        x, y, w, h = boxes[int(idx)]
        x = max(0, min(iw - 1, x))
        y = max(0, min(ih - 1, y))
        w = max(1, min(iw - x, w))
        h = max(1, min(ih - y, h))
        detections.append((x, y, w, h, float(confidences[int(idx)])))

    if not detections:
        return None

    score = sum(item[4] for item in detections)
    return {
        "path": image_path,
        "image": image,
        "detections": detections,
        "score": score,
    }


def capture_burst(tmp_dir):
    pattern = str(tmp_dir / "burst_%02d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "video4linux2",
        "-framerate",
        str(BURST_FPS),
        "-i",
        "/dev/video0",
        "-frames:v",
        str(BURST_FRAMES),
        pattern,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=10)
    except Exception as exc:
        log(f"yolo burst capture failed: {exc}")
    return sorted(tmp_dir.glob("burst_*.jpg"))



def keep_burst_sequence(image_path, burst_paths):
    event_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = BURST_KEEP_DIR / event_id
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [image_path] + list(burst_paths)
    kept = []
    for idx, src in enumerate(paths):
        img = cv2.imread(str(src))
        if img is None:
            continue
        dst = out_dir / f"{event_id}_{idx:02d}.jpg"
        cv2.imwrite(str(dst), img, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        kept.append(dst)
    for old in sorted([p for p in BURST_KEEP_DIR.glob("*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)[50:]:
        for child in old.glob("*"):
            child.unlink(missing_ok=True)
        old.rmdir()
    return kept


def save_detection(best, event_path):
    annotated = best["image"].copy()
    for x, y, w, h, conf in best["detections"]:
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (92, 200, 167), 2)
        cv2.putText(
            annotated,
            f"person {conf:.2f}",
            (x, max(18, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (92, 200, 167),
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(event_path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])



def trigger_person_synthesis_once():
    trigger_log = LOG_FILE.parent / "trigger-synthesis.log"
    try:
        with trigger_log.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} trigger start\n")
            result = subprocess.run(
                ["/usr/bin/python3", "/home/philip/bin/trigger_person_synthesis.py"],
                stdout=f,
                stderr=f,
                timeout=45,
                check=False,
            )
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} trigger exit={result.returncode}\n")
    except Exception as exc:
        log(f"person synthesis trigger failed: {exc}")

def main():
    if len(sys.argv) != 2:
        print("usage: person_detect.py IMAGE", file=sys.stderr)
        return 2
    if not MODEL_PATH.is_file():
        log(f"missing YOLO model {MODEL_PATH}")
        return 2

    image_path = Path(sys.argv[1])
    if not image_path.is_file():
        log(f"missing image {image_path}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cleanup()
    net = load_net()

    initial = detect_image(net, image_path)
    if initial is None:
        return 1

    candidates = [initial]
    with tempfile.TemporaryDirectory(prefix="person-yolo-burst-") as tmp:
        tmp_dir = Path(tmp)
        burst_paths = capture_burst(tmp_dir)
        keep_burst_sequence(image_path, burst_paths)
        for burst_path in burst_paths:
            detected = detect_image(net, burst_path)
            if detected is not None:
                candidates.append(detected)

    best = max(candidates, key=lambda item: item["score"])
    event_path = OUT_DIR / image_path.name
    save_detection(best, event_path)
    log(
        "person detected yolo_burst_saved "
        f"{event_path} count={len(best['detections'])} score={best['score']:.2f} "
        f"source={best['path'].name} burst_frames={len(candidates) - 1}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
