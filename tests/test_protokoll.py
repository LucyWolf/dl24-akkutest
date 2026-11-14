"""Bytes hin und zurück, auch zerstückelt und durcheinander."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import protokoll as p
from akkutest.geraet import Entwirrer


def test_atorch_hin_und_zurueck():
    w = p.AtorchWerte(12.3, 1.234, 1230, 20, 31, 3 * 3600 + 25 * 60 + 7)
    paket = p.atorch_bauen(w)
    assert len(paket) == 36 and paket[:4] == b"\xff\x55\x01\x02"
    zurueck = p.atorch_lesen(paket)
    assert zurueck == w, zurueck
    kaputt = bytearray(paket); kaputt[5] ^= 1
    assert p.atorch_lesen(bytes(kaputt)) is None, "Prüfsumme muss falsche Pakete abweisen"


def test_px100():
    assert p.px_befehl(p.PX_STROM_SETZEN, *p.px_zahl_mit_hundertsteln(1.25)) == bytes.fromhex("B1B2020119B6")
    assert p.px_zahl_mit_hundertsteln(2.999) == (3, 0)
    assert p.px_antwort_wert(bytes.fromhex("CACB001068CECF")) == 4200
    assert p.px_antwort_wert(bytes.fromhex("CACB001068CECE")) is None


def test_entwirrer_gemischt_und_zerstueckelt():
    bericht = p.atorch_bauen(p.AtorchWerte(4.1, 1.0, 100, 0, 25, 60))
    strom = (b"\x12\x34" + bericht + p.px_antwort_bauen(4100) + bytes([p.PX_OK])
             + bericht[:10] + p.px_antwort_bauen(7) + bericht)          # ein halber Bericht dazwischen
    rnd = random.Random(1)
    for _ in range(50):
        e, aus, i = Entwirrer(), [], 0
        while i < len(strom):
            n = rnd.randint(1, 20)
            aus += e.hinein(strom[i:i + n])
            i += n
        arten = [a for a, _ in aus]
        assert arten.count("atorch") == 2, arten
        assert ("px", 4100) in aus and ("px", 7) in aus, aus
        assert ("quittung", True) in aus


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
