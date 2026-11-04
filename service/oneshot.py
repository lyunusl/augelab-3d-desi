"""Tek seferlik rekonstrüksiyon: tek görüntü (MoGe-2) ve birkaç açı (Pi3X, tek geçiş).

Dönen noktalar OpenCV eksenlerinde (x sağ, y aşağı, z ileri; ilk kamera), RGB uint8 renkli.
Üçüncü dönüş değeri kare başına (nokta haritası HxWx3, maske HxW): ArUco ölçeklemede
görüntüdeki köşe piksellerinin 3D karşılığını bulmak için.
"""
import threading

import cv2
import numpy as np
import torch

from pi3.utils.geometry import depth_normal_edge
from recon import target_size

MAX_VIEWS = 8


class OneShot:
    def __init__(self, recon, multi_pixels=150_000, conf=0.15):
        self.recon = recon                        # Pi3X modelini ve GPU kilidini paylaşır
        self.multi_pixels, self.conf = multi_pixels, conf
        self._moge = None
        self._moge_lock = threading.Lock()

    def _moge_model(self):
        with self._moge_lock:                     # ilk istekte yükle; kullanılmazsa VRAM harcamaz
            if self._moge is None:
                from moge.model.v2 import MoGeModel
                print("MoGe-2 yükleniyor...")
                self._moge = MoGeModel.from_pretrained("Ruicheng/moge-2-vitl-normal").to(self.recon.dev).eval()
            return self._moge

    @torch.no_grad()
    def single(self, rgb):
        model = self._moge_model()
        with self.recon.gpu_lock:
            x = torch.from_numpy(rgb).to(self.recon.dev).permute(2, 0, 1).float() / 255
            out = model.infer(x)
            P = out["points"].cpu().numpy()
            mask = out["mask"].cpu().numpy().astype(bool) & np.isfinite(P).all(-1)
        torch.cuda.empty_cache()
        return P[mask].astype(np.float32), rgb[mask], [(P, mask)]

    @torch.no_grad()
    def multi(self, rgbs):
        if not 2 <= len(rgbs) <= MAX_VIEWS:
            raise ValueError(f"2-{MAX_VIEWS} görüntü gerekli, {len(rgbs)} geldi")
        h, w = rgbs[0].shape[:2]
        size = target_size(w, h, self.multi_pixels)
        cols = np.stack([cv2.resize(im, size, interpolation=cv2.INTER_AREA) for im in rgbs])
        with self.recon.gpu_lock:
            x = torch.from_numpy(cols).to(self.recon.dev).permute(0, 3, 1, 2).float()[None] / 255
            with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                pred = self.recon.model(x, with_prior=False)
            conf = torch.sigmoid(pred["conf"].float())[..., 0]
            conf[depth_normal_edge(pred["local_points"].float(), rtol=0.03, mask=conf > self.conf)] = 0
            mask = (conf[0] > self.conf).cpu().numpy()
            maps = pred["points"].float()[0].cpu().numpy()
            del pred, x
        torch.cuda.empty_cache()
        return maps[mask].astype(np.float32), cols[mask], [(maps[i], mask[i]) for i in range(len(maps))]
