#!/usr/bin/env python3
import subprocess
from pathlib import Path


OUT = Path("/home/philip/event_synthesis_demo/output")
NAMES = [
    "realtime_synthesis_960w_target60fps.mp4",
    "realtime_synthesis_480w_target60fps.mp4",
    "realtime_synthesis_320w_target400fps.mp4",
]


def main():
    for name in NAMES:
        src = OUT / name
        if not src.exists():
            print(f"missing {src}")
            continue
        dst = OUT / f"{src.stem}_h264.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                str(dst),
            ],
            check=True,
        )
        print(dst.name, dst.stat().st_size)


if __name__ == "__main__":
    main()
