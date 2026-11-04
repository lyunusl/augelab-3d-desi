"""Artımlı çok-kareli 3D rekonstrüksiyon (Pi3X) — webcam scripti ve servis ortak kullanır.

Her NEW yeni keyframe, son OVERLAP keyframe ile birlikte modele verilir; ortak
karelerin noktaları üzerinden Sim(3) hizalanıp global buluta eklenir.
"""
import math
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace

import cv2
import numpy as np
import torch
from torch.nn.attention import SDPBackend

import pi3.models.layers.attention as pi3_attn
from pi3.models.pi3x import Pi3X
from pi3.pipe.pi3x_vo import Pi3XVO
from pi3.utils.geometry import depth_normal_edge

# Windows PyTorch'ta flash attention yok; Pi3 bf16'da onu zorunlu kılıyor.
pi3_attn.SDPBackend = SimpleNamespace(
    FLASH_ATTENTION=[SDPBackend.EFFICIENT_ATTENTION, SDPBackend.CUDNN_ATTENTION, SDPBackend.MATH],
    EFFICIENT_ATTENTION=SDPBackend.EFFICIENT_ATTENTION,
    MATH=SDPBackend.MATH,
)


@dataclass
class Config:
    # 3+4 kare/adım: ~0.5 s, ~8 keyframe/s (5+6: ~0.7 s, ~9/s ama güncelleme seyrek)
    new: int = 4            # her adımda eklenecek yeni keyframe
    overlap: int = 3        # hizalama için ortak keyframe
    first: int = 4          # ilk rekonstrüksiyon için keyframe
    pixels: int = 92_000    # model giriş çözünürlüğü; ~120k üstü 12 GB VRAM'i taşırıyor (60k: ~11/s)
    conf: float = 0.15      # güven eşiği
    stride: int = 2         # her N pikselden bir nokta
    kf_gap: float = 0.15    # keyframe'ler arası min saniye
    motion: float = 4.0     # keyframe için min ortalama piksel farkı (160x120 gri)
    sharp: float = 20.0     # keyframe için min Laplacian varyansı


def target_size(w, h, limit):
    s = math.sqrt(limit / (w * h))
    k, m = round(w * s / 14), round(h * s / 14)
    while (k * 14) * (m * 14) > limit:
        if k / m > w / h:
            k -= 1
        else:
            m -= 1
    return k * 14, m * 14


class KeyframeGate:
    """Yeterince hareket etmiş ve net kareleri seçer."""

    def __init__(self, cfg, use_clock=True):
        self.cfg, self.use_clock = cfg, use_clock
        self.reset()

    def reset(self):
        self.last_t, self.last_small = 0.0, None
        self.motion, self.sharp = 0.0, 0.0

    def __call__(self, bgr):
        small = cv2.cvtColor(cv2.resize(bgr, (160, 120)), cv2.COLOR_BGR2GRAY).astype(np.int16)
        self.sharp = float(cv2.Laplacian(small.astype(np.uint8), cv2.CV_64F).var())
        self.motion = 255.0 if self.last_small is None else float(np.abs(small - self.last_small).mean())
        now = time.time()
        ok = (not self.use_clock or now - self.last_t >= self.cfg.kf_gap) \
            and self.motion >= self.cfg.motion and self.sharp > self.cfg.sharp
        if ok:
            self.last_t, self.last_small = now, small
        return ok


class Recon:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dev = torch.device("cuda")
        print("Pi3X yükleniyor...")
        self.model = Pi3X.from_pretrained("yyfz233/Pi3X").to(self.dev).eval()
        self.vo = Pi3XVO(self.model)              # yalnızca Sim(3) yardımcıları için
        self._warmup()
        self.lock = threading.Lock()              # kısa süreli; model çalışırken tutulmaz
        self.gpu_lock = threading.Lock()          # canlı adım ile tek seferlik istekler sırayla
        self.gen = 0                              # reset sayacı; eski adımların sonucunu atar
        self.reset()

    @torch.no_grad()
    def _warmup(self):
        """İlk adımdaki 3-5 s'lik CUDA ısınmasını açılışa taşır."""
        w, h = target_size(640, 480, self.cfg.pixels)
        x = torch.rand(1, self.cfg.overlap + self.cfg.new, 3, h, w, device=self.dev)
        with torch.amp.autocast("cuda", dtype=torch.bfloat16):
            self.model(x, with_prior=False)
        torch.cuda.synchronize()
        torch.cuda.empty_cache()

    def reset(self):
        with self.lock:
            self.gen += 1
            self.size = None
            self.kf = []                          # uint8 (H,W,3) RGB; GPU'ya sadece adımda çıkar
            self.glob_pts, self.glob_mask = [], []
            self.poses = []                       # keyframe başına 4x4 cam2world (OpenCV)
            self.cloud = []                       # (P, C) parçaları
            self.done = 0                         # hizalanmış keyframe sayısı
            self.n_points = 0

    def add(self, rgb):
        with self.lock:
            if self.size is None:
                self.size = target_size(rgb.shape[1], rgb.shape[0], self.cfg.pixels)
            # GPU kopyası burada yapılmaz: model çalışırken CUDA kuyruğunda bekler
            self.kf.append(cv2.resize(rgb, self.size, interpolation=cv2.INTER_AREA))

    def ready(self, final=False):
        pending = len(self.kf) - self.done
        if final:                                 # kapanışta elde kalanları da işle
            return pending >= (2 if self.done == 0 else 1)
        return pending >= (self.cfg.first if self.done == 0 else self.cfg.new)

    def accepting(self):
        """GPU geride kalınca yeni keyframe alma; aksi halde adımlar büyüyüp birikir."""
        return len(self.kf) - self.done < 3 * max(self.cfg.first, self.cfg.new)

    @torch.no_grad()
    def step(self):
        """Bir adım işler; (P, C) yeni noktaları ya da reset olduysa None döner."""
        cfg = self.cfg
        with self.lock:
            gen, done = self.gen, self.done
            start = 0 if done == 0 else done - cfg.overlap
            stop = min(len(self.kf), done + (cfg.first if done == 0 else cfg.new))
            idx = list(range(start, stop))        # sabit boyutlu adım; fazlası sonraki adıma
            cols = np.stack([self.kf[i] for i in idx])
            if done > 0:
                tgt = torch.stack(self.glob_pts[start:done])[None]
                tgt_m = torch.stack(self.glob_mask[start:done])[None]

        t0 = time.time()
        with self.gpu_lock:
            x = torch.from_numpy(cols).to(self.dev).permute(0, 3, 1, 2).float()[None] / 255
            with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                pred = self.model(x, with_prior=False)
        pts = pred["points"].float()
        poses = pred["camera_poses"].float()
        conf = torch.sigmoid(pred["conf"].float())[..., 0]
        conf[depth_normal_edge(pred["local_points"].float(), rtol=0.03, mask=conf > cfg.conf)] = 0
        mask = conf > cfg.conf

        first_new = 0
        if done > 0:
            ov = cfg.overlap
            T = self.vo._compute_sim3_umeyama_masked(pts[:, :ov], tgt, mask[:, :ov], tgt_m)
            pts = self.vo._apply_sim3_to_points(pts, T)
            poses = self.vo._apply_sim3_to_poses(poses, T)
            first_new = ov

        s = cfg.stride
        m_new = mask[0, first_new:, ::s, ::s]
        P = pts[0, first_new:, ::s, ::s][m_new].cpu().numpy()
        C = cols[first_new:, ::s, ::s][m_new.cpu().numpy()]

        with self.lock:
            if gen != self.gen:
                return None
            for j in range(first_new, len(idx)):
                self.glob_pts.append(pts[0, j])
                self.glob_mask.append(mask[0, j])
                self.poses.append(poses[0, j].cpu().numpy())
            self.cloud.append((P, C))
            self.n_points += len(P)
            self.done = idx[-1] + 1
        del pred, x
        torch.cuda.empty_cache()
        print(f"adım {len(self.cloud) - 1}: {len(idx)} kare, {time.time() - t0:.2f}s, +{len(P)} nokta")
        return P, C

    def snapshot(self, max_points=None):
        with self.lock:
            parts = list(self.cloud)
            pose = self.poses[-1].copy() if self.poses else None
        if not parts:
            return None, None, pose
        P = np.concatenate([p for p, _ in parts])
        C = np.concatenate([c for _, c in parts])
        if max_points and len(P) > max_points:
            keep = np.random.default_rng(0).choice(len(P), max_points, replace=False)
            P, C = P[keep], C[keep]
        return P, C, pose

    def save(self, path):
        P, C, _ = self.snapshot()
        return 0 if P is None else write_ply(path, P, C)


def write_ply(path, P, C):
    """OpenCV eksenli bulutu Blender eksenleriyle (Y yukarı, Z kameraya) .ply yazar."""
    P = P.astype("<f4") * np.array([1, -1, -1], "<f4")
    rec = np.empty(len(P), dtype=[("p", "<f4", 3), ("c", "u1", 3)])
    rec["p"], rec["c"] = P, C
    with open(path, "wb") as f:
        f.write((f"ply\nformat binary_little_endian 1.0\nelement vertex {len(P)}\n"
                 "property float x\nproperty float y\nproperty float z\n"
                 "property uchar red\nproperty uchar green\nproperty uchar blue\n"
                 "end_header\n").encode())
        f.write(rec.tobytes())
    return len(P)


def render_preview(P, C, pose, w=640, h=480):
    """Son kamera pozunun biraz arkasından ve yukarısından bulutu çizer (RGB)."""
    img = np.full((h, w, 3), 18, np.uint8)
    if P is None or pose is None:
        return img
    R, c = pose[:3, :3], pose[:3, 3]
    ext = float(np.linalg.norm(np.percentile(P, 95, 0) - np.percentile(P, 5, 0)))
    eye = c - R[:, 2] * 0.45 * ext - R[:, 1] * 0.2 * ext   # geri ve yukarı (OpenCV: -y yukarı)
    Q = (P - eye) @ R                                       # world -> kamera
    ok = Q[:, 2] > 1e-3
    Q, C = Q[ok], C[ok]
    f = 0.8 * w
    u = (f * Q[:, 0] / Q[:, 2] + w / 2).astype(np.int32)
    v = (f * Q[:, 1] / Q[:, 2] + h / 2).astype(np.int32)
    ok = (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1)
    u, v, z, C = u[ok], v[ok], Q[ok, 2], C[ok]
    order = np.argsort(-z)                                  # uzaktan yakına; yakın üstte kalır
    u, v, C = u[order], v[order], C[order]
    u, v = np.clip(u, 1, w - 2), np.clip(v, 1, h - 2)
    for du in (-1, 0, 1):                                   # 3x3 splat
        for dv in (-1, 0, 1):
            img[v + dv, u + du] = C
    return img
