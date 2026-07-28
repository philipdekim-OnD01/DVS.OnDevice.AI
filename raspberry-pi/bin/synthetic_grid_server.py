#!/usr/bin/env python3
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

BASE = Path("/home/philip")
SYNTH_DIR = BASE / "synthetic_frames"
SYNTH = BASE / "bin/synthesize_virtual_dvs_grid.py"
PORT = 8081


def events(limit=24):
    if not SYNTH_DIR.exists():
        return []
    dirs = [p for p in SYNTH_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for d in dirs[:limit]:
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {"id": d.name, "frames": [p.name for p in sorted(d.glob("*.jpg"))]}
        meta["id"] = d.name
        out.append(meta)
    return out


def page():
    cards = []
    for ev in events():
        thumbs = []
        for name in ev.get("frames", []):
            src = f"/image/{ev['id']}/{name}"
            thumbs.append(f'<button class="thumb" data-src="{src}"><img src="{src}" loading="lazy"><span>{name[-6:-4]}</span></button>')
        video = ev.get("video")
        movie = ""
        if video:
            movie_src = f"/video/{ev['id']}/{video}"
            movie = f'<div class="inline-player"><video autoplay muted loop playsinline controls src="{movie_src}"></video></div>'
        cards.append(f"""
        <section class="event">
          <div class="head">
            <div><h2>{ev.get('id','')}</h2><p>{ev.get('source_before','?')} to {ev.get('source_after','?')}</p><p><a target="_blank" href="/play/{ev.get('id','')}">Open Player</a></p></div>
            <div class="stat">frames {ev.get('output_frames', len(ev.get('frames', [])))} · fps {ev.get('video_fps', 20)} · events {ev.get('event_pixels',0)}</div>
          </div>
          <p class="dvs-meta">{ev.get('virtual_dvs_format', 'visual grid only')} - chunk {ev.get('virtual_dvs_chunk_us', '')}us</p>
          {movie}
          <div class="grid">{''.join(thumbs)}</div>
        </section>""")
    body = "".join(cards) if cards else '<div class="empty">No synthetic grids yet.</div>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic Grid</title><style>
body{{margin:0;background:#101114;color:#f4f1ea;font-family:Arial,sans-serif}} header{{display:flex;justify-content:space-between;align-items:center;padding:16px 22px;background:#17191e;border-bottom:1px solid #30343d;position:sticky;top:0;z-index:2}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:0 0 4px}} a{{color:#7dd3fc;text-decoration:none}} button{{font:inherit}}
.wrap{{max-width:1440px;margin:0 auto;padding:16px}} .event{{background:#191c22;border:1px solid #30343d;border-radius:8px;margin-bottom:18px;padding:12px}}
.head{{display:flex;justify-content:space-between;gap:12px;margin-bottom:10px}} .head p{{margin:0;color:#aab0bd;font-size:13px}} .dvs-meta{{margin:0 0 10px;color:#93c5fd;font-size:12px}} .stat{{color:#d9bd70;font-size:13px;white-space:nowrap}}
.inline-player{{width:min(100%,760px);aspect-ratio:4/3;margin:0 auto 12px;background:#0c0e12;border:1px solid #343945;border-radius:6px;overflow:hidden}}.inline-player video{{width:100%;height:100%;object-fit:contain;display:block}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}} .thumb{{position:relative;aspect-ratio:4/3;border:1px solid #343945;background:#0c0e12;border-radius:6px;overflow:hidden;padding:0;cursor:pointer}}
.thumb img,.movie{{width:100%;height:100%;object-fit:contain;display:block}} .movie+img{{display:none}} .thumb span{{position:absolute;right:7px;bottom:6px;background:rgba(0,0,0,.68);padding:2px 5px;border-radius:4px;color:white;font-size:11px}}
.actions{{display:flex;gap:10px;align-items:center}} .make{{background:#2f7d5f;color:white;border:0;border-radius:6px;padding:8px 12px;cursor:pointer}} .empty{{padding:40px;text-align:center;color:#aab0bd}}
.modal{{position:fixed;inset:0;background:rgba(0,0,0,.86);display:none;align-items:center;justify-content:center;z-index:5}} .modal.open{{display:flex}} .modal img{{max-width:94vw;max-height:92vh;object-fit:contain}}
@media(max-width:700px){{header{{padding:12px}}.wrap{{padding:10px}}.head{{display:block}}.stat{{margin-top:8px;white-space:normal}}}}
.global-nav{{position:sticky;top:0;z-index:30;display:flex;justify-content:center;align-items:center;gap:8px;padding:10px 12px;background:#111318;border-bottom:1px solid #30343d}}.global-nav a{{display:inline-flex;align-items:center;justify-content:center;min-width:86px;height:34px;padding:0 14px;border:1px solid #343d46;border-radius:6px;background:#1a1f25;color:#dbeafe;text-decoration:none;font-weight:700;font-size:14px;line-height:1;white-space:nowrap}}.global-nav a:hover{{background:#22303a;border-color:#5cc8a7;color:#ffffff}}@media(max-width:520px){{.global-nav{{gap:6px;padding:8px}}.global-nav a{{min-width:auto;height:32px;padding:0 10px;font-size:13px}}}}
</style></head><body><div class="global-nav"><a href="http://192.168.0.100:8080/">Home</a><a href="http://192.168.0.100:8080/person">Person</a><a href="/">Synthetic</a></div><header><h1>Synthetic DVS Grid</h1><div class="actions"><form method="post" action="/make"><button class="make">Make Grid</button></form></div></header>
<main class="wrap">{body}</main><div class="modal" id="modal"><img id="modalImg" alt=""></div>
<script>document.addEventListener('click',e=>{{let b=e.target.closest('.thumb');if(b){{modalImg.src=b.dataset.src;modal.classList.add('open')}}if(e.target.id==='modal')modal.classList.remove('open')}});setTimeout(()=>location.reload(),3000)</script>
</body></html>"""


def video_tag(event_id, meta):
    video = meta.get('video')
    if not video:
        return ''
    src = f'/video/{event_id}/{video}'
    return f'<video class="movie" controls autoplay loop muted playsinline src="{src}"></video>'

def player_page(event_id):
    safe_id = "".join(c for c in event_id if c.isdigit() or c == "_")
    folder = SYNTH_DIR / safe_id
    if not folder.exists():
        return None
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {"id": safe_id, "frames": [p.name for p in sorted(folder.glob("*.jpg"))]}
    frames = [f"/image/{safe_id}/{name}" for name in meta.get("frames", [])]
    frames_json = json.dumps(frames)
    movie = video_tag(safe_id, meta)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic Player {safe_id}</title><style>
body{{margin:0;background:#08090b;color:#f4f1ea;font-family:Arial,sans-serif;min-height:100vh;display:flex;flex-direction:column}}
header{{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:#15171c;border-bottom:1px solid #2d3138}}
h1{{font-size:18px;margin:0}} a{{color:#7dd3fc;text-decoration:none}} .stage{{flex:1;display:grid;place-items:center;padding:16px}}
.viewer{{width:min(96vw,1100px);aspect-ratio:4/3;background:#0d0f13;border:1px solid #30343d;border-radius:8px;display:grid;place-items:center;overflow:hidden}}
img{{width:100%;height:100%;object-fit:contain;display:block}} .bar{{display:flex;gap:12px;align-items:center;justify-content:center;padding:12px 16px;background:#15171c;border-top:1px solid #2d3138;flex-wrap:wrap}}
button{{background:#2f7d5f;color:white;border:0;border-radius:6px;padding:8px 12px;cursor:pointer}} input[type=range]{{width:min(420px,70vw)}} .meta{{color:#aab0bd;font-size:13px}}
.global-nav{{position:sticky;top:0;z-index:30;display:flex;justify-content:center;align-items:center;gap:8px;padding:10px 12px;background:#111318;border-bottom:1px solid #30343d}}.global-nav a{{display:inline-flex;align-items:center;justify-content:center;min-width:86px;height:34px;padding:0 14px;border:1px solid #343d46;border-radius:6px;background:#1a1f25;color:#dbeafe;text-decoration:none;font-weight:700;font-size:14px;line-height:1;white-space:nowrap}}.global-nav a:hover{{background:#22303a;border-color:#5cc8a7;color:#ffffff}}@media(max-width:520px){{.global-nav{{gap:6px;padding:8px}}.global-nav a{{min-width:auto;height:32px;padding:0 10px;font-size:13px}}}}
</style></head><body>
<div class="global-nav"><a href="http://192.168.0.100:8080/">Home</a><a href="http://192.168.0.100:8080/person">Person</a><a href="/">Synthetic</a></div><header><h1>Synthetic 20-frame Player · {safe_id}</h1></header>
<main class="stage"><div class="viewer">{movie}<img id="frame" alt=""></div></main>
<div class="bar"><button id="toggle">Pause</button><button id="prev">Prev</button><button id="next">Next</button><input id="seek" type="range" min="0" max="{max(0, len(frames)-1)}" value="0"><span class="meta" id="label"></span></div>
<script>
const frames={frames_json};
let idx=0, playing=true, fps=20, timer=null;
const img=document.getElementById('frame'), seek=document.getElementById('seek'), label=document.getElementById('label'), toggle=document.getElementById('toggle');
frames.forEach(src=>{{const i=new Image(); i.src=src}});
function show(i){{if(!frames.length)return; idx=(i+frames.length)%frames.length; img.src=frames[idx]; seek.value=idx; label.textContent=`${{idx+1}} / ${{frames.length}} · ${{fps}} fps browser playback`;}}
function start(){{clearInterval(timer); timer=setInterval(()=>show(idx+1),1000/fps); playing=true; toggle.textContent='Pause';}}
function stop(){{clearInterval(timer); playing=false; toggle.textContent='Play';}}
toggle.onclick=()=>playing?stop():start(); prev.onclick=()=>{{stop();show(idx-1)}}; next.onclick=()=>{{stop();show(idx+1)}}; seek.oninput=()=>{{stop();show(Number(seek.value))}};
show(0); start();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/":
            self.send_bytes(page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path.startswith("/play/"):
            event_id = path[len("/play/"):]
            html = player_page(event_id)
            if html is not None:
                self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
                return
        if path.startswith("/video/"):
            parts = [p for p in path[len("/video/"):].split("/") if p and ".." not in p]
            if len(parts) == 2:
                f = SYNTH_DIR / parts[0] / parts[1]
                if f.exists():
                    self.send_bytes(f.read_bytes(), "video/mp4")
                    return
        if path.startswith("/image/"):
            parts = [p for p in path[len("/image/"):].split("/") if p and ".." not in p]
            if len(parts) == 2:
                f = SYNTH_DIR / parts[0] / parts[1]
                if f.exists():
                    self.send_bytes(f.read_bytes(), "image/jpeg")
                    return
        self.send_error(404)

    def do_POST(self):
        if self.path == "/make":
            subprocess.run(["python3", str(SYNTH)], timeout=20)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return
        self.send_error(404)


if __name__ == "__main__":
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
