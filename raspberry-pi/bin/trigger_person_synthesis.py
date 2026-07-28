#!/usr/bin/env python3
import json
import subprocess
from datetime import datetime
from pathlib import Path

BASE = Path("/home/philip")
SNAP_DIR = BASE / "camera_snapshots"
PERSON_DIR = BASE / "person_snapshots"
BURST_DIR = BASE / ".local/state/camera-snapshots/person-bursts"
QUEUE_DIR = BASE / ".local/state/camera-snapshots/mail-queue"
SYNTH = BASE / "bin/synthesize_virtual_dvs_grid.py"


def newest(path, limit=30):
    if not path.exists():
        return []
    return sorted(path.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def unique_ordered(paths):
    seen = set()
    out = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def pick_sources():
    # 1. Best source: the latest 0.1s burst directory from an actual person
    # detection. Use all frames in chronological order.
    burst_dirs = [p for p in BURST_DIR.glob("*") if p.is_dir()] if BURST_DIR.exists() else []
    burst_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for burst_dir in burst_dirs[:3]:
        imgs = sorted(burst_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        imgs = unique_ordered(imgs)
        if len(imgs) >= 3:
            return imgs[:8]

    # 2. Practical fallback: use many recent person snapshots, not just two.
    # Restrict to a recent cluster so unrelated older people/events are not
    # stitched together. This directly addresses the unnatural video issue.
    persons_newest = newest(PERSON_DIR, 16)
    if len(persons_newest) >= 2:
        latest_time = persons_newest[0].stat().st_mtime
        cluster = [p for p in persons_newest if latest_time - p.stat().st_mtime <= 90]
        if len(cluster) < 4:
            cluster = persons_newest[:6]
        cluster = list(reversed(unique_ordered(cluster[:8])))
        if len(cluster) >= 2:
            return cluster

    # 3. Last resort: combine recent snapshots. Never return duplicate files.
    snaps = list(reversed(unique_ordered(newest(SNAP_DIR, 8))))
    return snaps


def queue_mail(meta):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    event_id = meta.get("id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    source_images = ", ".join(meta.get("source_images", []))
    payload = {
        "id": event_id,
        "created": datetime.now().isoformat(timespec="seconds"),
        "to": "philip.de.kim@gmail.com",
        "subject": f"Raspberry Pi 사람 감지 다중사진 합성 영상: {event_id}",
        "body": (
            "사람 감지가 발생하여 여러 person 사진을 활용한 합성 영상을 생성했습니다.\n\n"
            f"Event ID: {event_id}\n"
            f"Mode: {meta.get('mode', '')}\n"
            f"Output frames: {meta.get('output_frames', 0)}\n"
            f"Video FPS: {meta.get('video_fps', 20)}\n"
            f"Source count: {len(meta.get('source_images', []))}\n"
            f"Source images: {source_images}\n"
            f"Grid distribution: {meta.get('grid_distribution', [])}\n"
            f"Shape mask: {meta.get('shape_mask', '')}\n\n"
            "확인 링크:\n"
            f"- Grid: http://192.168.0.100:8081/\n"
            f"- Player: http://192.168.0.100:8081/play/{event_id}\n\n"
            "이번 버전은 같은 사진 2장을 반복하지 않고, 최근 person 사진 시퀀스를 우선 사용합니다."
        ),
        "attachments": [
            str(BASE / "synthetic_frames" / event_id / name)
            for name in meta.get("frames", [])
            if name.endswith(".jpg")
        ][:3],
        "player_url": f"http://192.168.0.100:8081/play/{event_id}",
        "grid_url": "http://192.168.0.100:8081/",
    }
    path = QUEUE_DIR / f"{event_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    sources = pick_sources()
    if len(sources) < 2:
        print("skip: source images unavailable")
        return 0
    result = subprocess.run(
        ["python3", str(SYNTH), *[str(p) for p in sources]],
        check=True,
        capture_output=True,
        text=True,
        timeout=35,
    )
    meta = json.loads(result.stdout)
    queue = queue_mail(meta)
    print(f"multi-person-source synthetic video created: {meta['id']}")
    print(f"sources: {len(meta.get('source_images', []))}")
    print(f"mail queued: {queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
