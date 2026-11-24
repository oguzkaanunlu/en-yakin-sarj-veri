#!/usr/bin/env python3
"""EPDK halka açık şarj istasyonu listesini günde bir kez indirip uygulamanın okuduğu
küçük JSON'a çevirir.

Kaynak: EPDK "Şarj İstasyonları" API geçidi (kimlik doğrulamasız, resmi). Geçit sıkı bir
kota uyguluyor (istemci başına günde yaklaşık bir tam indirme), bu yüzden uygulama EPDK'ya
hiç gitmez; bu betik günde bir kez çalışır ve çıktı statik dosya olarak yayınlanır.
Canlı doluluk (boş/dolu) bilgisi EPDK verisinde yoktur.

Kullanım:
    python3 epdk_snapshot.py --out public              # indir + dönüştür
    python3 epdk_snapshot.py --input ham.json --out public

Çıktı (v1), public/stations.json:
    {"v":1,"generatedAt":"<ISO8601>","source":"EPDK","count":N,"stations":[
      {"n":7918,"a":"<istasyon adı>","b":"<ağ markası>","o":"<işletmeci unvanı>",
       "d":"<adres>","y":<enlem>,"x":<boylam>,"s":[["DC_CCS",180.0,2],["AC_TYPE2",22.0,1]]}]}
"s" aynı soketleri gruplar: [tür, kW, adet]. Yalnız HALKA_ACIK ve Türkiye kutusundaki kayıtlar.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_URL = "https://apigateway.epdk.gov.tr/sarjIstasyonlari/"
MIN_STATIONS = 5000
MIN_RATIO = 0.7
MIN_HOURS_BETWEEN_PULLS = 20
KNOWN_SOCKETS = {"AC_TYPE2", "DC_CCS", "DC_CHADEMO"}

# EPDK'daki "marka" alanı bazen küçük harf, bazen fazlalıklı. Bilinen ağların görünen adı.
BRAND_NAMES = {
    "zes": "ZES",
    "trugo": "Trugo",
    "eşarj": "Eşarj",
    "esarj": "Eşarj",
    "voltrun": "Voltrun",
    "wat mobilite": "WAT Mobilite",
    "zeplin car rental": "Zeplin",
    "d-charge": "D-Charge",
    "5 şarj": "5Şarj",
    "k-şarj": "K-Şarj",
    "mks-şarj": "MKS Şarj",
    "otopriz": "Otopriz",
    "astor": "Astor",
    "en yakıt": "EN Yakıt",
    "ovolt": "Ovolt",
    "otojet": "Otojet",
    "beefull": "Beefull",
    "aksa şarj": "Aksa Şarj",
    "shell recharge": "Shell Recharge",
    "tesla": "Tesla",
    "sharz.net": "Sharz.net",
    "voltgo": "VoltGo",
    "migen": "Migen",
    "e-power": "e-POwer",
}

TR_UPPER = str.maketrans("iı", "İI")
TR_LOWER = str.maketrans("İI", "iı")


TURKISH_CHARS = set("ÇĞİÖŞÜçğıöşü")


def tr_title(text):
    """Büyük harfli metni "Başlık Biçimi"ne çevirir; Türkçe harf içermeyen kelimelerde
    İngilizce kuralı kullanır (CHARGING -> Charging, ŞARJ -> Şarj, İZMİR -> İzmir)."""
    words = []
    for w in text.split():
        if any(ch.islower() for ch in w):
            words.append(w)
            continue
        if TURKISH_CHARS & set(w):
            head, tail = w[:1], w[1:].translate(TR_LOWER).lower()
        else:
            head, tail = w[:1], w[1:].lower()
        words.append(head + tail)
    return " ".join(words)


def brand_name(raw, operator):
    key = " ".join((raw or "").split()).translate(TR_LOWER).lower().replace("i\u0307", "i")
    if key in BRAND_NAMES:
        return BRAND_NAMES[key]
    if key:
        text = " ".join(raw.split())
        if text == text.lower():
            return text[:1].translate(TR_UPPER).upper() + text[1:]
        return tr_title(text)
    # Marka yoksa işletmeci unvanının ilk kelimesi.
    first = (operator or "").split()[:1]
    return tr_title(first[0]) if first else ""


def parse_power(value):
    try:
        kw = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return kw if 0 < kw <= 1000 else None


def download():
    # Geçit gövdeli GET bekliyor; gövdesiz istek JSON şema hatası (ERR-241) döner.
    request = urllib.request.Request(
        API_URL, data=b"{}", method="GET",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "en-yakin-sarj-veri (gunluk kopya)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"EPDK isteği başarısız: HTTP {error.code} {error.read()[:300]!r}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SystemExit(f"Beklenmeyen EPDK yanıtı (kota?): {str(payload)[:300]}")
    return payload


def convert(payload, now=None):
    stations = {}
    for row in payload["data"]:
        if row.get("hizmetSekli") != "HALKA_ACIK":
            continue
        lat, lon = row.get("enlem"), row.get("boylam")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if not (35.5 <= lat <= 42.5 and 25.5 <= lon <= 45.0):
            continue
        digits = re.sub(r"\D", "", row.get("sarjIstasyonuNo") or "")
        if not digits:
            continue
        sockets = {}
        for socket in row.get("soketler") or []:
            kind = (socket.get("soketTuru") or "").strip().upper()
            if kind not in KNOWN_SOCKETS:
                kind = "DC_OTHER" if (socket.get("soketTipi") or "").upper() == "DC" else "AC_OTHER"
            power = parse_power(socket.get("soketGucu"))
            if power is None:
                continue
            sockets[(kind, power)] = sockets.get((kind, power), 0) + 1
        if not sockets:
            continue
        operator = " ".join((row.get("sarjAgiIsletmecisiUnvan") or "").split())
        stations[int(digits)] = {
            "n": int(digits),
            "a": " ".join((row.get("sarjIstasyonuAdi") or "").split()),
            "b": brand_name(row.get("marka"), operator),
            "o": operator,
            "d": " ".join((row.get("adres") or "").split()),
            "y": round(float(lat), 6),
            "x": round(float(lon), 6),
            "s": [[k, p, c] for (k, p), c in sorted(sockets.items(), key=lambda i: (-i[0][1], i[0][0]))],
        }
    ordered = [stations[k] for k in sorted(stations)]
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return {
        "v": 1,
        "generatedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "EPDK",
        "count": len(ordered),
        "stations": ordered,
    }


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="daha önce kaydedilmiş ham EPDK yanıtı (indirme yapılmaz)")
    parser.add_argument("--out", default="public")
    parser.add_argument("--force", action="store_true", help="20 saat korumasını atla")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    stations_path = os.path.join(args.out, "stations.json")
    meta_path = os.path.join(args.out, "meta.json")
    previous_meta = load_json(meta_path) or {}

    if not args.input and not args.force and previous_meta.get("pulledAt"):
        pulled = datetime.datetime.fromisoformat(previous_meta["pulledAt"].replace("Z", "+00:00"))
        age_h = (datetime.datetime.now(datetime.timezone.utc) - pulled).total_seconds() / 3600
        if age_h < MIN_HOURS_BETWEEN_PULLS:
            print(f"Son çekim {age_h:.1f} saat önce; EPDK kotası için atlandı.", file=sys.stderr)
            return 0

    payload = load_json(args.input) if args.input else download()
    snapshot = convert(payload)
    count = snapshot["count"]
    previous_count = previous_meta.get("count") or 0
    if count < MIN_STATIONS or (previous_count and count < previous_count * MIN_RATIO):
        raise SystemExit(f"Şüpheli küçük liste ({count}, önceki {previous_count}); yayınlanmadı.")

    previous = load_json(stations_path)
    pulled_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if previous and previous.get("stations") == snapshot["stations"]:
        meta = dict(previous_meta, pulledAt=pulled_at)
        print("İstasyon verisi değişmedi.", file=sys.stderr)
    else:
        body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        with open(stations_path, "w", encoding="utf-8") as f:
            f.write(body)
        meta = {
            "v": 1,
            "generatedAt": snapshot["generatedAt"],
            "pulledAt": pulled_at,
            "count": count,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "source": "EPDK",
        }
        print(f"{count} istasyon yazıldı: {stations_path}", file=sys.stderr)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
