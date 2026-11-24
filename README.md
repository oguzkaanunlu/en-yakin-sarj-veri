# En Yakın Şarj: günlük EPDK verisi

EPDK'nın resmi "Şarj İstasyonları" servisinden halka açık istasyon listesini günde bir kez çeker, küçük bir JSON'a çevirir ve GitHub Pages'te yayınlar. En Yakın Şarj uygulaması EPDK'ya hiç gitmez, yalnız bu dosyayı okur.

- Çıktı: `https://<kullanıcı>.github.io/<depo>/stations.json` ve `meta.json`.
- Kaynak: EPDK. Veri EPDK'ya aittir. Canlı doluluk (boş/dolu) bilgisi kaynakta yoktur.
- Kota: EPDK geçidi istemci başına günde yaklaşık bir tam indirmeye izin veriyor. Betik son çekimden 20 saat geçmeden tekrar çekmez.
- Güvenlik: liste 5.000 istasyonun ya da bir öncekinin %70'inin altına düşerse yayınlanmaz, eski dosya kalır.

Kurulum: bu klasörün içeriği herkese açık ayrı bir depoya konur. Depo ayarlarından Pages kaynağı `gh-pages` dalı seçilir. İlk veri için Actions'tan "Günlük EPDK verisi" elle çalıştırılır.

Test: `python3 -m unittest discover -s tests -v`
