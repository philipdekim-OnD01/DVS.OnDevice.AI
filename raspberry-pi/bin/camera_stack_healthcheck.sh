#!/usr/bin/env bash
set -u
STATE_DIR=/home/philip/.local/state/camera-snapshots
FAIL_FILE="$STATE_DIR/healthcheck-fails"
LOG_FILE="$STATE_DIR/healthcheck.log"
mkdir -p "$STATE_DIR"

log() {
  printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG_FILE"
}

fail=0

systemctl --user is-active --quiet camera-snapshots-web.service || {
  log "camera web inactive; restarting"
  systemctl --user restart camera-snapshots-web.service || fail=1
}

systemctl --user is-active --quiet synthetic-grid-web.service || {
  log "synthetic web inactive; restarting"
  systemctl --user restart synthetic-grid-web.service || fail=1
}

systemctl is-active --quiet ssh || {
  log "ssh inactive; asking sudo systemctl start ssh"
  sudo -n /usr/bin/systemctl start ssh || fail=1
}

if command -v vcgencmd >/dev/null 2>&1; then
  throttled="$(vcgencmd get_throttled 2>/dev/null || true)"
  temp="$(vcgencmd measure_temp 2>/dev/null || true)"
  log "status $throttled $temp"
fi

if [ "$fail" -eq 0 ]; then
  echo 0 > "$FAIL_FILE"
  exit 0
fi

count=0
[ -f "$FAIL_FILE" ] && count="$(cat "$FAIL_FILE" 2>/dev/null || echo 0)"
count=$((count + 1))
echo "$count" > "$FAIL_FILE"
log "healthcheck fail count=$count"

if [ "$count" -ge 3 ]; then
  log "rebooting after repeated service recovery failures"
  sudo -n /usr/bin/systemctl reboot
fi
