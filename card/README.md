# ArUco ölçüm kartı (100 mm)

- `aruco_kart_100mm_A4.pdf` — yazdırılacak dosya (A4, 300 dpi)
- `aruco_kart_100mm_A4.png` — aynı kart, görüntü olarak

Kart: ArUco sözlüğü `DICT_4X4_50`, id 0. Ortadaki siyah karenin kenarı **tam 100 mm** olmalı.

## Yazdırma

1. PDF'i aç, yazdırırken ölçeği **%100 / Gerçek boyut** seç. "Sayfaya sığdır" **kapalı** olmalı.
2. Kartın altındaki 10 cm'lik çizgiyi cetvelle ölç. 100 mm değilse yazıcı ayarını düzelt ve yeniden yazdır.
3. Mat kâğıt tercih et, kartı düz tut (karton üstüne yapıştırmak iyi olur).

Siyah kare 100 mm'den farklı çıktıysa Studio'daki "Kart boyu (mm)" ayarına ölçtüğün değeri yaz.

## Yeniden üretmek

```powershell
python make_card.py            # bu klasöre yazar
python make_card.py C:\baska\klasor
```

Gerekenler: `opencv-python` (aruco modülü), `pillow`, numpy. Yazı için Windows'taki Arial fontunu kullanır.
