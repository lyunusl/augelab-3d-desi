"""Birleşik "3D Nokta Bulutu" bloğunun mod mantığı (blok ince istemci, karar burada).

Modlar:
  live   — kareler keyframe seçiciye gider, bulut büyür; trigger .ply kaydeder.
  single — tek kareden MoGe-2; trigger bağlıysa onunla, değilse görüntü değişince.
  multi  — `count` farklı kare topla, dolunca Pi3X ile bir kez birleştir; trigger bağlıysa
           onunla ekle; `folder` doluysa klasörü oku (içerik değişince yeniden).
"""
import glob
import os
import threading
import time

import cv2
import numpy as np

from measure import crop_to_objects, scale_to_marker, world_to_transport
from recon import write_ply

MAX_VIEWS = 8
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
DEDUPE_DIFF = 12.0     # 32x24 gri küçük resimde ortalama fark; altı "aynı açı" sayılır


def thumb(bgr):
    return cv2.cvtColor(cv2.resize(bgr, (32, 24), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.int16)


def differs(t, others, limit):
    return all(o.shape == t.shape and float(np.abs(o - t).mean()) >= limit for o in others)


def contact_sheet(frames, slots):
    """Toplanan kareler; boş yuvalar hedef sayıyı gösterir (BGR)."""
    tw, th, cols = 200, 150, 4
    rows = max(1, (slots + cols - 1) // cols)
    img = np.full((rows * th, cols * tw, 3), 24, np.uint8)
    for k in range(slots):
        r, c = divmod(k, cols)
        if k < len(frames):
            img[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = cv2.resize(frames[k], (tw, th), interpolation=cv2.INTER_AREA)
        else:
            cv2.rectangle(img, (c * tw + 4, r * th + 4), ((c + 1) * tw - 5, (r + 1) * th - 5), (90, 90, 90), 1)
        cv2.putText(img, str(k + 1), (c * tw + 8, r * th + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    return img


def read_folder(folder):
    files = sorted(p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(IMAGE_EXT))[:MAX_VIEWS]
    sig = tuple((p, os.path.getmtime(p)) for p in files)
    return files, sig


class Session:
    def __init__(self, state, out_dir):
        self.S = state                     # server.State: recon, oneshot, canlı işlemler
        self.out = out_dir
        self.lock = threading.Lock()
        self.mode = None
        self.version = 0                   # tek/çok sonucu her değiştiğinde artar
        self._clear()

    def _clear(self):
        self.frames, self.thumbs = [], []
        self.cloud = None                  # (P, C) OpenCV eksenli
        self.total, self.ply = 0, ""
        self.status, self.preview = "Bekleniyor", None
        self.done, self.sig = False, None
        self.folder_sig, self.scan_t = None, 0.0
        self.version += 1

    # --- sonuçlar (server /result, /result_preview) ---
    def result_cloud(self, max_points):
        if self.mode == "live":
            P, C, _ = self.S.recon.snapshot(max_points=max_points)
            return P, C
        if self.cloud is None:
            return None, None
        P, C = self.cloud
        if len(P) > max_points:
            keep = np.random.default_rng(0).choice(len(P), max_points, replace=False)
            P, C = P[keep], C[keep]
        return P, C

    def result_preview(self):
        if self.mode == "live":
            return self.S.preview
        return None if self.preview is None else cv2.imencode(".jpg", self.preview)[1].tobytes()

    def _reply(self):
        live = self.mode == "live"
        return {"status": self.status, "points": self.S.recon.n_points if live else self.total,
                "version": self.S.version if live else self.version, "ply": self.ply}

    # --- tek giriş noktası ---
    def process(self, mode, bgr, trig_connected, trig, reset, count, folder, save, marker_mm=0.0):
        with self.lock:
            self.marker_mm = marker_mm         # >0: tek/çok sonucu karta göre mm'ye ölçekle
            if mode != self.mode:          # mod değişince baştan başla
                self.mode = mode
                self._clear()
                if mode == "live":
                    self.S.live_reset()
            if mode == "live":
                self._live(bgr, trig, reset)
            elif mode == "single":
                self._single(bgr, trig_connected, trig, reset, save)
            else:
                self._multi(bgr, trig_connected, trig, reset, count, folder, save)
            return self._reply()

    def capture(self, frames, save, marker_mm):
        """Sabit kameraların eşzamanlı kareleri: toplama yok, gelen kareler tek geçişte birleşir."""
        with self.lock:
            if self.mode != "capture":
                self.mode = "capture"
                self._clear()
            self.marker_mm = marker_mm
            if not 2 <= len(frames) <= MAX_VIEWS:
                self.status = f"2-{MAX_VIEWS} kamera görüntüsü gerekli ({len(frames)} geldi)"
                return self._reply()
            self.frames = frames
            self.preview = contact_sheet(frames, len(frames))
            self._run("multi", frames, save)
            return self._reply()

    def _live(self, bgr, trig, reset):
        if reset:
            self.S.live_reset()
        if bgr is not None:
            s = self.S.live_frame(bgr)
            self.status = f"{s['processed']}/{s['keyframes']} keyframe" + (" · GPU çalışıyor" if s["busy"] else "") \
                          + " · Trigger: .ply kaydet"
        if trig:
            self.ply, pts = self.S.live_save()
            self.status = f"Kaydedildi: {pts} nokta" if self.ply else "Kaydedilecek nokta yok"

    def _single(self, bgr, trig_connected, trig, reset, save):
        if reset:
            self._clear()
        if bgr is None:
            self.status = "Görüntü bekleniyor"
            return
        if trig_connected:
            run = trig
            if not run and self.cloud is None:
                self.status = "Trigger bekleniyor"
        else:
            t = thumb(bgr)
            run = self.sig is None or differs(t, [self.sig], 2.0)
            self.sig = t
        if run:
            self._run("single", [bgr], save)

    def _multi(self, bgr, trig_connected, trig, reset, count, folder, save):
        count = max(2, min(MAX_VIEWS, count))
        if reset:
            self._clear()
        if folder:
            if time.time() - self.scan_t > 1.0:          # klasörü saniyede en fazla bir kez tara
                self.scan_t = time.time()
                files, sig = read_folder(folder)
                if sig != self.folder_sig:
                    self.folder_sig = sig
                    imgs = [cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) for p in files]
                    self.frames = [im for im in imgs if im is not None]
                    self.preview = contact_sheet(self.frames, max(len(self.frames), 1))
                    if len(self.frames) >= 2:
                        self._run("multi", self.frames, save)
                    else:
                        self.status = f"Klasörde en az 2 görüntü olmalı ({len(self.frames)} var)"
            return
        if not self.done and bgr is not None:
            add = trig if trig_connected else differs(thumb(bgr), self.thumbs, DEDUPE_DIFF)
            if add:
                self.frames.append(bgr)
                self.thumbs.append(thumb(bgr))
                self.done = len(self.frames) >= count
        self.preview = contact_sheet(self.frames, count)
        if self.done and self.cloud is None:
            self._run("multi", self.frames, save)
            self.status += " · yeniden için Reset"
        elif not self.done:
            self.status = f"{len(self.frames)}/{count} kare · " + ("Trigger ile ekle" if trig_connected else "otomatik")

    def _run(self, kind, frames, save):
        rgbs = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames]
        t = time.time()
        P, C, maps = self.S.oneshot.single(rgbs[0]) if kind == "single" else self.S.oneshot.multi(rgbs)
        ms = int(1000 * (time.time() - t))
        scale_note = ""
        if self.marker_mm > 0:
            fit = scale_to_marker(frames, maps, self.marker_mm)
            if fit is None:
                scale_note = " · kart bulunamadı, ölçek göreli"
            else:
                s, R, tr, info = fit
                Pw = s * P @ R.T + tr                            # kart dünyası, mm, Z yukarı
                keep = crop_to_objects(Pw)                       # uzaktaki masa/zemin görünümü boğmasın
                P, C = world_to_transport(Pw[keep]), C[keep]     # mm, kart düzlemi y = 0
                scale_note = f" · mm (kart {info['frames']} karede, köşe hatası {info['rms_mm']} mm)"
        self.cloud, self.total = (P, C), len(P)
        if save and len(P):
            os.makedirs(self.out, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            self.ply = os.path.abspath(os.path.join(self.out, f"{kind}_{stamp}.ply"))
            write_ply(self.ply, P, C)
        self.version += 1
        self.status = f"{len(frames)} kare · {ms} ms · {self.total} nokta" + scale_note
        print(f"oturum {kind}: {len(frames)} kare, {ms} ms, {self.total} nokta{scale_note}")
