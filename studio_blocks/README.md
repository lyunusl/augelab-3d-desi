# AugeLab Studio özel blokları

Bu dört dosyayı Studio'nun özel blok klasörüne kopyala:

```
%APPDATA%\AugeLab Studio\marketplace\custom_blocks\
```

PowerShell ile (depo kökünden):

```powershell
$blockFolder = Join-Path $env:APPDATA 'AugeLab Studio\marketplace\custom_blocks'
New-Item -ItemType Directory -Force -Path $blockFolder | Out-Null
Copy-Item .\studio_blocks\*.py -Destination $blockFolder
```

Ardından **Studio'yu yeniden başlat**. Özellikle `PointCloudOrbitViewer3D.py` elle yazılmış
Block API bloğudur; yeniden başlatmadan görünmez ya da eski sürümü kalır.

| Dosya | Studio'daki adı | Ne yapar |
|---|---|---|
| `MultiCam3D.py` | Çok Kameralı 3D | 2-3 sabit kameranın aynı anki karelerini servise yollar (`/capture`), mm ölçekli bulut döner |
| `Measure3D.py` | 3D Ölçüm | Buluttaki masa üstü nesneleri ayırır; L×W×H, Kargo modunda cm + desi |
| `PointCloud3D.py` | 3D Nokta Bulutu | Tek blok, üç mod: Canlı / Tek görüntü / Çok açı |
| `PointCloudOrbitViewer3D.py` | 3B Bulut (Fareyle Döndür) | Bulutu blok içinde fareyle döndürülebilir gösterir |

Bloklar ince istemcidir: modeller ve ölçüm `service/` altındaki yerel GPU servisinde çalışır
(varsayılan `http://127.0.0.1:8770`, her blokta "Servis adresi" ayarı). Servis kapalıysa
Status çıktısı "Servise ulaşılamadı" der.

Bloklar Studio'nun `studio.custom_block` modülünü içe aktarır; Studio dışında çalıştırılamaz.
