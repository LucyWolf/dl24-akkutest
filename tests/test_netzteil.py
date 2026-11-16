"""Netzteil-/Ladegerättest im Zeitraffer gegen ein nachgebautes Netzteil -
über dieselben USB-Bytes wie mit dem echten DL24."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import netzteil as nt
from akkutest.geraet import Geraet
from akkutest.simulator import SimNetzteil, SimPowerbank, SimulatorVerbindung


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


def trigger_durchspielen(q, basis, stufen, kann, tempo=200, frist=90):
    """Spielt den Menschen am Trigger-Adapter: stellt die verlangte Spannung ein,
    wenn das Ladegerät sie kann - sonst bleibt es bei der vorigen."""
    nt.TRIGGER_WARTEN_S = 20
    v = SimulatorVerbindung(protokoll="hid", akku=q, tempo=tempo, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    assert g.erkennen(warten=0.2) == "hid"
    fertig = threading.Event()
    ereignisse = []

    def melden(art, text):
        ereignisse.append((art, text))
        if art == "umschalten":
            ziel = float(text.split("jetzt ")[1].split(" V")[0].replace(",", "."))
            if ziel in kann:
                q.nenn_v = ziel
        if art == "fertig":
            fertig.set()

    ab = nt.TriggerAblauf(basis, stufen, g, bei_ereignis=melden)
    g.bei_messwert = ab.messwert
    g.starten()
    assert fertig.wait(frist), f"nicht fertig: {ab.zustand} {ereignisse[-3:]}"
    for _ in range(100):
        if not v.geraet.an:
            break
        time.sleep(0.01)
    g.trennen()
    assert not v.geraet.an and not v.geraet.update_modus
    return ab, ereignisse


def test_schnellladen_mit_trigger():
    q = SimNetzteil(5.0, innen_mohm=100, abschalt_a=3.3)
    basis = nt.NetzteilEinstellung("PD-Lader", 5.0, 0, stufen=3, stufe_s=10, dauertest=False)
    ab, ev = trigger_durchspielen(q, basis, [(5.0, 3.0), (9.0, 0), (12.0, 0), (15.0, 0)], kann={9.0, 12.0})
    r = ab.ergebnis
    print("PD:", r.grund, [(t["einstellung"]["nenn_v"], t["ergebnis"]["haelt"], nt.bestleistung(t["ergebnis"]))
                           for t in r.teile], r.nicht)
    assert [t["einstellung"]["nenn_v"] for t in r.teile] == [5.0, 9.0, 12.0]
    assert r.teile[0]["ergebnis"]["haelt"] is True                   # 5 V / 3 A angegeben und gehalten
    neun = r.teile[1]
    assert neun["einstellung"]["unbekannt"] and neun["ergebnis"]["abschalt_a"] == 3.5
    w, a = nt.bestleistung(neun["ergebnis"])
    assert 27 < w < 30 and a == 3.25, (w, a)                         # 9 V × 3,25 A
    assert r.nicht == [{"volt": 15.0, "gemessen": 12.05, "grund": "kam nicht"}], r.nicht
    assert r.haelt is False and "nicht unterstützt: 15 V" in r.grund
    assert sum(1 for a, _ in ev if a == "umschalten") == 4
    from akkutest import speicher
    import json
    json.dumps(r.als_dict())                                          # speicherbar


def test_kein_schnellladen():
    q = SimNetzteil(5.0, innen_mohm=100, abschalt_a=2.2)
    basis = nt.NetzteilEinstellung("Alter Lader", 5.0, 0, dauertest=False)
    ab, _ = trigger_durchspielen(q, basis, [(5.0, 0), (9.0, 0)], kann=set())
    r = ab.ergebnis
    print("ohne PD:", r.grund, r.nicht)
    assert [t["einstellung"]["nenn_v"] for t in r.teile] == [5.0]
    assert r.nicht and r.nicht[0]["volt"] == 9.0 and r.nicht[0]["grund"] == "kam nicht"
    w, _ = nt.bestleistung(r.teile[0]["ergebnis"])
    assert 9.5 < w < 11.5, w                                          # 5 V × 2,0–2,2 A


def test_unbekannter_strom_ohne_trigger():
    q = SimNetzteil(12.0, innen_mohm=60, abschalt_a=2.7)
    e = nt.ermitteln(nt.NetzteilEinstellung("Steckernetzteil", 12.0, 0), usb=False)
    assert e.unbekannt and e.nenn_a == 10.0 and not e.dauertest
    ab, _ = durchspielen(q, e, tempo=300)
    r = ab.ergebnis
    print("unbekannt:", r.grund, nt.bestleistung(r.als_dict()))
    assert r.haelt is None and r.abschalt_a == 2.75
    assert abs(nt.bestleistung(r.als_dict())[1] - 2.5) < 1e-6
    # Fühler abgewählt: keine Temperatur, keine Grenze
    q = SimNetzteil(12.0, innen_mohm=50, abschalt_a=9.0, heiz_c_je_w=3.0)
    e = nt.NetzteilEinstellung("Heiß", 12.0, 2.0, stufentest=False, dauer_min=20, temp_grenze=50, fuehler=False)
    r = durchspielen(q, e, tempo=600)[0].ergebnis
    assert r.temp_max is None and not r.zu_heiss and r.urteil == "gut", (r.temp_max, r.grund)


def test_urteil_mit_und_ohne_kabel():
    # wie Lucys Hub: gleichmäßig 0,34 Ω - bei 2 A kommen am Kabelende nur 4,32 V an.
    # Das Kabel wird nicht herausgerechnet: bewertet wird, was beim Gerät ankommt.
    def hub(kabel, innen=340):
        q = SimNetzteil(5.0, innen_mohm=innen, abschalt_a=9)
        e = nt.NetzteilEinstellung("Hub", 5.0, 2.0, stufen=5, stufe_s=10, dauertest=False, kabel_mohm=kabel,
                                   hub=True)
        return durchspielen(q, e)[0].ergebnis
    ohne = hub(0)
    print("Hub ohne Kabelwert:", ohne.urteil, ohne.widerstand_mohm, ohne.laien)
    assert ohne.urteil == "nicht" and ohne.spez_verletzt and ohne.verspricht is True
    assert 320 <= ohne.widerstand_mohm <= 360
    mit = hub(300)
    # gleiches Urteil wie ohne Kabelwert - nur ein Hinweis, wie viel aufs Kabel geht
    assert mit.urteil == ohne.urteil and mit.stufen[-1].buchse_v is None
    assert not mit.kabel_kreis and not mit.kabel_unplausibel
    assert any("auf das Kabel" in g for g in mit.gruende), mit.gruende
    knapp = hub(0, innen=220)               # rund 4,6 V: unter 4,75 V, über 4,40 V
    assert knapp.urteil == "eingeschraenkt" and knapp.spez_verletzt, (knapp.urteil, knapp.gruende)
    assert any("entspricht damit nicht den Vorgaben" in t for t in knapp.laien), knapp.laien
    assert knapp.unter_ab_a is not None and knapp.unter_ab_a <= 2.0
    assert any("Mindestwert wurde unterschritten" in t and "keine stabile Spannung" in t for t in knapp.laien), \
        knapp.laien
    assert any("einzelner Port des Hubs" in t and "10 Watt" in t for t in ohne.laien), ohne.laien
    assert any("§7.2.2" in g for g in knapp.gruende)
    gut = hub(0, innen=60)
    assert gut.urteil == "gut", (gut.urteil, gut.gruende)


def test_pd_grenzen():
    # über 5 V: USB-PD §7.1.8 - ±5 % (grün), höchstens 0,5 V darüber hinaus (gelb), sonst rot
    basis = nt.NetzteilEinstellung("PD", 5.0, 3.0, toleranz_proz=10)
    neun = nt.trigger_einstellung(basis, 9.0, 2.0)
    assert neun.pd and not neun.usb
    assert [round(x, 3) for x in neun.grenzen()] == [8.05, 8.55, 9.45, 9.95], neun.grenzen()
    zwanzig = nt.trigger_einstellung(basis, 20.0, 3.0)
    assert [round(x, 3) for x in zwanzig.grenzen()] == [18.5, 19.0, 21.0, 21.5]
    fuenf = nt.trigger_einstellung(basis, 5.0, 3.0)
    assert not fuenf.pd and fuenf.grenzen() == (4.4, 4.75, 5.25, 5.5)
    # alte gespeicherte Einstellung ohne Feld "pd": wie bisher
    assert not nt.NetzteilEinstellung("alt", 9.0, 2.0).pd


def test_tabelle_wie_urteil():
    # Quest-Netzteil mit 160-mΩ-Kabel: Tabelle zeigt, was am Kabelende ankommt, wie das Urteil
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from akkutest.netzteil_reiter import ergebnis_html
    e = nt.NetzteilEinstellung("Quest", 5.0, 3.0, kabel_mohm=160).__dict__
    st = lambda a, v: {"soll_a": a, "spannung": v, "min_v": v - 0.002, "strom": a, "ok": v >= 4.75, "max_v": v}
    r = {"stufen": [st(2.4, 4.779), st(3.0, 4.678)], "leerlauf_v": 5.165, "max_w": 14.0, "max_w_tol": 11.5,
         "widerstand_mohm": 164}
    h = ergebnis_html(e, r, fach=True)
    assert h.count("⚠ unter 4,75 V") == 1 and h.count("✔") >= 1, h
    assert "1,4 W im Kabel verloren" in h and "15,5 W" in h, h
    assert "im Kabel verloren</td>" in h and "1,44 W (9,3 %)" in h, h      # 3 A: 1,44 W von 15,5 W


def pb(**kw):
    werte = dict(stufen=4, stufe_s=30, dauertest=False, powerbank=True, mindest_a=0.3, fuehler=False)
    werte.update(kw)
    return nt.NetzteilEinstellung("PB", 5.0, 2.0, **werte)


def test_powerbank_nie_unter_mindeststrom():
    e = pb()
    ströme = [s.soll_a for s in nt.plan(e)]
    assert ströme[0] == 0.3 and ströme[-1] == 2.0 and min(ströme) >= 0.3, ströme
    # schaltet sich unter 0,25 A nach 20 s ab - mit 0,3 A Mindeststrom passiert das nicht
    q = SimPowerbank(wh=20, auto_aus_a=0.25, auto_s=20)
    r = durchspielen(q, e)[0].ergebnis
    print("Powerbank Stufen:", r.grund, r.urteil, r.energie_wh)
    assert r.haelt is True and r.abschalt_a is None and r.energie_wh > 0, r.grund
    assert r.leerlauf_v and 4.9 < r.leerlauf_v < 5.1


def test_powerbank_abschaltautomatik():
    # Mindeststrom zu klein: sie geht in der ersten Stufe aus - das soll klar dastehen
    q = SimPowerbank(wh=20, auto_aus_a=0.25, auto_s=20)
    r = durchspielen(q, pb(mindest_a=0.1))[0].ergebnis
    print("Abschaltautomatik:", r.grund)
    assert r.abschalt_a == 0.1 and "Abschaltautomatik" in r.grund, r.grund


def test_powerbank_kapazitaet():
    # 2 Wh drin, 15 % Wandlerverlust: es kommen etwa 1,7 Wh heraus
    q = SimPowerbank(wh=2.0)
    e = pb(stufentest=False, kapazitaet=True, kap_a=1.0, mah=600)          # 600 mAh × 3,7 V = 2,22 Wh
    assert nt.plan(e)[-1].art == "kapazitaet" and not any(s.art == "abschalt" for s in nt.plan(e))
    assert 1000 < nt.geplant_s(e) < 2000
    ab, _ = durchspielen(q, e, frist=60)
    r = ab.ergebnis
    print("Kapazität:", r.grund, r.energie_wh, r.ladung_mah, r.kap_anteil, r.kap_s, r.urteil, r.laien)
    assert r.kap_leer and not r.autoaus and "leer" in r.grund
    assert 1.55 < r.energie_wh < 1.8, r.energie_wh
    assert 300 < r.ladung_mah < 370, r.ladung_mah
    # neu: 2,22 Wh × 82 % = 1,82 Wh am Ausgang → Zustand rund 93 %
    assert 70 < r.kap_anteil < 81 and r.urteil == "gut", (r.kap_anteil, r.urteil, r.gruende)
    assert 88 <= r.zustand_proz <= 98 and r.zustand_geschaetzt, r.zustand_proz
    assert any("Akkuzustand" in s for s in r.laien) and any("geschätzt" in s for s in r.laien), r.laien
    assert r.kap_min_v and r.kap_min_v > 4.75 and any("bis kurz vor leer" in s for s in r.laien)
    # mit "Rated capacity" vom Aufdruck: genau statt geschätzt; 450 mAh × 5 V = 2,25 Wh → gealtert
    e2 = pb(stufentest=False, kapazitaet=True, kap_a=1.0, mah=600, nenn_mah_aus=450)
    r2 = nt.NetzteilErgebnis(energie_wh=r.energie_wh, kap_leer=True, kap_s=1200, leerlauf_v=5.0)
    nt.bewerten(e2, r2)
    assert not r2.zustand_geschaetzt and 70 <= r2.zustand_proz < 80 and r2.urteil == "eingeschraenkt", r2.gruende
    assert any("gealtert" in s for s in r2.laien)
    # gefälscht: 2000 mAh drauf, 2 Wh drin
    q = SimPowerbank(wh=2.0)
    r = durchspielen(q, pb(stufentest=False, kapazitaet=True, kap_a=1.0, mah=2000), frist=60)[0].ergebnis
    print("Fälschung:", r.kap_anteil, r.urteil)
    assert r.kap_anteil < 30 and r.zustand_proz < 40 and r.urteil == "nicht" and r.verspricht is False
    assert any("stimmt nicht" in s for s in r.laien)


def test_powerbank_wartet_auf_knopf():
    q = SimPowerbank(wh=20)
    q.schlaeft = True                         # aus - erst der Knopf schaltet sie ein
    threading.Timer(0.15, q.knopf).start()        # Zeitraffer: 0,15 s sind 30 s
    r = durchspielen(q, pb(stufen=2, stufe_s=10))[0].ergebnis
    assert r.haelt is True and len(r.stufen) == 2, r.grund
    q = SimPowerbank(wh=20)
    q.schlaeft = True                         # niemand drückt
    ab, _ = durchspielen(q, pb(stufen=2, stufe_s=10))
    assert ab.zustand == "abgebrochen" and "eingeschaltet" in ab.ergebnis.grund, ab.ergebnis.grund


def test_powerbank_mit_trigger():
    # erst alle Spannungen, zum Schluss bei 5 V bis leer - die Energie davor zählt mit
    from akkutest.simulator import SimDL24
    q = SimPowerbank(wh=2.0)
    v = SimulatorVerbindung(protokoll="hid", akku=q, tempo=200, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    assert g.erkennen(warten=0.2) == "hid"
    fertig = threading.Event()
    ev = []

    def melden(a, t):
        ev.append((a, t))
        if a == "umschalten":
            # der Mensch am Adapter: Spannung einstellen
            ziel = float(t.split("jetzt ")[1].split(" V")[0])
            threading.Timer(0.05, lambda: setattr(q, "nenn_v", ziel)).start()
        if a == "fertig":
            fertig.set()
    e = pb(stufen=2, stufe_s=10, kapazitaet=True, kap_a=1.0, mah=600)
    ab = nt.TriggerAblauf(e, [(5.0, 2.0), (9.0, 1.0)], g, bei_ereignis=melden)
    g.bei_messwert = ab.messwert
    g.starten()
    assert fertig.wait(60), ev[-3:]
    g.trennen()
    r = ab.ergebnis
    arten = [(t["einstellung"]["nenn_v"], t["einstellung"].get("kapazitaet")) for t in r.teile]
    print("Powerbank mit Trigger:", r.grund, arten, r.urteil)
    assert arten == [(5.0, False), (9.0, False), (5.0, True)], arten
    neun = r.teile[1]["einstellung"]
    assert neun["pd"] and neun["powerbank"] and not neun["kapazitaet"]
    kap = r.teile[2]["ergebnis"]
    vorher = r.teile[0]["ergebnis"]["energie_wh"] + r.teile[1]["ergebnis"]["energie_wh"]
    assert vorher > 0 and kap["kap_leer"] and kap["energie_wh"] > vorher
    assert 1.55 < kap["energie_wh"] < 1.8, kap["energie_wh"]       # alles ab voll, wie ohne Trigger
    assert kap["zustand_proz"] and any("Darin enthalten" in h for h in kap["hinweise"])
    assert "Kapazitätstest" in [t for a, t in ev if a == "umschalten"][-1]
    assert r.haelt is True and r.urteil == "gut", (r.haelt, r.urteil)


def test_zu_hohe_spannung():
    q = SimNetzteil(5.6, innen_mohm=50, abschalt_a=9)
    e = nt.NetzteilEinstellung("Billig", 5.0, 1.0, stufen=2, stufe_s=10, dauertest=False, toleranz_proz=20)
    r = durchspielen(q, e)[0].ergebnis
    assert r.urteil == "nicht" and "Überspannung" in r.gruende[0] and r.spez_verletzt, r.gruende
    assert any("Überspannung" in t and "höchstens 5,25 Volt" in t and "beschädigen" in t for t in r.laien), r.laien
    # leicht drüber (5,3 V): gelb - entspricht nicht der Vorgabe, aber nicht gefährlich
    q = SimNetzteil(5.25, innen_mohm=50, abschalt_a=9)
    r = durchspielen(q, nt.NetzteilEinstellung("Etwas hoch", 5.0, 1.0, stufen=2, stufe_s=10, dauertest=False,
                                                kabel_mohm=50))[0].ergebnis
    assert r.urteil == "eingeschraenkt" and r.spez_verletzt and r.spitze_v > 5.25, (r.urteil, r.spitze_v)


def test_maximum_suchen():
    q = SimNetzteil(5.0, innen_mohm=60, abschalt_a=3.8)
    e = nt.NetzteilEinstellung("Lader", 5.0, 2.0, stufen=4, stufe_s=10, dauertest=False,
                               abschalttest=True, bis_ende=True)
    assert e.hoechster_strom() == 5.0 and nt.plan(e)[-1].soll_a == 5.0
    r = durchspielen(q, e)[0].ergebnis
    print("Maximum:", r.grund, r.max_w, r.max_w_tol)
    assert r.abschalt_a == 3.9 and r.urteil == "gut"
    assert 18 < r.max_w < 19 and r.max_w_tol == r.max_w      # 3,8 A × ~4,82 V
    nie = nt.NetzteilEinstellung("Stark", 5.0, 2.0, stufen=2, stufe_s=10, dauertest=False,
                                 abschalttest=True, bis_ende=True)
    r = durchspielen(SimNetzteil(5.0, innen_mohm=20, abschalt_a=99, heiz_c_je_w=0.5), nie, tempo=300)[0].ergebnis
    assert r.abschalt_a is None and "5 A bei USB" in r.grund and r.max_getestet_a == 5.0, r.grund


def test_unruhige_spannung():
    q = SimNetzteil(5.0, innen_mohm=60, abschalt_a=9, rauschen_v=0.3)
    e = nt.NetzteilEinstellung("Unruhig", 5.0, 1.0, stufen=2, stufe_s=20, dauertest=False, kabel_mohm=60)
    r = durchspielen(q, e)[0].ergebnis
    print("unruhig:", r.urteil, r.schwankung_mv, r.gruende)
    assert r.schwankung_mv > 150 and r.urteil == "eingeschraenkt"
    assert any("unruhig" in t for t in r.laien)
    assert nt.ampel(e, 4.8) == "gruen" and nt.ampel(e, 4.6) == "gelb" and nt.ampel(e, 4.3) == "rot"
    assert nt.ampel(e, 5.3) == "gelb" and nt.ampel(e, 5.6) == "rot"
    ruhig = durchspielen(SimNetzteil(5.0, innen_mohm=60, abschalt_a=9),
                         nt.NetzteilEinstellung("Ruhig", 5.0, 1.0, stufen=2, stufe_s=20, dauertest=False,
                                                kabel_mohm=60))[0].ergebnis
    assert ruhig.schwankung_mv < 20 and ruhig.urteil == "gut", (ruhig.schwankung_mv, ruhig.urteil)


def test_kabel_bewerten():
    assert nt.kabel_bewerten(120, "usbc3")[0] == "gruen"
    a, t = nt.kabel_bewerten(400, "usbc3")
    assert a == "gelb" and "1,9 A" in t, t                  # 0,75 V / 0,4 Ω
    a, t = nt.kabel_bewerten(600, "usbc3")
    assert a == "rot" and "Schrott" in t
    assert nt.kabel_bewerten(160, "usbc5")[0] == "gelb"
    assert nt.kabel_bewerten(450, "usb2")[0] == "gruen"
    assert nt.kabel_bewerten(120, "") is None and nt.kabel_bewerten(0, "usbc3") is None


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
