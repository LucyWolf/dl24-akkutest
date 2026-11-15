"""Ganze Entladungen im Zeitraffer gegen den Simulator - über dieselben Bytes
wie mit dem echten Gerät, in beiden Protokollen."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import akkus
from akkutest.ablauf import Ablauf, Einstellung
from akkutest.geraet import Geraet
from akkutest.simulator import SimAkku, SimulatorVerbindung


def durchspielen(protokoll, akku, strom, abschalt, tempo=600, frist=60, abbruch_bei_v=None):
    v = SimulatorVerbindung(protokoll=protokoll, akku=akku, tempo=tempo, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    assert g.erkennen(warten=0.2) == protokoll, g.protokoll
    e = Einstellung(akku.typ, akku.zellen, int(akku.mah), strom, abschalt)
    ereignisse = []
    fertig = threading.Event()
    ab = Ablauf(e, g, bei_ereignis=lambda a, t: (ereignisse.append((a, t)), a == "fertig" and fertig.set()))

    def messwert(m):
        ab.messwert(m)
        # beim Atorch-Gerät spielt der Test den Menschen am Gerät
        if protokoll in ("atorch", "hid"):
            if ab.zustand == "warten" and not v.geraet.an:
                v.geraet.soll_a, v.geraet.abschalt_v, v.geraet.an = strom, abschalt, True
            if abbruch_bei_v and m.spannung <= abbruch_bei_v:
                v.geraet.an = False

    g.bei_messwert = messwert
    g.starten()
    assert fertig.wait(frist), f"nicht fertig geworden: {ab.zustand}, {ereignisse}"
    g.trennen()
    return ab, ereignisse, v.geraet


def test_px100_volle_entladung():
    akku = SimAkku("liion", 1, mah=2500, innen_mohm=40)
    ab, ev, dev = durchspielen("px100", akku, 1.25, 3.0)
    r = ab.ergebnis
    print("px100:", r, len(ab.punkte), "Punkte")
    assert r.vollstaendig, r.grund
    assert ab.zustand == "fertig"
    assert not dev.an, "Last muss am Ende aus sein"
    assert abs(dev.abschalt_v - 3.0) < 0.001 and abs(dev.soll_a - 1.25) < 0.001, "Einstellungen nicht ans Gerät"
    # Der Akku hat 2500 mAh; bis 3,0 V unter Last (40 mΩ) kommt man auf fast alles
    assert 2250 < r.mah < 2510, r.mah
    assert abs(r.mah - dev.mah) / dev.mah < 0.02, (r.mah, dev.mah)
    assert 4.1 < r.leerlauf_v < 4.2
    assert r.innen_mohm and 30 < r.innen_mohm < 50, r.innen_mohm
    assert 8.0 < r.wh < 9.5, r.wh


def test_atorch_nur_berichte():
    akku = SimAkku("liion", 3, mah=2000, innen_mohm=50)
    ab, ev, dev = durchspielen("atorch", akku, 1.0, 9.0)
    r = ab.ergebnis
    print("atorch:", r)
    assert not ab.steuerbar
    assert any("Am Gerät einstellen" in t for _, t in ev), ev
    assert r.vollstaendig, r.grund                         # Gerät hat selbst abgeschaltet
    assert 1800 < r.mah < 2010, r.mah


def test_usb_hid():
    # DL24/P am USB-Kabel: nur Messwerte, aber auf 1 mV genau; Strom kommt negativ
    akku = SimAkku("liion", 1, mah=2000, innen_mohm=50)
    ab, ev, dev = durchspielen("hid", akku, 1.0, 3.0)
    r = ab.ergebnis
    print("hid:", r)
    assert not ab.steuerbar
    assert r.vollstaendig, r.grund
    assert 1800 < r.mah < 2010, r.mah
    assert abs(r.mah - dev.mah) / dev.mah < 0.02, (r.mah, dev.mah)
    # 4,18 V Ruhe - über Bluetooth käme hier 4,2 an
    assert 4.17 < r.leerlauf_v < 4.19, r.leerlauf_v
    assert round(r.leerlauf_v, 3) != round(r.leerlauf_v, 1)


def test_atorch_vorzeitig_aus():
    akku = SimAkku("liion", 1, mah=2000, innen_mohm=50)
    ab, ev, dev = durchspielen("atorch", akku, 1.0, 3.0, abbruch_bei_v=3.7)
    assert not ab.ergebnis.vollstaendig
    assert "vorzeitig" in ab.ergebnis.grund
    assert ab.ergebnis.mah < 1500


def test_leerer_akku_startet_nicht():
    akku = SimAkku("liion", 1, mah=2000, ladung=0.0)
    ab, ev, dev = durchspielen("px100", akku, 1.0, 3.0)
    assert ab.zustand == "abgebrochen" and "leer" in ab.ergebnis.grund
    assert not dev.an


def test_abbrechen_schaltet_aus():
    akku = SimAkku("nimh", 1, mah=1900)
    v = SimulatorVerbindung(protokoll="px100", akku=akku, tempo=50, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    g.erkennen(warten=0.1)
    ab = Ablauf(Einstellung("nimh", 1, 1900, 0.5, 1.0), g)
    g.bei_messwert = ab.messwert
    g.starten()
    ende = time.time() + 10
    while ab.zustand != "laeuft" and time.time() < ende:
        time.sleep(0.05)
    time.sleep(0.3)
    assert v.geraet.an
    ab.abbrechen()
    assert ab.zustand == "abgebrochen" and not v.geraet.an
    g.trennen()


def test_erkennung():
    def beste(u):
        v = akkus.erkennen(u)
        return (v[0].typ, v[0].zellen) if v else None
    assert beste(4.18) == ("liion", 1)
    assert beste(1.40) == ("nimh", 1)
    assert beste(3.40) == ("lifepo4", 1)
    assert beste(16.7) == ("liion", 4)
    assert beste(13.4) == ("lifepo4", 4)
    # 12,6 V ist doppeldeutig: beides muss angeboten werden
    alle = {(x.typ, x.zellen) for x in akkus.erkennen(12.6)}
    assert ("liion", 3) in alle and ("blei", 6) in alle, alle
    assert akkus.erkennen(0.2) == []


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
