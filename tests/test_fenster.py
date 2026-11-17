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
os.environ["AKKUTEST_KEINE_UPDATES"] = "1"
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
    f.reiter.setCurrentIndex(6)
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
    from akkutest import netzteil as nt_mod
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
    # TZT/CKCS-Modul: Schnellladen mit allen Spannungen; 15 V steht im Datenblatt nur als "etc."
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("TZT/CKCS PD65W", flags=fenster.Qt.MatchStartsWith))
    f.nt._vorlage()
    assert f.nt.schnell.isChecked()
    assert [(v, h.isChecked(), a.value()) for v, h, a in f.nt.trigger] == [
        (5.0, True, 3.0), (9.0, True, 3.0), (12.0, True, 3.0), (15.0, True, 3.0), (20.0, True, 3.25), (28.0, False, 0)]
    f.nt.schnell.setChecked(False)
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
    assert warten(lambda: f.nt.anz["r"].wert.text().endswith("mΩ"), 30), f.nt.anz["r"].wert.text()
    assert 80 <= int(f.nt.anz["r"].wert.text().split()[0]) <= 160, f.nt.anz["r"].wert.text()   # Simulator: 120
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
    assert "Grundlage der Grenzwerte" in text and "62680-2-1" in text and "Gesetzlicher Bezug" in text, text
    assert "Messaufbau" in text and "Kabel / Adapter" in text and "nicht bekannt" in text, text
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
    # Diagramm und Ergebnis dürfen sich nicht überlappen - auch mit allen Streifen in einem kleinen Fenster
    f.resize(1280, 800)
    f.nt._kabel_r = 0.137
    f.nt._kurven([(0, 5.06, 0.0, 22.0), (10, 4.9, 1.0, 23.0), (20, 4.75, 2.0, 24.0)])
    f.nt.ergebnis_rahmen.show()
    warten(lambda: False, 0.3)
    fl, er = f.nt.flaeche.geometry(), f.nt.ergebnis_rahmen.geometry()
    assert f.nt.flaeche.parent() is f.nt.ergebnis_rahmen.parent() and fl.bottom() < er.top(), (fl, er)
    f.nt._kabel_r = 0.0
    f.resize(1280, 900)
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
    assert f.nt.kabel_warnung.isVisible() and "zu groß" in f.nt.kabel_warnung.text()
    assert f.nt.linie_b.getData()[0] is None or not len(f.nt.linie_b.getData()[0])
    f.nt._kabel_ohm = 0.1
    f.nt._kurven([(0, 5.05, 0.0, None), (10, 4.9, 1.0, None), (20, 4.75, 2.0, None)])
    assert not f.nt.kabel_warnung.isVisible()
    gelb = list(f.nt.linie_b.getData()[1])
    assert abs(gelb[2] - (4.75 - 0.2)) < 1e-6, gelb                # Mindestwert minus Kabelverlust bei 2 A
    f.nt._kabel_ohm = 0.15                                           # erklärt alles: Kreis
    f.nt._kurven([(0, 5.05, 0.0, None), (10, 4.9, 1.0, None), (20, 4.75, 2.0, None)])
    assert f.nt.kabel_warnung.isVisible() and "genau diesem Netzteil" in f.nt.kabel_warnung.text()
    f.nt._grenzen_zeigen(None)
    # Kabelverlust-Streifen unter Strom/Leistung, nur mit Kabelwert; Zeitachse am untersten Streifen
    f.nt._kabel_r = 0.16
    f.nt._kurven([(0, 5.16, 0.0, None), (10, 4.68, 3.0, 30.0)])
    assert f.nt._mit_kabel and f.nt.box_k.isVisible() and abs(f.nt.linie_kw.getData()[1][1] - 1.44) < 1e-9
    assert abs(f.nt.linie_kp.getData()[1][1] - 1.44 / (4.68 * 3 + 1.44) * 100) < 1e-9
    assert f.nt.bild_t.getAxis("bottom").isVisible() and not f.nt.bild_k.getAxis("bottom").isVisible()
    warten(lambda: False, 0.3)
    foto(f, "13-kabelverlust")
    # Kabel herausgerechnet: auch beim Schnellladen (eigene Achse je Spannung) bleibt die Buchsen-Kurve im Bild
    f.nt._grenzen_zeigen(nt_mod.trigger_einstellung(nt_mod.NetzteilEinstellung("T", 5.0, 3.0, kabel_mohm=114,
                                                                               kabel_raus=True), 5.0, 3.0))
    f.nt._nenn_v, f.nt._teil_ab = 5.0, 1
    f.nt._kurven([(0, 9.0, 0.0, None), (10, 5.06, 0.3, None), (20, 4.78, 2.7, None)])
    oben = f.nt.bild.viewRange()[1][1]
    assert oben > 4.78 + 2.7 * 0.114, (oben, f.nt.bild.viewRange())
    f.nt._teil_ab = 0
    f.nt._grenzen_zeigen(None)
    # Maus darf die Ansicht nicht verstellen
    assert not any(f.nt.bild.vb.state["mouseEnabled"]) and not any(f.nt.bild_i.vb.state["mouseEnabled"])
    f.nt.bild_i.vb.disableAutoRange()
    f.nt._kurven([(0, 5.16, 0.0, None), (10, 4.68, 3.0, 30.0)])
    assert f.nt.bild_i.vb.autoRangeEnabled()[1]
    f.nt._kabel_r = 0.0
    f.nt._kurven([(0, 5.16, 0.0, None), (10, 4.68, 3.0, None)])
    assert not f.nt._mit_kabel and not f.nt.box_k.isVisible() and f.nt.bild_i.getAxis("bottom").isVisible()
        # Kabel messen: kurzer Lauf, Wert landet im Feld, nicht in der Liste
    f.nt.kabel.setValue(500)                 # schon ein Wert drin - neu messen muss trotzdem gehen
    f.nt.kabel_messen()
    assert f.nt.laeuft
    # während einer Prüfung eine alte ansehen: eigenes Fenster, das laufende Diagramm bleibt
    assert warten(lambda: len(f.nt.ablauf.ergebnis.marken) >= 1, 10)
    f.nt._fenster = None
    f.nt.tabelle.clearSelection()
    f.nt.tabelle.selectRow(0)
    app.processEvents()
    assert f.nt._fenster is not None and f.nt._fenster.isVisible()
    from PySide6.QtWidgets import QTextBrowser
    assert "Test-Lader" in f.nt._fenster.findChild(QTextBrowser).toPlainText()
    live = [x.label.toPlainText() for x in f.nt._marken]
    soll = [text for _, text in f.nt.ablauf.ergebnis.marken]
    assert live == soll[:len(live)] and "↑ 2,10 A" not in live, (live, soll)
    f.nt._fenster.close()
    assert warten(lambda: not f.nt.laeuft, 60)
    app.processEvents()
    assert 100 <= f.nt.kabel.value() <= 150, f.nt.kabel.value()
    f.nt.kabel_name.setText("Testkabel 1 m")
    f.nt.kabel_typ.setCurrentIndex(f.nt.kabel_typ.findData("usbc3"))
    assert f.nt.kabel_urteil.isVisible() and "In Ordnung" in f.nt.kabel_urteil.text()
    e = f.nt.einstellung()
    assert e.kabel_name == "Testkabel 1 m" and e.kabel_wann > 0
    from akkutest.netzteil_reiter import messaufbau_html
    t = messaufbau_html(e.__dict__, {})
    assert "Testkabel 1 m" in t and "gemessen am" in t and "herausgerechnet" in t and "Bewertung Kabel" in t, t
    f.nt.kabel_typ.setCurrentIndex(0)
    assert len(sp.netzteil_tests()) == 1 and "eingetragen" in f.nt.schritt.text()
    f.nt.kabel.setValue(0)
    f.trennen()
    f.close()


def test_steuerung_von_hand():
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 5}
    f = fenster.Fenster(Speicher())
    f.show()
    f.reiter.setCurrentIndex(5)
    assert f.reiter.tabText(5) == "Steuerung"
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
    # als eigene Vorlage speichern und wieder laden
    f.nt.vorlage_speichern()
    assert sp.vorlagen()[0][0] == "Schnelllader" and f.nt.vorlage.currentText() == "★ Schnelllader"
    f.nt.schnell.setChecked(False)
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("USB-Hub 10 W", flags=fenster.Qt.MatchStartsWith))
    f.nt._vorlage()
    assert not f.nt.schnell.isChecked() and f.nt.nenn_a.value() == 2.0
    f.nt.vorlage.setCurrentIndex(f.nt.vorlage.findText("★ Schnelllader"))
    f.nt._vorlage()
    assert f.nt.schnell.isChecked() and f.nt.knopf_vorlage_weg.isEnabled()
    assert [(v, h.isChecked(), a.value()) for v, h, a in f.nt.trigger][:3] == [(5.0, True, 2.0), (9.0, True, 0),
                                                                                (12.0, False, 0)]
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
    assert [t for t, _ in f.nt._bilder] == ["5 V", "9 V"], f.nt._bilder      # ein Diagramm je Spannung
    if FOTOS:
        f.nt._bilder[1][1].save(str(FOTOS / "13-bericht-9V.png"))
    alle = sp.netzteil_tests()
    assert alle[0]["name"] == "Schnelllader" and f.nt.tabelle.item(0, 2).text() == "PD/QC 5/9 V", f.nt.tabelle.item(0, 2).text()
    assert f.nt.tabelle.item(0, 4).text().startswith("bis ")
    f.trennen()
    f.close()


def test_kabeltester():
    from akkutest import kabel_reiter as kr
    # Auswertung: Referenz abziehen, Grenzen nach Typ
    d = kr.auswerten(120, 237, "usbc3", 22.0, 31.0)
    assert d["kabel_mohm"] == 117 and d["ampel"] == "gruen" and abs(d["bis_a"] - 0.75 / 0.117) < 0.01
    assert [round(v, 3) for _, v, _ in d["tabelle"]] == [0.117, 0.234, 0.351]
    h = kr.bericht_html(dict(d, name="Testkabel", wann=0))
    assert "117 mΩ" in h and "237 mΩ mit Kabel − 120 mΩ ohne" in h and "+9 K" in h
    assert kr.auswerten(None, 300, "usbc5")["ohne_referenz"]
    # Erwärmung nach USB Type-C Compliance B-6-1: höchstens +30 K
    gut = dict(kr.auswerten(0, 120, "usbc5", 24.0, 41.0), pruef_a=5.0, stabil=True, wann=0)
    assert "✔ bestanden" in kr.bericht_html(gut) and "B-6-1" in kr.bericht_html(gut)
    heiss = dict(kr.auswerten(0, 120, "usbc5", 24.0, 58.0), pruef_a=3.0, stabil=False, wann=0)
    h = kr.bericht_html(heiss)
    assert "✘ nicht bestanden" in h and "gilt nur für 3,0 A" in h and "noch nicht stabil" in h
    # kritisch: 3 A machen +12 K -> +30 K bei 3·√(30/12) ≈ 4,7 A; Spannungsabfall erst bei 0,75/0,12 = 6,25 A
    krit = kr.kritisch(dict(kr.auswerten(0, 120, "usbc5", 24.0, 36.0), pruef_a=3.0))
    assert abs(krit[0] - 3 * (30 / 12) ** 0.5) < 0.01 and "Wärme" in krit[1], krit
    h = kr.bericht_html(dict(kr.auswerten(0, 120, "usbc5", 24.0, 36.0), pruef_a=3.0, stabil=True, wann=0))
    assert "Kritisch ab" in h and "etwa 4,7 A" in h and "unter dem Nennstrom von 5 A" in h, h
    # im Fenster: Referenz ohne Kabel, dann "Kabel" mit 100 mΩ mehr
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 60}
    sp = Speicher()
    f = fenster.Fenster(sp)
    f.resize(1280, 900)
    f.show()
    f.reiter.setCurrentIndex(4)
    assert f.reiter.tabText(4) == "Kabel"
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – USB-Ladegerät", flags=fenster.Qt.MatchStartsWith))
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None and f.letzter is not None), meldungen
    kt = f.kt
    assert kt.mit_dauer.isChecked()                    # Dauertest standardmäßig an
    kt.mit_dauer.setChecked(False)                     # hier zu lang
    kt.name.setText("Testkabel")
    kt.ref_name.setText("Kurz 15 cm")
    kt.strom.setValue(2.0)
    assert kt.knopf_start.isEnabled()
    kt.starten()
    assert kt.laeuft and not f.nt.knopf_start.isEnabled()
    assert warten(lambda: kt.bild_t.isVisible(), 30)              # Temperatur schon während der Referenz
    assert warten(lambda: "Läuft seit" in kt.zeit.text() and "noch etwa" in kt.zeit.text(), 10), kt.zeit.text()
    assert warten(lambda: kt.knopf_weiter.isVisible(), 60), kt.schritt.text()
    assert 100 <= kt._ref <= 140 and "„Kurz 15 cm“ HERAUSZIEHEN" in kt.schritt.text(), kt.schritt.text()
    assert "background:#fff1d6" in kt.schritt.styleSheet()        # auffällig: jetzt muss jemand etwas tun
    assert "⚠ Die Referenz hat" in kt.schritt.text()          # 120 mΩ: über 80 mΩ
    f.geraet.v.geraet.akku.innen += 0.100          # jetzt steckt ein Kabel mit 100 mΩ dazwischen
    kt.knopf_weiter.click()
    assert warten(lambda: not kt.laeuft and kt.ergebnis.isVisible(), 90), kt.schritt.text()
    d = kt._letztes
    print("Kabel:", d["kabel_mohm"], d["ref_mohm"], d["gesamt_mohm"], d["ampel"])
    assert 80 <= d["kabel_mohm"] <= 120 and d["ampel"] == "gruen" and d["nenn_a"] == 3.0, d
    assert "Taugt bis" in kt.ergebnis.text() and "3 A – mehr ist" in kt.ergebnis.text()
    assert "Referenzkabel „Kurz 15 cm“" in kt.ergebnis.text()
    # die Referenz wurde gespeichert - beim nächsten Mal ohne Schritt 1
    assert kt.ref_wahl.count() == 2 and "Kurz 15 cm" in kt.ref_wahl.itemText(1)
    kt.ref_wahl.setCurrentIndex(1)
    kt.starten()
    assert kt.phase == "kabel" and kt.laeuft and 100 <= kt._ref <= 140
    kt.abbrechen()
    assert warten(lambda: not kt.laeuft, 10)
    kt.ref_wahl.setCurrentIndex(0)
    assert "Geprüft mit" in kt.ergebnis.text() and "W</b> (2,00 A" in kt.ergebnis.text(), kt.ergebnis.text()
    assert kt.tabelle.rowCount() == 1 and "Testkabel" in kt.tabelle.item(0, 1).text()
    foto(f, "16-kabeltester")
    kt.uebernehmen()
    assert f.nt.kabel.value() == d["kabel_mohm"] and f.pb.kabel.value() == d["kabel_mohm"]
    assert f.nt.kabel_name.text() == "Testkabel"
    pdf = Path(os.environ["AKKUTEST_DATEN"]) / "kabel.pdf"
    assert kt.bericht_speichern(str(pdf)) == str(pdf) and pdf.stat().st_size > 5000
    bild = kr.diagramm_bild(dict(d, kurve=[[0, 5.0, 0, 25.0], [60, 4.9, 1.0, 27.0], [120, 4.8, 2.0, 30.0]],
                                 temp_start=25.0))
    assert bild.width() >= 800 and bild.height() >= 400, (bild.width(), bild.height())
    assert bild.pixelColor(5, 5).lightness() > 240            # heller Grund, auch im dunklen Design
    if FOTOS:
        bild.save(str(FOTOS / "17-kabel-diagramm.png"))
        import shutil
        shutil.copy(pdf, FOTOS / "kabel.pdf")
    # über den Trigger-Adapter: Referenz bei 5 und 9 V, dann mit Kabel bei 5 und 9 V
    from akkutest import netzteil as nt_mod
    nt_mod.TRIGGER_WARTEN_S = 30
    quelle = f.geraet.v.geraet.akku
    quelle.innen -= 0.100                          # Kabel wieder weg
    kt.alle_v.setChecked(True)
    for v, h in kt.spannungen:
        h.setChecked(v in (5.0, 9.0))
    # mit Dauertest: standardmäßig bei jeder Spannung, wahlweise nur bei der niedrigsten
    kt.mit_dauer.setChecked(True)
    kt.phase = "kabel"
    assert kt.dauer_jede.isChecked()
    kt._lauf(kt._einstellung(ref=False))
    ab = kt.ablauf
    assert ab.einstellung_fuer(5.0, 2.0).dauertest and ab.einstellung_fuer(9.0, 2.0).dauertest
    ab.abbrechen()
    kt.dauer_jede.setChecked(False)
    kt._lauf(kt._einstellung(ref=False))
    ab = kt.ablauf
    assert ab.einstellung_fuer(5.0, 2.0).dauertest and not ab.einstellung_fuer(9.0, 2.0).dauertest
    ab.abbrechen()
    kt.dauer_jede.setChecked(True)
    kt.mit_dauer.setChecked(False)
    kt.strom.setValue(2.0)
    import threading as th, time as tm
    halt = th.Event()

    def adapter():                                 # der Mensch am Trigger-Adapter
        while not halt.is_set():
            text = kt.schritt.text()
            for v in (5.0, 9.0):
                if f"jetzt {v:g} V" in text:
                    quelle.nenn_v = v
            if "auf 5 V stellen" in text:
                quelle.nenn_v = 5.0
            tm.sleep(0.02)
    th.Thread(target=adapter, daemon=True).start()
    quelle.nenn_v = 5.0
    kt.starten()
    assert warten(lambda: kt.knopf_weiter.isVisible(), 90), kt.schritt.text()
    assert "Spannung" in kt.zeit.text() or kt.zeit.text() == "", kt.zeit.text()
    assert isinstance(kt._ref, dict) and set(kt._ref) == {5.0, 9.0}, kt._ref
    quelle.innen += 0.080
    quelle.nenn_v = 5.0
    kt.knopf_weiter.click()
    assert warten(lambda: not kt.laeuft and "Mittel über" in kt.schritt.text(), 120), kt.schritt.text()
    halt.set()
    d = kt._letztes
    print("Kabel je Spannung:", d["je_spannung"], d["kabel_mohm"])
    assert [x[0] for x in d["je_spannung"]] == [5.0, 9.0] and 60 <= d["kabel_mohm"] <= 100, d
    assert all(x[5] is not None for x in d["je_spannung"]) and "Stecker max." in kt.ergebnis.text()
    assert all(x[6] and x[7] for x in d["je_spannung"]) and "Leistung" in kt.ergebnis.text()
    assert "Je Spannung" in kt.ergebnis.text() and "9 V" in kt.ergebnis.text()
    quelle.innen -= 0.080
    f.nt.kabel.setValue(0)
    f.pb.kabel.setValue(0)
    f.trennen()
    f.close()


def test_update_leiste():
    f = fenster.Fenster(Speicher())
    f.show()
    assert f.knopf_update.isVisible() and not f.update_leiste.isVisible()
    f._update_stand({"neuer": True, "verfuegbar": "9.9.9", "installiert": fenster.VERSION, "aktualisierbar": True})
    assert f.update_leiste.isVisible() and "9.9.9" in f.update_text.text() and f.knopf_jetzt.isVisible()
    f._update_von_hand = True
    f._update_stand({"neuer": False, "installiert": fenster.VERSION, "fehler": None})
    assert "neueste Version" in f.banner.text() and f.banner.isVisible()
    # kommt danach doch eine neue: die alte Meldung verschwindet
    f._update_stand({"neuer": True, "verfuegbar": "9.9.10", "installiert": fenster.VERSION, "aktualisierbar": True})
    assert not f.banner.isVisible() and "9.9.10" in f.update_text.text()
    assert "color:#1b5e20" in f.update_leiste.styleSheet() and "QPushButton" in f.update_leiste.styleSheet()
    f.close()


def test_powerbank_im_fenster():
    from akkutest import netzteil as nt
    geraet.HID_INTERVALL = 0.02
    SimulatorVerbindung.voreinstellung = {"tempo": 100}
    sp = Speicher()
    f = fenster.Fenster(sp)
    f.resize(1280, 1000)
    f.show()
    f.reiter.setCurrentIndex(3)
    assert f.reiter.tabText(3) == "Powerbanks"
    pb = f.pb
    assert pb.schnell.isVisible() and not pb.schnell_box.isVisible() and not pb.unbekannt.isVisible() and pb.mah.isVisible()
    assert not pb.knopf_start.isEnabled() and not pb.tests_gruppe.isEnabled()
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator – Powerbank", flags=fenster.Qt.MatchStartsWith))
    f.verbinden_umschalten()
    assert warten(lambda: f.geraet is not None and f.letzter is not None), meldungen
    # bekannte Modelle bringen die Kapazität gleich mit
    pb.vorlage.setCurrentIndex(pb.vorlage.findText("INIU MegaPower", flags=fenster.Qt.MatchStartsWith))
    pb._vorlage()
    assert pb.nenn_a.value() == 3.0 and pb.mah.value() == 20000 and pb.wh.value() == 74
    assert pb.einstellung().name.startswith("INIU") and pb.einstellung().aufdruck_wh == 74
    assert [(v, h.isChecked(), a.value()) for v, h, a in pb.trigger][:3] == [(5.0, True, 3.0), (9.0, True, 2.22),
                                                                            (12.0, True, 1.5)]
    assert pb.schnell.isChecked()                       # die INIU kann PD - Haken kommt mit
    assert pb.modus.currentData() == "last" and not pb.mit_kap.isChecked()
    pb.modus.setCurrentIndex(pb.modus.findData("beides"))
    plan = pb._plan()
    assert [(e.nenn_v, e.kapazitaet) for e in plan] == [(5, False), (9, False), (12, False), (5, True)], plan
    assert "Umschalten" in pb.dauer.text() and pb.schnell.isVisible() and pb.schnell_box.isVisible()
    # nur Kapazität: 5 V, ohne Trigger-Adapter und ohne Lasttest
    pb.modus.setCurrentIndex(pb.modus.findData("kap"))
    assert not pb.schnell.isChecked() and not pb.schnell.isEnabled() and not pb.mit_stufen.isEnabled()
    e = pb.einstellung()
    assert e.kapazitaet and not (e.stufentest or e.dauertest or e.abschalttest)
    assert [s.art for s in nt.plan(e)] == ["kapazitaet"] and len(pb._plan()) == 1
    pb.modus.setCurrentIndex(pb.modus.findData("last"))
    assert pb.schnell.isChecked() and pb.mit_stufen.isEnabled() and not pb.mit_kap.isChecked()   # wie vorher
    pb.schnell.setChecked(False)
    pb.vorlage.setCurrentIndex(pb.vorlage.findText("Anker 325", flags=fenster.Qt.MatchStartsWith))
    pb._vorlage()
    assert pb.nenn_a.value() == 2.4 and pb.mah.value() == 20000 and pb.wh.value() == 0
    pb.vorlage.setCurrentIndex(pb.vorlage.findText("Powerbank 10 W", flags=fenster.Qt.MatchStartsWith))
    pb._vorlage()
    assert pb.nenn_a.value() == 2.0 and pb.knopf_start.isEnabled()
    assert f.nt.vorlage.findText("Powerbank 10 W", flags=fenster.Qt.MatchStartsWith) < 0   # nicht beim Netzteil
    pb.name.setText("Test-Powerbank")
    pb.mah.setValue(600)
    assert "2,2 Wh" in pb.angabe_hinweis.text(), pb.angabe_hinweis.text()
    pb.stufen.setValue(2)
    pb.stufe_s.setValue(10)
    pb.modus.setCurrentIndex(pb.modus.findData("beides"))
    assert pb.mit_abschalt.isEnabled()                  # geht zusammen: erst Abschalttest, dann Kapazität
    e = pb.einstellung()
    assert e.powerbank and e.kapazitaet and e.mah == 600 and e.mindest_a == 0.3 and not e.hub
    assert "Kapazitätstest" in pb.dauer.text(), pb.dauer.text()
    pb.starten()
    assert pb.laeuft and not f.nt.knopf_start.isEnabled() and not f.knopf_start.isEnabled()
    assert warten(lambda: "Kapazitätstest" in pb.schritt.text(), 30), pb.schritt.text()
    foto(f, "14-powerbank-laeuft")
    # "fertig" kommt im Gerätefaden - das Fenster zeigt es erst einen Moment später
    assert warten(lambda: not pb.laeuft and pb.ergebnis.isVisible() and pb.ergebnis.text(), 90), pb.ablauf.zustand
    r = pb.ablauf.ergebnis
    print("Powerbank:", r.grund, r.energie_wh, r.kap_anteil, r.urteil)
    assert r.kap_leer and r.urteil == "gut"
    text = pb.ergebnis.text()
    assert "Abgegeben" in text and "vom Aufdruck" in text and "600 mAh" in text and "Akkuzustand" in text, text
    from PySide6.QtWidgets import QTextBrowser
    gross = pb._fenster.findChild(QTextBrowser).toPlainText()
    assert "Kurz gesagt" in gross and "Wattstunden" in gross and "nie weniger als 0,30 Ampere" in gross, gross
    foto(pb._fenster, "15-powerbank-ergebnis")
    pb._fenster.close()
    assert pb.tabelle.rowCount() == 1 and "Wh" in pb.tabelle.item(0, 4).text()
    # Netzteil-Liste bleibt sauber (frühere Tests haben dort schon Einträge)
    assert all(not d["einstellung"].get("powerbank") for d in f.nt._alle)
    assert len(sp.netzteil_tests()) == len(f.nt._alle) + 1
    pdf = Path(os.environ["AKKUTEST_DATEN"]) / "powerbank.pdf"
    assert pb.bericht_speichern(str(pdf)) == str(pdf) and pdf.stat().st_size > 20000
    if FOTOS:
        import shutil
        shutil.copy(pdf, FOTOS / "powerbank.pdf")
    # eigene Vorlage: nur im Powerbank-Reiter, mit Kapazität
    pb.vorlage_speichern()
    assert pb.vorlage.currentText() == "★ Test-Powerbank"
    pb.mah.setValue(0)
    pb._vorlage()
    assert pb.mah.value() == 600
    f.nt.vorlagen_laden()
    assert f.nt.vorlage.findText("★ Test-Powerbank") < 0
    f.trennen()
    f.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
