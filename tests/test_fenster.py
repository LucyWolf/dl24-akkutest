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
    f.anschluss.setCurrentIndex(f.anschluss.findText("Simulator", flags=fenster.Qt.MatchStartsWith)
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
    f.reiter.setCurrentIndex(2)
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
