"""Netzteil-/Ladegerättest im Zeitraffer gegen ein nachgebautes Netzteil -
über dieselben USB-Bytes wie mit dem echten DL24."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import netzteil as nt
from akkutest.geraet import Geraet
from akkutest.simulator import SimNetzteil, SimulatorVerbindung


def durchspielen(quelle, e, tempo=200, frist=60):
    v = SimulatorVerbindung(protokoll="hid", akku=quelle, tempo=tempo, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    assert g.erkennen(warten=0.2) == "hid", g.protokoll
    fertig = threading.Event()
    ereignisse = []
    ab = nt.NetzteilAblauf(e, g, bei_ereignis=lambda a, t: (ereignisse.append((a, t)),
                                                           a == "fertig" and fertig.set()))
    g.bei_messwert = ab.messwert
    g.starten()
    assert fertig.wait(frist), f"nicht fertig: {ab.zustand} {ereignisse[-3:]}"
    for _ in range(100):                  # der Aus-Befehl ist noch unterwegs
        if not v.geraet.an:
            break
        time.sleep(0.01)
    g.trennen()
    assert not v.geraet.an, "Last nach dem Test noch an"
    assert not v.geraet.update_modus
    return ab, ereignisse


def test_gutes_ladegeraet():
    # 5 V / 2 A, schaltet erst bei 2,6 A ab
    q = SimNetzteil(5.0, innen_mohm=100, abschalt_a=2.6)
    e = nt.NetzteilEinstellung("Gut 5V 2A", 5.0, 2.0, stufen=5, stufe_s=10, dauer_min=2,
                               abschalttest=True, max_proz=150)
    ab, ev = durchspielen(q, e)
    r = ab.ergebnis
    print("gut:", r.grund, r.abschalt_a, [(s.soll_a, s.spannung) for s in r.stufen])
    assert r.haelt is True, r
    assert r.leerlauf_v and 5.0 < r.leerlauf_v < 5.1
    assert len([s for s in r.stufen if s.soll_a <= 2.0]) == 5
    assert r.dauer and r.dauer.ok
    assert r.abschalt_a is not None and 2.6 < r.abschalt_a <= 2.75 and r.abschalt_art == "abgeschaltet", r
    assert r.temp_max and r.temp_max > 22          # Fühler wurde mitgeschrieben
    assert any(a == "schritt" for a, _ in ev)


def test_schwaches_ladegeraet():
    # steht 2,4 A drauf, ab 1,5 A sackt die Spannung ab
    q = SimNetzteil(5.0, innen_mohm=150, abschalt_a=5.0, tol_a=1.5)
    e = nt.NetzteilEinstellung("Billig 2,4A", 5.0, 2.4, stufen=4, stufe_s=10, dauertest=False)
    ab, _ = durchspielen(q, e)
    r = ab.ergebnis
    print("schwach:", r.grund, [(s.soll_a, s.min_v, s.ok) for s in r.stufen])
    assert r.haelt is False, r
    assert r.stufen[0].ok and not r.stufen[-1].ok


def test_schaltet_vor_nennstrom_ab():
    q = SimNetzteil(5.0, innen_mohm=100, abschalt_a=1.2)
    e = nt.NetzteilEinstellung("Fake 2A", 5.0, 2.0, stufen=4, stufe_s=10, dauertest=False)
    ab, _ = durchspielen(q, e)
    r = ab.ergebnis
    print("fake:", r.grund)
    assert r.haelt is False and r.abschalt_a == 1.5 and "abgeschaltet" in r.grund, r


def test_temperaturgrenze():
    q = SimNetzteil(12.0, innen_mohm=50, abschalt_a=9.0, heiz_c_je_w=3.0)
    e = nt.NetzteilEinstellung("Heiß 12V", 12.0, 2.0, stufentest=False, dauer_min=60, temp_grenze=50)
    ab, _ = durchspielen(q, e, tempo=600)
    r = ab.ergebnis
    print("heiß:", r.grund, r.temp_max)
    assert "50" in r.grund and r.temp_max >= 50 and r.haelt is None, r


def test_ohne_spannung_und_grenzen():
    q = SimNetzteil(0.0, abschalt_a=9)
    e = nt.NetzteilEinstellung("nix", 5.0, 1.0, stufen=2, stufe_s=5)
    ab, _ = durchspielen(q, e)
    assert ab.zustand == "abgebrochen" and "Keine Spannung" in ab.ergebnis.grund
    # 24 V × 5 A × 130 % = 156 W > 150 W
    assert "150 W" in nt.NetzteilEinstellung("x", 24, 5, abschalttest=True).pruefen()
    assert nt.NetzteilEinstellung("x", 5, 0, nenn_w=10).strom_a == 2.0
    assert nt.NetzteilEinstellung("x", 5, 2, stufentest=False, dauertest=False).pruefen()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
