#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
import html
import json
import os
import shutil
import tempfile
import subprocess
import time
import datetime


SNAPSHOT_DIR = Path("/home/philip/camera_snapshots")
PERSON_DIR = Path("/home/philip/person_snapshots")
LOG_FILE = Path("/home/philip/.local/state/camera-snapshots/capture.log")
PERSON_LOG_FILE = Path("/home/philip/.local/state/camera-snapshots/person-events.log")
TEMP_HISTORY_FILE = Path("/home/philip/.local/state/camera-snapshots/temperature-history.json")
ROOT_WATCHDOG_LOG = Path("/var/log/camera-root-watchdog/watchdog.log")
POWER_SAMPLE_LOG = Path("/home/philip/.local/state/camera-snapshots/power-samples.log")
THERMAL_GUARD_LOG = Path("/var/log/pi-thermal-clock-guard.log")
EVENT_SYNTH_DIR = Path("/home/philip/event_synthesis_demo")
EVENT_SYNTH_OUTPUT_DIR = EVENT_SYNTH_DIR / "output"
PI5_ARCH_ASSET_DIR = Path("/home/philip/pi5_arch_assets")
TEMP_HISTORY_SECONDS = 24 * 60 * 60
TEMP_HISTORY_MAX_POINTS = 28800


def read_text(path, default=""):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return default


def run_text(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
    except Exception:
        return ""


LAST_CPU_SAMPLE = None
TEMP_HISTORY = []
TEMP_HISTORY_LOADED = False


def cpu_usage_percent():
    global LAST_CPU_SAMPLE
    try:
        parts = read_text("/proc/stat").splitlines()[0].split()[1:]
        vals = [int(x) for x in parts]
    except Exception:
        return 0.0

    idle = vals[3] + vals[4]
    total = sum(vals)
    current = (idle, total)

    if LAST_CPU_SAMPLE is None:
        LAST_CPU_SAMPLE = current
        load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        cores = os.cpu_count() or 1
        return max(0.0, min(100.0, load / cores * 100.0))

    prev_idle, prev_total = LAST_CPU_SAMPLE
    LAST_CPU_SAMPLE = current
    total_delta = total - prev_total
    idle_delta = idle - prev_idle
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def memory_status():
    values = {}
    for line in read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        try:
            values[key] = int(rest.strip().split()[0])
        except Exception:
            pass
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    pct = (used / total * 100.0) if total else 0.0
    return used // 1024, total // 1024, pct


def get_temperature():
    out = run_text(["vcgencmd", "measure_temp"])
    if out:
        return out.replace("temp=", "")
    raw = read_text("/sys/class/thermal/thermal_zone0/temp").strip()
    if raw.isdigit():
        return f"{int(raw) / 1000:.1f}'C"
    return "n/a"


def parse_temperature_c(value):
    try:
        return float(str(value).replace("temp=", "").replace("'C", "").replace("C", "").strip())
    except Exception:
        return None


def load_temperature_history():
    global TEMP_HISTORY_LOADED
    if TEMP_HISTORY_LOADED:
        return
    TEMP_HISTORY_LOADED = True
    try:
        loaded = json.loads(TEMP_HISTORY_FILE.read_text())
    except Exception:
        loaded = []
    now = int(time.time())
    cutoff = now - TEMP_HISTORY_SECONDS
    for item in loaded:
        try:
            ts = int(item["ts"])
            temp_c = float(item["temp_c"])
        except Exception:
            continue
        if ts >= cutoff:
            TEMP_HISTORY.append({"ts": ts, "temp_c": temp_c})
    del TEMP_HISTORY[:-TEMP_HISTORY_MAX_POINTS]


def save_temperature_history():
    try:
        TEMP_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="temperature-history.", suffix=".tmp", dir=str(TEMP_HISTORY_FILE.parent))
        with os.fdopen(fd, "w") as tmp:
            json.dump(TEMP_HISTORY, tmp, separators=(",", ":"))
        os.replace(tmp_name, TEMP_HISTORY_FILE)
    except Exception:
        pass


def record_temperature(value):
    load_temperature_history()
    temp_c = parse_temperature_c(value)
    if temp_c is None:
        return
    now = int(time.time())
    if TEMP_HISTORY and now - TEMP_HISTORY[-1]["ts"] < 2:
        TEMP_HISTORY[-1] = {"ts": now, "temp_c": temp_c}
    else:
        TEMP_HISTORY.append({"ts": now, "temp_c": temp_c})
    cutoff = now - TEMP_HISTORY_SECONDS
    while TEMP_HISTORY and TEMP_HISTORY[0]["ts"] < cutoff:
        TEMP_HISTORY.pop(0)
    del TEMP_HISTORY[:-TEMP_HISTORY_MAX_POINTS]
    save_temperature_history()


def get_throttled():
    out = run_text(["vcgencmd", "get_throttled"])
    return out.replace("throttled=", "") if out else "n/a"


def service_state(unit):
    out = run_text(["systemctl", "--user", "is-active", unit])
    return out or "unknown"


def list_images(directory=SNAPSHOT_DIR):
    items = []
    for path in directory.glob("*.jpg"):
        try:
            st = path.stat()
        except OSError:
            continue
        items.append({"name": path.name, "mtime": st.st_mtime, "size": st.st_size})
    return sorted(items, key=lambda x: x["mtime"], reverse=True)


def format_age(ts):
    seconds = max(0, int(time.time() - ts))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h {minutes % 60}m ago"



def parse_hz(value):
    try:
        return float(str(value).strip()) / 1000000000.0
    except Exception:
        return None


def parse_volts(value):
    text = str(value).replace("volt=", "").replace("V", "").strip()
    try:
        return float(text)
    except Exception:
        return None


def parse_root_watchdog_history():
    points = []
    cutoff = time.time() - TEMP_HISTORY_SECONDS
    lines = []
    for log_path in (POWER_SAMPLE_LOG, ROOT_WATCHDOG_LOG):
        try:
            lines.extend(log_path.read_text(errors="ignore").splitlines()[-12000:])
        except Exception:
            pass
    for line in lines[-16000:]:
        if " hw " not in line or "temp=" not in line:
            continue
        try:
            ts_text = line[:19]
            dt = datetime.datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
            ts = dt.timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        point = {"ts": ts, "temp_c": None, "throttled": "", "core_volts": None, "arm_clock_ghz": None}
        for token in line.split():
            if token.startswith("throttled="):
                point["throttled"] = token.split("=", 1)[1]
            elif token.startswith("temp="):
                point["temp_c"] = parse_temperature_c(token.split("=", 1)[1])
            elif token.startswith("volt="):
                point["core_volts"] = parse_volts(token.split("=", 1)[1])
            elif token.startswith("arm_clock="):
                point["arm_clock_ghz"] = parse_hz(token.split("=", 1)[1])
            elif token.startswith("snapshot="):
                point["snapshot"] = token.split("=", 1)[1].rsplit("/", 1)[-1]
        if point["temp_c"] is None:
            continue
        points.append(point)
    points.sort(key=lambda x: x["ts"])
    deduped = []
    seen = set()
    for point in points:
        key = (int(point["ts"]), point.get("snapshot", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped[-TEMP_HISTORY_MAX_POINTS:]

def get_status():
    images = list_images()
    person_images = list_images(PERSON_DIR)
    used_mb, total_mb, mem_pct = memory_status()
    disk = shutil.disk_usage(SNAPSHOT_DIR)
    latest = images[0] if images else None
    log_tail = read_text(LOG_FILE).splitlines()[-8:]
    person_log_tail = read_text(PERSON_LOG_FILE).splitlines()[-8:]
    temp = get_temperature()
    record_temperature(temp)
    return {
        "cpu_pct": cpu_usage_percent(),
        "mem_used_mb": used_mb,
        "mem_total_mb": total_mb,
        "mem_pct": mem_pct,
        "temp": temp,
        "temp_history": TEMP_HISTORY,
        "temp_history_hours": 24,
        "power_history": parse_root_watchdog_history(),
        "throttled": get_throttled(),
        "arm_clock": run_text(["vcgencmd", "measure_clock", "arm"]).replace("frequency(0)=", ""),
        "core_volts": run_text(["vcgencmd", "measure_volts", "core"]).replace("volt=", ""),
        "arm_mem": run_text(["vcgencmd", "get_mem", "arm"]).replace("arm=", ""),
        "gpu_mem": run_text(["vcgencmd", "get_mem", "gpu"]).replace("gpu=", ""),
        "cpu_thermal_type": read_text("/sys/class/thermal/thermal_zone0/type").strip() or "n/a",
        "usb_devices": run_text(["lsusb"]).splitlines(),
        "video_devices": run_text(["sh", "-c", "v4l2-ctl --list-devices 2>/dev/null"]).splitlines(),
        "i2c_devices": run_text(["sh", "-c", "ls -1 /dev/i2c-* 2>/dev/null"]).splitlines(),
        "gpio_devices": run_text(["sh", "-c", "ls -1 /dev/gpiomem* 2>/dev/null"]).splitlines(),
        "capture_timer": service_state("camera-snapshot.timer"),
        "thermal_guard": run_text(["systemctl", "is-active", "pi-thermal-clock-guard.timer"]) or "unknown",
        "thermal_guard_tail": read_text(THERMAL_GUARD_LOG).splitlines()[-3:],
        "web_service": service_state("camera-snapshots-web.service"),
        "image_count": len(images),
        "person_event_count": len(person_images),
        "latest_name": latest["name"] if latest else "",
        "latest_age": format_age(latest["mtime"]) if latest else "n/a",
        "disk_free_gb": disk.free / 1024 / 1024 / 1024,
        "log_tail": log_tail,
        "person_log_tail": person_log_tail,
        "images": [
            {
                "name": item["name"],
                "age": format_age(item["mtime"]),
                "size_kb": round(item["size"] / 1024),
                "mtime": int(item["mtime"]),
            }
            for item in images[:120]
        ],
        "person_images": [
            {
                "name": item["name"],
                "age": format_age(item["mtime"]),
                "size_kb": round(item["size"] / 1024),
                "mtime": int(item["mtime"]),
            }
            for item in person_images[:80]
        ],
    }


def pct_style(value):
    value = max(0, min(100, float(value)))
    return f"width:{value:.1f}%"


def render_global_nav():
    return '''<div class="global-nav">
  <a href="/">Home</a>
  <span style="display:flex;align-items:center;gap:6px;padding-left:8px;border-left:1px solid #343d46">
    <span style="color:#91a0ad;font-size:12px;font-weight:800;white-space:nowrap">기능</span>
    <a href="/person">Person</a>
    <a href="/raspberry-pi5-architecture">Pi 5 Architecture</a>
    <a href="/event-synthesis">Event Synthesis</a>
    <a href="http://192.168.0.100:8081/">Synthetic</a>
  </span>
  <span style="display:flex;align-items:center;gap:6px;padding-left:8px;border-left:1px solid #343d46">
    <span style="color:#91a0ad;font-size:12px;font-weight:800;white-space:nowrap">제안서</span>
    <a href="/space-edge-proposal">Space Edge</a>
    <a href="/fall-plan">Fall Plan</a>
  </span>
</div>'''


def render_person_page():
    images = list_images(PERSON_DIR)
    cards = []
    for img in images[:240]:
        name = html.escape(img["name"])
        age = html.escape(format_age(img["mtime"]))
        size_kb = img["size"] / 1024
        cards.append(f'''
          <a class="thumb" href="/person-image/{name}" data-src="/person-image/{name}" data-name="{name}" title="{name}">
            <img src="/person-image/{name}" loading="lazy" alt="{name}">
            <span class="thumb-meta"><b>{name}</b><small>{age} · {size_kb:.0f} KB</small></span>
          </a>
        ''')

    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Person Events</title>
  <style>
    :root {{ color-scheme: dark; --bg:#101214; --panel:#191d21; --line:#303840; --text:#edf2f4; --muted:#9aa6ad; --accent:#5cc8a7; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }}
    header {{ position:sticky; top:0; z-index:5; background:rgba(16,18,20,.92); backdrop-filter:blur(14px); border-bottom:1px solid var(--line); }}
    .bar {{ max-width:1480px; margin:0 auto; padding:14px 18px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    h1 {{ margin:0; font-size:20px; font-weight:720; }}
    .sub {{ color:var(--muted); font-size:13px; }}
    .nav {{ display:flex; gap:10px; align-items:center; }}
    .link {{ color:var(--text); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:8px 10px; background:var(--panel); font-size:13px; }}
    main {{ max-width:1480px; margin:0 auto; padding:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(156px,1fr)); gap:12px; }}
    .thumb {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; color:inherit; text-decoration:none; min-width:0; box-shadow:0 8px 24px rgba(0,0,0,.16); }}
    .thumb:hover {{ border-color:#60717d; transform:translateY(-1px); transition:.12s ease; }}
    .thumb img {{ width:100%; aspect-ratio:4 / 3; object-fit:contain; display:block; background:#050607; }}
    .thumb-meta {{ display:block; padding:9px; min-width:0; }}
    .thumb-meta b {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }}
    .thumb-meta small {{ display:block; color:var(--muted); margin-top:3px; font-size:11px; }}
    .empty {{ color:var(--muted); }}
  .global-nav{{position:sticky;top:0;z-index:30;display:flex;justify-content:center;align-items:center;gap:8px;padding:10px 12px;background:#111318;border-bottom:1px solid #30343d}}.global-nav a{{display:inline-flex;align-items:center;justify-content:center;min-width:86px;height:34px;padding:0 14px;border:1px solid #343d46;border-radius:6px;background:#1a1f25;color:#dbeafe;text-decoration:none;font-weight:700;font-size:14px;line-height:1;white-space:nowrap}}.global-nav a:hover{{background:#22303a;border-color:#5cc8a7;color:#ffffff}}@media(max-width:520px){{.global-nav{{gap:6px;padding:8px}}.global-nav a{{min-width:auto;height:32px;padding:0 10px;font-size:13px}}}}
</style>
</head>
<body>{render_global_nav()}
  <header>
    <div class="bar">
      <div>
        <h1>Person Events</h1>
        <div class="sub">{len(images)} detected snapshots · 24h retention</div>
      </div>
      <nav class="nav">
        <a class="link" href="/">Dashboard</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="grid">{''.join(cards) if cards else '<div class="empty">No person events yet.</div>'}</section>
  </main>
</body>
</html>'''


def load_event_synthesis_metrics():
    metrics = []
    for path in sorted(EVENT_SYNTH_OUTPUT_DIR.glob("metrics_*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        item["_file"] = path.name
        metrics.append(item)
    if not metrics:
        legacy = EVENT_SYNTH_OUTPUT_DIR / "metrics.json"
        try:
            item = json.loads(legacy.read_text(encoding="utf-8"))
            item["_file"] = legacy.name
            metrics.append(item)
        except Exception:
            pass
    return sorted(metrics, key=lambda item: (item.get("resolution", ""), item.get("target_output_fps", 0)))


def load_realtime_synthesis_metrics():
    metrics = []
    for path in sorted(EVENT_SYNTH_OUTPUT_DIR.glob("realtime_metrics_*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        item["_file"] = path.name
        metrics.append(item)
    return sorted(metrics, key=lambda item: (item.get("resolution", ""), item.get("target_output_fps", 0)))


def find_realtime_metric(metrics, resolution, target_fps):
    for item in metrics:
        if str(item.get("resolution")) == resolution and int(item.get("target_output_fps", 0) or 0) == target_fps:
            return item
    return None


def render_event_synthesis_page():
    metrics = load_event_synthesis_metrics()
    realtime_metrics = load_realtime_synthesis_metrics()
    videos = [
        ("960x540 @ 60FPS", "event_synthesis_5s_960w_60fps_h264.mp4"),
        ("480x270 @ 60FPS", "event_synthesis_5s_480w_60fps_h264.mp4"),
        ("480x270 @ 30FPS", "event_synthesis_5s_480w_30fps_h264.mp4"),
        ("320x180 @ 200FPS / 1000 frames", "event_synthesis_5s_320w_200fps_h264.mp4"),
        ("320x180 @ 400FPS / 2000 frames", "event_synthesis_5s_320w_400fps_h264.mp4"),
    ]
    video_cards = []
    for label, name in videos:
        path = EVENT_SYNTH_OUTPUT_DIR / name
        if not path.exists():
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        video_cards.append(f'''
          <section class="video-card">
            <div class="card-head"><h2>{html.escape(label)}</h2><span>{size_mb:.1f} MB</span></div>
            <video controls muted playsinline src="/event-synthesis-video/{html.escape(name)}"></video>
          </section>
        ''')

    metric_rows = []
    for item in metrics:
        target = float(item.get("target_output_fps", 0) or 0)
        achieved = float(item.get("achieved_fps", 0) or 0)
        realtime = float(item.get("realtime_factor", 0) or 0)
        need = target / achieved if achieved > 0 else 0
        verdict = "실시간 가능" if realtime >= 1.0 else f"{need:.1f}x 개선 필요"
        metric_rows.append(f'''
          <tr>
            <td>{html.escape(str(item.get("resolution", "n/a")))}</td>
            <td>{target:.0f}</td>
            <td>{int(item.get("frames_written", 0))}</td>
            <td>{float(item.get("wall_seconds", 0) or 0):.2f}s</td>
            <td>{achieved:.2f}</td>
            <td>{realtime:.3f}x</td>
            <td>{float(item.get("events_per_second_processed", 0) or 0)/1_000_000:.2f}M/s</td>
            <td>{verdict}</td>
          </tr>
        ''')

    realtime_videos = [
        ("960x540 target 60FPS", "realtime_synthesis_960w_target60fps_h264.mp4"),
        ("480x270 target 60FPS", "realtime_synthesis_480w_target60fps_h264.mp4"),
        ("320x180 target 60FPS", "realtime_synthesis_320w_target60fps_h264.mp4"),
    ]
    realtime_cards = []
    for label, name in realtime_videos:
        path = EVENT_SYNTH_OUTPUT_DIR / name
        if not path.exists():
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        resolution = label.split()[0]
        metric = find_realtime_metric(realtime_metrics, resolution, 60)
        detail = "metrics pending"
        if metric:
            detail = (
                f"5s run · {int(metric.get('frames_written', 0))} frames · "
                f"{float(metric.get('achieved_fps', 0) or 0):.2f} FPS · "
                f"CPU {float(metric.get('cpu_percent_mean', 0) or 0):.1f}% avg / {float(metric.get('cpu_percent_max', 0) or 0):.1f}% max · "
                f"MEM {float(metric.get('mem_percent_mean', 0) or 0):.1f}% · "
                f"TEMP {float(metric.get('temperature_c_mean', 0) or 0):.1f}C avg / {float(metric.get('temperature_c_max', 0) or 0):.1f}C max"
            )
        realtime_cards.append(f'''
          <section class="video-card">
            <div class="card-head"><h2>{html.escape(label)}</h2><span>{size_mb:.1f} MB</span></div>
            <video controls muted playsinline src="/event-synthesis-video/{html.escape(name)}"></video>
            <div class="realtime-caption">{html.escape(detail)}</div>
          </section>
        ''')

    realtime_rows = []
    for item in realtime_metrics:
        if int(item.get("target_output_fps", 0) or 0) != 60:
            continue
        realtime_rows.append(f'''
          <tr>
            <td>{html.escape(str(item.get("resolution", "n/a")))}</td>
            <td>{float(item.get("target_output_fps", 0) or 0):.0f}</td>
            <td>{float(item.get("wall_seconds", 0) or 0):.1f}s</td>
            <td>{int(item.get("frames_written", 0))}</td>
            <td>{float(item.get("achieved_fps", 0) or 0):.2f}</td>
            <td>{float(item.get("realtime_factor", 0) or 0):.3f}x</td>
            <td>{float(item.get("cpu_percent_mean", 0) or 0):.1f}% / {float(item.get("cpu_percent_max", 0) or 0):.1f}%</td>
            <td>{float(item.get("mem_percent_mean", 0) or 0):.1f}%</td>
            <td>{float(item.get("temperature_c_mean", 0) or 0):.1f}C / {float(item.get("temperature_c_max", 0) or 0):.1f}C</td>
          </tr>
        ''')

    status = get_status()
    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CIS-DVS Event Synthesis Demo</title>
  <style>
    :root {{ color-scheme:dark; --bg:#0f1114; --panel:#191d22; --panel2:#222832; --line:#343b45; --text:#edf2f4; --muted:#a6b0b8; --accent:#5cc8a7; --blue:#7bb7ff; --warn:#f6c96d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .global-nav {{ position:sticky; top:0; z-index:30; display:flex; justify-content:center; align-items:center; gap:8px; padding:10px 12px; background:#111318; border-bottom:1px solid #30343d; }}
    .global-nav a {{ display:inline-flex; align-items:center; justify-content:center; min-width:86px; height:34px; padding:0 14px; border:1px solid #343d46; border-radius:6px; background:#1a1f25; color:#dbeafe; text-decoration:none; font-weight:700; font-size:14px; line-height:1; white-space:nowrap; }}
    .global-nav a:hover {{ background:#22303a; border-color:#5cc8a7; color:#fff; }}
    header {{ border-bottom:1px solid var(--line); background:#15191f; }}
    .system-strip {{ display:flex; justify-content:center; gap:10px; flex-wrap:wrap; padding:9px 12px; background:#0b0d10; border-bottom:1px solid var(--line); }}
    .sys {{ display:inline-flex; align-items:center; gap:7px; min-height:30px; padding:5px 10px; border:1px solid var(--line); border-radius:6px; background:#15191f; font-size:13px; }}
    .sys b {{ color:var(--accent); }}
    .hero {{ max-width:1360px; margin:0 auto; padding:26px 18px 20px; display:grid; grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr); gap:22px; align-items:end; }}
    h1 {{ margin:0 0 8px; font-size:32px; line-height:1.15; letter-spacing:0; }}
    .lead {{ margin:0; color:var(--muted); font-size:15px; line-height:1.65; max-width:840px; }}
    .summary {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }}
    .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .stat b {{ display:block; font-size:20px; }}
    .stat span {{ color:var(--muted); font-size:12px; }}
    main {{ max-width:1360px; margin:0 auto; padding:18px; display:grid; gap:18px; }}
    section.block {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    h2 {{ margin:0 0 10px; font-size:18px; letter-spacing:0; }}
    h3 {{ margin:16px 0 8px; font-size:15px; }}
    p {{ color:var(--muted); line-height:1.62; margin:8px 0; }}
    code, pre {{ font-family:ui-monospace, SFMono-Regular, Consolas, monospace; }}
    pre {{ margin:10px 0 0; padding:12px; border:1px solid var(--line); border-radius:8px; background:#0b0d10; color:#d8dee5; white-space:pre-wrap; overflow:auto; }}
    .videos {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }}
    .video-card {{ border:1px solid var(--line); border-radius:8px; background:#11151a; overflow:hidden; }}
    .card-head {{ display:flex; justify-content:space-between; gap:10px; align-items:center; padding:10px 12px; border-bottom:1px solid var(--line); }}
    .card-head h2 {{ margin:0; font-size:14px; }}
    .card-head span {{ color:var(--muted); font-size:12px; white-space:nowrap; }}
    .realtime-caption {{ min-height:68px; padding:10px 12px; border-top:1px solid var(--line); color:#d8dee5; font-size:13px; line-height:1.45; font-weight:600; }}
    video {{ width:100%; aspect-ratio:16 / 9; object-fit:contain; display:block; background:#050607; }}
    table {{ width:100%; border-collapse:collapse; overflow:hidden; border-radius:8px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; font-size:13px; }}
    th {{ color:#c7d2dc; background:#11151a; }}
    td {{ color:#edf2f4; }}
    .flow {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
    .step {{ border:1px solid var(--line); border-radius:8px; background:#11151a; padding:12px; }}
    .step b {{ color:var(--accent); }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .warn {{ color:var(--warn); }}
    ul {{ margin:8px 0 0; padding-left:20px; color:var(--muted); line-height:1.65; }}
    @media(max-width:850px) {{ .hero, .two {{ grid-template-columns:1fr; }} h1 {{ font-size:25px; }} }}
    @media(max-width:520px) {{ .global-nav {{ gap:6px; padding:8px; }} .global-nav a {{ min-width:auto; height:32px; padding:0 10px; font-size:13px; }} }}
  </style>
</head>
<body>
  {render_global_nav()}
  <div class="system-strip">
    <span class="sys">CPU <b id="es-cpu">{status["cpu_pct"]:.1f}%</b></span>
    <span class="sys">Memory <b id="es-mem">{status["mem_used_mb"]} / {status["mem_total_mb"]} MB</b></span>
    <span class="sys">Temp <b id="es-temp">{html.escape(status["temp"])}</b></span>
    <span class="sys">Clock <b id="es-clock">{html.escape(status["arm_clock"])}</b></span>
    <span class="sys">Throttle <b id="es-throttle">{html.escape(status["throttled"])}</b></span>
  </div>
  <header>
    <div class="hero">
      <div>
        <h1>CIS-DVS Event Synthesis Demo</h1>
        <p class="lead">CIS는 장면의 색과 질감을 낮은 시간 해상도로 제공하고, DVS는 프레임 사이의 움직임을 x/y/t/p 이벤트로 제공한다. 이 페이지는 비어 있는 timestamp의 이미지를 이벤트 누적으로 생성하는 구조와 Raspberry Pi 실측 성능을 보여준다.</p>
      </div>
      <div class="summary">
        <div class="stat"><b>50 FPS</b><span>CIS source cadence</span></div>
        <div class="stat"><b>4.1M/s</b><span>average DVS events</span></div>
        <div class="stat"><b>2000</b><span>frames tested at 320x180</span></div>
        <div class="stat"><b>0.186x</b><span>400FPS Pi Python realtime factor</span></div>
      </div>
    </div>
  </header>
  <main>
    <section class="block">
      <h2>Demo Videos</h2>
      <div class="videos">{''.join(video_cards) if video_cards else '<p>No generated videos found.</p>'}</div>
    </section>

    <section class="block">
      <h2>Synthesis Structure</h2>
      <div class="flow">
        <div class="step"><b>1. CIS anchor</b><p>현재 CIS 프레임 I0를 색상과 texture 기준으로 사용한다.</p></div>
        <div class="step"><b>2. Event window</b><p>I0와 I1 사이의 events/NNNNNN.npz에서 target timestamp까지의 이벤트만 선택한다.</p></div>
        <div class="step"><b>3. Polarity accumulation</b><p>p=1은 양의 밝기 변화, p=0은 음의 밝기 변화로 누적한다.</p></div>
        <div class="step"><b>4. Missing frame</b><p>누적 polarity를 intensity 변화로 바꿔 비어 있는 timestamp의 이미지를 생성한다.</p></div>
      </div>
      <pre>log I(t) = log I(t0) + C * accumulated_polarity_events

events/000000.npz = images/000000 과 images/000001 사이 이벤트
event fields = x, y, t, p</pre>
    </section>

    <section class="block two">
      <div>
        <h2>Lightweight Reconstruction Explained</h2>
        <p>이 방식은 딥러닝이 새 이미지를 상상해서 만드는 보간이 아니다. CIS 이미지 한 장을 기준 화면으로 두고, DVS 이벤트가 알려주는 밝아짐/어두워짐 변화를 그 위에 빠르게 더해서 중간 timestamp 이미지를 만든다.</p>
        <pre>CIS frame = color, texture, background
DVS event = where and when brightness changed

synthetic_frame(t)
  = CIS_anchor_frame
  + accumulated_event_change(t0 -> t)</pre>
        <p>DVS 이벤트의 `p` 값은 polarity다. `p=1`은 밝아지는 변화, `p=0`은 어두워지는 변화로 보고 같은 위치에 누적한다.</p>
        <pre>p = 1 -> +1 brightness change
p = 0 -> -1 brightness change

synth = anchor + polarity_count * gain</pre>
      </div>
      <div>
        <h2>Core Code</h2>
        <pre>import cv2
import numpy as np

I0 = cv2.imread("images/000000.jpg").astype(np.float32)
I1 = cv2.imread("images/000001.jpg").astype(np.float32)

z = np.load("events/000000.npz")
x = z["x"].astype(np.int32)
y = z["y"].astype(np.int32)
t = z["t"]
p = z["p"]

target_t = 10_000.0  # 10 ms
mask = t <= target_t
x, y, p = x[mask], y[mask], p[mask]

h, w = I0.shape[:2]
event_memory = np.zeros((h, w), np.float32)

pos = p > 0
np.add.at(event_memory, (y[pos], x[pos]), 1.0)
np.add.at(event_memory, (y[~pos], x[~pos]), -1.0)

contrast_gain = 4.8
synth = I0 + event_memory[:, :, None] * contrast_gain
synth = np.clip(synth, 0, 255).astype(np.uint8)</pre>
      </div>
    </section>

    <section class="block">
      <h2>Real-Time Loop Additions</h2>
      <div class="flow">
        <div class="step"><b>Decay</b><p>오래된 이벤트가 계속 남아 밝기 drift를 만들지 않도록 매 프레임 event memory를 줄인다.</p></div>
        <div class="step"><b>Anchor blend</b><p>I0만 쓰면 시간이 갈수록 어긋나므로 I1을 약하게 섞어 다음 CIS 프레임 방향으로 잡아준다.</p></div>
        <div class="step"><b>Scale correction</b><p>출력 해상도를 낮출 때 DVS x/y 좌표도 같은 비율로 줄여야 이벤트가 맞는 위치에 찍힌다.</p></div>
        <div class="step"><b>Wall-clock test</b><p>목표 프레임을 끝까지 만드는 대신 5초 동안 실제 몇 프레임을 만들었는지 측정한다.</p></div>
      </div>
      <pre>event_memory *= 0.70

new_events = events[(last_t < events.t) & (events.t <= target_t)]
accumulate(new_events, event_memory)

alpha = (target_t - t0) / (t1 - t0)
anchor = I0 * (1 - 0.12 * alpha) + I1 * (0.12 * alpha)

synth = anchor + event_memory[..., None] * contrast_gain</pre>
      <p>장점은 빠르고 작은 장비에서도 동작한다는 점이다. 한계는 새로운 texture를 만들지 못하고, 큰 occlusion이나 이벤트가 부족한 영역에서는 품질이 떨어진다는 점이다. 그래서 이 방식은 실시간 preview 또는 작은 AI refinement 전 단계로 보는 것이 맞다.</p>
    </section>

    <section class="block">
      <h2>Raspberry Pi Performance</h2>
      <table>
        <thead><tr><th>Resolution</th><th>Target FPS</th><th>Frames</th><th>Wall Time</th><th>Achieved FPS</th><th>Realtime</th><th>Event Throughput</th><th>Verdict</th></tr></thead>
        <tbody>{''.join(metric_rows) if metric_rows else '<tr><td colspan="8">No metrics found.</td></tr>'}</tbody>
      </table>
      <p class="warn">현재 Python/NumPy 구현은 실시간 데모 검증용이다. 병목은 딥러닝 TOPS가 아니라 이벤트 scatter 누적, 메모리 대역폭, 이미지 디코딩, MP4 인코딩, Python overhead다.</p>
    </section>

    <section class="block">
      <h2>Real-Time 5s Run: How Many Frames Are Produced?</h2>
      <p>아래 3개 영상은 모두 target 60FPS 조건에서 Raspberry Pi가 정확히 5초 동안 실제로 몇 프레임까지 합성하는지 보여준다. 영상 내부 오버레이는 제거했고, CPU, memory, temperature 수치는 각 영상 하단에 같은 글자 크기로 표시했다.</p>
      <div class="videos">{''.join(realtime_cards) if realtime_cards else '<p>No realtime demo videos found.</p>'}</div>
      <table style="margin-top:14px">
        <thead><tr><th>Resolution</th><th>Target FPS</th><th>Run Time</th><th>Frames Made</th><th>Achieved FPS</th><th>Realtime</th><th>CPU mean/max</th><th>Memory mean</th><th>Temp mean/max</th></tr></thead>
        <tbody>{''.join(realtime_rows) if realtime_rows else '<tr><td colspan="9">No realtime metrics found.</td></tr>'}</tbody>
      </table>
      <p>비교 의도는 같은 target 60FPS에서 해상도에 따른 실제 처리량을 보는 것이다. 정상적인 순서는 해상도가 낮을수록 더 많은 프레임이 생성되는 것이다.</p>
    </section>

    <section class="block two">
      <div>
        <h2>Frame Scaling Formula</h2>
        <pre>required_fps = output_frames / video_seconds

OPS = Fout * (W * H * Cpix) + Esec * Cevent

TOPS_required = OPS / 1e12 / efficiency</pre>
        <p>여기서 FPS는 playback FPS가 아니라 온디바이스가 실제 시간 1초 동안 만들어내는 synthesis FPS다. 1000프레임을 5초 안에 실시간 생성하려면 합성 엔진이 최소 200 synthesis FPS를 내야 한다. 2000프레임을 5초 안에 만들려면 400 synthesis FPS가 필요하다.</p>
        <pre>1000 frames / 5s = 200 synthesis FPS
2000 frames / 5s = 400 synthesis FPS
1000 frames / 1s = 1000 synthesis FPS</pre>
      </div>
      <div>
        <h2>How To Increase Frames</h2>
        <ul>
          <li>출력 해상도를 먼저 낮춘다. 960x540에서 480x270으로 내리면 픽셀 연산량은 1/4이다.</li>
          <li>NPZ 대신 binary packed event stream을 사용해 압축 해제와 배열 생성 비용을 줄인다.</li>
          <li>np.add.at 기반 random scatter를 C++ tile accumulation 또는 SIMD-friendly histogram으로 바꾼다.</li>
          <li>exp/log는 LUT 또는 linear contrast update로 대체한다.</li>
          <li>합성 루프와 비디오 인코딩을 분리하고, 웹에는 최신 생성 MP4만 제공한다.</li>
          <li>실시간 200FPS 이상은 Python이 아니라 C++/OpenCV/NEON 또는 GPU compute 경로가 필요하다.</li>
        </ul>
      </div>
    </section>

    <section class="block two">
      <div>
        <h2>What Hardware Must Be Strong At</h2>
        <p>이 작업은 AI TOPS 하나로만 판단하면 안 된다. 병목은 프레임 전체를 매번 계산하는 픽셀 처리량과, 이벤트를 좌표별로 누적하는 random memory write다.</p>
        <pre>required_pixel_rate = target_fps * width * height
required_event_rate = input_events_per_second

device_is_suitable if:
  generated_fps >= required_synthesis_fps
  sustained_event_rate >= peak_event_rate
  encode_fps >= output_stream_fps
  memory_bandwidth leaves enough headroom</pre>
        <ul>
          <li>픽셀 처리량: 200FPS 이상에서는 해상도 감소가 가장 큰 효과를 낸다.</li>
          <li>이벤트 처리량: 평균 4.1M events/sec보다 피크 38M events/sec를 버틸 수 있어야 한다.</li>
          <li>메모리 대역폭: event scatter, frame buffer, encode buffer가 동시에 돈다.</li>
          <li>하드웨어 인코더: 합성 결과를 웹으로 보낼 때 CPU 인코딩을 피해야 한다.</li>
          <li>동기화 입력: CIS와 DVS가 같은 시간축을 쓰도록 trigger/PPS/GPIO timestamp가 필요하다.</li>
        </ul>
      </div>
      <div>
        <h2>Is IQ8 Suitable?</h2>
        <p>공식적으로 판단하면 IQ8 계열은 Raspberry Pi보다 이 구조에 더 적합하다. 이유는 AI TOPS 때문만이 아니라, 카메라 입력, ISP, 하드웨어 비디오 인코딩, 메모리 대역폭, GPU/DSP/NPU 같은 병렬 처리 블록을 함께 쓸 수 있기 때문이다.</p>
        <pre>IQ8 suitability formula:

if CSI_input >= 2 streams
and hardware_encoder supports output_fps
and GPU/DSP/NPU can run fusion_kernel
and sustained_memory_bandwidth > frame_buffers + event_buffers
then suitable_for_realtime_fusion = yes

For 1000 frames / 5s:
  required_synthesis_fps = 200

For 2000 frames / 5s:
  required_synthesis_fps = 400</pre>
        <p>따라서 IQ8은 후보로 적합하다. 다만 TimeLens 같은 큰 딥러닝 interpolation을 그대로 올리는 방향보다, event accumulation과 contrast update를 GPU/DSP/NPU-friendly kernel로 바꾸는 쪽이 실시간 가능성이 높다.</p>
      </div>
    </section>

    <section class="block">
      <h2>Hardware Architecture For Real-Time Dual-Stream Fusion</h2>
      <p>현실적으로 두 개의 영상/센서 스트림을 동시에 받으면서 합성하려면 Raspberry Pi 하나에 모든 처리를 몰아넣기보다, 입력 수집, timestamp 동기화, 이벤트 누적, 인코딩을 분리해야 한다.</p>
      <div class="flow">
        <div class="step"><b>1. Sensor input</b><p>CIS 카메라는 MIPI CSI-2 또는 USB3로 받고, DVS는 USB3, MIPI, FPGA bridge, 또는 Ethernet 기반 event packet으로 받는다.</p></div>
        <div class="step"><b>2. Time sync</b><p>두 센서에 공통 PPS/trigger/GPIO timestamp를 넣는다. 소프트웨어 수신 시간만 쓰면 frame-event alignment가 흔들린다.</p></div>
        <div class="step"><b>3. Fusion compute</b><p>CPU는 orchestration, GPU/ISP/FPGA/NPU는 누적, warp, interpolation, encode 같은 병렬 작업을 맡긴다.</p></div>
        <div class="step"><b>4. Output service</b><p>실시간 스트림은 raw frame 저장이 아니라 ring buffer와 H.264/H.265 hardware encoder로 바로 웹에 제공한다.</p></div>
      </div>
      <h3>Recommended practical build</h3>
      <pre>CIS camera -> MIPI CSI-2 -> ISP / DMA buffer
DVS sensor -> USB3 or FPGA bridge -> event packet ring buffer
Common trigger/PPS -> shared monotonic timestamp
Fusion engine -> C++/NEON or FPGA/GPU tile accumulator
Video output -> hardware H.264/H.265 encoder -> WebRTC or HLS

Raspberry Pi 5 role:
  dashboard, capture control, low-resolution preview, logging

Production role:
  Qualcomm Dragonwing IQ8 / Jetson / FPGA-assisted SoC for real-time fusion</pre>
      <p>Raspberry Pi 5는 PoC와 저해상도 preview에는 적합하지만, 두 입력을 동시에 받으면서 200~400FPS급 합성까지 실시간으로 처리하려면 DMA-friendly buffer, hardware encoder, 병렬 누적 엔진이 있는 SoC 구성이 필요하다.</p>
    </section>

    <section class="block two">
      <div>
        <h2>High-Quality Interpolation Limits</h2>
        <p>고품질 보간은 가능하지만, 전체 프레임 대형 neural interpolation을 200FPS 이상으로 실시간 처리하는 것은 어렵다. 현재 데모는 TimeLens류 고품질 모델이 아니라, 온디바이스 실시간 가능성을 확인하기 위한 lightweight event-based reconstruction이다.</p>
        <pre>Lightweight synthesis:
  CIS frame + DVS polarity accumulation
  fast, lower compute, limited image quality

High-quality interpolation:
  CIS frame pair + event voxel + neural network
  better quality, higher latency, larger memory use</pre>
        <p>고품질 모델이 실시간이 되려면 inference, event preprocessing, postprocessing, encode handoff가 모두 프레임 budget 안에 들어와야 한다.</p>
        <pre>model_latency_ms <= 1000 / required_synthesis_fps

200 synthesis FPS -> <= 5.0 ms/frame
400 synthesis FPS -> <= 2.5 ms/frame
1000 synthesis FPS -> <= 1.0 ms/frame</pre>
      </div>
      <div>
        <h2>IQ8 Practical Judgment</h2>
        <p>IQ8은 Raspberry Pi보다 이 프로젝트에 훨씬 적합하다. 이유는 NPU TOPS만이 아니라 CPU, GPU, NPU, DSP, real-time MCU, multi-camera input, hardware video encoder를 함께 쓸 수 있는 heterogeneous compute 구조 때문이다.</p>
        <pre>IQ8_is_suitable if:
  camera_input >= 2 synchronized streams
  and hardware_encoder_fps >= output_stream_fps
  and fusion_kernel_fps >= required_synthesis_fps
  and event_ingest_rate >= peak_event_rate
  and memory_bandwidth has enough headroom</pre>
        <ul>
          <li>320x180~480x270 경량 neural refinement는 IQ8에서 가능성 있음.</li>
          <li>960x540 고품질 neural interpolation @ 200FPS는 매우 어려움.</li>
          <li>1080p 고품질 neural interpolation @ 200FPS 이상은 비현실적에 가까움.</li>
          <li>TimeLens-XL급 큰 모델을 그대로 실시간 구동하는 방식은 IQ8에서도 어렵다.</li>
          <li>작은 모델, ROI 처리, INT8 quantization, NPU/DSP/GPU 분산이 필요하다.</li>
        </ul>
      </div>
    </section>

    <section class="block">
      <h2>Recommended Product Architecture</h2>
      <pre>CIS camera -> ISP / DMA buffer
DVS sensor -> packed event stream ring buffer
Time sync -> trigger / PPS / GPIO timestamp
Fusion core -> C++ / NEON / GPU / DSP tile accumulator
Optional AI -> small INT8 ROI refinement model on NPU
Output -> hardware H.264 / H.265 encoder
Web -> preview stream + latest generated MP4</pre>
      <p>최종 방향은 전체 프레임 대형 AI 보간이 아니라, 경량 실시간 합성 위에 선택적 AI refinement를 얹는 구조가 가장 현실적이다.</p>
    </section>

    <section class="block two">
      <div>
        <h2>Lightweight Techniques</h2>
        <ul>
          <li><b>NPZ 대신 binary packed event stream</b>: 지금 NPZ는 zip 압축을 풀고 x/y/t/p 배열을 새로 만드는 비용이 크다. 실시간에서는 이벤트 하나를 8~12 byte 정도의 고정 구조체로 저장해 바로 읽는 편이 낫다.</li>
          <li><b>np.add.at 제거</b>: np.add.at는 좌표가 흩어진 곳에 계속 더하는 random scatter라 느리다. C++에서 화면을 작은 tile로 나누고, 각 tile 안에서 histogram을 만든 뒤 합치면 cache 효율이 좋아진다.</li>
          <li><b>SIMD-friendly histogram</b>: 이벤트를 한 점씩 처리하지 말고, x/y 좌표를 정렬하거나 tile별 bucket에 넣어 NEON/SIMD가 연속 메모리를 처리하게 만든다.</li>
          <li><b>exp/log 제거</b>: log/exp는 품질은 좋지만 실시간에는 비싸다. 256 또는 1024 단계 LUT를 쓰거나, brightness += polarity_count * gain 같은 linear contrast update로 바꾼다.</li>
          <li><b>rolling event buffer</b>: 매 출력 프레임마다 처음부터 이벤트를 다시 누적하지 않고, 오래된 이벤트는 빼고 새 이벤트만 더하는 ring buffer를 유지한다.</li>
          <li><b>ROI/tile update</b>: 이벤트가 없는 영역은 CIS frame을 그대로 둔다. 움직임이 있는 tile만 갱신하면 960x540 전체를 매번 계산하지 않아도 된다.</li>
          <li><b>합성 루프와 인코딩 분리</b>: fusion thread는 frame만 만들고, encoder thread가 별도로 H.264/H.265를 만든다. 두 작업을 한 루프에 넣으면 latency spike가 커진다.</li>
          <li><b>웹 출력 단순화</b>: 실시간 스트림은 WebRTC/HLS로 보내고, 데모 페이지에는 최신 MP4 또는 낮은 FPS preview만 둔다. 웹서버가 합성 계산을 직접 하지 않게 한다.</li>
          <li><b>Python 탈출</b>: 200FPS 이상은 Python/NumPy 프로토타입으로는 어렵다. C++/OpenCV/NEON, GPU compute, DSP, FPGA 중 하나로 핵심 누적 루프를 옮겨야 한다.</li>
        </ul>
      </div>
      <div>
        <h2>Frame Increase Strategy</h2>
        <pre>현재 Pi Python 결과:
320x180 @ 200FPS, 1000 frames -> 15.77s
320x180 @ 400FPS, 2000 frames -> 26.90s

실시간 목표:
1000 frames / 5s = 200FPS
2000 frames / 5s = 400FPS

필요 개선:
200FPS target: 약 3.2x
400FPS target: 약 5.4x</pre>
        <p>가장 먼저 C++/NEON으로 event accumulation을 옮기고, 그 다음 packed event stream과 tile accumulator를 적용하는 순서가 현실적이다. 모델 기반 TimeLens류 interpolation은 품질은 좋지만 라즈베리 CPU 실시간 목표에는 맞지 않는다.</p>
      </div>
    </section>

    <section class="block">
      <h2>Current Conclusion</h2>
      <p>Raspberry Pi 5 CPU에서 960x540 @ 60FPS는 현재 구현으로 실시간이 아니다. 480x270 @ 30FPS도 아직 0.735x realtime 수준이다. 1000프레임 생성 테스트는 320x180 @ 200FPS 목표에서 15.77초가 걸려 0.317x realtime, 2000프레임 생성 테스트는 320x180 @ 400FPS 목표에서 26.90초가 걸려 0.186x realtime으로 측정됐다. 다음 단계는 C++/NEON 최적화, packed event stream, tile accumulation, hardware encode 적용이다.</p>
    </section>
  </main>
  <script>
    const setText = (id, value) => {{ const el = document.getElementById(id); if (el) el.textContent = value; }};
    async function refreshSystem() {{
      try {{
        const response = await fetch('/status.json', {{cache:'no-store'}});
        if (!response.ok) return;
        const data = await response.json();
        setText('es-cpu', `${{Number(data.cpu_pct || 0).toFixed(1)}}%`);
        setText('es-mem', `${{data.mem_used_mb}} / ${{data.mem_total_mb}} MB`);
        setText('es-temp', data.temp || 'n/a');
        setText('es-clock', data.arm_clock || 'n/a');
        setText('es-throttle', data.throttled || 'n/a');
      }} catch (e) {{}}
    }}
    setInterval(refreshSystem, 3000);
    refreshSystem();
  </script>
</body>
</html>'''


def render_space_edge_proposal_page():
    return '''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Space Edge DVS Proposal</title>
  <style>
    :root { color-scheme:dark; --bg:#0f1114; --panel:#191d22; --panel2:#222832; --line:#343b45; --text:#edf2f4; --muted:#a6b0b8; --accent:#5cc8a7; --blue:#7bb7ff; --warn:#f6c96d; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .global-nav { position:sticky; top:0; z-index:30; display:flex; justify-content:center; align-items:center; gap:8px; padding:10px 12px; background:#111318; border-bottom:1px solid #30343d; flex-wrap:wrap; }
    .global-nav a { display:inline-flex; align-items:center; justify-content:center; min-width:86px; height:34px; padding:0 14px; border:1px solid #343d46; border-radius:6px; background:#1a1f25; color:#dbeafe; text-decoration:none; font-weight:700; font-size:14px; line-height:1; white-space:nowrap; }
    .global-nav a:hover { background:#22303a; border-color:#5cc8a7; color:#fff; }
    header { border-bottom:1px solid var(--line); background:#15191f; }
    .hero { max-width:1360px; margin:0 auto; padding:28px 18px 22px; display:grid; grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr); gap:22px; align-items:end; }
    h1 { margin:0 0 10px; font-size:32px; line-height:1.15; letter-spacing:0; }
    .lead { margin:0; color:var(--muted); font-size:15px; line-height:1.65; max-width:860px; }
    .summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .stat { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; }
    .stat b { display:block; font-size:20px; }
    .stat span { color:var(--muted); font-size:12px; }
    main { max-width:1360px; margin:0 auto; padding:18px; display:grid; gap:18px; }
    section.block { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    h2 { margin:0 0 10px; font-size:18px; letter-spacing:0; }
    h3 { margin:16px 0 8px; font-size:15px; }
    p { color:var(--muted); line-height:1.62; margin:8px 0; }
    ul { margin:8px 0 0; padding-left:20px; color:var(--muted); line-height:1.65; }
    pre { margin:10px 0 0; padding:12px; border:1px solid var(--line); border-radius:8px; background:#0b0d10; color:#d8dee5; white-space:pre-wrap; overflow:auto; font-family:ui-monospace, SFMono-Regular, Consolas, monospace; font-size:13px; line-height:1.5; }
    .flow { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }
    .step { border:1px solid var(--line); border-radius:8px; background:#11151a; padding:12px; }
    .step b { color:var(--accent); }
    .two { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    table { width:100%; border-collapse:collapse; }
    th, td { border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; font-size:13px; vertical-align:top; }
    th { color:#c7d2dc; background:#11151a; }
    td { color:#edf2f4; }
    a { color:#7dd3fc; text-decoration:none; }
    a:hover { text-decoration:underline; }
    .warn { color:var(--warn); }
    @media(max-width:850px) { .hero, .two { grid-template-columns:1fr; } h1 { font-size:25px; } }
  </style>
</head>
<body>
  <div class="global-nav">
  <a href="/">Home</a>
  <span style="display:flex;align-items:center;gap:6px;padding-left:8px;border-left:1px solid #343d46">
    <span style="color:#91a0ad;font-size:12px;font-weight:800;white-space:nowrap">기능</span>
    <a href="/person">Person</a>
    <a href="/event-synthesis">Event Synthesis</a>
    <a href="http://192.168.0.100:8081/">Synthetic</a>
  </span>
  <span style="display:flex;align-items:center;gap:6px;padding-left:8px;border-left:1px solid #343d46">
    <span style="color:#91a0ad;font-size:12px;font-weight:800;white-space:nowrap">제안서</span>
    <a href="/space-edge-proposal">Space Edge</a>
    <a href="/fall-plan">Fall Plan</a>
  </span>
</div>
  <header>
    <div class="hero">
      <div>
        <h1>Space Edge DVS On-Device Box Proposal</h1>
        <p class="lead">DVS 센서와 CIS 카메라를 결합한 저전력 온디바이스 박스를 SpaceX/Starlink급 원격 인프라와 tactical edge 플랫폼에 적용하는 제안이다. 평상시에는 DVS 이벤트만 기록하고, 의미 있는 변화가 발생했을 때 CIS를 깨워 영상 합성과 사건 판단을 수행한 뒤 핵심 정보만 빠르게 전송한다.</p>
      </div>
      <div class="summary">
        <div class="stat"><b>DVS idle</b><span>low-power always-on sensing</span></div>
        <div class="stat"><b>CIS wake</b><span>capture only on event</span></div>
        <div class="stat"><b>Edge AI</b><span>local summary before uplink</span></div>
        <div class="stat"><b>Fast report</b><span>metadata-first transmission</span></div>
      </div>
    </div>
  </header>
  <main>
    <section class="block">
      <h2>Executive Proposal</h2>
      <p>원격 데이터센터, 위성 지상국, 우주/항공 설비, 드론 운용 환경에서는 모든 영상을 계속 전송하기 어렵다. 대역폭, 전력, 저장 공간, 지연 시간이 제한되기 때문이다. 이 제안의 핵심은 평상시에는 DVS 이벤트만 수집하고, 움직임·충격·섬광·침입·장비 이상 같은 이벤트가 발생하면 CIS를 깨워 짧은 burst 영상을 확보한 뒤, DVS와 CIS를 합성해 상황을 빠르게 판단하는 것이다.</p>
      <pre>Normal mode:
  DVS only -> tiny event stream -> low power storage

Event mode:
  DVS trigger -> wake CIS -> capture burst -> synthesize frames
  -> classify event -> send compact incident packet to Earth / operator</pre>
    </section>

    <section class="block">
      <h2>Why DVS Is Needed</h2>
      <div class="flow">
        <div class="step"><b>Bandwidth</b><p>RGB 영상을 항상 보내는 대신, 변화가 있을 때만 이벤트와 요약 영상을 보낸다.</p></div>
        <div class="step"><b>Power</b><p>CIS/ISP/encoder를 계속 켜두지 않고, DVS가 event trigger 역할을 한다.</p></div>
        <div class="step"><b>Latency</b><p>DVS는 motion/brightness change를 빠르게 감지하므로 사건 시작점을 놓칠 가능성이 줄어든다.</p></div>
        <div class="step"><b>Evidence</b><p>이벤트 전후의 sparse motion trace와 CIS burst를 함께 보관해 원인 분석이 쉬워진다.</p></div>
      </div>
    </section>

    <section class="block two">
      <div>
        <h2>On-Device Box Architecture</h2>
        <pre>DVS sensor
  -> always-on event ring buffer
  -> event trigger detector

CIS camera
  -> normally sleeping or low FPS
  -> wakes on DVS trigger
  -> short burst capture

Fusion engine
  -> lightweight reconstruction
  -> optional AI refinement/classifier

Communication
  -> event metadata first
  -> thumbnail/contact sheet second
  -> short H.264 clip only when needed</pre>
      </div>
      <div>
        <h2>Incident Packet</h2>
        <pre>{
  "time": "UTC timestamp",
  "event_type": "motion / flash / impact / anomaly",
  "confidence": 0.0-1.0,
  "location": "device or site id",
  "event_rate": "events/sec",
  "frames": "key thumbnails",
  "clip": "optional short encoded video",
  "raw_events": "optional compressed event slice"
}</pre>
        <p>전송 우선순위는 metadata, thumbnail, short clip, raw event 순서가 현실적이다. 링크 품질이 낮으면 metadata만 먼저 보내고, 대역폭이 회복되면 clip과 raw event를 보낸다.</p>
      </div>
    </section>

    <section class="block">
      <h2>SpaceX / Starlink Data-Center Use Case</h2>
      <p>공개적으로 Starlink는 저궤도 위성을 사용해 저지연 인터넷을 제공하는 시스템으로 설명된다. 이 제안은 SpaceX 내부 시스템을 단정하는 것이 아니라, Starlink급 원격 통신/지상 인프라에서 유용한 edge sensing box의 적용 시나리오다.</p>
      <table>
        <thead><tr><th>Scenario</th><th>DVS role</th><th>CIS role</th><th>What gets sent</th></tr></thead>
        <tbody>
          <tr><td>Remote equipment room</td><td>motion, spark, flash, vibration-like visual change 감지</td><td>event 발생 시 현장 burst image 확보</td><td>event type, timestamp, thumbnails, short clip</td></tr>
          <tr><td>Satellite ground site</td><td>평상시 sparse activity log 유지</td><td>침입/장비 이상/환경 변화 때만 활성화</td><td>operator alert plus compressed evidence</td></tr>
          <tr><td>Space asset monitoring concept</td><td>continuous low-bandwidth visual change sensing</td><td>triggered context frame capture</td><td>priority packet over constrained link</td></tr>
        </tbody>
      </table>
    </section>

    <section class="block">
      <h2>Starcloud Whitepaper Summary: Space Data Centers</h2>
      <p>Starcloud의 공개 자료와 백서 소개는 데이터센터가 우주로 이동할 수 있는 이유를 세 가지로 설명한다. 첫째, 저궤도/태양동기궤도에서는 태양광을 거의 지속적으로 사용할 수 있다. 둘째, 우주는 물 냉각이나 칠러 대신 방열판으로 열을 우주 공간에 복사할 수 있다. 셋째, 지상 데이터센터가 겪는 토지, 전력망, 인허가 병목을 피하면서 모듈식으로 확장할 수 있다.</p>
      <div class="flow">
        <div class="step"><b>Power</b><p>우주에서는 대기 손실과 야간 문제가 작아 solar capacity factor가 높다. AI compute의 전력 병목을 줄이는 논리다.</p></div>
        <div class="step"><b>Cooling</b><p>진공은 대류 냉각이 안 되지만, 큰 radiator로 폐열을 복사 방출한다. 물 사용량을 줄일 수 있는 대신 radiator 면적과 열전달 설계가 중요하다.</p></div>
        <div class="step"><b>Scale</b><p>compute container, solar array, radiator를 모듈화하면 지상보다 빠르게 확장할 수 있다는 주장이다.</p></div>
        <div class="step"><b>Data movement</b><p>대용량 원시 데이터를 모두 지구로 내리는 대신, 우주에서 inference/분석을 먼저 수행하고 결과만 전송하는 구조가 중요하다.</p></div>
      </div>
      <pre>Starcloud-style orbital data center:
  compute container + solar array + passive radiator
  optical link / constellation relay for data transport
  in-space inference to reduce raw downlink

Implication for this DVS box:
  do not send all video all the time
  process event data locally
  transmit incident summary first
  send short clip/raw event only when needed</pre>
      <p>우리 제안의 DVS on-device box는 이 백서 논리와 잘 맞는다. 우주 데이터센터나 원격 지상국에서는 대역폭과 전력, 열 관리가 모두 제한되므로, 평상시 DVS-only로 sparse event를 기록하고 사건이 발생했을 때만 CIS와 AI를 깨우는 구조가 유리하다.</p>
    </section>

    <section class="block two">
      <div>
        <h2>Data-Center Monitoring Fit</h2>
        <p>데이터센터는 서버 랙, 전력 장치, 냉각 장치, 출입 구역, 케이블/모듈 접속부처럼 지속 감시가 필요한 영역이 많다. 하지만 모든 카메라 영상을 항상 고해상도로 저장하거나 전송하면 저장 비용과 네트워크 비용이 커진다.</p>
        <ul>
          <li>DVS는 평상시 변화가 없으면 데이터가 거의 없다.</li>
          <li>섬광, 스파크, 연기 전조, 급격한 움직임, 팬/패널 이상 같은 visual change를 빠르게 잡는다.</li>
          <li>CIS는 이벤트 발생 시에만 깨워 색상, texture, 현장 context를 보완한다.</li>
          <li>on-device classifier가 사건 유형을 먼저 판단해 operator에게 요약을 보낸다.</li>
          <li>지구/중앙 관제에는 metadata, thumbnail, short clip 순서로 전송해 bandwidth를 줄인다.</li>
        </ul>
      </div>
      <div>
        <h2>Why Not Always-On RGB?</h2>
        <table>
          <thead><tr><th>Always-on RGB/CIS</th><th>DVS-triggered CIS</th></tr></thead>
          <tbody>
            <tr><td>항상 큰 영상 스트림 발생</td><td>변화가 있을 때만 데이터 증가</td></tr>
            <tr><td>전력/열/저장 부담 큼</td><td>idle 전력과 저장량 감소</td></tr>
            <tr><td>빠른 순간 변화는 motion blur 가능</td><td>DVS가 microsecond 단위 변화 포착</td></tr>
            <tr><td>관제자가 많은 영상을 봐야 함</td><td>사건 중심 incident packet으로 요약</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="block two">
      <div>
        <h2>Palantir / Drone Edge Use Case</h2>
        <p>Palantir는 공개적으로 tactical edge, defense decision making, edge AI 같은 방향을 강조한다. 드론 적용에서는 원본 영상을 계속 전송하기보다, 온디바이스에서 사건을 먼저 줄여서 판단 가능한 형태로 만드는 것이 가치가 있다.</p>
        <pre>Drone normal flight:
  DVS watches fast motion and flashes
  CIS runs low FPS or sleeps

Potential event:
  wake CIS
  synthesize missing frames
  classify scene change locally
  send compact event packet to command software</pre>
        <p>이 접근은 통신이 끊기거나 대역폭이 낮은 환경에서 특히 유리하다. 단, 사람 추적/무기화된 자율 판단이 아니라 human-in-the-loop 상황 인식과 증거 압축 용도로 제한하는 설계가 바람직하다.</p>
      </div>
      <div>
        <h2>Why It Fits Edge Platforms</h2>
        <ul>
          <li>영상 전체가 아니라 사건 중심 데이터만 보내므로 지휘 시스템의 부담이 줄어든다.</li>
          <li>DVS는 빠른 움직임, 섬광, 갑작스러운 조도 변화를 포착하는 데 유리하다.</li>
          <li>CIS는 필요한 순간에만 texture와 색 정보를 보완한다.</li>
          <li>온디바이스 summary는 Palantir류 decision platform에 바로 ingest하기 쉽다.</li>
          <li>raw event와 short clip을 함께 저장하면 사후 검증 가능성이 높아진다.</li>
        </ul>
      </div>
    </section>

    <section class="block two">
      <div>
        <h2>Required Technology</h2>
        <ul>
          <li>DVS sensor with timestamped x/y/t/p event output</li>
          <li>CIS camera with fast wake or low-power standby mode</li>
          <li>shared clock, PPS, trigger, or GPIO timestamp sync</li>
          <li>packed event ring buffer and event-rate trigger logic</li>
          <li>C++/NEON/GPU/DSP lightweight reconstruction engine</li>
          <li>small INT8 classifier or ROI refinement model</li>
          <li>hardware H.264/H.265 encoder</li>
          <li>secure event packet uplink and store-and-forward queue</li>
        </ul>
      </div>
      <div>
        <h2>Pros And Cons</h2>
        <table>
          <thead><tr><th>Pros</th><th>Cons / Risks</th></tr></thead>
          <tbody>
            <tr><td>낮은 idle 전력</td><td>DVS와 CIS 시간/공간 calibration 필요</td></tr>
            <tr><td>대역폭 절감</td><td>이벤트가 부족하면 texture 복원 한계</td></tr>
            <tr><td>빠른 이상 감지</td><td>큰 neural interpolation은 edge 실시간이 어려움</td></tr>
            <tr><td>사건 중심 전송</td><td>오탐/미탐 threshold tuning 필요</td></tr>
            <tr><td>raw event로 사후 분석 가능</td><td>radiation, vibration, thermal design 검증 필요</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="block">
      <h2>Performance Target</h2>
      <pre>1000 frames / 5s = 200 synthesis FPS
2000 frames / 5s = 400 synthesis FPS

device_is_ready if:
  synthesis_fps >= target_synthesis_fps
  event_ingest_rate >= peak_event_rate
  encoder_fps >= delivery_fps
  power_budget is acceptable
  thermal throttling does not occur</pre>
      <p class="warn">Raspberry Pi 5는 PoC와 dashboard에는 적합하지만, 200~400 synthesis FPS의 제품 목표에는 C++/NEON 최적화 또는 IQ8/Jetson/FPGA-assisted SoC급 구성이 필요하다.</p>
    </section>

    <section class="block">
      <h2>Reference Context</h2>
      <ul>
        <li><a href="https://starlink.com/us/technology" target="_blank">Starlink Technology</a>: low Earth orbit 기반 저지연 위성 인터넷 설명.</li>
        <li><a href="https://www.starcloud.com/" target="_blank">Starcloud White Paper landing page</a>: space data center의 전력, 냉각, 확장성 논리.</li>
        <li><a href="https://www.starcloud.com/blog/how-data-centres-in-space-sustainably-enable-the-ai-revolution" target="_blank">Starcloud Blog</a>: 우주 데이터센터가 AI 전력/냉각/인허가 병목을 줄인다는 설명.</li>
        <li><a href="https://www.mckinsey.com/industries/technology-media-and-telecommunications/our-insights/the-case-for-data-centers-in-space" target="_blank">McKinsey interview with Starcloud</a>: orbital compute infrastructure, rack-scale system, inference workload 방향.</li>
        <li><a href="https://www.palantir.com/offerings/defense/" target="_blank">Palantir Defense</a>: tactical edge와 defense decision software 방향.</li>
        <li><a href="https://www.palantir.com/offerings/defense/solutions/" target="_blank">Palantir Defense Solutions</a>: edge AI, data-centric operations 관련 공개 설명.</li>
      </ul>
    </section>
  </main>
</body>
</html>'''


def render_pi5_architecture_page():
    return '''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Raspberry Pi 5 Architecture</title>
  <style>
    :root { color-scheme:dark; --bg:#0f1114; --panel:#191d22; --panel2:#222832; --line:#343b45; --text:#edf2f4; --muted:#a6b0b8; --accent:#5cc8a7; --blue:#7bb7ff; --warn:#f6c96d; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .global-nav { position:sticky; top:0; z-index:30; display:flex; justify-content:center; align-items:center; gap:8px; padding:10px 12px; background:#111318; border-bottom:1px solid #30343d; flex-wrap:wrap; }
    .global-nav a { display:inline-flex; align-items:center; justify-content:center; min-width:86px; height:34px; padding:0 14px; border:1px solid #343d46; border-radius:6px; background:#1a1f25; color:#dbeafe; text-decoration:none; font-weight:700; font-size:14px; line-height:1; white-space:nowrap; }
    .global-nav a:hover { background:#22303a; border-color:#5cc8a7; color:#fff; }
    .nav-group { display:flex; align-items:center; gap:6px; padding-left:8px; border-left:1px solid #343d46; }
    .nav-label { color:#91a0ad; font-size:12px; font-weight:800; white-space:nowrap; }
    header { border-bottom:1px solid var(--line); background:#15191f; }
    .hero { max-width:1360px; margin:0 auto; padding:28px 18px 22px; display:grid; grid-template-columns:minmax(0,1.0fr) minmax(320px,.9fr); gap:22px; align-items:center; }
    h1 { margin:0 0 10px; font-size:32px; line-height:1.15; letter-spacing:0; }
    .lead { margin:0; color:var(--muted); font-size:15px; line-height:1.65; max-width:820px; }
    .hero img { width:100%; max-height:330px; object-fit:contain; background:#0b0d10; border:1px solid var(--line); border-radius:8px; }
    main { max-width:1360px; margin:0 auto; padding:18px; display:grid; gap:18px; }
    section.block { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
    h2 { margin:0 0 10px; font-size:18px; letter-spacing:0; }
    h3 { margin:16px 0 8px; font-size:15px; }
    p { color:var(--muted); line-height:1.62; margin:8px 0; }
    ul { margin:8px 0 0; padding-left:20px; color:var(--muted); line-height:1.65; }
    pre { margin:10px 0 0; padding:12px; border:1px solid var(--line); border-radius:8px; background:#0b0d10; color:#d8dee5; white-space:pre; overflow:auto; font-family:ui-monospace, SFMono-Regular, Consolas, monospace; font-size:13px; line-height:1.45; }
    table { width:100%; border-collapse:collapse; }
    th, td { border-bottom:1px solid var(--line); padding:9px 8px; text-align:left; font-size:13px; vertical-align:top; }
    th { color:#c7d2dc; background:#11151a; }
    td { color:#edf2f4; }
    .two { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }
    .card { border:1px solid var(--line); border-radius:8px; background:#11151a; padding:12px; }
    .card b { color:var(--accent); display:block; margin-bottom:4px; }
    .image-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:12px; }
    figure { margin:0; border:1px solid var(--line); border-radius:8px; background:#11151a; overflow:hidden; }
    figure img { width:100%; aspect-ratio:16/10; object-fit:contain; display:block; background:#0b0d10; }
    figcaption { padding:9px 11px; color:var(--muted); font-size:12px; line-height:1.45; border-top:1px solid var(--line); }
    a { color:#7dd3fc; text-decoration:none; }
    a:hover { text-decoration:underline; }
    @media(max-width:850px) { .hero, .two { grid-template-columns:1fr; } h1 { font-size:25px; } }
  </style>
</head>
<body>
  <div class="global-nav">
    <a href="/">Home</a>
    <span class="nav-group"><span class="nav-label">기능</span><a href="/person">Person</a><a href="/raspberry-pi5-architecture">Pi 5 Architecture</a><a href="/event-synthesis">Event Synthesis</a><a href="http://192.168.0.100:8081/">Synthetic</a></span>
    <span class="nav-group"><span class="nav-label">제안서</span><a href="/space-edge-proposal">Space Edge</a><a href="/fall-plan">Fall Plan</a></span>
  </div>
  <header>
    <div class="hero">
      <div>
        <h1>Raspberry Pi 5 구조, 성능, 인터페이스</h1>
        <p class="lead">Raspberry Pi 5는 BCM2712 application processor와 RP1 I/O controller가 분리된 구조다. CPU/GPU/메모리/HDMI/PCIe 핵심 기능은 BCM2712 쪽에 있고, USB, Ethernet, GPIO, MIPI camera/display 같은 I/O는 RP1이 담당한다. 이 페이지는 DVS-CIS 합성 PoC 관점에서 Pi 5의 블록 구조와 인터페이스 한계를 정리한다.</p>
      </div>
      <img src="/pi5-asset/raspberry-pi-5.png" alt="Raspberry Pi 5 official image">
    </div>
  </header>
  <main>
    <section class="block image-grid">
      <figure><img src="/pi5-asset/pi5-board-retail-photo.jpg" alt="Raspberry Pi 5 board retail photo"><figcaption>실물 보드 전체 사진. 커넥터 위치와 포트 배치를 한눈에 보기 위한 참고 이미지.</figcaption></figure>
      <figure><img src="/pi5-asset/raspberry-pi-5.png" alt="Raspberry Pi 5 board"><figcaption>Raspberry Pi 5 board image, source: Raspberry Pi official product assets.</figcaption></figure>
      <figure><img src="/pi5-asset/bcm2712.png" alt="BCM2712 SoC"><figcaption>BCM2712 application processor close-up. CPU, GPU, memory, HDMI, PCIe root-side functions are centered here.</figcaption></figure>
      <figure><img src="/pi5-asset/rp1.png" alt="RP1 I/O controller"><figcaption>RP1 I/O controller close-up. RP1 handles much of the external I/O including USB, Ethernet, GPIO, and MIPI transceivers.</figcaption></figure>
    </section>

    <section class="block">
      <h2>실물 보드 사진에서 확인할 포인트</h2>
      <p>위 실물 사진은 DVS-CIS 합성 장비를 만들 때 더 직관적이다. 문서상의 블록 다이어그램은 BCM2712, RP1, MIPI, USB, PCIe 역할을 보여주지만, 실제 제작에서는 어느 케이블을 어디에 꽂고 열과 전원을 어떻게 처리할지가 더 중요하다.</p>
      <table>
        <thead><tr><th>사진에서 볼 부분</th><th>역할</th><th>DVS-CIS 합성 장비에서의 의미</th></tr></thead>
        <tbody>
          <tr><td>보드 중앙의 큰 SoC/방열 위치</td><td>BCM2712가 CPU/GPU/메모리 주변 처리를 담당</td><td>event accumulation, frame fusion, encode handoff가 몰리는 영역이다. 장시간 실시간 합성은 방열판과 팬이 필요하다.</td></tr>
          <tr><td>두 개의 CAM/DISP FFC 커넥터</td><td>각각 4-lane MIPI CSI-2 camera 또는 DSI display로 사용 가능</td><td>CIS 센서는 이 포트에 연결하는 구성이 가장 안정적이다. dual camera도 가능하지만 DVS와 timestamp 동기화가 별도 과제다.</td></tr>
          <tr><td>USB 3.0 포트</td><td>고속 외부 장치 입력</td><td>DVS 센서를 USB event stream으로 받을 때 가장 현실적인 입력 경로다. CIS는 MIPI, DVS는 USB로 분리하면 병목을 줄일 수 있다.</td></tr>
          <tr><td>40-pin GPIO 헤더</td><td>3.3V GPIO, UART, SPI, I2C, PWM, trigger line</td><td>DVS와 CIS의 촬영 시작 신호, PPS, 외부 인터럽트, 보조 MCU 동기화에 사용한다.</td></tr>
          <tr><td>PCIe FFC 커넥터</td><td>외부 PCIe 2.0 x1 확장</td><td>NVMe 저장장치 또는 AI accelerator HAT 연결 후보지만 대역폭은 x1이다. 고속 저장에는 유용하지만 대형 NPU급 처리 성능을 기대하면 안 된다.</td></tr>
          <tr><td>USB-C 전원 입력</td><td>5V/5A PD 전원 권장</td><td>카메라, DVS, NVMe, 팬을 동시에 쓰면 전원 여유가 중요하다. 저전원 어댑터는 프레임 드롭과 USB 불안정 원인이 된다.</td></tr>
        </tbody>
      </table>
      <p>따라서 실험용 배선은 CIS camera를 MIPI CAM 포트에, DVS를 USB 3.0에, 동기화 신호를 GPIO에, 결과 전송은 Ethernet에 두는 구성이 가장 단순하다. 이 구성은 Pi 5의 장점을 잘 쓰지만, 200FPS 이상 고품질 합성은 CPU만으로는 어렵기 때문에 C++/NEON 최적화나 외부 AI accelerator를 함께 검토해야 한다.</p>
    </section>

    <section class="block">
      <h2>Top-Level Block Diagram</h2>
      <pre>                         +-------------------------------+
                         | Broadcom BCM2712 AP           |
                         | - 4x Cortex-A76 @ 2.4GHz      |
                         | - VideoCore VII GPU           |
                         | - LPDDR4X-4267 controller     |
                         | - Dual micro-HDMI 4Kp60       |
                         | - 4Kp60 HEVC decode           |
                         +---------------+---------------+
                                         |
                          PCIe 2.0 x4 internal link
                                         |
                         +---------------v---------------+
                         | RP1 I/O Controller            |
                         | - USB 3.0 / USB 2.0           |
                         | - Gigabit Ethernet MAC        |
                         | - 2x 4-lane MIPI transceivers |
                         | - GPIO, UART, SPI, I2C, PWM   |
                         +-----+------------+------------+
                               |            |
             +-----------------+            +------------------+
             |                                      |
       USB / Ethernet / GPIO              CAM/DISP0, CAM/DISP1
                                          CSI-2 camera or DSI display

External PCIe FPC:
  BCM2712 -> PCIe 2.0 x1 connector for NVMe / accelerator HATs</pre>
      <p>Pi 5의 중요한 특징은 RP1이다. RP1은 standalone MCU가 아니라 Pi 5 보드에 들어간 I/O controller이며, BCM2712와 internal PCIe 2.0 x4 link로 연결된다. 외부 확장용 PCIe는 별도의 FPC connector로 PCIe 2.0 x1이 제공된다.</p>
    </section>

    <section class="block">
      <h2>Performance Summary</h2>
      <table>
        <thead><tr><th>Subsystem</th><th>Specification</th><th>DVS-CIS Fusion Meaning</th></tr></thead>
        <tbody>
          <tr><td>CPU</td><td>Broadcom BCM2712, quad-core 64-bit Arm Cortex-A76 @ 2.4GHz</td><td>Python/NumPy PoC, orchestration, lightweight C++ fusion 가능. 200FPS 이상은 C++/NEON 최적화 필요.</td></tr>
          <tr><td>GPU</td><td>VideoCore VII, OpenGL ES 3.1, Vulkan 1.3</td><td>GPU compute 가능성을 검토할 수 있지만 일반 CUDA 환경은 아님. Vulkan compute/GL path는 개발 난도가 있음.</td></tr>
          <tr><td>Memory</td><td>LPDDR4X-4267, 1GB/2GB/4GB/8GB/16GB variants</td><td>event buffer, frame buffer, encode buffer 동시 운용. 8GB 이상 권장.</td></tr>
          <tr><td>Video decode</td><td>4Kp60 HEVC decoder</td><td>입력 영상 decode에는 유리하나, 실시간 합성 병목은 event accumulation과 encode handoff.</td></tr>
          <tr><td>Display</td><td>Dual 4Kp60 micro-HDMI with HDR support</td><td>데모 모니터링/대시보드에 충분.</td></tr>
          <tr><td>I/O controller</td><td>RP1 via internal PCIe 2.0 x4 to BCM2712</td><td>USB, Ethernet, MIPI, GPIO를 RP1이 담당. 고속 I/O 부하와 CPU 연산을 분리하는 구조.</td></tr>
        </tbody>
      </table>
    </section>

    <section class="block">
      <h2>Interface Specifications</h2>
      <table>
        <thead><tr><th>Interface</th><th>Raspberry Pi 5 Spec</th><th>Notes For This Project</th></tr></thead>
        <tbody>
          <tr><td>MIPI camera/display</td><td>2x 4-lane MIPI transceivers, each usable as CSI-2 camera or DSI display</td><td>CIS camera input에 핵심. 두 커넥터를 모두 camera로 쓰거나 camera+display 조합 가능.</td></tr>
          <tr><td>USB</td><td>2x USB 3.0 ports, simultaneous 5Gbps operation; 2x USB 2.0 ports</td><td>USB DVS sensor 또는 USB camera 입력 가능. USB DVS + MIPI CIS 조합이 현실적.</td></tr>
          <tr><td>Ethernet</td><td>Gigabit Ethernet with PoE+ support via HAT</td><td>웹 대시보드, event packet 전송, remote monitoring에 사용.</td></tr>
          <tr><td>PCIe external</td><td>PCIe 2.0 x1 FPC connector, adapter/HAT required</td><td>NVMe 저장장치 또는 AI accelerator 연결 가능. 외부 대역폭은 x1 한계가 있음.</td></tr>
          <tr><td>microSD</td><td>High-speed SDR104 mode support</td><td>OS/간단 저장에는 충분하지만 event/video 장기 저장은 NVMe 권장.</td></tr>
          <tr><td>GPIO</td><td>Raspberry Pi 40-pin header, 3.3V GPIO</td><td>DVS/CIS trigger, PPS, external sync, interrupt line 연결에 사용.</td></tr>
          <tr><td>Low-speed buses</td><td>UART, SPI, I2C, I2S, PWM via GPIO mux</td><td>sensor control, IMU, temperature sensor, external MCU, lens control 등에 사용.</td></tr>
          <tr><td>Power</td><td>5V/5A USB-C with Power Delivery support</td><td>카메라, USB 센서, NVMe, HAT 사용 시 전원 margin 중요. Active cooling 권장.</td></tr>
          <tr><td>Wireless</td><td>Dual-band 802.11ac Wi-Fi, Bluetooth 5.0/BLE</td><td>개발/저대역 원격 접속에는 편리하지만 안정적 영상/이벤트 전송은 Ethernet 권장.</td></tr>
        </tbody>
      </table>
    </section>

    <section class="block two">
      <div>
        <h2>CIS Camera Interface Detail</h2>
        <p>Pi 5의 CIS 카메라 입력은 MIPI CSI-2를 사용한다. 보드에는 2개의 4-lane MIPI transceiver가 있으며, 각 커넥터는 camera 또는 display 용도로 사용할 수 있다. 공식 제품 설명에서는 이 커넥터를 camera/display transceiver라고 부른다.</p>
        <pre>CIS sensor
  -> MIPI CSI-2 data lanes
  -> Pi 5 CAM/DISP connector
  -> RP1 MIPI transceiver
  -> BCM2712 / ISP path
  -> application frame buffer</pre>
        <ul>
          <li>카메라 모듈은 Pi 5용 22-pin FFC/adapter compatibility를 확인해야 한다.</li>
          <li>두 MIPI 포트 모두 camera로 쓰면 dual-CIS 입력 실험 가능.</li>
          <li>DVS가 USB라면 CIS는 MIPI, DVS는 USB3로 분리하는 구성이 안정적이다.</li>
          <li>DVS와 CIS의 timestamp sync는 GPIO trigger/PPS 또는 host monotonic clock 보정이 필요하다.</li>
        </ul>
      </div>
      <div>
        <h2>DVS-CIS Fusion Wiring Example</h2>
        <pre>Recommended PoC wiring:

MIPI CAM0:
  CIS camera, 50FPS or burst capture

USB 3.0:
  DVS sensor event stream

GPIO:
  trigger / sync pulse / event interrupt

Ethernet:
  dashboard and result upload

NVMe over PCIe x1:
  optional raw event + video storage

Cooling:
  active cooler or case fan</pre>
        <p>이 구성은 Pi 5에서 PoC를 만들기에 적합하다. 단, 200 synthesis FPS 이상 제품 목표에서는 Pi 5 CPU만으로는 부족하므로 C++/NEON, GPU compute, 또는 IQ8/Jetson/FPGA-assisted SoC로 확장해야 한다.</p>
      </div>
    </section>

    <section class="block">
      <h2>Pi 5 In This Project: Strengths And Limits</h2>
      <div class="cards">
        <div class="card"><b>Strength: fast prototyping</b><p>Python, OpenCV, web server, camera stack을 빠르게 붙여 실험 가능.</p></div>
        <div class="card"><b>Strength: flexible I/O</b><p>MIPI CIS, USB DVS, Ethernet dashboard, GPIO sync를 한 보드에서 구성 가능.</p></div>
        <div class="card"><b>Limit: no large NPU</b><p>고품질 neural interpolation을 온디바이스 200FPS로 돌리기에는 AI 가속 구조가 부족.</p></div>
        <div class="card"><b>Limit: memory scatter</b><p>DVS event accumulation은 random write가 많아 Python/NumPy에서 병목이 큼.</p></div>
        <div class="card"><b>Limit: thermal</b><p>장시간 합성/인코딩/USB 입력 부하에서는 active cooling과 안정 전원 필요.</p></div>
        <div class="card"><b>Recommendation</b><p>Pi 5는 PoC와 dashboard, 저해상도 preview용. 제품은 IQ8/Jetson/FPGA급으로 이전.</p></div>
      </div>
    </section>

    <section class="block">
      <h2>References</h2>
      <ul>
        <li><a href="https://www.raspberrypi.com/products/raspberry-pi-5/" target="_blank">Raspberry Pi 5 product specification</a></li>
        <li><a href="https://www.raspberrypi.com/news/introducing-raspberry-pi-5/" target="_blank">Raspberry Pi 5 launch article: BCM2712, RP1, DA9091 architecture</a></li>
        <li><a href="https://www.raspberrypi.com/documentation/computers/io-controllers.html" target="_blank">Raspberry Pi RP1 I/O controller documentation</a></li>
        <li><a href="https://www.raspberrypi.com/documentation/computers/raspberry-pi.html" target="_blank">Raspberry Pi hardware documentation, PCIe connector</a></li>
      </ul>
    </section>
  </main>
</body>
</html>'''


def render_page():
    images = list_images()
    status = get_status()
    latest = images[0] if images else None
    cards = []
    for img in images[:120]:
        name = html.escape(img["name"])
        age = html.escape(format_age(img["mtime"]))
        size_kb = img["size"] / 1024
        cards.append(f'''
          <a class="thumb" href="/image/{name}" data-src="/image/{name}" data-name="{name}" title="{name}">
            <img src="/image/{name}" loading="lazy" alt="{name}">
            <span class="thumb-meta"><b>{name}</b><small>{age} · {size_kb:.0f} KB</small></span>
          </a>
        ''')
    latest_html = ""
    if latest:
        latest_name = html.escape(latest["name"])
        latest_html = f'<img class="hero-img" src="/image/{latest_name}?v={int(latest["mtime"])}" alt="{latest_name}">'
    else:
        latest_html = '<div class="empty">No snapshots yet</div>'

    log_lines = "\n".join(html.escape(x) for x in status["log_tail"])
    timer_class = "ok" if status["capture_timer"] == "active" else "warn"
    web_class = "ok" if status["web_service"] == "active" else "warn"

    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Camera Snapshots</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#101214; --panel:#191d21; --panel2:#20262b; --line:#303840;
      --text:#edf2f4; --muted:#9aa6ad; --accent:#5cc8a7; --warn:#ffbf69;
      --blue:#7bb7ff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }}
    header {{ position:sticky; top:0; z-index:5; background:rgba(16,18,20,.92); backdrop-filter:blur(14px); border-bottom:1px solid var(--line); }}
    .bar {{ max-width:1480px; margin:0 auto; padding:14px 18px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
    h1 {{ margin:0; font-size:20px; font-weight:720; letter-spacing:0; }}
    .sub {{ color:var(--muted); font-size:13px; }}
    main {{ max-width:1480px; margin:0 auto; padding:18px; display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:18px; align-items:start; }}
    .gallery-wrap {{ min-width:0; }}
    .dialog {{ position:fixed; inset:0; z-index:20; display:none; align-items:center; justify-content:center; padding:24px; background:rgba(0,0,0,.78); backdrop-filter:blur(10px); }}
    .dialog.open {{ display:flex; }}
    .dialog-inner {{ max-width:min(96vw,1280px); max-height:92vh; display:flex; flex-direction:column; gap:10px; }}
    .dialog img {{ max-width:100%; max-height:84vh; object-fit:contain; background:#050607; border:1px solid var(--line); border-radius:8px; }}
    .dialog-bar {{ display:flex; align-items:center; justify-content:space-between; gap:12px; color:var(--text); }}
    .close {{ border:1px solid var(--line); border-radius:8px; background:var(--panel2); color:var(--text); padding:8px 12px; cursor:pointer; }}
    .side {{ display:flex; flex-direction:column; gap:12px; position:sticky; top:74px; max-height:calc(100vh - 92px); overflow:auto; padding-right:2px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:13px; box-shadow:0 10px 30px rgba(0,0,0,.18); }}
    .metric {{ display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; margin:10px 0; }}
    .chart {{ width:100%; height:120px; margin-top:10px; border:1px solid var(--line); border-radius:8px; background:#0c0e10; }}
    .chart-meta {{ display:flex; justify-content:space-between; gap:10px; margin-top:7px; color:var(--muted); font-size:11px; }}
    .metric:first-child {{ margin-top:0; }}
    .label {{ color:var(--muted); font-size:13px; }}
    .value {{ font-size:13px; font-weight:700; }}
    .track {{ grid-column:1 / -1; height:8px; border-radius:999px; background:#0c0e10; overflow:hidden; border:1px solid #252b31; }}
    .fill {{ height:100%; background:linear-gradient(90deg,var(--accent),var(--blue)); }}
    .pill {{ display:inline-flex; align-items:center; min-height:24px; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:700; border:1px solid var(--line); background:var(--panel2); }}
    .top-link {{ color:var(--accent); text-decoration:none; }}
    .top-link:hover {{ text-decoration:underline; }}
    .ok {{ color:var(--accent); }}
    .warn {{ color:var(--warn); }}
    .grid-title {{ display:flex; align-items:end; justify-content:space-between; margin:0 0 12px; }}
    h2 {{ margin:0; font-size:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(156px,1fr)); gap:12px; }}
    .thumb {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; color:inherit; text-decoration:none; min-width:0; box-shadow:0 8px 24px rgba(0,0,0,.16); padding:0; text-align:left; cursor:pointer; font:inherit; }}
    .thumb:hover {{ border-color:#60717d; transform:translateY(-1px); transition:.12s ease; }}
    .thumb img {{ width:100%; aspect-ratio:4 / 3; object-fit:contain; display:block; background:#050607; }}
    .thumb-meta {{ display:block; padding:9px; min-width:0; }}
    .thumb-meta b {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }}
    .thumb-meta small {{ display:block; color:var(--muted); margin-top:3px; font-size:11px; }}
    pre {{ margin:8px 0 0; white-space:pre-wrap; color:#cbd5da; font-size:11px; line-height:1.45; }}
    .empty {{ color:var(--muted); }}
    @media (max-width:980px) {{
      main {{ grid-template-columns:1fr; }}
      .side {{ position:static; max-height:none; overflow:visible; padding-right:0; }}
    }}
  .global-nav{{position:sticky;top:0;z-index:30;display:flex;justify-content:center;align-items:center;gap:8px;padding:10px 12px;background:#111318;border-bottom:1px solid #30343d}}.global-nav a{{display:inline-flex;align-items:center;justify-content:center;min-width:86px;height:34px;padding:0 14px;border:1px solid #343d46;border-radius:6px;background:#1a1f25;color:#dbeafe;text-decoration:none;font-weight:700;font-size:14px;line-height:1;white-space:nowrap}}.global-nav a:hover{{background:#22303a;border-color:#5cc8a7;color:#ffffff}}@media(max-width:520px){{.global-nav{{gap:6px;padding:8px}}.global-nav a{{min-width:auto;height:32px;padding:0 10px;font-size:13px}}}}
</style>
</head>
<body>{render_global_nav()}
  <header>
    <div class="bar">
      <div>
        <h1>Camera Snapshots</h1>
        <div class="sub">Latest: <span id="latest-name">{html.escape(status["latest_name"] or "none")}</span> · <span id="latest-age">{html.escape(status["latest_age"])}</span> · live refresh 3s</div>
      </div>
      <div class="pill"><a class="top-link" href="/person">Person events: <span id="person-count">{status["person_event_count"]}</span></a> · <span id="image-count">{status["image_count"]}</span> images</div>
    </div>
  </header>
  <main>
    <section class="gallery-wrap">
      <div class="grid-title"><h2>Snapshots</h2><div class="sub">Newest first · click to enlarge</div></div>
      <section class="grid" id="snapshot-grid">{''.join(cards) if cards else '<div class="empty">No images found.</div>'}</section>
      <div class="grid-title person-title"><h2>Person events</h2><div class="sub">Detected separately · 24h retention</div></div>
      <section class="grid" id="person-grid"><div class="empty">No person events yet.</div></section>
    </section>
    <aside class="side">
      <section class="panel">
        <div class="metric"><span class="label">CPU</span><span class="value" id="cpu-value">{status["cpu_pct"]:.1f}%</span><div class="track"><div class="fill" id="cpu-fill" style="{pct_style(status["cpu_pct"])}"></div></div></div>
        <div class="metric"><span class="label">Memory</span><span class="value" id="mem-value">{status["mem_used_mb"]} / {status["mem_total_mb"]} MB</span><div class="track"><div class="fill" id="mem-fill" style="{pct_style(status["mem_pct"])}"></div></div></div>
        <div class="metric"><span class="label">Temperature</span><span class="value" id="temp-value">{html.escape(status["temp"])}</span></div>
        <div class="metric"><span class="label">Disk free</span><span class="value" id="disk-value">{status["disk_free_gb"]:.1f} GB</span></div>
        <div class="metric"><span class="label">Throttle flag</span><span class="value" id="throttle-value">{html.escape(status["throttled"])}</span></div>
        <div class="metric"><span class="label">CPU thermal</span><span class="value">{html.escape(status["cpu_thermal_type"])}</span></div>
        <div class="metric"><span class="label">ARM clock</span><span class="value" id="clock-value">{html.escape(status["arm_clock"])}</span></div>
        <div class="metric"><span class="label">Core voltage</span><span class="value" id="volts-value">{html.escape(status["core_volts"])}</span></div>
        <div class="metric"><span class="label">ARM / GPU memory</span><span class="value">{html.escape(status["arm_mem"])} / {html.escape(status["gpu_mem"])}</span></div>
        <div class="label">Temperature history · 24h</div>
        <canvas class="chart" id="temp-chart" width="320" height="120"></canvas>
        <div class="chart-meta"><span id="temp-chart-min">min</span><span id="temp-chart-max">max</span></div>
        <div class="label" style="margin-top:14px">Power / thermal watchdog · 24h</div>
        <canvas class="chart" id="power-chart" width="320" height="120"></canvas>
        <div class="chart-meta"><span id="power-chart-min">min</span><span id="power-chart-max">max / throttle</span></div>
      </section>
      <section class="panel">
        <div class="metric"><span class="label">Capture timer</span><span class="value {timer_class}" id="timer-value">{html.escape(status["capture_timer"])}</span></div>
        <div class="metric"><span class="label">Web service</span><span class="value {web_class}" id="web-value">{html.escape(status["web_service"])}</span></div>
        <div class="metric"><span class="label">Retention</span><span class="value">max 200, similar-first pruning</span></div>
        <div class="metric"><span class="label">Interval</span><span class="value">3 seconds</span></div>
        <div class="metric"><span class="label">Thermal guard</span><span class="value" id="thermal-guard-value">{html.escape(status["thermal_guard"])}</span></div>
        <div class="label" style="margin-top:10px">Thermal guard log</div>
        <pre id="thermal-guard-tail">{html.escape(chr(10).join(status["thermal_guard_tail"]))}</pre>
      </section>
      <section class="panel">
        <div class="label">Connected devices</div>
        <pre>{html.escape(chr(10).join(status["usb_devices"][:12]) or "none")}</pre>
      </section>
      <section class="panel">
        <div class="label">Camera / video devices</div>
        <pre>{html.escape(chr(10).join(status["video_devices"][:22]) or "none")}</pre>
      </section>
      <section class="panel">
        <div class="label">GPIO / I2C</div>
        <pre>{html.escape("I2C:\n" + (chr(10).join(status["i2c_devices"]) or "none") + "\n\nGPIO:\n" + (chr(10).join(status["gpio_devices"]) or "none"))}</pre>
      </section>
      <section class="panel">
        <div class="label">Recent capture log</div>
        <pre id="log-tail">{log_lines}</pre>
        <div class="label" style="margin-top:10px">Recent person events</div>
        <pre id="person-log-tail">{html.escape(chr(10).join(status["person_log_tail"]))}</pre>
      </section>
    </aside>
  </main>
  <div class="dialog" id="viewer" aria-hidden="true">
    <div class="dialog-inner">
      <div class="dialog-bar"><strong id="viewer-title"></strong><button class="close" type="button" id="viewer-close">Close</button></div>
      <img id="viewer-img" src="" alt="">
    </div>
  </div>
  <script>
    const viewer = document.getElementById('viewer');
    const viewerImg = document.getElementById('viewer-img');
    const viewerTitle = document.getElementById('viewer-title');
    const grid = document.getElementById('snapshot-grid');
    let lastImageKey = '';
    const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({{
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }}[ch]));
    const closeViewer = () => {{
      viewer.classList.remove('open');
      viewer.setAttribute('aria-hidden', 'true');
      viewerImg.src = '';
    }};
    const openViewer = (src, name) => {{
      viewerImg.src = src;
      viewerImg.alt = name;
      viewerTitle.textContent = name;
      viewer.classList.add('open');
      viewer.setAttribute('aria-hidden', 'false');
    }};
    const setText = (id, value) => {{
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }};
    const setWidth = (id, value) => {{
      const el = document.getElementById(id);
      if (el) el.style.width = `${{Math.max(0, Math.min(100, Number(value) || 0)).toFixed(1)}}%`;
    }};
    const renderImages = (images) => {{
      if (viewer.classList.contains('open')) return;
      const key = Array.isArray(images) ? images.map((img) => `${{img.name}}:${{img.mtime}}`).join('|') : '';
      if (key === lastImageKey) return;
      lastImageKey = key;
      if (!Array.isArray(images) || images.length === 0) {{
        grid.innerHTML = '<div class="empty">No images found.</div>';
        return;
      }}
      grid.innerHTML = images.map((img) => {{
        const name = escapeHtml(img.name);
        const age = escapeHtml(img.age);
        const size = escapeHtml(img.size_kb);
        return `<button class="thumb" type="button" data-src="/image/${{name}}" data-name="${{name}}" title="${{name}}">
          <img src="/image/${{name}}?v=${{img.mtime}}" loading="lazy" alt="${{name}}">
          <span class="thumb-meta"><b>${{name}}</b><small>${{age}} · ${{size}} KB</small></span>
        </a>`;
      }}).join('');
    }};
    const drawTempChart = (history) => {{
      const canvas = document.getElementById('temp-chart');
      if (!canvas || !Array.isArray(history) || history.length === 0) return;
      const ctx = canvas.getContext('2d');
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      const temps = history.map((p) => Number(p.temp_c)).filter((v) => Number.isFinite(v));
      if (!temps.length) return;
      const min = Math.floor(Math.min(...temps) - 1);
      const max = Math.ceil(Math.max(...temps) + 1);
      const range = Math.max(1, max - min);
      ctx.strokeStyle = '#303840';
      ctx.lineWidth = 1;
      for (let i = 1; i < 4; i += 1) {{
        const y = Math.round((height / 4) * i);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }}
      ctx.strokeStyle = '#5cc8a7';
      ctx.lineWidth = 2;
      ctx.beginPath();
      history.forEach((point, index) => {{
        const x = history.length === 1 ? width - 2 : (index / (history.length - 1)) * (width - 4) + 2;
        const y = height - 8 - ((Number(point.temp_c) - min) / range) * (height - 16);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();
      const last = temps[temps.length - 1];
      setText('temp-chart-min', `min ${{Math.min(...temps).toFixed(1)}}°C`);
      setText('temp-chart-max', `now ${{last.toFixed(1)}}°C / max ${{Math.max(...temps).toFixed(1)}}°C`);
    }};


    const drawPowerChart = (history) => {{
      const canvas = document.getElementById('power-chart');
      if (!canvas || !Array.isArray(history) || history.length === 0) return;
      const ctx = canvas.getContext('2d');
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#0c0e10';
      ctx.fillRect(0, 0, width, height);
      if (history.length < 2) {{
        ctx.fillStyle = '#8b98a5';
        ctx.font = '12px system-ui';
        ctx.fillText('Waiting for power samples...', 12, 24);
        return;
      }}
      const pad = {{left: 34, right: 34, top: 18, bottom: 20}};
      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const tsValues = history.map((p) => Number(p.ts)).filter((v) => Number.isFinite(v));
      const minTs = Math.min(...tsValues);
      const maxTs = Math.max(...tsValues);
      const tempValues = history.map((p) => Number(p.temp_c)).filter((v) => Number.isFinite(v));
      const voltValues = history.map((p) => Number(p.core_volts)).filter((v) => Number.isFinite(v));
      const clockValues = history.map((p) => Number(p.arm_clock_ghz)).filter((v) => Number.isFinite(v));
      const minTemp = Math.min(35, Math.floor(Math.min(...tempValues) - 2));
      const maxTemp = Math.max(85, Math.ceil(Math.max(...tempValues) + 2));
      const minVolt = voltValues.length ? Math.max(0.55, Math.min(...voltValues) - 0.03) : 0.65;
      const maxVolt = voltValues.length ? Math.min(1.10, Math.max(...voltValues) + 0.03) : 1.00;
      const minClock = clockValues.length ? Math.max(0, Math.min(...clockValues) - 0.15) : 0;
      const maxClock = clockValues.length ? Math.max(2.5, Math.max(...clockValues) + 0.15) : 2.5;
      const xFor = (ts) => pad.left + ((Number(ts) - minTs) / Math.max(1, maxTs - minTs)) * chartW;
      const yFor = (v, min, max) => height - pad.bottom - ((v - min) / Math.max(0.0001, max - min)) * chartH;

      ctx.strokeStyle = '#2a323a';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i += 1) {{
        const y = pad.top + (chartH * i / 4);
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }}

      const plot = (getter, min, max, color, lineWidth) => {{
        let started = false;
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        history.forEach((point) => {{
          const value = Number(getter(point));
          if (!Number.isFinite(value)) return;
          const x = xFor(point.ts);
          const y = yFor(value, min, max);
          if (!started) {{ ctx.moveTo(x, y); started = true; }}
          else ctx.lineTo(x, y);
        }});
        if (started) ctx.stroke();
      }};

      history.forEach((point) => {{
        if (point.throttled && point.throttled !== '0x0') {{
          const x = xFor(point.ts);
          ctx.fillStyle = 'rgba(239,68,68,.22)';
          ctx.fillRect(x - 1, pad.top, 3, chartH);
        }}
      }});
      plot((p) => p.temp_c, minTemp, maxTemp, '#ef4444', 2.2);
      plot((p) => p.core_volts, minVolt, maxVolt, '#3b82f6', 2);
      plot((p) => p.arm_clock_ghz, minClock, maxClock, '#22c55e', 1.8);

      const last = history[history.length - 1] || {{}};
      const throttleCount = history.filter((p) => p.throttled && p.throttled !== '0x0').length;
      ctx.font = '11px system-ui';
      ctx.fillStyle = '#ef4444';
      ctx.fillText(`${{maxTemp}}C`, 3, pad.top + 4);
      ctx.fillText(`${{minTemp}}C`, 5, height - pad.bottom);
      ctx.fillStyle = '#3b82f6';
      ctx.fillText(`${{maxVolt.toFixed(2)}}V`, width - 32, pad.top + 4);
      ctx.fillText(`${{minVolt.toFixed(2)}}V`, width - 32, height - pad.bottom);
      setText('power-chart-min', `red temp / blue core V / green ARM GHz · samples ${{history.length}}`);
      const lastTemp = Number.isFinite(Number(last.temp_c)) ? `${{Number(last.temp_c).toFixed(1)}}C` : 'n/a';
      const lastVolt = Number.isFinite(Number(last.core_volts)) ? `${{Number(last.core_volts).toFixed(4)}}V` : 'n/a';
      const lastClock = Number.isFinite(Number(last.arm_clock_ghz)) ? `${{Number(last.arm_clock_ghz).toFixed(2)}}GHz` : 'n/a';
      setText('power-chart-max', `now ${{lastTemp}} / ${{lastVolt}} / ${{lastClock}} · events ${{throttleCount}}`);
    }};

    const refresh = async () => {{
      try {{
        const response = await fetch('/status.json', {{ cache: 'no-store' }});
        if (!response.ok) return;
        const data = await response.json();
        setText('latest-name', data.latest_name || 'none');
        setText('latest-age', data.latest_age || 'n/a');
        setText('image-count', data.image_count ?? 0);
        setText('person-count', data.person_event_count ?? 0);
        setText('cpu-value', `${{Number(data.cpu_pct || 0).toFixed(1)}}%`);
        setWidth('cpu-fill', data.cpu_pct);
        setText('mem-value', `${{data.mem_used_mb}} / ${{data.mem_total_mb}} MB`);
        setWidth('mem-fill', data.mem_pct);
        setText('temp-value', data.temp || 'n/a');
        drawTempChart(data.temp_history);
        drawPowerChart(data.power_history);
        setText('disk-value', `${{Number(data.disk_free_gb || 0).toFixed(1)}} GB`);
        setText('throttle-value', data.throttled || 'n/a');
        setText('clock-value', data.arm_clock || 'n/a');
        setText('volts-value', data.core_volts || 'n/a');
        setText('timer-value', data.capture_timer || 'unknown');
        setText('web-value', data.web_service || 'unknown');
        setText('log-tail', Array.isArray(data.log_tail) ? data.log_tail.join('\\n') : '');
        renderImages(data.images);
      }} catch (error) {{
      }}
    }};
    document.addEventListener('click', (event) => {{
      const button = event.target.closest('.thumb');
      if (!button) return;
      event.preventDefault();
      openViewer(button.dataset.src || button.href, button.dataset.name || button.getAttribute('title') || 'snapshot');
    }});
    setInterval(refresh, 3000);
    document.getElementById('viewer-close').addEventListener('click', closeViewer);
    viewer.addEventListener('click', (event) => {{
      if (event.target === viewer) closeViewer();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') closeViewer();
    }});
  </script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def send_file_response(self, path, content_type, allow_range=False, include_body=True):
        size = path.stat().st_size
        start = 0
        end = size - 1
        status = 200
        range_header = self.headers.get("Range") if allow_range else None
        if range_header and range_header.startswith("bytes="):
            spec = range_header.split("=", 1)[1].split(",", 1)[0].strip()
            if "-" in spec:
                left, right = spec.split("-", 1)
                try:
                    if left:
                        start = int(left)
                        end = int(right) if right else size - 1
                    else:
                        suffix = int(right)
                        start = max(0, size - suffix)
                        end = size - 1
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    status = 206
                except Exception:
                    start = 0
                    end = size - 1
                    status = 200

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if not include_body:
            return
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def handle_request(self, include_body=True):
        path_only = self.path.split("?", 1)[0]
        if path_only == "/fall-plan":
            self.send_file_response(Path("/home/philip/fall_detection_plan.html"), "text/html; charset=utf-8", include_body=include_body)
            return

        if path_only == "/status.json":
            data = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        if path_only in ("/event-synthesis", "/event-synthesis.html"):
            data = render_event_synthesis_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        if path_only in ("/space-edge-proposal", "/space-edge-proposal.html"):
            data = render_space_edge_proposal_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        if path_only in ("/raspberry-pi5-architecture", "/raspberry-pi5-architecture.html"):
            data = render_pi5_architecture_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        if path_only.startswith("/pi5-asset/"):
            name = unquote(path_only.split("/pi5-asset/", 1)[1])
            if "/" in name or "\\" in name:
                self.send_error(400)
                return
            path = PI5_ARCH_ASSET_DIR / name
            if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                self.send_error(404)
                return
            content_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }[path.suffix.lower()]
            self.send_file_response(path, content_type, include_body=include_body)
            return

        if path_only.startswith("/event-synthesis-video/"):
            name = unquote(path_only.split("/event-synthesis-video/", 1)[1])
            if "/" in name or "\\" in name:
                self.send_error(400)
                return
            path = EVENT_SYNTH_OUTPUT_DIR / name
            if not path.is_file() or path.suffix.lower() != ".mp4":
                self.send_error(404)
                return
            self.send_file_response(path, "video/mp4", allow_range=True, include_body=include_body)
            return

        if path_only.startswith("/image/") or path_only.startswith("/person-image/"):
            prefix = "/person-image/" if path_only.startswith("/person-image/") else "/image/"
            directory = PERSON_DIR if prefix == "/person-image/" else SNAPSHOT_DIR
            name = unquote(path_only.split(prefix, 1)[1])
            if "/" in name or "\\" in name:
                self.send_error(400)
                return
            path = directory / name
            if not path.is_file() or path.suffix.lower() != ".jpg":
                self.send_error(404)
                return
            self.send_file_response(path, "image/jpeg", include_body=include_body)
            return

        if path_only in ("/person", "/person.html"):
            data = render_person_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        if path_only in ("/", "/index.html"):
            data = render_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if include_body:
                self.wfile.write(data)
            return

        self.send_error(404)

    def do_GET(self):
        self.handle_request(include_body=True)

    def do_HEAD(self):
        self.handle_request(include_body=False)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()
