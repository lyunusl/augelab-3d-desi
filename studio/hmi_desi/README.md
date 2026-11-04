# Desi ölçümü HMI

Bu paket, AugeLab Studio'nun dışa aktardığı HMI senaryosunu ve kurulu
Studio ile çalıştıran başlatıcıları içerir. Hedef makinede Studio'nun HMI
için uygun headless lisansı gerekir. Studio aktivasyon sorarsa kendi
kurulumundaki resmî akıştan tamamla.

1. [Kurulum adımlarını](../../docs/KURULUM.md) tamamla, özellikle güncel dört
   özel bloğu kur ve yerel GPU servisini başlat.
2. Senaryo demo görüntülerini `C:/augelab-3d-desi/studio/demo/` yolundan okur.
   Depo başka bir klasördeyse [demo görüntü yollarını](../demo/README.md)
   Studio'da `hmi_scenario.pmod` içinde değiştir ve kaydet.
3. Windows'ta `run_hmi.bat` çalıştır. Studio varsayılan dizinde değilse
   `AUGELAB_STUDIO_PYTHON` ortam değişkenine Studio'nun `python.exe`
   dosyasının tam yolunu ver. Studio modülünün özel kaynak dizini varsa
   `AUGELAB_STUDIO_SOURCE` ile belirt.
4. **Ölç** alanına `1` yazıp **Run Step** ile ölçümü al. Her yeni ölçümde
   alana farklı bir değer yaz (`2`, `3`, ...) ve tekrar **Run Step** çalıştır.
   Aynı değerle tekrar çalıştırmak yeni ölçüm almaz; `0` ya da boş bekletir.

**Kargo modu** boyutları cm ve hacim ağırlığını desi olarak gösterir.
**Kart boyu (mm)** sahnedeki siyah ArUco karesinin gerçek kenar uzunluğudur.
**View** üstten ölçüm haritasını, **Measurements** ölçüm metnini, **Count**
nesne sayısını, **Preview** kamera görüntülerini ve **Status** servis durumunu
gösterir.

`sh run_hmi.sh` mevcut uyumlu Studio runtime'ıyla kullanılabilir.
Bu proje için belgelenen kurulum Windows ve NVIDIA CUDA üzerindedir.
