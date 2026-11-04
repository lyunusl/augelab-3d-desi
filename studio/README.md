# Studio senaryosu ve HMI

Ana operatör arayüzü servisle birlikte açılan
[tarayıcı ekranıdır](http://127.0.0.1:8770/). Bu klasördeki Studio ve yerel HMI
seçeneklerini sahneyi düzenlemek veya Studio içinde çalıştırmak için kullan.

- [desi_3kamera.pmod](desi_3kamera.pmod) düzenlenebilir AugeLab Studio sahnesi.
- [hmi_desi](hmi_desi/README.md) operatör arayüzü ve başlatıcıları.
- [demo](demo/README.md) üç Blender kamera görüntüsü ve bağlantı sırası.

Önce [Windows kurulumunu](../docs/KURULUM.md) tamamla. Sahne üç **String Input**
ve **Load Image From Path** çiftiyle Blender görüntülerini
`C:/augelab-3d-desi/studio/demo/` klasöründen alır (Studio göreli yolu açmıyor).
Depoyu `C:\augelab-3d-desi` klasörüne klonlarsan sahne olduğu gibi çalışır;
başka bir yere klonladıysan üç String Input'taki yolu kendi klasörüne göre
değiştir. Gerçek kameralarda bunların yerine üç kamera bloğu bağla.

Sahnenin kök girişinde **Ölç** tetikleyicisi bulunur. HMI'de **Kargo modu**
ve **Kart boyu (mm)** ayarlanabilir. **View**, **Measurements**, **Count**,
**Preview** ve **Status** arayüzde ayrı çıkışlardır.

Paketlenen üç görüntüyle tarayıcı testinde dört koli ve toplam 16,1 desi
görüldü. Ayrı yerel servis testinde desi sonuçları 7,3; 5,1; 2,8 ve 0,9 idi.
Bu testler Blender görüntülerine aittir. Fiziksel kameralarla doğrulama yapılmadı.
