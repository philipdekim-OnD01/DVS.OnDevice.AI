#!/usr/bin/env bash
set -u

OUT_DIR="/home/philip/camera_snapshots"
LOG_DIR="/home/philip/.local/state/camera-snapshots"
POWER_LOG="$LOG_DIR/power-samples.log"
QUEUE_DIR="$LOG_DIR/detect-queue"
PERSON_DIR="/home/philip/person_snapshots"
LOCK_FILE="/tmp/camera-snapshot.lock"

mkdir -p "$OUT_DIR" "$LOG_DIR" "$QUEUE_DIR" "$PERSON_DIR"

{
  flock -n 9 || {
    echo "$(date --iso-8601=seconds) capture skipped: previous run still active"
    exit 0
  }

  ts="$(date +%Y%m%d_%H%M%S)"
  tmp="$OUT_DIR/.${ts}.tmp.jpg"
  final="$OUT_DIR/${ts}.jpg"

  if timeout 12 ffmpeg -y -hide_banner -loglevel error -f video4linux2 -i /dev/video0 -frames:v 1 "$tmp"; then
    mv "$tmp" "$final"
    echo "$(date --iso-8601=seconds) saved $final"
    if command -v vcgencmd >/dev/null 2>&1; then
      sample_stamp="${ts:0:4}-${ts:4:2}-${ts:6:2} ${ts:9:2}:${ts:11:2}:${ts:13:2}"
      echo "$sample_stamp hw $(vcgencmd get_throttled 2>/dev/null || true) $(vcgencmd measure_temp 2>/dev/null || true) $(vcgencmd measure_volts core 2>/dev/null || true) arm_clock=$(vcgencmd measure_clock arm 2>/dev/null | sed 's/frequency(0)=//' || true) snapshot=$final" >> "$POWER_LOG"
    fi
    /home/philip/bin/prune_similar_snapshots.py "$OUT_DIR" || true
    queue_tmp="$QUEUE_DIR/.${ts}.queue.tmp"
    queue_final="$QUEUE_DIR/${ts}.queue"
    printf '%s\n' "$final" > "$queue_tmp"
    mv "$queue_tmp" "$queue_final"
  else
    rm -f "$tmp"
    echo "$(date --iso-8601=seconds) capture failed"
    exit 1
  fi

  find "$PERSON_DIR" -maxdepth 1 -type f -name "*.jpg" -mmin +1440 -delete
  find "$QUEUE_DIR" -maxdepth 1 -type f -name "*.queue" -mmin +60 -delete
} 9>"$LOCK_FILE" >>"$LOG_DIR/capture.log" 2>&1
