# Windows kurulum ve ilk ölçüm

1. [README'deki donanım ve lisans koşullarını](../README.md#donanım) kontrol et.
   NVIDIA sürücüsü, Python 3.12 ve AugeLab Studio'yu hazırla.
2. Depo kökünde `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
   çalıştır. Bu adım sanal ortamı ve Python bağımlılıklarını kurar.
3. `service\start_server.cmd` dosyasını çalıştır. İlk açılışta Pi3X modeli
   indirilir. Hazır mesajından sonra
   [ana ölçüm arayüzünü](http://127.0.0.1:8770/) aç. Üç demo görselini
   [demo klasöründen](../studio/demo/README.md) yükleyerek bir ölçüm al.
4. Studio senaryosunu veya isteğe bağlı yerel HMI'yi kullanacaksan
   [dört Studio özel bloğunu](../studio_blocks/README.md) kur. Başka bir
   bilgisayarda, açık çalışmalarını kaydettikten sonra Studio'yu yeniden aç.
   Daha önce kurulmuş eski `MultiCam3D.py` dosyasını bu sürümle değiştir.
   HMI'nin **Ölç** metin alanına yazılan her yeni değer (`1`, `2`, `3`, ...) bu sürümde bir ölçüm alır.
5. [Studio senaryosu ve HMI notlarını](../studio/README.md) izle.
   Üç **Load Image From Path** girişini [depodaki demo görüntüleriyle](../studio/demo/README.md)
   eşleştir. Gerçek kurulumda bu üç girişi **Camera USB** ile değiştir.
6. [ArUco kartını](../card/aruco_kart_100mm_A4.pdf) %100 boyutta yazdır, siyah
   karenin kenarını ölç ve **Kart boyu (mm)** alanına gir. Kartı masa düzlemine
   yerleştir. İlk denemede bilinen boyutlarda, birbirinden ayrık koliler kullan.
7. Önizlemede üç görüntüyü ve **Status** alanında milimetre ölçeğini gör.
   Üstten görünümde işaretlenen nesne sayısını kontrol et ve **Measurements**
   değerlerini elle aldığın ölçülerle karşılaştır.

## Sorun giderme

| Belirti | Kontrol |
|---|---|
| Yerel önizleme açılmıyor | Servis konsolunda model indirme veya CUDA hatası olup olmadığına bak. |
| Özel bloklar görünmüyor | Dosyaların özel blok klasörüne kopyalandığını ve Studio'nun yeniden açıldığını doğrula. |
| Kart bulunamadı | Kameralardan en az birinde dört köşenin de net göründüğünü kontrol et. |
| Ölçüm sonucu boş | Her kameranın görüntü ürettiğini ve Status çıktısında milimetre ölçeği olduğunu doğrula. |

## İsteğe bağlı Codex ve Claude Code eklentisi

Studio sahnesini Codex veya Claude Code ile yönetmek istiyorsan
[resmî AugeLab Studio eklentisinin kurulum adımlarını](https://github.com/AugelabTech/augelab-codex-claude-plugin)
izle. Studio'nun varsayılan MCP adresi `http://127.0.0.1:8765/mcp` iken
bu projenin GPU servisi ve tarayıcı ekranı `http://127.0.0.1:8770/`
adresindedir. Tarayıcıdan ölçüm almak için MCP eklentisi gerekmez.

Örnek sonuçlar Blender simülasyonuna aittir. Gerçek kamera ve koliyle ölçüm
sapmasını ayrı doğrula. Pi3X ağırlıkları CC BY-NC 4.0 lisanslıdır. Ticari
kullanım ayrıntıları için [README lisans tablosuna](../README.md#lisanslar) bak.
