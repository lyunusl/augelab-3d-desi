"""Fareyle döndürülen 3D nokta bulutu görünümü (blok içinde).

Girdi: {'points': Nx3 float32 (x sağ, y yukarı, z ileri), 'colors': Nx3 RGB uint8}
— "Canlı Point Cloud (Pi3X)" bloğunun Point Cloud çıkışı. Sol tuşla sürükle: döndür,
Yakınlaştırma slider'ı: yaklaş/uzaklaş. Sahne durduktan sonra da döndürülebilir.
"""
import math
import time

import cv2
import numpy

from studio.custom_block import Block, Button, Image, Label, SocketTypes, Slider, add_block

VIEW_W, VIEW_H = 480, 360
DRAG_POINTS = 60_000       # sürüklerken hızlı çizim için seyreltme
DRAG_INTERVAL = 0.04       # sürüklerken en sık çizim aralığı (s)


class PointCloudOrbitViewer3D(Block):
    op_code = 'PointCloudOrbitViewer3D'
    tooltip = ('Nokta bulutunu blok içinde fareyle döndürülebilir 3B görünüm olarak çizer.\n'
               'Inputs:\n- Point Cloud: {points: Nx3, colors: Nx3 RGB}.\n'
               'Outputs:\n- 3D View: Son çizilen görünüm.\n- Rendered Points: Çizilen nokta sayısı.')

    def init(self):
        self.op_title = '3B Bulut (Fareyle Döndür)'
        self.width = VIEW_W + 40
        self.height = VIEW_H + 190
        self.input_sockets = [SocketTypes.Generic('Point Cloud')]
        self.output_sockets = [SocketTypes.ImageRGB('3D View'), SocketTypes.Integer('Rendered Points')]
        self.param['view'] = Image(fixed_width=VIEW_W, fixed_height=VIEW_H)
        self.param['hint'] = Label(text='Sol tuşla sürükle: döndür')
        self.param['zoom_label'] = Label(text='Yakınlaştırma')
        self.param['zoom'] = Slider(min=2, max=60, val=10)
        self.param['reset'] = Button(text='Görünümü sıfırla')
        self.param['reset'].set_clicked_callback(self._reset_view)
        self.param['view'].registerMouseDragEvent(self._on_drag)
        self._yaw, self._pitch = 0.0, 0.0             # bırakılmış (kalıcı) açılar
        self._drag = (0.0, 0.0)                        # sürüklenen ek açı
        self._pts = self._cols = self._center = self._src = None
        self._radius = 1.0
        self._last_draw = 0.0
        self._frame = None                             # (görüntü, nokta sayısı)

    # --- etkileşim (Qt ana iş parçacığı) ---
    def _on_drag(self, pos):
        (x0, y0), (x1, y1) = pos
        self._drag = ((x1 - x0) * 2 * math.pi, (y1 - y0) * math.pi)
        if not self.param['view'].isMouseDrawing():   # bırakıldı: açıyı kalıcı yap
            self._yaw += self._drag[0]
            self._pitch = max(-1.5, min(1.5, self._pitch + self._drag[1]))
            self._drag = (0.0, 0.0)
            self._frame = self._show(full=True)
        elif time.time() - self._last_draw > DRAG_INTERVAL:
            self._show(full=False)

    def _reset_view(self, *args):
        self._yaw, self._pitch, self._drag = 0.0, 0.0, (0.0, 0.0)
        self._frame = self._show(full=True)

    # --- çizim ---
    def _zoom(self):
        try:
            return max(float(self.param['zoom'].value), 1.0) / 10.0
        except (TypeError, ValueError):
            return 1.0

    def _render(self, full):
        img = numpy.full((VIEW_H, VIEW_W, 3), 18, numpy.uint8)
        pts, cols = self._pts, self._cols
        if pts is None or len(pts) == 0:
            cv2.putText(img, 'Nokta bulutu bekleniyor', (20, VIEW_H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (160, 160, 160), 2)
            return img, 0
        if not full and len(pts) > DRAG_POINTS:
            step = len(pts) // DRAG_POINTS
            pts, cols = pts[::step], cols[::step]
        yaw = self._yaw + self._drag[0]
        pitch = max(-1.5, min(1.5, self._pitch + self._drag[1]))
        cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        ry = numpy.array(((cy, 0, -sy), (0, 1, 0), (sy, 0, cy)), numpy.float32)
        rx = numpy.array(((1, 0, 0), (0, cp, sp), (0, -sp, cp)), numpy.float32)
        q = (pts - self._center) @ (rx @ ry).T
        dist = 2.2 * self._radius / self._zoom()        # kamera merkezin -z tarafında
        z = q[:, 2] + dist
        ok = z > 1e-3
        q, z, cols = q[ok], z[ok], cols[ok]
        f = 0.9 * VIEW_W
        u = (f * q[:, 0] / z + VIEW_W / 2).astype(numpy.int32)
        v = (-f * q[:, 1] / z + VIEW_H / 2).astype(numpy.int32)
        ok = (u >= 1) & (u < VIEW_W - 1) & (v >= 1) & (v < VIEW_H - 1)
        u, v, z, cols = u[ok], v[ok], z[ok], cols[ok]
        order = numpy.argsort(-z)                         # uzaktan yakına
        u, v, bgr = u[order], v[order], cols[order][:, ::-1]
        r = (0,) if not full else (-1, 0, 1)
        for du in r:
            for dv in r:
                img[v + dv, u + du] = bgr
        return img, int(len(u))

    def _show(self, full):
        self._last_draw = time.time()
        img, n = self._render(full)
        self.param['view'].update(img)
        return img, n

    # --- motor ---
    def run(self):
        cloud = self.input['Point Cloud'].data
        src = cloud.get('points') if isinstance(cloud, dict) else None
        if src is None and self._src is not None:            # kaynak sıfırlandı: görünümü temizle
            self._src = self._pts = self._cols = None
            self._frame = self._show(full=True)
        if src is not None and src is not self._src:        # yalnızca bulut değişince yeniden çiz
            self._src = src
            pts = numpy.asarray(src, numpy.float32).reshape(-1, 3)
            cols = numpy.asarray(cloud.get('colors', []), numpy.uint8)
            if cols.shape != pts.shape:
                cols = numpy.full(pts.shape, 220, numpy.uint8)
            if len(pts):
                self._center = numpy.median(pts, axis=0)
                self._radius = float(numpy.percentile(numpy.linalg.norm(pts - self._center, axis=1), 90)) or 1.0
                self._pts, self._cols = pts, cols
                self._frame = self._show(full=True)
        if self._frame is None:
            self._frame = self._show(full=True)
        self.output['3D View'].data = self._frame[0]
        self.output['Rendered Points'].data = self._frame[1]


add_block(PointCloudOrbitViewer3D.op_code, PointCloudOrbitViewer3D)
