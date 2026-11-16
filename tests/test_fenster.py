"""Das Fenster wirklich benutzen: Simulator wählen, verbinden, Zelle aus der
Liste nehmen, Test laufen lassen, Ergebnis und Verlauf ansehen.

Läuft ohne Bildschirm (QT_QPA_PLATFORM=offscreen). Mit einem Pfad als
Argument speichert er Bildschirmfotos dorthin.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AKKUTEST_DATEN"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from akkutest import fenster, geraet
from akkutest.simulator import SimAkku, SimulatorVerbindung
from akkutest.speicher import Speicher

geraet.INTERVALL = 0.02       # Zeitraffer: sonst liegen 25 Simulator-Minuten zwischen zwei Werten
FOTOS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
app = QApplication([])
# Rückfragen und Meldungen dürfen den Test nicht anhalten
meldungen = []
QMessageBox.warning = lambda *a, **k: meldungen.append(a[2]) or QMessageBox.Ok
QMessageBox.information = lambda *a, **k: meldungen.append(a[2]) or QMessageBox.Ok
QMessageBox.question = lambda *a, **k: QMessageBox.Yes


def warten(bedingung, frist=30.0):
    ende = time.time() + frist
    while time.time() < ende:
        app.processEvents()
        if bedingung():
            return True
        time.sleep(0.01)
    return False


def foto(w, name):
    if FOTOS:
        FOTOS.mkdir(parents=True, exist_ok=True)
        w.grab().save(str(FOTOS / f"{name}.png"))


def verbinden(f, protokoll):
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – ausprobieren", flags=fenster.Qt.MatchStartsWith)
                                if protokoll == "px100" else f.anschluss.count() - 1)
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None), meldungen
    assert warten(lambda: f.letzter is not None)


def test_ganzer_ablauf():
    SimulatorVerbindung.voreinstellung = {"akku": SimAkku("liion", 1, mah=2700, innen_mohm=38),
                                          "tempo": 300, "bericht_s": 0.02}
    sp = Speicher()
    f = fenster.Fenster(sp)
    f.show()
    assert "Simulator" in f.anschluss.itemText(f.anschluss.count() - 2)
    verbinden(f, "px100")
    assert "fernsteuerbar" in f.status.text(), f.status.text()

    # Erkennen aus der Spannung: 4,18 V → Li-Ion
    vorschlaege = fenster.akkus.erkennen(f.letzter.spannung)
    f._vorschlag_nehmen(vorschlaege[0])
    assert f.typ.currentData() == "liion" and f.zellen.value() == 1
    assert abs(f.abschalt.value() - 3.0) < 0.001

    # Zelle aus der Liste: Samsung 30Q → 3000 mAh, 0,5C = 1,5 A
    i = f.modell.findData("Samsung INR18650-30Q")
    f.modell.setCurrentIndex(i)
    f._modell_gewaehlt()
    assert f.nenn.value() == 3000 and abs(f.strom.value() - 1.5) < 0.001
    f.name.setText("Zelle A")
    foto(f, "1-vor-dem-test")

    f.starten(nachfragen=False)
    assert f.ablauf is not None
    assert warten(lambda: f.ablauf.zustand == "laeuft", 10)
    assert warten(lambda: len(f.ablauf.punkte) > 20, 10)
    foto(f, "2-laeuft")
    assert warten(lambda: not f.ablauf.laeuft, 60), f.ablauf.zustand
    # Das Fenster erfährt das Ende per Signal aus dem Gerätefaden - erst danach steht das Ergebnis da
    assert warten(lambda: f.ergebnis.isVisible() and f.knopf_start.isEnabled(), 10)
    r = f.ablauf.ergebnis
    print("Ergebnis:", r)
    assert r.vollstaendig and 2400 < r.mah < 2710
    html = f.ergebnis.text()
    assert "Zustand" in html and "Verlust" in html, html
    assert f.ergebnis.isVisible()
    foto(f, "3-ergebnis")

    tests = sp.tests(sp.akkus()[0].id)
    assert len(tests) == 1 and tests[0]["vollstaendig"] == 1
    assert sp.akkus()[0].name == "Zelle A" and sp.akkus()[0].modell == "Samsung INR18650-30Q"

    # Zweiter Test desselben Akkus: Verlauf mit zwei Punkten
    SimulatorVerbindung.voreinstellung["akku"] = SimAkku("liion", 1, mah=2600, innen_mohm=45)
    f.trennen()
    assert warten(lambda: f.geraet is None)
    verbinden(f, "px100")
    f.starten(nachfragen=False)
    assert warten(lambda: "Seit dem ersten Test" in f.ergebnis.text(), 60), f.ergebnis.text()
    f.reiter.setCurrentIndex(1)
    app.processEvents()
    assert f.akku_tabelle.rowCount() == 1
    assert f.test_tabelle.rowCount() == 2
    f.test_tabelle.selectRow(0)
    app.processEvents()
    foto(f, "4-verlauf")

    # CSV
    pfad = Path(os.environ["AKKUTEST_DATEN"]) / "x.csv"
    assert sp.csv_schreiben(pfad) == 2
    inhalt = pfad.read_text(encoding="utf-8-sig")
    assert "Zelle A" in inhalt and "Zustand %" in inhalt

    # Diagnose zeigt die Bytes
    f.reiter.setCurrentIndex(4)
    assert "> B1 B2 11" in f.diag.toPlainText()
    assert "< CA CB" in f.diag.toPlainText()
    foto(f, "5-diagnose")
    f.trennen()
    f.close()


def test_geraet_ohne_fernsteuerung():
    SimulatorVerbindung.voreinstellung = {"akku": SimAkku("nimh", 4, mah=1900, innen_mohm=30),
                                          "tempo": 300, "bericht_s": 0.02, "protokoll": "atorch"}
    f = fenster.Fenster(Speicher())
    f.show()
    verbinden(f, "atorch")
    assert "nur Messwerte" in f.status.text()
    assert warten(lambda: f.anz["u"].wert.text().count(",") == 1)
    assert len(f.anz["u"].wert.text().split(",")[1]) == len("3 V"), f.anz["u"].wert.text()   # eine Nachkommastelle
    f.typ.setCurrentIndex(f.typ.findData("nimh"))
    f.zellen.setValue(4)
    f.nenn.setValue(1900)
    f.starten(nachfragen=False)
    assert warten(lambda: f.banner.isVisible() and "Am Gerät einstellen" in f.banner.text(), 5)
    foto(f, "6-ohne-fernsteuerung")
    # Mensch am Gerät
    dev = f.geraet.v.geraet
    dev.soll_a, dev.abschalt_v, dev.an = 0.5, 4.0, True
    assert warten(lambda: not f.ablauf.laeuft and f.ergebnis.isVisible(), 60)
    assert f.ablauf.ergebnis.vollstaendig, f.ablauf.ergebnis.grund
    assert 1700 < f.ablauf.ergebnis.mah < 1910
    f.trennen()
    f.close()


def test_zu_tiefe_abschaltung_wird_abgelehnt():
    SimulatorVerbindung.voreinstellung = {"tempo": 10, "bericht_s": 0.05}
    f = fenster.Fenster(Speicher())
    verbinden(f, "px100")
    f.typ.setCurrentIndex(f.typ.findData("liion"))
    f._abschalt_von_hand = True
    f.abschalt.setValue(2.0)
    meldungen.clear()
    f.starten(nachfragen=False)
    assert f.ablauf is None and meldungen and "zu tief" in meldungen[0]
    f.trennen()
    f.close()


def test_unbekanntes_format_bleibt_verbunden():
    import logging
    SimulatorVerbindung.voreinstellung = {"tempo": 10, "bericht_s": 0.1, "protokoll": "fremd"}
    zeilen = []
    h = logging.Handler()
    h.emit = lambda r: zeilen.append(r.getMessage())
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)
    f = fenster.Fenster(Speicher())
    f.anschluss.setCurrentIndex(f.anschluss.count() - 1)
    meldungen.clear()
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None, 20), meldungen
    assert "Format unbekannt" in f.status.text(), f.status.text()
    assert not f.knopf_start.isEnabled()
    assert meldungen and "Logdatei" in meldungen[0], meldungen
    assert any(z.startswith("< AA 55 01") for z in zeilen), zeilen[:5]
    time = __import__("time")
    time.sleep(0.5)
    app.processEvents()
    assert f.geraet is not None, "Verbindung muss bestehen bleiben"
    logging.getLogger().removeHandler(h)
    f.trennen()
    f.close()


def test_netzteil_reiter():
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 50}
    sp = Speicher()
    f = fenster.Fenster(sp)
    f.resize(1280, 900)
    f.show()
    f.reiter.setCurrentIndex(2)
    assert f.reiter.tabText(2).startswith("Ladegeräte")
    assert not f.nt.knopf_start.isEnabled()                 # nicht verbunden
    assert not f.nt.tests_gruppe.isEnabled() and f.nt.nenn_v.value() == 0   # erst Typenschild
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – USB-Ladegerät", flags=fenster.Qt.MatchStartsWith))
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None), meldungen
    assert warten(lambda: f.letzter is not None)
    assert not f.nt.knopf_start.isEnabled()                 # verbunden, aber noch keine Angaben
    # Watt eintragen → Ampere stellt sich selbst ein, und umgekehrt
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("USB-Hub 10 W", flags=fenster.Qt.MatchStartsWith))
    f.nt._vorlage()
    assert f.nt.vorlage.currentText() == "USB-Hub 10 W – 5 V / 2 A (10 W)", f.nt.vorlage.currentText()
    assert f.nt.knopf_start.isEnabled() and f.nt.tests_gruppe.isEnabled()
    assert f.nt.name.placeholderText() == "USB-Hub 10 W"
    assert f.nt.einstellung().hub and "Port" in f.nt.angabe_hinweis.text()
    assert f.nt.nenn_a.value() == 2.0 and f.nt.nenn_w.value() == 10.0
    f.nt.nenn_w.setValue(12)
    assert abs(f.nt.nenn_a.value() - 2.4) < 1e-9
    f.nt.nenn_a.setValue(3)
    assert f.nt.nenn_w.value() == 15
    f.nt.nenn_v.setValue(9)
    assert f.nt.nenn_a.value() == 3 and f.nt.nenn_w.value() == 27
    f.nt.nenn_a.setValue(0)
    assert f.nt.nenn_w.value() == 0
    assert not f.nt.bereit() and not f.nt.tests_gruppe.isEnabled() and f.nt.sperr_hinweis.isVisible()
    f.nt.unbekannt.setChecked(True)                           # "steht nicht drauf"
    assert f.nt.bereit() and f.nt.tests_gruppe.isEnabled() and not f.nt.nenn_a.isEnabled()
    assert "ermittelt" in f.nt.angabe_hinweis.text()
    # bis zur Abschaltung nur mit Warnung
    f.nt.bis_ende.setChecked(True)
    assert f.nt.warnung_ende.isVisible() and f.nt.mit_abschalt.isChecked() and not f.nt.max_proz.isEnabled()
    f.nt.bis_ende.setChecked(False)
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("USB-Ladegerät 10 W", flags=fenster.Qt.MatchStartsWith))
    f.nt._vorlage()
    assert f.nt.nenn_v.value() == 5.0 and f.nt.nenn_a.value() == 2.0 and f.nt.nenn_w.value() == 10.0
    f.nt.name.setText("Test-Lader")
    f.nt.stufen.setValue(4)
    f.nt.mit_dauer.setChecked(False)
    f.nt.mit_abschalt.setChecked(True)
    f.nt.max_proz.setValue(150)
    assert not f.nt.mit_fuehler.isChecked() and not f.nt.temp_grenze.isEnabled()   # Fühler standardmäßig aus
    f.nt.mit_fuehler.setChecked(True)
    assert f.nt.temp_grenze.isEnabled()
    assert "4,75" in f.nt.angabe_hinweis.text()
    f.nt.starten()
    assert f.nt.laeuft and not f.knopf_start.isEnabled()      # kein Akkutest nebenher
    assert warten(lambda: f.nt.schritt.text().startswith("Stufentest") and "gesamt noch" in f.nt.schritt.text(),
                  10), f.nt.schritt.text()
    foto(f, "7-netzteil-laeuft")
    assert warten(lambda: not f.nt.laeuft and f.nt.ergebnis.isVisible(), 60), f.nt.ablauf.zustand
    r = f.nt.ablauf.ergebnis
    print("Netzteil:", r.grund, r.abschalt_a)
    assert r.haelt is True and r.abschalt_a and 2.6 < r.abschalt_a <= 2.75
    text = f.nt.ergebnis.text()
    assert "Empfehlenswert" in text and "Schafft, was es verspricht" in text, text
    assert "schaltet ab bei 2,70 A" in text and "Kennlinie" in text and "Widerstand" in text, text
    # Ergebnis im eigenen Fenster - öffnet sich nach dem Test von selbst
    from PySide6.QtWidgets import QTextBrowser
    text = f.nt._fenster.findChild(QTextBrowser).toPlainText()
    assert f.nt._fenster.isVisible() and "Kurz gesagt" in text and "Messwerte für Fachleute" in text
    foto(f.nt._fenster, "12-ergebnisfenster")
    f.nt._fenster.close()
    # Bericht als PDF
    pdf = Path(os.environ["AKKUTEST_DATEN"]) / "bericht.pdf"
    assert f.nt.bericht_speichern(str(pdf)) == str(pdf)
    assert pdf.read_bytes()[:4] == b"%PDF" and pdf.stat().st_size > 20000, pdf.stat().st_size
    if FOTOS:
        import shutil
        shutil.copy(pdf, FOTOS / "bericht.pdf")
    # Widerstand als Kabelwert
    assert f.nt.knopf_kabel.isEnabled()
    f.nt.knopf_kabel.click()
    assert 100 <= f.nt.kabel.value() <= 150, f.nt.kabel.value()       # Simulator: 120 mΩ
    f.nt.kabel.setValue(0)
    assert "Temperatur" in text and "°C" in text
    assert not f.geraet.v.geraet.an
    marken = [x.label.toPlainText() for x in f.nt._marken]
    assert marken[:4] == ["0,50 A", "1,00 A", "1,50 A", "2,00 A"] and marken[4] == "↑ 2,10 A", marken
    foto(f, "8-netzteil-ergebnis")
    # gespeichert und in der Liste
    alle = sp.netzteil_tests()
    assert len(alle) == 1 and alle[0]["name"] == "Test-Lader" and alle[0]["haelt"] == 1
    assert f.nt.tabelle.rowCount() == 1
    f.nt.ergebnis.setText("")
    f.nt.tabelle.selectRow(0)
    app.processEvents()
    assert "Empfehlenswert" in f.nt.ergebnis.text()
    assert "✔" in f.nt.tabelle.item(0, 3).text() and "Empfehlenswert" in f.nt.tabelle.item(0, 3).text()
    # Zu großer Kabelwert: keine erfundene Buchsen-Spannung, sondern eine Warnung
    f.nt._grenzen_zeigen(f.nt.einstellung())
    f.nt._kabel_ohm = 0.5
    f.nt._kurven([(0, 5.05, 0.0, None), (10, 4.9, 1.0, None), (20, 4.75, 2.0, None)])
    assert f.nt.kabel_warnung.isVisible() and not f.nt.linie_b.getData()[0]
    f.nt._kabel_ohm = 0.1
    f.nt._kurven([(0, 5.05, 0.0, None), (10, 4.9, 1.0, None), (20, 4.75, 2.0, None)])
    assert not f.nt.kabel_warnung.isVisible() and len(f.nt.linie_b.getData()[0]) == 3
    f.nt._grenzen_zeigen(None)
        # Kabel messen: kurzer Lauf, Wert landet im Feld, nicht in der Liste
    f.nt.kabel.setValue(500)                 # schon ein Wert drin - neu messen muss trotzdem gehen
    f.nt.kabel_messen()
    assert f.nt.laeuft
    assert warten(lambda: not f.nt.laeuft, 60)
    app.processEvents()
    assert 100 <= f.nt.kabel.value() <= 150, f.nt.kabel.value()
    assert len(sp.netzteil_tests()) == 1 and "eingetragen" in f.nt.schritt.text()
    f.nt.kabel.setValue(0)
    f.trennen()
    f.close()


def test_steuerung_von_hand():
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 5}
    f = fenster.Fenster(Speicher())
    f.show()
    f.reiter.setCurrentIndex(3)
    assert f.reiter.tabText(3) == "Steuerung"
    assert not f.steuerung.knopf_ein.isEnabled()
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – USB-Ladegerät", flags=fenster.Qt.MatchStartsWith))
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None and f.letzter is not None), meldungen
    assert f.steuerung.knopf_ein.isEnabled()
    dev = f.geraet.v.geraet
    f.steuerung.strom.setValue(1.25)
    f.steuerung.last(True)
    assert warten(lambda: dev.an and abs(dev.soll_a - 1.25) < 1e-6, 5)
    assert warten(lambda: "an" in f.steuerung.zustand.text() and f.steuerung.anz["i"].wert.text() == "1,250 A", 5), \
        f.steuerung.anz["i"].wert.text()
    f.steuerung.strom.setValue(0.8)
    f.steuerung.strom_setzen()
    assert warten(lambda: abs(dev.soll_a - 0.8) < 1e-6, 5)
    f.steuerung.abschalt.setValue(3.3)
    f.steuerung.abschalt_setzen()
    assert warten(lambda: abs(dev.abschalt_v - 3.3) < 1e-4, 5)
    foto(f, "9-steuerung")
    f.steuerung.last(False)
    assert warten(lambda: not dev.an and "aus" in f.steuerung.zustand.text(), 5)
    # zu viel Leistung wird abgelehnt
    f.steuerung.strom.setValue(19.0)
    f.steuerung.letzter.spannung = 12.0
    meldungen.clear()
    f.steuerung.last(True)
    assert meldungen and "150 W" in meldungen[0]
    # Stop während einer Netzteilprüfung bricht sie ab
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("USB-Ladegerät 10 W", flags=fenster.Qt.MatchStartsWith))
    f.nt._vorlage()
    f.nt.mit_dauer.setChecked(False)
    f.nt.stufen.setValue(2)
    f.nt.starten()
    assert warten(lambda: dev.an, 10)
    assert not f.steuerung.knopf_ein.isEnabled() and f.steuerung.knopf_aus.isEnabled()
    f.steuerung.last(False)
    assert warten(lambda: not f.nt.laeuft and not dev.an, 10)
    f.trennen()
    f.close()


def test_schnellladen_im_fenster():
    from akkutest import netzteil as nt
    nt.TRIGGER_WARTEN_S = 30
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 50}
    sp = Speicher()
    f = fenster.Fenster(sp)
    f.resize(1280, 1000)
    f.show()
    f.reiter.setCurrentIndex(2)
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – USB-Ladegerät", flags=fenster.Qt.MatchStartsWith))
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None and f.letzter is not None), meldungen
    quelle = f.geraet.v.geraet.akku
    f.nt.name.setText("Schnelllader")
    f.nt.schnell.setChecked(True)
    assert f.nt.schnell_box.isVisible() and not f.nt.nenn_v.isEnabled()
    for v, haken, a in f.nt.trigger:
        haken.setChecked(v in (5.0, 9.0, 15.0))
        a.setValue(2.0 if v == 5.0 else 0)
    f.nt.mit_dauer.setChecked(False)
    f.nt.stufen.setValue(2)
    f.nt.stufe_s.setValue(10)
    assert "Umschalten" in f.nt.dauer.text(), f.nt.dauer.text()
    f.nt.starten()
    assert warten(lambda: "jetzt 5 V" in f.nt.schritt.text() and f.nt.knopf_weiter.isVisible(), 5), f.nt.schritt.text()
    assert warten(lambda: "Spannung 1 von 3, danach 9 V, 15 V" in f.nt.schritt.text(), 30), f.nt.schritt.text()
    assert warten(lambda: "jetzt 9 V" in f.nt.schritt.text(), 30), f.nt.schritt.text()
    foto(f, "10-trigger-umschalten")
    quelle.nenn_v = 9.0                      # Mensch drückt am Adapter
    assert warten(lambda: f.nt._nenn_v == 9.0 and f.nt.baender[2].isVisible(), 30)    # Ampel für 9 V
    lo, hi = f.nt.baender[2].getRegion()
    assert abs(lo - 8.55) < 0.01 and abs(hi - 9.45) < 0.01, (lo, hi)
    assert warten(lambda: "jetzt 15 V" in f.nt.schritt.text(), 60), f.nt.schritt.text()
    f.nt.knopf_weiter.click()                # 15 V gibt es nicht
    assert warten(lambda: not f.nt.laeuft and f.nt.ergebnis.isVisible(), 30), f.nt.ablauf.zustand
    text = f.nt.ergebnis.text()
    print(f.nt.ablauf.ergebnis.grund)
    assert "Unterstützt: 5 V, 9 V" in text and "15 V (übersprungen)" in text, text
    assert "Liefert bis" in text and "ermittelt" in text
    marken = [x.label.toPlainText() for x in f.nt._marken]
    assert marken[0] == "5 V 1,00 A" and any(m.startswith("9 V ") for m in marken), marken
    foto(f, "11-trigger-ergebnis")
    alle = sp.netzteil_tests()
    assert alle[0]["name"] == "Schnelllader" and f.nt.tabelle.item(0, 2).text() == "PD/QC 5/9 V", f.nt.tabelle.item(0, 2).text()
    assert f.nt.tabelle.item(0, 4).text().startswith("bis ")
    f.trennen()
    f.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
