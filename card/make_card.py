"""Basılacak A4 ArUco kart (DICT_4X4_50, id 0): siyah kare tam 100 mm, 300 dpi PDF + PNG.

python make_card.py [çıktı klasörü]   (varsayılan: bu klasör; Windows Arial fontu gerekir)
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPI = 300
MM = DPI / 25.4                                   # 1 mm = 11.81 px
out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
os.makedirs(out, exist_ok=True)

W, H = round(210 * MM), round(297 * MM)
page = Image.new("L", (W, H), 255)
side = round(100 * MM)                            # siyah kare (ArUco kenarı) = 100 mm
marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 0, side)
mx, my = (W - side) // 2, round(55 * MM)
page.paste(Image.fromarray(marker), (mx, my))

d = ImageDraw.Draw(page)
font_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
big = ImageFont.truetype(os.path.join(font_dir, "arialbd.ttf"), round(6 * MM))
small = ImageFont.truetype(os.path.join(font_dir, "arial.ttf"), round(3.6 * MM))
d.text((W // 2, round(25 * MM)), "AugeLab 3D ölçüm kartı", font=big, fill=0, anchor="mm")
d.text((W // 2, round(38 * MM)), "Siyah kare kenarı tam 100 mm  ·  ArUco 4x4 id 0", font=small, fill=0, anchor="mm")

# 100 mm kontrol cetveli: her cm'de çentik
ry = my + side + round(25 * MM)
x0 = (W - round(100 * MM)) // 2
d.line([(x0, ry), (x0 + round(100 * MM), ry)], fill=0, width=4)
for cm in range(11):
    x = x0 + round(cm * 10 * MM)
    d.line([(x, ry - round((4 if cm % 5 == 0 else 2.5) * MM)), (x, ry)], fill=0, width=4)
    d.text((x, ry + round(3 * MM)), str(cm), font=small, fill=0, anchor="mt")
d.text((W // 2, ry + round(12 * MM)), "Bu çizgi cetvelle tam 10 cm olmalı", font=small, fill=0, anchor="mt")

notes = ["Yazdırırken ölçek: %100 / Gerçek boyut (\"Sayfaya sığdır\" KAPALI)",
         "Kartı düz tut: buruşuk ya da kıvrık kart ölçüyü bozar",
         "Mat kâğıt tercih et, parlak kâğıt ışığı yansıtır"]
for i, t in enumerate(notes):
    d.text((W // 2, ry + round((26 + i * 7) * MM)), t, font=small, fill=0, anchor="mt")

page.save(os.path.join(out, "aruco_kart_100mm_A4.pdf"), resolution=DPI)
page.save(os.path.join(out, "aruco_kart_100mm_A4.png"), dpi=(DPI, DPI))
print("siyah kare:", side, "px =", round(side / MM, 2), "mm ->", os.path.abspath(out))
