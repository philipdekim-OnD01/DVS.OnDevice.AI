#!/usr/bin/env python3
import subprocess
from pathlib import Path


OUT = Path("/home/philip/event_synthesis_demo/output")
NAMES = [
    "event_synthesis_5s_960w_60fps.mp4",
    "event_synthesis_5s_480w_60fps.mp4",
    "event_synthesis_5s_480w_30fps.mp4",
    "event_synthesis_5s_320w_200fps.mp4",
]


def main():
    for name in NAMES:
        src = OUT / name
        if not src.exists():
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
        print(dst, dst.stat().st_size)


if __name__ == "__main__":
    main()
