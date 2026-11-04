"""AugeLab bulutunun dikey (9:16) 360° dönüş videosu: ölçü kutuları ve cm/desi etiketleriyle.

render_orbit.py <3 kamera görüntüsü...> --out video.mp4 [--seconds 8]
Görüntüler servise /capture ile gider (kartla mm), bulut ve /measure sonucu çizilir.
"""
import argparse
import json
import math
import os
import subprocess
import tempfile
import urllib.request

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("images", nargs="+")
ap.add_argument("--out", required=True)
ap.add_argument("--seconds", type=float, default=8)
ap.add_argument("--fps", type=int, default=30)
ap.add_argument("--url", default="http://127.0.0.1:8770")
ap.add_argument("--points", type=int, default=900_000)
args = ap.parse_args()
W, H = 1080, 1920


def post(path, data, headers=None):
    req = urllib.request.Request(args.url + path, data=data, method="POST", headers=headers or {})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def prep(p):
    """Çok Kameralı 3D bloğuyla aynı hazırlık (1280 px, JPEG 92): etiketler Studio'dakiyle aynı çıksın."""
    f = cv2.imread(p)
    if f.shape[1] > 1280:
        f = cv2.resize(f, (1280, int(f.shape[0] * 1280 / f.shape[1])), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


bufs = [prep(p) for p in args.images]
print(json.loads(post("/capture?sid=orbit-video&marker=100", b"".join(bufs), {"X-Sizes": ",".join(str(len(b)) for b in bufs)}))["status"])
# ölçüm tam buluttan (Studio'daki 3D Ölçüm ile aynı sonuç), çizim seyreltilmiş buluttan
raw = urllib.request.urlopen(f"{args.url}/result?max=5000000&sid=orbit-video").read()
objs = json.loads(post("/measure?cargo=1", raw))["objects"]
rec = np.frombuffer(raw, dtype=[("p", "<f4", 3), ("c", "u1", 3)])
rec = rec[rec["p"][:, 1] > -8.0]                       # masanın altına sarkan uçan pikselleri at
if len(rec) > args.points:
    rec = rec[np.random.default_rng(0).choice(len(rec), args.points, replace=False)]
P, C = rec["p"].astype(np.float32) / 1000.0, rec["c"][:, ::-1].copy()     # m, BGR
print(len(P), "nokta,", len(objs), "nesne")

# ölçü kutuları (Studio ekseni: x, y yukarı, z; taban düzlemi (x, -z)). /measure yönü döndürmüyor:
# nesnenin üst dilim noktalarından yönü bul, ölçülen L/W ile kutuyu kur
hgt = P[:, 1] * 1000
for o in objs:
    sel = (np.hypot(P[:, 0] * 1000 - o["x"], -P[:, 2] * 1000 - o["y"]) < max(o["L"], o["W"]) * 0.75) & (hgt > 0.85 * o["H"])
    xy = np.stack([P[sel, 0] * 1000, -P[sel, 2] * 1000], 1).astype(np.float32)
    _, (rw, rl), ang = cv2.minAreaRect(xy)
    rw, rl = (o["L"], o["W"]) if rw >= rl else (o["W"], o["L"])
    base = cv2.boxPoints(((o["x"], o["y"]), (rw, rl), ang)) / 1000.0
    o["_corners"] = np.array([[bx, y, -by] for y in (0.0, o["H"] / 1000.0) for bx, by in base], np.float32)

EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
center = np.array([np.mean([o["_corners"][:, 0].mean() for o in objs]), 0.08,
                   np.mean([o["_corners"][:, 2].mean() for o in objs])], np.float32)
radius = 0.95 * max(np.ptp(np.concatenate([o["_corners"][:, [0, 2]] for o in objs]), 0)) + 0.25

bg = np.zeros((H, W, 3), np.uint8)
for yy in range(H):                                   # koyu lacivert dikey gradyan
    t = yy / H
    bg[yy] = (int(28 + 20 * t), int(16 + 10 * t), int(10 + 6 * t))
font = cv2.FONT_HERSHEY_SIMPLEX


def project(X, yaw, elev):
    eye = center + radius * np.array([math.cos(elev) * math.cos(yaw), math.sin(elev), math.cos(elev) * math.sin(yaw)])
    f = center - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    d = X - eye
    z = d @ f
    fl = 1.05 * W
    return W / 2 + fl * (d @ r) / z, H * 0.50 - fl * (d @ u) / z, z


tmp = tempfile.mkdtemp()
n = int(args.seconds * args.fps)
for i in range(n):
    yaw = 2 * math.pi * i / n
    elev = math.radians(32 + 6 * math.sin(2 * math.pi * i / n))
    u, v, z = project(P, yaw, elev)
    ok = (z > 0.05) & (u >= 1) & (u < W - 2) & (v >= 1) & (v < H - 2)
    order = np.argsort(-z[ok])
    ui, vi, col = u[ok][order].astype(np.int32), v[ok][order].astype(np.int32), C[ok][order]
    img = bg.copy()
    ui, vi = np.clip(ui, 1, W - 2), np.clip(vi, 1, H - 2)
    for du in (-1, 0, 1):                             # 3x3: seyrek yüzeyler dolu görünsün
        for dv in (-1, 0, 1):
            img[vi + dv, ui + du] = col
    for o in objs:                                    # ölçü kutusu + etiket
        cu, cv_, _ = project(o["_corners"], yaw, elev)
        for a, b in EDGES:
            cv2.line(img, (int(cu[a]), int(cv_[a])), (int(cu[b]), int(cv_[b])), (0, 230, 255), 3, cv2.LINE_AA)
        top = o["_corners"][4:].mean(0) + np.array([0, 0.04, 0], np.float32)
        tu, tv, _ = project(top[None], yaw, elev)
        lab = f"{o['L'] / 10:.0f} x {o['W'] / 10:.0f} x {o['H'] / 10:.0f} cm  {o['desi']:.1f} desi".replace(".", ",")
        (tw, th), _ = cv2.getTextSize(lab, font, 0.8, 2)
        x0, y0 = int(np.clip(tu[0] - tw / 2, 10, W - tw - 10)), int(np.clip(tv[0], th + 20, H - 20))
        cv2.rectangle(img, (x0 - 8, y0 - th - 10), (x0 + tw + 8, y0 + 10), (20, 20, 20), -1)
        cv2.rectangle(img, (x0 - 8, y0 - th - 10), (x0 + tw + 8, y0 + 10), (0, 230, 255), 2)
        cv2.putText(img, lab, (x0, y0), font, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(os.path.join(tmp, f"f{i:04d}.png"), img)
    if i % 30 == 0:
        print("kare", i, "/", n)

subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps), "-i", os.path.join(tmp, "f%04d.png"),
                "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", args.out], check=True)
print("->", args.out)
