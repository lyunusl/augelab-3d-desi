"""Canlı point cloud GPU servisi — AugeLab custom block'u buna kare yollar.

Sözleşme (127.0.0.1, varsayılan port 8770):
  POST /frame    gövde: JPEG kare (BGR)          -> durum JSON
  GET  /status                                   -> durum JSON
  GET  /preview  son bulut önizlemesi (JPEG)      başlık X-Preview-Version
  GET  /cloud?max=N  en fazla N nokta, ikili: N x (3 float32 xyz, 3 uint8 rgb)
                 eksenler x sağ, y yukarı, z ileri (ilk kamera); başlık X-Points
  POST /reset                                    -> durum JSON
  POST /save     .ply yazar                      -> {"path", "points", ...durum}
  POST /single?max=N&save=1  gövde: tek JPEG      -> /cloud biçiminde bulut (MoGe-2)
  POST /multi?max=N&save=1   gövde: art arda JPEG'ler, başlık X-Sizes: "n1,n2,..."
                             2-8 açı, tek geçişte Pi3X -> /cloud biçiminde bulut
  Tek seferlik yanıt başlıkları: X-Points (gönderilen), X-Total, X-PLY (yol ya da boş), X-Ms
  POST /process?sid=..&mode=live|single|multi&tc=0|1&trig=0|1&reset=0|1&count=N&folder=..&save=0|1
                 gövde: JPEG ya da boş (birleşik blok)  -> {"status","points","version","ply"}
  GET  /result?sid=..&max=N  oturumun bulutu (/cloud biçimi)   GET /result_preview?sid=..  önizleme (JPEG)
  POST /capture?sid=..&marker=mm&save=0|1  gövde: art arda JPEG'ler (X-Sizes), 2-8 sabit kameranın
                 eşzamanlı kareleri -> tek geçişte birleşir; sonuç /result ve /result_preview ile alınır
  marker=mm (process): >0 ise tek/çok sonucu ArUco kartla (DICT_4X4_50) mm'ye ve kart eksenlerine ölçeklenir.
  POST /measure?min_h=8&cell=2&cargo=0|1  gövde: /cloud biçiminde mm bulut
                 -> {"objects":[{id,L,W,H,x,y,area_mm2,desi}], "image": b64 JPEG (cargo=1: cm + desi etiketi)}
  GET  /  ve  /ui/...  tarayıcı arayüzü (web/ klasörü: 3 kamera -> koli desi)
  sid: blok örneği başına oturum. Canlı rekonstrüksiyon tek; aynı anda bir canlı blok kullanılmalı.
Durum JSON: keyframe, keyframes, processed, points, preview_version, busy, fps
"""
import argparse
import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from measure import draw_top_view, measure_objects
from oneshot import OneShot
from recon import Config, KeyframeGate, Recon, render_preview, write_ply
from session import Session

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8770)
ap.add_argument("--rerun", action="store_true", help="Rerun 3D penceresini de aç")
# .ply çıktıları: DESI3D_OUT ya da depo kökünde out/pointcloud
ap.add_argument("--out", default=os.environ.get("DESI3D_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "pointcloud"))
for k, v in vars(Config()).items():
    ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
args = ap.parse_args()
cfg = Config(**{k: getattr(args, k) for k in vars(Config())})

# tarayıcı arayüzü: GET / ve /ui/... -> web/ klasörü (ör. http://127.0.0.1:8770/)
WEB_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
WEB_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png",
             ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class State:
    def __init__(self):
        self.recon = Recon(cfg)
        self.oneshot = OneShot(self.recon)
        self.gate = KeyframeGate(cfg)
        self.gate_lock = threading.Lock()
        self.preview = cv2.imencode(".jpg", render_preview(None, None, None))[1].tobytes()
        self.version = 0
        self.busy = False
        self.fps, self.last_frame_t = 0.0, 0.0    # gelen kare hızı (üstel ortalama)
        self.rr = None
        if args.rerun:
            import sys
            os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]
            import rerun as rr
            rr.init("augelab_pointcloud", spawn=True)
            rr.log("world", rr.ViewCoordinates.RDF, static=True)
            self.rr = rr
        self.sessions = {}                        # blok örneği başına oturum (sid -> Session)
        self.sessions_lock = threading.Lock()

    def session(self, sid):
        with self.sessions_lock:
            if sid not in self.sessions:
                self.sessions[sid] = Session(self, args.out)
            return self.sessions[sid]

    def status(self, keyframe=False):
        r = self.recon
        return {"keyframe": keyframe, "keyframes": len(r.kf), "processed": r.done,
                "points": r.n_points, "preview_version": self.version, "busy": self.busy,
                "fps": round(self.fps, 1)}

    def tick(self):
        now = time.time()
        dt = now - self.last_frame_t
        if 0 < dt < 2:
            self.fps = 0.9 * self.fps + 0.1 / dt
        self.last_frame_t = now

    # --- canlı mod işlemleri (/frame, /reset, /save ve oturum ortak kullanır) ---
    def live_frame(self, bgr):
        with self.gate_lock:
            self.tick()
            is_kf = self.recon.accepting() and self.gate(bgr)
        if is_kf:
            self.recon.add(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        return self.status(is_kf)

    def live_reset(self):
        self.recon.reset()
        with self.gate_lock:
            self.gate.reset()
        # sürüm artınca Studio bloğu boş önizleme/bulutu çeker; eski görüntü kalmaz
        self.preview = cv2.imencode(".jpg", render_preview(None, None, None))[1].tobytes()
        self.version += 1
        if self.rr:
            self.rr.log("world/cloud", self.rr.Clear(recursive=True))

    def live_save(self):
        os.makedirs(args.out, exist_ok=True)
        path = os.path.abspath(os.path.join(args.out, time.strftime("augelab_%Y%m%d_%H%M%S.ply")))
        pts = self.recon.save(path)
        return (path if pts else ""), pts

    def worker(self):
        while True:
            if not self.recon.ready():
                time.sleep(0.02)
                continue
            self.busy = True
            try:
                res = self.recon.step()
                if res is not None:
                    P, C, pose = self.recon.snapshot(max_points=1_000_000)
                    img = render_preview(P, C, pose)
                    self.preview = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()
                    self.version += 1
                    if self.rr:
                        self.log_rerun(*res)
            except Exception as e:                # servis ayakta kalsın; aynı hatayı döngüde basma
                print("adım hatası:", repr(e))
                time.sleep(2)
            finally:
                self.busy = False

    def log_rerun(self, P, C):
        rr, r = self.rr, self.recon
        rr.log(f"world/cloud/{self.version:04d}", rr.Points3D(P, colors=C, radii=0.003))
        rr.log("world/trajectory", rr.LineStrips3D([np.array([p[:3, 3] for p in r.poses])],
                                                   colors=[[255, 200, 0]]))
        last = r.poses[-1]
        rr.log("world/camera", rr.Transform3D(translation=last[:3, 3], mat3x3=last[:3, :3]))
        rr.log("world/camera", rr.Pinhole(focal_length=0.9 * r.size[0], width=r.size[0],
                                          height=r.size[1], image_plane_distance=0.1))
        rr.log("world/camera/image", rr.Image(r.kf[-1]))


S: State


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                    # her kare için log basma
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cloud(self, P, C, headers=None):
        n = 0 if P is None else len(P)
        rec = np.empty(n, dtype=[("p", "<f4", 3), ("c", "u1", 3)])
        if n:
            rec["p"], rec["c"] = P * np.array([1, -1, 1], "<f4"), C   # OpenCV y aşağı -> y yukarı
        body = rec.tobytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("X-Points", str(n))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _oneshot(self, kind, images):
        """Tek seferlik rekonstrüksiyon; tam bulutu isteğe bağlı kaydeder, seyreltilmişini döner."""
        q = parse_qs(urlparse(self.path).query)
        rgbs = [cv2.cvtColor(im, cv2.COLOR_BGR2RGB) for im in images]
        t = time.time()
        P, C, _ = S.oneshot.single(rgbs[0]) if kind == "single" else S.oneshot.multi(rgbs)
        ms = int(1000 * (time.time() - t))
        ply = ""
        if q.get("save", ["0"])[0] == "1" and len(P):
            os.makedirs(args.out, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            ply = os.path.abspath(os.path.join(args.out, f"{kind}_{stamp}.ply"))
            write_ply(ply, P, C)
        total, cap = len(P), int(q.get("max", ["200000"])[0])
        if total > cap:
            keep = np.random.default_rng(0).choice(total, cap, replace=False)
            P, C = P[keep], C[keep]
        print(f"{kind}: {len(images)} görüntü, {ms} ms, {total} nokta")
        self._cloud(P, C, {"X-Total": total, "X-PLY": ply, "X-Ms": ms})

    def _web(self, route):
        rel = "index.html" if route in ("/", "/ui", "/ui/") else route[len("/ui/"):]
        path = os.path.realpath(os.path.join(WEB_DIR, rel))
        if not path.startswith(WEB_DIR + os.sep) or not os.path.isfile(path):
            return self._json({"error": "bulunamadı"}, 404)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", WEB_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/" or route == "/ui" or route.startswith("/ui/"):
            return self._web(route)
        if self.path == "/status":
            return self._json(S.status())
        if self.path.startswith("/cloud"):
            q = parse_qs(urlparse(self.path).query)
            P, C, _ = S.recon.snapshot(max_points=int(q.get("max", ["200000"])[0]))
            return self._cloud(P, C)
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if self.path.startswith("/result_preview"):
            body = S.session(q.get("sid", "")).result_preview() or b""
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path.startswith("/result"):
            return self._cloud(*S.session(q.get("sid", "")).result_cloud(int(q.get("max", "200000"))))
        if self.path == "/preview":
            body = S.preview
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("X-Preview-Version", str(S.version))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self._json({"error": "bulunamadı"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n) if n else b""
        if self.path == "/frame":
            bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                return self._json({"error": "JPEG çözülemedi"}, 400)
            return self._json(S.live_frame(bgr))
        if self.path == "/reset":
            S.live_reset()
            return self._json(S.status())
        if self.path == "/save":
            path, pts = S.live_save()
            return self._json({"path": path, "saved_points": pts, **S.status()})
        route = urlparse(self.path).path
        if route == "/process":
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
            try:
                return self._json(S.session(q.get("sid", "")).process(
                    q.get("mode", "multi"), bgr, q.get("tc") == "1", q.get("trig") == "1",
                    q.get("reset") == "1", int(q.get("count", "5")), q.get("folder", ""), q.get("save") == "1",
                    float(q.get("marker", "0") or 0)))
            except Exception as e:                # bloğa okunur hata dönsün, servis ayakta kalsın
                return self._json({"error": repr(e)[:200]}, 500)
        if route == "/capture":
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            sizes = [int(s) for s in self.headers.get("X-Sizes", "").split(",") if s]
            if sum(sizes) != len(data):
                return self._json({"error": "X-Sizes gövde boyutuyla uyuşmuyor"}, 400)
            frames, o = [], 0
            for s in sizes:
                im = cv2.imdecode(np.frombuffer(data[o:o + s], np.uint8), cv2.IMREAD_COLOR)
                o += s
                if im is not None:
                    frames.append(im)
            try:
                return self._json(S.session(q.get("sid", "")).capture(
                    frames, q.get("save") == "1", float(q.get("marker", "0") or 0)))
            except Exception as e:                # bloğa okunur hata dönsün, servis ayakta kalsın
                return self._json({"error": repr(e)[:200]}, 500)
        if route == "/measure":
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            rec = np.frombuffer(data, dtype=[("p", "<f4", 3), ("c", "u1", 3)])
            objs, grid = measure_objects(rec["p"].astype(np.float64), float(q.get("min_h", "8")),
                                         float(q.get("cell", "2")))
            img = cv2.imencode(".jpg", draw_top_view(objs, grid, cargo=q.get("cargo") == "1"))[1].tobytes()
            for o in objs:
                o.pop("rect", None)
            return self._json({"objects": objs, "image": base64.b64encode(img).decode()})
        if route in ("/single", "/multi"):
            sizes = [int(s) for s in self.headers.get("X-Sizes", str(len(data))).split(",") if s]
            if sum(sizes) != len(data):
                return self._json({"error": "X-Sizes gövde boyutuyla uyuşmuyor"}, 400)
            images, o = [], 0
            for s in sizes:
                im = cv2.imdecode(np.frombuffer(data[o:o + s], np.uint8), cv2.IMREAD_COLOR)
                o += s
                if im is None:
                    return self._json({"error": f"{len(images) + 1}. JPEG çözülemedi"}, 400)
                images.append(im)
            try:
                return self._oneshot(route[1:], images)
            except ValueError as e:               # yanlış görüntü sayısı vb.
                return self._json({"error": str(e)}, 400)
        self._json({"error": "bulunamadı"}, 404)


if __name__ == "__main__":
    S = State()
    threading.Thread(target=S.worker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"hazır: http://{args.host}:{args.port}")
    srv.serve_forever()
