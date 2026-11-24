import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import epdk_snapshot as m  # noqa: E402


def row(no="ŞRJ/1", hizmet="HALKA_ACIK", lat=39.9, lon=32.8, marka="zes", sockets=None, **kw):
    r = {
        "sarjIstasyonuNo": no, "sarjIstasyonuAdi": "  Test  İstasyon ", "marka": marka,
        "sarjAgiIsletmecisiUnvan": "ZES DİJİTAL TİCARET ANONİM ŞİRKETİ", "adres": "Çankaya /  ANKARA",
        "hizmetSekli": hizmet, "enlem": lat, "boylam": lon,
        "soketler": sockets if sockets is not None else [
            {"soketTipi": "DC", "soketTuru": "DC_CCS", "soketGucu": "180"},
            {"soketTipi": "DC", "soketTuru": "DC_CCS", "soketGucu": "180"},
            {"soketTipi": "AC", "soketTuru": "AC_TYPE2", "soketGucu": "22,0"},
        ],
    }
    r.update(kw)
    return r


class ConvertTests(unittest.TestCase):
    def test_keeps_public_valid_rows_and_groups_sockets(self):
        payload = {"data": [
            row(),
            row(no="ŞRJ/2", hizmet="OZEL"),
            row(no="ŞRJ/3", lat=0, lon=0),
            row(no="", ),
            row(no="ŞRJ/5", lat="39.9"),
            row(no="ŞRJ/6", sockets=[]),
            row(no="ŞRJ/7", sockets=[{"soketTipi": "DC", "soketTuru": "GB_T", "soketGucu": "60"}]),
        ]}
        snap = m.convert(payload, now=datetime.datetime(2026, 11, 24, tzinfo=datetime.timezone.utc))
        self.assertEqual(snap["count"], 2)
        self.assertEqual(snap["generatedAt"], "2026-11-24T00:00:00Z")
        first = snap["stations"][0]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["a"], "Test İstasyon")
        self.assertEqual(first["b"], "ZES")
        self.assertEqual(first["d"], "Çankaya / ANKARA")
        self.assertEqual(first["s"], [["DC_CCS", 180.0, 2], ["AC_TYPE2", 22.0, 1]])
        self.assertEqual(snap["stations"][1]["s"], [["DC_OTHER", 60.0, 1]])

    def test_brand_names(self):
        self.assertEqual(m.brand_name("eşarj", ""), "Eşarj")
        self.assertEqual(m.brand_name("ZEPLİN CAR rental", ""), "Zeplin")
        self.assertEqual(m.brand_name("CHARGING VEHICLES CV", ""), "Charging Vehicles Cv")
        self.assertEqual(m.brand_name("ŞARJMATİK", ""), "Şarjmatik")
        self.assertEqual(m.brand_name("tunçmatik", ""), "Tunçmatik")
        self.assertEqual(m.brand_name("", "OVOLT ŞARJ TEKNOLOJİLERİ"), "Ovolt")


class MainTests(unittest.TestCase):
    def test_refuses_small_snapshot_and_respects_quota_guard(self):
        with tempfile.TemporaryDirectory() as d:
            raw = os.path.join(d, "raw.json")
            with open(raw, "w") as f:
                json.dump({"data": [row()]}, f)
            with self.assertRaises(SystemExit):
                m.main(["--input", raw, "--out", os.path.join(d, "out")])

            out = os.path.join(d, "out2")
            os.makedirs(out)
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with open(os.path.join(out, "meta.json"), "w") as f:
                json.dump({"pulledAt": now, "count": 10}, f)
            # İndirme yapılmamalı: koruma 20 saatten yeni çekimi atlar.
            m.download = lambda: self.fail("indirme yapılmamalıydı")
            self.assertEqual(m.main(["--out", out]), 0)

    def test_writes_stations_and_meta(self):
        with tempfile.TemporaryDirectory() as d:
            raw = os.path.join(d, "raw.json")
            rows = [row(no=f"ŞRJ/{i}", lat=39 + i / 100000) for i in range(1, m.MIN_STATIONS + 1)]
            with open(raw, "w") as f:
                json.dump({"data": rows}, f)
            out = os.path.join(d, "out")
            self.assertEqual(m.main(["--input", raw, "--out", out]), 0)
            meta = json.load(open(os.path.join(out, "meta.json")))
            self.assertEqual(meta["count"], m.MIN_STATIONS)
            self.assertEqual(json.load(open(os.path.join(out, "stations.json")))["count"], m.MIN_STATIONS)


if __name__ == "__main__":
    unittest.main()
