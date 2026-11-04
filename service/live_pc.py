"""Studio olmadan: webcam'i gezdirirken canlı 3D point cloud (Pi3X + Rerun).

Kamera penceresi:  q = kaydet + çık   s = .ply kaydet   r = sıfırla
3D görünüm Rerun penceresinde canlı büyür. --video ile dosyadan test edilir.
"""
import argparse
import os
import sys
import threading
import time

import cv2
import numpy as np
import rerun as rr

from recon import Config, KeyframeGate, Recon

ap = argparse.ArgumentParser()
ap.add_argument("--cam", type=int, default=0)
ap.add_argument("--video", default=None, help="webcam yerine video dosyası (test için)")
# .ply çıktıları: DESI3D_OUT ya da depo kökünde out/pointcloud
ap.add_argument("--out", default=os.environ.get("DESI3D_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "pointcloud"))
for k, v in vars(Config()).items():
    ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
args = ap.parse_args()
cfg = Config(**{k: getattr(args, k) for k in vars(Config())})


def log_step(rec, n, P, C):
    rr.log(f"world/cloud/{n:04d}", rr.Points3D(P, colors=C, radii=0.003))
    rr.log("world/trajectory", rr.LineStrips3D([np.array([p[:3, 3] for p in rec.poses])],
                                               colors=[[255, 200, 0]]))
    last = rec.poses[-1]
    rr.log("world/camera", rr.Transform3D(translation=last[:3, 3], mat3x3=last[:3, :3]))
    rr.log("world/camera", rr.Pinhole(focal_length=0.9 * rec.size[0], width=rec.size[0],
                                      height=rec.size[1], image_plane_distance=0.1))
    rr.log("world/camera/image", rr.Image(rec.kf[-1]))


def worker(rec, stop):
    n = 0
    while not stop.is_set():
        if not rec.ready():
            time.sleep(0.02)
            continue
        res = rec.step()
        if res is not None:
            log_step(rec, n, *res)
            n += 1


def main():
    os.makedirs(args.out, exist_ok=True)
    cap = cv2.VideoCapture(args.video) if args.video else cv2.VideoCapture(args.cam, cv2.CAP_DSHOW)
    if not args.video:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        raise SystemExit("Kamera açılamadı")

    # venv aktive edilmeden çalışınca rerun.exe PATH'te olmuyor
    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]
    rr.init("canli_pointcloud", spawn=True)
    rr.log("world", rr.ViewCoordinates.RDF, static=True)

    rec, gate, stop = Recon(cfg), KeyframeGate(cfg, use_clock=not args.video), threading.Event()
    th = threading.Thread(target=worker, args=(rec, stop), daemon=True)
    th.start()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    while True:
        ok, frame = cap.read()
        if not ok:
            if args.video:
                break
            continue
        is_kf = rec.accepting() and gate(frame)
        if is_kf:
            rec.add(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        h, w = frame.shape[:2]
        hud = frame.copy()
        txt = f"keyframe {len(rec.kf)}  islenen {rec.done}  hareket {gate.motion:4.1f}  netlik {gate.sharp:5.0f}"
        cv2.putText(hud, txt, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(hud, "q: kaydet+cik   s: kaydet   r: sifirla", (10, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        if is_kf:
            cv2.rectangle(hud, (0, 0), (w - 1, h - 1), (0, 255, 0), 6)
        cv2.imshow("kamera", hud)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            print(rec.save(os.path.join(args.out, f"live_{stamp}.ply")), "nokta kaydedildi")
        if key == ord("r"):
            rec.reset()
            gate.reset()
            rr.log("world/cloud", rr.Clear(recursive=True))
            stamp = time.strftime("%Y%m%d_%H%M%S")

    stop.set()
    th.join()                                     # iki adım aynı anda koşmasın
    while rec.ready(final=True):                  # elde kalan keyframe'leri de işle
        rec.step()
    path = os.path.abspath(os.path.join(args.out, f"live_{stamp}.ply"))
    print(rec.save(path), "nokta ->", path)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
