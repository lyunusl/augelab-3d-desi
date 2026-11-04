"""ArUco kartla metrik ölçekleme ve masa üstü nesne ölçümü.

Eksenler (Studio'ya giden bulut): x sağ, y yukarı, z ileri. Kartla ölçeklenince birim mm,
kart düzlemi y = 0, orijin kartın sol alt köşesi. Ölçüm bu eksenlerle çalışır: yükseklik = y,
taban düzlemi = (x, -z).
"""
import cv2
import numpy as np

ARUCO = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))


def umeyama(src, dst):
    """dst ≈ s * R @ src + t; (s, R, t) döner."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    a, b = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean()
    return s, R, mu_d - s * R @ mu_s


def _sample(pmap, mask, u, v, r=2):
    """(u, v) pikselinin çevresindeki geçerli noktaların medyanı."""
    h, w = mask.shape
    x0, x1 = max(0, int(u) - r), min(w, int(u) + r + 1)
    y0, y1 = max(0, int(v) - r), min(h, int(v) + r + 1)
    win = pmap[y0:y1, x0:x1][mask[y0:y1, x0:x1]]
    return np.median(win, 0) if len(win) else None


def scale_to_marker(frames_bgr, maps, marker_mm):
    """Kare başına nokta haritalarından kart köşelerini bulur; OpenCV bulut -> kart dünyası (mm).

    Kart dünyası: X kart sağı, Y kart yukarısı, Z masadan yukarı. None ya da (s, R, t, bilgi) döner.
    """
    s = float(marker_mm)
    model = np.array([[0, s, 0], [s, s, 0], [s, 0, 0], [0, 0, 0]], float)   # TL, TR, BR, BL
    src, dst, used = [], [], 0
    for bgr, (pmap, mask) in zip(frames_bgr, maps):
        corners, ids, _ = ARUCO.detectMarkers(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
        if ids is None:
            continue
        c = corners[0].reshape(4, 2)
        fx, fy = mask.shape[1] / bgr.shape[1], mask.shape[0] / bgr.shape[0]
        pts = [_sample(pmap, mask, u * fx, v * fy) for u, v in c]
        if any(p is None for p in pts):
            continue
        src += pts
        dst += list(model)
        used += 1
    if used == 0:
        return None
    src, dst = np.array(src), np.array(dst)
    sc, R, t = umeyama(src, dst)
    rms = float(np.sqrt((((sc * src @ R.T + t) - dst) ** 2).sum(1).mean()))
    return sc, R, t, {"frames": used, "rms_mm": round(rms, 2)}


def crop_to_objects(Pw, min_h=8.0, pad=200.0):
    """Kart dünyasında (mm, Z yukarı) masa üstü nesnelerin kapladığı alan + pay: tutulacak noktalar maskesi.

    Masadan yükselen nokta yoksa hepsini tutar. Aykırı uzak noktalar alanı büyütmesin diye %1-99.
    """
    up = (Pw[:, 2] > min_h) & (Pw[:, 2] < 2000)
    if up.sum() < 100:
        return np.ones(len(Pw), bool)
    lo = np.percentile(Pw[up, :2], 1, 0) - pad
    hi = np.percentile(Pw[up, :2], 99, 0) + pad
    return ((Pw[:, :2] >= lo) & (Pw[:, :2] <= hi)).all(1) & (Pw[:, 2] < 2000)


def world_to_transport(Pw):
    """Kart dünyası (X, Y, Z yukarı) -> sunucunun OpenCV-benzeri saklama düzeni.

    /result y'yi çevirir; sonuç Studio'da (X, Z, -Y): y yukarı, sağ elli.
    """
    return np.stack([Pw[:, 0], -Pw[:, 2], -Pw[:, 1]], 1).astype(np.float32)


def measure_objects(P, min_h=8.0, cell=2.0, min_area=400.0, top_frac=0.85, trim=2.0):
    """Studio eksenli mm bulutundan masa üstü nesneleri: L, W, H (mm), merkez, açı."""
    h = P[:, 1]
    keep = (h > min_h) & (h < 2000)
    if keep.sum() < 50:
        return [], None
    X, Y, Hk = P[keep, 0], -P[keep, 2], h[keep]
    x0, y0 = X.min(), Y.min()
    gx, gy = ((X - x0) / cell).astype(int), ((Y - y0) / cell).astype(int)
    grid = (gy.max() + 1, gx.max() + 1)
    cnt = np.zeros(grid, np.int32)
    np.add.at(cnt, (gy, gx), 1)
    hmap = np.zeros(grid, np.float32)
    np.maximum.at(hmap, (gy, gx), Hk)
    # büyük nesnede üst yüzey hücre başına 1-2 noktaya düşüyor: tek noktalı hücreleri de say,
    # 1 cm'lik boşlukları kapat (yoksa sadece duvarlar kalıp nesne parçalanıyor), sonra kırıntıyı at
    occ = (cnt >= 1).astype(np.uint8)
    occ = cv2.morphologyEx(occ, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    occ = cv2.morphologyEx(occ, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab = cv2.connectedComponents(occ, connectivity=8)
    plab = lab[gy, gx]
    objs = []
    for k in range(1, n):
        cells = np.argwhere(lab == k)
        if len(cells) * cell * cell < min_area:
            continue
        sel = plab == k
        hk = Hk[sel]
        # taban ölçüsü üst dilimdeki noktalardan ve ana eksenlerde %2-98 kırpmayla: kenarlardaki
        # "uçan pikseller" ve masaya değen yerdeki taşmalar kutuyu 5-20 mm şişiriyordu
        top = hk >= top_frac * np.percentile(hk, 98)
        xy = np.stack([X[sel][top], Y[sel][top]], 1)
        if len(xy) < 20:
            xy = np.stack([X[sel], Y[sel]], 1)
        (cx0, cy0), _, ang = cv2.minAreaRect(xy.astype(np.float32))
        a = np.radians(ang)
        R = np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
        loc = (xy - [cx0, cy0]) @ R.T
        lo, hi = np.percentile(loc, trim, 0), np.percentile(loc, 100 - trim, 0)
        w, l = hi - lo
        cx, cy = (lo + hi) / 2 @ R + [cx0, cy0]
        objs.append({"L": round(float(max(w, l)), 1), "W": round(float(min(w, l)), 1),
                     "H": round(float(np.percentile(hk, 98)), 1), "x": round(float(cx), 1),
                     "y": round(float(cy), 1), "rect": [float(cx), float(cy), float(w), float(l), float(ang)],
                     "area_mm2": round(float(len(cells) * cell * cell))})
    # masadaki gölge/gürültü izleri ince ve yassı çıkıyor: eşiğin 2.5 katından alçakları at
    objs = [o for o in objs if o["H"] >= 2.5 * min_h]
    objs.sort(key=lambda o: -o["area_mm2"])
    for i, o in enumerate(objs):
        o["id"] = i + 1
        o["desi"] = round(o["L"] * o["W"] * o["H"] / 1000 / 3000, 1)   # cm³ / 3000
    return objs, (hmap, occ, lab, x0, y0, cell)


def label_of(o, cargo):
    if cargo:
        return f"{o['L'] / 10:.0f} x {o['W'] / 10:.0f} x {o['H'] / 10:.0f} cm  {o['desi']:.1f} desi".replace(".", ",")
    return f"{o['id']}: {o['L']:.0f} x {o['W']:.0f} x {o['H']:.0f} mm"


def draw_top_view(objs, grid, size=(800, 600), cargo=False):
    """Üstten yükseklik haritası + nesne kutuları ve L×W×H etiketleri (BGR)."""
    W, H = size
    img = np.full((H, W, 3), 24, np.uint8)
    if grid is None:
        cv2.putText(img, "Masa ustunde nesne yok", (20, H // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)
        return img
    hmap, occ, lab, x0, y0, cell = grid
    if objs:
        # uzaktaki gürültü haritayı büyütüp nesneleri küçültmesin: nesnelerin çevresine kırp
        pts = np.array([p for o in objs for p in cv2.boxPoints(((o["rect"][0], o["rect"][1]),
                                                                  (o["rect"][2], o["rect"][3]), o["rect"][4]))])
        pad = 80.0
        c0 = max(0, int((pts[:, 0].min() - pad - x0) / cell))
        c1 = min(hmap.shape[1], int((pts[:, 0].max() + pad - x0) / cell) + 1)
        r0 = max(0, int((pts[:, 1].min() - pad - y0) / cell))
        r1 = min(hmap.shape[0], int((pts[:, 1].max() + pad - y0) / cell) + 1)
        hmap, occ, lab = hmap[r0:r1, c0:c1], occ[r0:r1, c0:c1], lab[r0:r1, c0:c1]
        x0, y0 = x0 + c0 * cell, y0 + r0 * cell
    gh, gw = hmap.shape
    k = min((W - 40) / gw, (H - 40) / gh)
    norm = np.clip(hmap / max(float(hmap.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    col = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
    col[occ == 0] = 40
    col = cv2.flip(col, 0)                              # +y yukarı çizilsin
    big = cv2.resize(col, (int(gw * k), int(gh * k)), interpolation=cv2.INTER_NEAREST)
    ox, oy = (W - big.shape[1]) // 2, (H - big.shape[0]) // 2
    img[oy:oy + big.shape[0], ox:ox + big.shape[1]] = big

    def to_px(x, y):
        return ox + (x - x0) / cell * k, oy + big.shape[0] - (y - y0) / cell * k

    for o in objs:
        cx, cy, w, l, ang = o["rect"]
        box = cv2.boxPoints(((cx, cy), (w, l), ang))
        pts = np.array([to_px(x, y) for x, y in box], np.int32)
        cv2.polylines(img, [pts], True, (0, 255, 255), 2)
        # etiket kutunun altında, koyu zemin üzerinde; görüntü dışına taşmasın
        label = label_of(o, cargo)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        lx = int(np.clip(pts[:, 0].mean() - tw / 2, 4, W - tw - 4))
        ly = int(np.clip(pts[:, 1].max() + th + 10, th + 6, H - 6))
        cv2.rectangle(img, (lx - 4, ly - th - 6), (lx + tw + 4, ly + 6), (0, 0, 0), -1)
        cv2.putText(img, label, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return img
