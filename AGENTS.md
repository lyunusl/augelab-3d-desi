# 3 kameralı desi projesi

- `service/` yerel GPU servisini, `studio_blocks/` dört Studio özel bloğunu,
  `studio/` senaryoyu ve HMI paketini içerir.
- Var olan Studio sahnesini düzenlemeden önce ayrı bir `.pmod` olarak kaydet.
  Kök SubSystem In/Out portlarını tek tek ekle ve her değişikliği kaydet.
- Yerel servis `127.0.0.1:8770` üzerinde çalışır. Kimlik doğrulaması
  bulunmadığı için bu uç noktayı ağa açma. Çalışan servisi kesintiye uğratmadan
  yapılan kontrolde yalnız GET isteklerini kullan.
- Yerel ayarları, anahtarları, sanal ortamları, model ağırlıklarını ve üretilen
  nokta bulutlarını Git'e ekleme. Studio örneklerinde kişiye özel mutlak
  yolları kontrol et. Depo herkese açıktır; gizli ya da kişisel bilgi ekleme.
- Blender simülasyonu ile fiziksel kamera ve koli doğrulamasını ayrı raporla.
  Pi3X ağırlıklarının ticari kullanım kısıtına ilişkin README notunu koru.
