"""Das Programmfenster: Verbinden, Akku wählen, testen, Verlauf ansehen."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from . import akkus, verbindung
from .ablauf import Ablauf, Einstellung
from .geraet import Geraet, Messwert
from .protokoll import hex_text
from .speicher import Speicher, datenordner

log = logging.getLogger("akkutest")
WURZEL = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
VERSION = (Path(__file__).resolve().parent / "VERSION").read_text().strip()
NEUER_AKKU = -1


def protokoll_einrichten() -> Path:
    pfad = datenordner() / "akkutest.log"
    h = logging.handlers.RotatingFileHandler(pfad, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    wurzel = logging.getLogger()
    wurzel.addHandler(h)
    wurzel.setLevel(logging.INFO)
    return pfad


def gedaempft() -> str:
    """Graue Nebenschrift, die in hellem und dunklem Design lesbar bleibt:
    die normale Schriftfarbe, halb durchsichtig."""
    c = QApplication.palette().windowText().color()
    return f"color: rgba({c.red()}, {c.green()}, {c.blue()}, 0.62);"


def dauer_text(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def zahl(x: float | None, stellen: int = 2, einheit: str = "") -> str:
    if x is None:
        return "–"
    return f"{x:.{stellen}f}".replace(".", ",") + (f" {einheit}" if einheit else "")


class Bruecke(QObject):
    """Nachrichten aus den Hintergrund-Fäden in den Qt-Faden."""
    messwert = Signal(object)
    ereignis = Signal(str, str)
    roh = Signal(str, bytes)
    fehler = Signal(str)
    verbunden = Signal(object, str)        # Geraet oder None, Fehlertext
    gefunden = Signal(object, str)         # Liste Anschlüsse, Fehlertext


class Anzeige(QFrame):
    """Ein großer Messwert mit Beschriftung."""

    def __init__(self, titel: str) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        t = QLabel(titel)
        t.setStyleSheet(gedaempft() + " font-size: 11px;")
        self.wert = QLabel("–")
        f = QFont()
        f.setPointSize(17)
        f.setBold(True)
        self.wert.setFont(f)
        lay.addWidget(t)
        lay.addWidget(self.wert)

    def setzen(self, text: str) -> None:
        self.wert.setText(text)


class Fenster(QMainWindow):
    def __init__(self, speicher: Speicher | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"DL24 Akkutest {VERSION}")
        icon = WURZEL / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1180, 760)
        self.speicher = speicher or Speicher()
        self.b = Bruecke()
        self.geraet: Geraet | None = None
        self.ablauf: Ablauf | None = None
        self.letzter: Messwert | None = None
        self.akku_id: int | None = None
        self._abschalt_von_hand = False
        self._ble: list[verbindung.Anschluss] = []

        self.b.messwert.connect(self._messwert)
        self.b.ereignis.connect(self._ereignis)
        self.b.roh.connect(self._roh)
        self.b.fehler.connect(self._verbindung_weg)
        self.b.verbunden.connect(self._verbunden)
        self.b.gefunden.connect(self._ble_gefunden)

        mitte = QWidget()
        self.setCentralWidget(mitte)
        lay = QVBoxLayout(mitte)
        lay.addLayout(self._leiste())
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        lay.addWidget(self.banner)
        self.reiter = QTabWidget()
        self.reiter.addTab(self._reiter_test(), "Test")
        self.reiter.addTab(self._reiter_akkus(), "Akkus && Verlauf")
        self.reiter.addTab(self._reiter_diagnose(), "Diagnose")
        self.reiter.currentChanged.connect(lambda i: i == 1 and self._akkus_laden())
        lay.addWidget(self.reiter)

        self.anschluesse_laden()
        self._akku_liste_laden()
        self._zustand_zeigen()

    # ==================================================================
    # Verbindung
    # ==================================================================
    def _leiste(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(QLabel("Anschluss:"))
        self.anschluss = QComboBox()
        self.anschluss.setMinimumWidth(340)
        h.addWidget(self.anschluss, 1)
        self.knopf_neu = QPushButton("↻")
        self.knopf_neu.setToolTip("USB neu einlesen (DL24 über das USB-Kabel: genaue Spannung)")
        self.knopf_neu.clicked.connect(self.anschluesse_laden)
        h.addWidget(self.knopf_neu)
        self.knopf_ble = QPushButton("Bluetooth suchen")
        self.knopf_ble.clicked.connect(self.ble_suchen)
        h.addWidget(self.knopf_ble)
        self.knopf_verbinden = QPushButton("Verbinden")
        self.knopf_verbinden.clicked.connect(self.verbinden_umschalten)
        h.addWidget(self.knopf_verbinden)
        self.status = QLabel("nicht verbunden")
        self.status.setMinimumWidth(260)
        h.addWidget(self.status)
        return h

    def anschluesse_laden(self) -> None:
        vorher = self.anschluss.currentData()
        self.anschluss.clear()
        liste = verbindung.hid_anschluesse() + verbindung.serielle_anschluesse() + self._ble
        for a in liste:
            self.anschluss.addItem(a.name, a)
        self.anschluss.addItem("Simulator – ausprobieren ohne Gerät", verbindung.Anschluss("sim", "sim:px100", "Simulator"))
        self.anschluss.addItem("Simulator – Gerät ohne Fernsteuerung",
                               verbindung.Anschluss("sim", "sim:atorch", "Simulator (nur Berichte)"))
        if vorher:
            for i in range(self.anschluss.count()):
                if self.anschluss.itemData(i).adresse == vorher.adresse:
                    self.anschluss.setCurrentIndex(i)

    def ble_suchen(self) -> None:
        self.knopf_ble.setEnabled(False)
        self.knopf_ble.setText("suche …")

        def suchen():
            try:
                self.b.gefunden.emit(verbindung.ble_suchen(), "")
            except Exception as e:
                self.b.gefunden.emit([], str(e))

        threading.Thread(target=suchen, daemon=True).start()

    def _ble_gefunden(self, liste, fehler: str) -> None:
        self.knopf_ble.setEnabled(True)
        self.knopf_ble.setText("Bluetooth suchen")
        if fehler:
            QMessageBox.warning(self, "Bluetooth", fehler)
            return
        self._ble = liste
        self.anschluesse_laden()
        if liste:
            self.anschluss.setCurrentIndex(self.anschluss.findData(liste[0]))
        else:
            QMessageBox.information(self, "Bluetooth", "Kein Bluetooth-Gerät gefunden.\n\n"
                                    "Ist der DL24 eingeschaltet und die Handy-App getrennt?")

    def verbinden_umschalten(self) -> None:
        if self.geraet:
            self.trennen()
            return
        a: verbindung.Anschluss = self.anschluss.currentData()
        if not a:
            return
        self.knopf_verbinden.setEnabled(False)
        self.status.setText(f"verbinde mit {a.adresse} …")
        log.info("Verbinden: %s", a)

        def verbinden():
            try:
                v = verbindung.oeffnen(a)
                for zeile in v.info:
                    self.b.roh.emit("i", zeile.encode())
                g = Geraet(v, bei_roh=lambda r, d: self.b.roh.emit(r, d))
                try:
                    g.erkennen()
                except Exception:
                    v.schliessen()
                    raise
                self.b.verbunden.emit(g, "")
            except Exception as e:
                log.exception("Verbinden")
                self.b.roh.emit("i", f"Fehler: {e}".encode())
                self.b.verbunden.emit(None, str(e))

        threading.Thread(target=verbinden, daemon=True).start()

    def _verbunden(self, g: Geraet | None, fehler: str) -> None:
        self.knopf_verbinden.setEnabled(True)
        if g is None:
            self.status.setText("nicht verbunden")
            QMessageBox.warning(self, "Verbinden", fehler)
            return
        self.geraet = g
        g.bei_messwert = self._messwert_faden
        g.bei_fehler = lambda t: self.b.fehler.emit(t)
        g.starten()
        self._zustand_zeigen()
        if g.protokoll == "unbekannt":
            QMessageBox.information(
                self, "Verbunden",
                "Der DL24 ist verbunden und sendet Daten – aber in einem Format, das die App noch "
                "nicht kennt. Messen und Testen gehen deshalb noch nicht.\n\n"
                "Die Verbindung bleibt bestehen, und alles, was ankommt, wird in die Logdatei "
                f"geschrieben:\n{datenordner() / 'akkutest.log'}\n\n"
                "Lass sie ein paar Sekunden laufen und schick die Datei – damit wird das Format eingebaut.")

    def trennen(self) -> None:
        if self.ablauf and self.ablauf.laeuft:
            if not self._frage("Trennen", "Es läuft ein Test. Wirklich trennen? Der Test wird abgebrochen."):
                return
            self.abbrechen(ohne_frage=True)
        g, self.geraet = self.geraet, None
        if g:
            threading.Thread(target=g.trennen, daemon=True).start()
        self.letzter = None
        self._zustand_zeigen()

    def _verbindung_weg(self, grund: str) -> None:
        if not self.geraet:
            return
        self.geraet = None
        if self.ablauf and self.ablauf.laeuft:
            self.ablauf.zustand = "abgebrochen"
            self.ablauf.ergebnis.grund = f"Verbindung verloren: {grund}"
            self._test_fertig()
            grund += ("\n\nDer Test wurde abgebrochen. Die Last läuft am Gerät womöglich weiter - "
                      "die Abschaltspannung am Gerät beendet sie.")
        self._zustand_zeigen()
        QMessageBox.warning(self, "Verbindung", grund)

    def _zustand_zeigen(self) -> None:
        g = self.geraet
        self.knopf_verbinden.setText("Trennen" if g else "Verbinden")
        self.anschluss.setEnabled(not g)
        self.knopf_ble.setEnabled(not g)
        if g:
            if g.protokoll == "unbekannt":
                self.status.setText("✔ verbunden – Format unbekannt (Daten werden mitgeschrieben)")
            else:
                if g.protokoll == "hid":
                    art = "USB, nur Messwerte" + (f" (Firmware {g.firmware})" if g.firmware else "")
                else:
                    art = "fernsteuerbar (PX100)" if g.kann_steuern else "nur Messwerte (Atorch-Bericht)"
                self.status.setText(f"✔ verbunden – {art}")
        else:
            self.status.setText("nicht verbunden")
        laeuft = bool(self.ablauf and self.ablauf.laeuft)
        bekannt = bool(g) and g.protokoll != "unbekannt"
        self.knopf_start.setEnabled(bekannt and not laeuft)
        self.knopf_abbruch.setEnabled(laeuft)
        self.knopf_erkennen.setEnabled(bekannt and not laeuft)
        for w in (self.akku_wahl, self.name, self.modell, self.typ, self.zellen, self.nenn, self.strom, self.abschalt):
            w.setEnabled(not laeuft)
        self.diag_info.setText(
            f"Protokoll: {g.protokoll if g else '–'}    Logdatei: {datenordner() / 'akkutest.log'}")

    # ==================================================================
    # Reiter Test
    # ==================================================================
    def _reiter_test(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)

        links = QVBoxLayout()
        gruppe = QGroupBox("Akku")
        f = QFormLayout(gruppe)
        self.akku_wahl = QComboBox()
        self.akku_wahl.currentIndexChanged.connect(self._akku_gewaehlt)
        f.addRow("Akku:", self.akku_wahl)
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. Akkuschrauber 1 oder Zelle #3")
        f.addRow("Name:", self.name)
        self.modell = QComboBox()
        self.modell.setEditable(True)
        self.modell.addItem("")
        for z in akkus.ZELLEN:
            self.modell.addItem(f"{z.name}  ({z.mah} mAh)", z.name)
        self.modell.lineEdit().setPlaceholderText("bekannte Zelle wählen oder frei eintragen")
        self.modell.activated.connect(self._modell_gewaehlt)
        f.addRow("Modell:", self.modell)
        self.typ = QComboBox()
        for t in akkus.TYPEN.values():
            self.typ.addItem(t.name, t.schluessel)
        self.typ.currentIndexChanged.connect(self._typ_geaendert)
        f.addRow("Typ:", self.typ)
        self.zellen = QSpinBox()
        self.zellen.setRange(1, 48)
        self.zellen.setSuffix(" Zelle(n) in Reihe")
        self.zellen.valueChanged.connect(self._typ_geaendert)
        f.addRow("Zellen:", self.zellen)
        self.nenn = QSpinBox()
        self.nenn.setRange(0, 1_000_000)
        self.nenn.setSingleStep(100)
        self.nenn.setSuffix(" mAh")
        self.nenn.setSpecialValueText("unbekannt")
        self.nenn.valueChanged.connect(self._dauer_schaetzen)
        f.addRow("Nennkapazität:", self.nenn)
        self.knopf_erkennen = QPushButton("Typ aus der Spannung erkennen")
        self.knopf_erkennen.setToolTip("Nur bei voll geladenem Akku und ausgeschalteter Last sinnvoll")
        self.knopf_erkennen.clicked.connect(self.erkennen)
        f.addRow("", self.knopf_erkennen)
        self.typ_hinweis = QLabel()
        self.typ_hinweis.setWordWrap(True)
        self.typ_hinweis.setStyleSheet(gedaempft())
        f.addRow(self.typ_hinweis)
        links.addWidget(gruppe)

        gruppe = QGroupBox("Entladung")
        f = QFormLayout(gruppe)
        zeile = QHBoxLayout()
        self.strom = QDoubleSpinBox()
        self.strom.setRange(0.05, 20.0)
        self.strom.setDecimals(2)
        self.strom.setSingleStep(0.1)
        self.strom.setSuffix(" A")
        self.strom.setValue(1.0)
        self.strom.valueChanged.connect(self._dauer_schaetzen)
        zeile.addWidget(self.strom, 1)
        for c in (0.2, 0.5, 1.0):
            k = QPushButton(f"{c:g}C".replace(".", ","))
            k.setToolTip(f"{c:g} × Nennkapazität".replace(".", ","))
            k.setFixedWidth(46)
            k.clicked.connect(lambda _=False, c=c: self._c_rate(c))
            zeile.addWidget(k)
        f.addRow("Strom:", zeile)
        self.abschalt = QDoubleSpinBox()
        self.abschalt.setRange(0.5, 200.0)
        self.abschalt.setDecimals(2)
        self.abschalt.setSingleStep(0.05)
        self.abschalt.setSuffix(" V")
        self.abschalt.editingFinished.connect(lambda: setattr(self, "_abschalt_von_hand", True))
        f.addRow("Abschaltung bei:", self.abschalt)
        self.dauer = QLabel()
        f.addRow("Dauer etwa:", self.dauer)
        knoepfe = QHBoxLayout()
        self.knopf_start = QPushButton("▶  Test starten")
        self.knopf_start.setStyleSheet("font-weight: bold; padding: 8px;")
        self.knopf_start.clicked.connect(lambda: self.starten())
        self.knopf_abbruch = QPushButton("■  Abbrechen")
        self.knopf_abbruch.setStyleSheet("padding: 8px;")
        self.knopf_abbruch.clicked.connect(lambda: self.abbrechen())
        knoepfe.addWidget(self.knopf_start, 2)
        knoepfe.addWidget(self.knopf_abbruch, 1)
        f.addRow(knoepfe)
        links.addWidget(gruppe)
        links.addStretch(1)
        lw = QWidget()
        lw.setLayout(links)
        lw.setMaximumWidth(430)
        h.addWidget(lw)

        rechts = QVBoxLayout()
        raster = QGridLayout()
        self.anz = {}
        for i, (k, t) in enumerate([("u", "Spannung"), ("i", "Strom"), ("p", "Leistung"), ("t", "Temperatur"),
                                    ("mah", "Kapazität"), ("wh", "Energie"), ("zeit", "Laufzeit"),
                                    ("proz", "Zustand")]):
            self.anz[k] = Anzeige(t)
            raster.addWidget(self.anz[k], i // 4, i % 4)
        rechts.addLayout(raster)
        self.kurve_bild = pg.PlotWidget()
        self.kurve_bild.setBackground(None)
        self.kurve_bild.showGrid(x=True, y=True, alpha=0.25)
        self.kurve_bild.setLabel("left", "Spannung (V)")
        self.kurve_bild.setLabel("bottom", "Zeit (min)")
        self.kurve_linie = self.kurve_bild.plot([], [], pen=pg.mkPen("#2f80ed", width=2))
        self.grenz_linie = pg.InfiniteLine(angle=0, pen=pg.mkPen("#d03b3b", width=1, style=Qt.DashLine))
        self.grenz_linie.hide()            # erst beim Test, sonst zieht sie die Achse auf 0
        self.kurve_bild.addItem(self.grenz_linie)
        self.kurve_bild.setYRange(0, 5)
        self._ohne_vorsatz(self.kurve_bild)
        rechts.addWidget(self.kurve_bild, 1)
        self.ergebnis = QLabel()
        self.ergebnis.setWordWrap(True)
        self.ergebnis.setTextFormat(Qt.RichText)
        self.ergebnis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ergebnis.setFrameShape(QFrame.StyledPanel)
        self.ergebnis.setMargin(10)
        self.ergebnis.hide()
        rechts.addWidget(self.ergebnis)
        h.addLayout(rechts, 1)

        self._typ_geaendert()
        return w

    def _akku_liste_laden(self, auswaehlen: int | None = None) -> None:
        self.akku_wahl.blockSignals(True)
        self.akku_wahl.clear()
        self.akku_wahl.addItem("＋ Neuer Akku", NEUER_AKKU)
        for a in self.speicher.akkus():
            self.akku_wahl.addItem(f"{a.name}" + (f"  –  {a.modell}" if a.modell else ""), a.id)
        if auswaehlen is not None:
            self.akku_wahl.setCurrentIndex(max(0, self.akku_wahl.findData(auswaehlen)))
        self.akku_wahl.blockSignals(False)
        self._akku_gewaehlt()

    def _akku_gewaehlt(self) -> None:
        aid = self.akku_wahl.currentData()
        if aid in (None, NEUER_AKKU):
            self.name.setText("")
            return
        a = self.speicher.akku(aid)
        if not a:
            return
        self.name.setText(a.name)
        self.modell.setEditText(a.modell)
        self.typ.setCurrentIndex(self.typ.findData(a.typ))
        self.zellen.setValue(a.zellen)
        self.nenn.setValue(a.nenn_mah)
        self._abschalt_von_hand = False
        self._typ_geaendert()
        self._c_rate(0.5)

    def _modell_gewaehlt(self) -> None:
        z = akkus.zelle_finden(self.modell.currentData() or "")
        if not z:
            return
        self.modell.setEditText(z.name)
        self.typ.setCurrentIndex(self.typ.findData(z.typ))
        self.nenn.setValue(z.mah)   # Zellen in Reihe: mAh bleiben gleich
        self._c_rate(0.5)

    def _typ_geaendert(self) -> None:
        t = akkus.TYPEN[self.typ.currentData()]
        if not self._abschalt_von_hand:
            self.abschalt.setValue(akkus.abschaltspannung(t.schluessel, self.zellen.value()))
        n = self.zellen.value()
        text = (f"Nennspannung {zahl(t.nenn_v * n, 1)} V · voll {zahl(t.voll_v[1] * n, 2)} V · "
                f"üblich bis {zahl(t.abschalt_v * n, 2)} V, nie unter {zahl(t.min_abschalt_v * n, 2)} V")
        if t.hinweis:
            text += "\n" + t.hinweis
        self.typ_hinweis.setText(text)
        self._dauer_schaetzen()

    def _c_rate(self, c: float) -> None:
        if self.nenn.value() > 0:
            self.strom.setValue(akkus.strom_vorschlag(self.nenn.value(), c))

    def _dauer_schaetzen(self) -> None:
        if self.nenn.value() > 0 and self.strom.value() > 0:
            h = self.nenn.value() / 1000 / self.strom.value()
            self.dauer.setText(f"{dauer_text(h * 3600)[:-3]} h bei voller Kapazität")
        else:
            self.dauer.setText("– (Nennkapazität unbekannt)")

    def erkennen(self) -> None:
        m = self.letzter
        if not m:
            QMessageBox.information(self, "Erkennen", "Noch kein Messwert vom Gerät.")
            return
        if m.strom > 0.01:
            QMessageBox.information(self, "Erkennen", "Die Last läuft - zum Erkennen bitte ausschalten.")
            return
        vorschlaege = akkus.erkennen(m.spannung)
        if not vorschlaege:
            QMessageBox.information(self, "Erkennen",
                                    f"Bei {zahl(m.spannung, 2)} V passt kein voll geladener Akkutyp.\n\n"
                                    "Ist der Akku geladen? Sonst Typ und Zellen bitte selbst wählen.")
            return
        menue = QMenu(self)
        menue.addSection(f"{zahl(m.spannung, 2)} V – passt zu:")
        for v in vorschlaege:
            a = menue.addAction(v.text + ("" if v.sicher else "  (nicht ganz voll?)"))
            a.triggered.connect(lambda _=False, v=v: self._vorschlag_nehmen(v))
        menue.exec(self.knopf_erkennen.mapToGlobal(self.knopf_erkennen.rect().bottomLeft()))

    def _vorschlag_nehmen(self, v: akkus.Vorschlag) -> None:
        self._abschalt_von_hand = False
        self.typ.setCurrentIndex(self.typ.findData(v.typ))
        self.zellen.setValue(v.zellen)
        self._typ_geaendert()

    # ---- Testablauf ----
    def _einstellung(self) -> Einstellung:
        return Einstellung(self.typ.currentData(), self.zellen.value(), self.nenn.value(),
                           round(self.strom.value(), 2), round(self.abschalt.value(), 2))

    def starten(self, nachfragen: bool = True) -> None:
        if not self.geraet:
            return
        e = self._einstellung()
        t = akkus.TYPEN[e.typ]
        if e.abschalt_v < t.min_abschalt_v * e.zellen - 0.001:
            QMessageBox.warning(self, "Abschaltspannung",
                                f"{zahl(e.abschalt_v)} V ist zu tief für {e.zellen}× {t.name} - "
                                f"darunter wird der Akku beschädigt (Grenze {zahl(t.min_abschalt_v * e.zellen)} V).")
            return
        if self.letzter and self.letzter.spannung > 0 and e.strom_a * self.letzter.spannung > 150:
            QMessageBox.warning(self, "Zu viel Leistung",
                                f"{zahl(e.strom_a)} A × {zahl(self.letzter.spannung, 1)} V = "
                                f"{zahl(e.strom_a * self.letzter.spannung, 0)} W. Der DL24 schafft 150 W.")
            return
        if nachfragen and not self._frage(
                "Test starten", "Ist der Akku voll geladen?\n\nDer DL24 entlädt nur. Ein halb voller Akku "
                                "ergibt eine zu kleine Kapazität."):
            return
        # Akku anlegen oder aktualisieren - das Ergebnis braucht einen Platz
        name = self.name.text().strip()
        modell = self.modell.currentText().split("  (")[0].strip()
        aid = self.akku_wahl.currentData()
        if aid in (None, NEUER_AKKU):
            name = name or self.speicher.naechster_name(modell or akkus.TYPEN[e.typ].name.split(" (")[0])
            aid = self.speicher.akku_anlegen(name, e.typ, e.zellen, e.nenn_mah, modell)
            self._akku_liste_laden(auswaehlen=aid)
        else:
            self.speicher.akku_aendern(aid, name=name or self.akku_wahl.currentText(), typ=e.typ,
                                       zellen=e.zellen, nenn_mah=e.nenn_mah, modell=modell)
        self.akku_id = aid
        self.ablauf = Ablauf(e, self.geraet, bei_ereignis=lambda a, t: self.b.ereignis.emit(a, t))
        self.ergebnis.hide()
        self.banner.hide()
        self.grenz_linie.setValue(e.abschalt_v)
        self.grenz_linie.show()
        self.kurve_bild.enableAutoRange()
        self.kurve_linie.setData([], [])
        log.info("Test gestartet: %s", e)
        self._zustand_zeigen()

    def abbrechen(self, ohne_frage: bool = False) -> None:
        ab = self.ablauf
        if not ab or not ab.laeuft:
            return
        if not ohne_frage and not self._frage("Abbrechen", "Test wirklich abbrechen?"):
            return
        threading.Thread(target=ab.abbrechen, daemon=True).start() if ab.steuerbar else ab.abbrechen()

    def _messwert_faden(self, m: Messwert) -> None:
        """Im Faden des Geräts: der Ablauf darf hier Befehle schicken."""
        ab = self.ablauf
        if ab and ab.laeuft:
            ab.messwert(m)
        self.b.messwert.emit(m)

    def _messwert(self, m: Messwert) -> None:
        self.letzter = m
        a = self.anz
        # Im Atorch-Bericht (Bluetooth) kommt die Spannung nur in 0,1-V-Schritten -
        # drei Nachkommastellen täuschten eine Genauigkeit vor, die es nicht gibt.
        # Über USB kommt sie auf 1 mV genau.
        stellen = self.geraet.spannung_stellen if self.geraet else 3
        a["u"].setzen(zahl(m.spannung, stellen, "V"))
        a["i"].setzen(zahl(m.strom, 3, "A"))
        a["p"].setzen(zahl(m.leistung, 2, "W"))
        a["t"].setzen(zahl(m.temperatur, 0, "°C") if m.temperatur is not None else "–")
        ab = self.ablauf
        if ab:
            r = ab.ergebnis
            a["mah"].setzen(zahl(r.mah, 0, "mAh"))
            a["wh"].setzen(zahl(r.wh, 2, "Wh"))
            a["zeit"].setzen(dauer_text(r.dauer_s))
            p = r.prozent(ab.einstellung.nenn_mah)
            a["proz"].setzen(f"{p:.0f} %" if p is not None and ab.zustand == "fertig" else "–")
            # Momentaufnahme: der Gerätefaden hängt währenddessen weiter an,
            # sonst sind x und y verschieden lang
            punkte = list(ab.punkte)
            if punkte:
                self.kurve_linie.setData([x[0] / 60 for x in punkte], [x[1] for x in punkte])

    def _ereignis(self, art: str, text: str) -> None:
        if art == "fertig":
            self._test_fertig()
            return
        farbe = "#fde7e7; color:#8a1c1c" if art == "warnung" else "#e7f0fd; color:#123a6b"
        self.banner.setStyleSheet(f"background:{farbe}; padding:8px; border-radius:4px; font-weight:bold;")
        self.banner.setText(text)
        self.banner.show()
        if art == "warnung":
            QApplication.beep()

    def _test_fertig(self) -> None:
        ab = self.ablauf
        if not ab:
            return
        r, e = ab.ergebnis, ab.einstellung
        if self.akku_id and r.dauer_s >= 30:
            self.speicher.test_speichern(self.akku_id, e, r, ab.punkte, ab.start_wann)
        self.banner.hide()
        self.ergebnis.setText(self.ergebnis_html(ab))
        self.ergebnis.show()
        self._messwert(self.letzter) if self.letzter else None
        self._zustand_zeigen()
        QApplication.beep()
        QApplication.alert(self)

    def ergebnis_html(self, ab: Ablauf) -> str:
        r, e = ab.ergebnis, ab.einstellung
        zeilen = [f"<b style='font-size:15px'>{self.name.text() or 'Akku'}</b>"
                  f"{' – ' + self.modell.currentText() if self.modell.currentText() else ''}"]
        if not r.vollstaendig:
            zeilen.append(f"<span style='color:#d03b3b'><b>Nicht vollständig:</b> {r.grund}. "
                          "Die Kapazität ist deshalb zu klein und zählt nicht als Zustand.</span>")
        tab = [("Gemessen", f"<b>{zahl(r.mah, 0)} mAh</b> ({zahl(r.wh, 2)} Wh)")]
        p = r.prozent(e.nenn_mah)
        if p is not None:
            tab.insert(0, ("Nennkapazität", f"{e.nenn_mah} mAh"))
            if r.vollstaendig:
                wort, farbe = akkus.bewertung(p)
                tab.append(("Zustand", f"<b style='color:{farbe}'>{p:.0f} %</b> → Verlust "
                                       f"<b>{max(0.0, 100 - p):.0f} %</b> – {wort}"))
        tab.append(("Innenwiderstand", zahl(r.innen_mohm, 0, "mΩ") if r.innen_mohm else
                    "– (bei diesem Gerät zu ungenau)" if not ab.steuerbar else "–"))
        if self.akku_id:
            alle = [t for t in self.speicher.tests(self.akku_id) if t["vollstaendig"]]
            if len(alle) >= 2:
                erster = alle[0]
                tab.append(("Seit dem ersten Test", f"{zahl(alle[-1]['mah'] - erster['mah'], 0)} mAh "
                                                    f"({datetime.fromtimestamp(erster['wann']):%d.%m.%Y})"))
        tab.append(("Dauer", f"{dauer_text(r.dauer_s)} bei {zahl(e.strom_a)} A, "
                             f"{zahl(r.leerlauf_v, 2)} V → {zahl(r.ende_v, 2)} V"))
        tab.append(("Ende", r.grund))
        zeilen.append("<table cellspacing=4>" + "".join(
            f"<tr><td style='color:gray'>{k}</td><td>{v}</td></tr>" for k, v in tab) + "</table>")
        return "<br>".join(zeilen)

    # ==================================================================
    # Reiter Akkus & Verlauf
    # ==================================================================
    def _reiter_akkus(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        knoepfe = QHBoxLayout()
        k = QPushButton("Alle Tests als CSV …")
        k.clicked.connect(self.csv_export)
        knoepfe.addWidget(k)
        knoepfe.addStretch(1)
        self.knopf_akku_weg = QPushButton("Akku löschen")
        self.knopf_akku_weg.clicked.connect(self.akku_loeschen)
        knoepfe.addWidget(self.knopf_akku_weg)
        self.knopf_test_weg = QPushButton("Test löschen")
        self.knopf_test_weg.clicked.connect(self.test_loeschen)
        knoepfe.addWidget(self.knopf_test_weg)
        lay.addLayout(knoepfe)

        teiler = QSplitter(Qt.Vertical)
        self.akku_tabelle = self._tabelle(["Akku", "Modell / Typ", "Nenn", "Zuletzt", "Zustand", "Innenwid.",
                                           "Tests", "Letzter Test"])
        self.akku_tabelle.itemSelectionChanged.connect(self._akku_zeigen)
        teiler.addWidget(self.akku_tabelle)
        unten = QSplitter(Qt.Horizontal)
        self.test_tabelle = self._tabelle(["Datum", "Gemessen", "Zustand", "Wh", "Innenwid.", "Strom", "Ende"])
        self.test_tabelle.itemSelectionChanged.connect(self._test_zeigen)
        unten.addWidget(self.test_tabelle)
        bilder = QSplitter(Qt.Vertical)
        self.verlauf_bild = pg.PlotWidget()
        self.verlauf_bild.setBackground(None)
        self.verlauf_bild.showGrid(x=True, y=True, alpha=0.25)
        self.verlauf_bild.setLabel("left", "Kapazität (mAh)")
        self.verlauf_bild.setAxisItems({"bottom": pg.DateAxisItem()})
        self.verlauf_bild.setTitle("Kapazität über die Zeit")
        self.verlauf_bild.getAxis("left").enableAutoSIPrefix(False)
        bilder.addWidget(self.verlauf_bild)
        self.test_bild = pg.PlotWidget()
        self.test_bild.setBackground(None)
        self.test_bild.showGrid(x=True, y=True, alpha=0.25)
        self.test_bild.setLabel("left", "Spannung (V)")
        self.test_bild.setLabel("bottom", "entnommen (mAh)")
        self.test_bild.setTitle("Entladekurven (gewählter Test hervorgehoben)")
        self._ohne_vorsatz(self.test_bild)
        bilder.addWidget(self.test_bild)
        unten.addWidget(bilder)
        unten.setSizes([520, 600])
        teiler.addWidget(unten)
        teiler.setSizes([260, 440])
        lay.addWidget(teiler)
        return w

    @staticmethod
    def _ohne_vorsatz(bild) -> None:
        """Keine Vorsätze wie x0.001 oder k an den Achsen."""
        for achse in ("left", "bottom"):
            bild.getAxis(achse).enableAutoSIPrefix(False)

    @staticmethod
    def _tabelle(spalten: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(spalten))
        t.setHorizontalHeaderLabels(spalten)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    @staticmethod
    def _zelle(text: str, daten=None, farbe: str | None = None) -> QTableWidgetItem:
        z = QTableWidgetItem(text)
        if daten is not None:
            z.setData(Qt.UserRole, daten)
        if farbe:
            z.setForeground(QColor(farbe))
        return z

    def _akkus_laden(self) -> None:
        gewaehlt = self._gewaehlter_akku()
        t = self.akku_tabelle
        t.setRowCount(0)
        for a in self.speicher.akkus():
            tests = self.speicher.tests(a.id)
            letzter = self.speicher.letzter_test(a.id)
            r = t.rowCount()
            t.insertRow(r)
            typ = akkus.TYPEN.get(a.typ)
            t.setItem(r, 0, self._zelle(a.name, a.id))
            t.setItem(r, 1, self._zelle(a.modell or f"{a.zellen}× {typ.name if typ else a.typ}"))
            t.setItem(r, 2, self._zelle(f"{a.nenn_mah} mAh" if a.nenn_mah else "–"))
            if letzter:
                t.setItem(r, 3, self._zelle(f"{letzter['mah']:.0f} mAh"))
                if letzter["nenn_mah"]:
                    p = letzter["mah"] / letzter["nenn_mah"] * 100
                    wort, farbe = akkus.bewertung(p)
                    t.setItem(r, 4, self._zelle(f"{p:.0f} % – {wort}", farbe=farbe))
                t.setItem(r, 5, self._zelle(zahl(letzter["innen_mohm"], 0, "mΩ")))
                t.setItem(r, 7, self._zelle(f"{datetime.fromtimestamp(letzter['wann']):%d.%m.%Y}"))
            t.setItem(r, 6, self._zelle(str(len(tests))))
            if a.id == gewaehlt:
                t.selectRow(r)
        if t.rowCount() and not t.selectedItems():
            t.selectRow(0)
        self._akku_zeigen()

    def _gewaehlter_akku(self) -> int | None:
        z = self.akku_tabelle.selectedItems()
        return self.akku_tabelle.item(z[0].row(), 0).data(Qt.UserRole) if z else None

    def _gewaehlter_test(self) -> int | None:
        z = self.test_tabelle.selectedItems()
        return self.test_tabelle.item(z[0].row(), 0).data(Qt.UserRole) if z else None

    def _akku_zeigen(self) -> None:
        aid = self._gewaehlter_akku()
        self._tests = self.speicher.tests(aid) if aid else []
        t = self.test_tabelle
        t.setRowCount(0)
        for x in reversed(self._tests):
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, self._zelle(f"{datetime.fromtimestamp(x['wann']):%d.%m.%Y %H:%M}", x["id"]))
            t.setItem(r, 1, self._zelle(f"{x['mah']:.0f} mAh"))
            if x["nenn_mah"] and x["vollstaendig"]:
                p = x["mah"] / x["nenn_mah"] * 100
                t.setItem(r, 2, self._zelle(f"{p:.0f} %", farbe=akkus.bewertung(p)[1]))
            elif not x["vollstaendig"]:
                t.setItem(r, 2, self._zelle("unvollständig", farbe="#888888"))
            t.setItem(r, 3, self._zelle(zahl(x["wh"], 2)))
            t.setItem(r, 4, self._zelle(zahl(x["innen_mohm"], 0, "mΩ")))
            t.setItem(r, 5, self._zelle(zahl(x["strom_a"], 2, "A")))
            t.setItem(r, 6, self._zelle(x["grund"]))
        self.verlauf_bild.clear()
        voll = [x for x in self._tests if x["vollstaendig"]]
        if voll:
            self.verlauf_bild.plot([x["wann"] for x in voll], [x["mah"] for x in voll],
                                   pen=pg.mkPen("#2f80ed", width=2), symbol="o", symbolBrush="#2f80ed")
            nenn = voll[-1]["nenn_mah"]
            if nenn:
                self.verlauf_bild.addItem(pg.InfiniteLine(nenn, angle=0, pen=pg.mkPen("#888", style=Qt.DashLine),
                                                          label="Nenn", labelOpts={"position": 0.05}))
        self.knopf_akku_weg.setEnabled(bool(aid))
        self._test_zeigen()

    def _test_zeigen(self) -> None:
        import json
        self.test_bild.clear()
        gewaehlt = self._gewaehlter_test()
        for x in getattr(self, "_tests", []):
            punkte = json.loads(x["kurve"] or "[]")
            if len(punkte) < 2:
                continue
            # x-Achse: entnommene mAh, so liegen Tests mit verschiedenem Strom übereinander
            mah, achse = 0.0, [0.0]
            for (t0, _, i0), (t1, _, i1) in zip(punkte, punkte[1:]):
                mah += (i0 + i1) / 2 * (t1 - t0) / 3.6
                achse.append(mah)
            stift = pg.mkPen("#d0671f", width=2.5) if x["id"] == gewaehlt else pg.mkPen((140, 140, 140, 110), width=1)
            self.test_bild.plot(achse, [p[1] for p in punkte], pen=stift)
        self.knopf_test_weg.setEnabled(gewaehlt is not None)

    def akku_loeschen(self) -> None:
        aid = self._gewaehlter_akku()
        a = aid and self.speicher.akku(aid)
        if a and self._frage("Akku löschen", f"„{a.name}“ mit allen Tests löschen?"):
            self.speicher.akku_loeschen(aid)
            self._akkus_laden()
            self._akku_liste_laden()

    def test_loeschen(self) -> None:
        tid = self._gewaehlter_test()
        if tid and self._frage("Test löschen", "Diesen Test löschen?"):
            self.speicher.test_loeschen(tid)
            self._akkus_laden()

    def csv_export(self) -> None:
        pfad, _ = QFileDialog.getSaveFileName(self, "Tests speichern", str(Path.home() / "akkutests.csv"),
                                              "CSV (*.csv)")
        if pfad:
            n = self.speicher.csv_schreiben(Path(pfad))
            QMessageBox.information(self, "CSV", f"{n} Tests gespeichert:\n{pfad}")

    # ==================================================================
    # Reiter Diagnose
    # ==================================================================
    def _reiter_diagnose(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        erkl = QLabel("Hier steht roh, was zwischen App und Gerät hin- (&gt;) und hergeht (&lt;). "
                      "Wenn etwas nicht klappt: ein paar Sekunden mitlaufen lassen und den Inhalt kopieren.")
        erkl.setWordWrap(True)
        lay.addWidget(erkl)
        self.diag_info = QLabel()
        self.diag_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.diag_info)
        self.diag = QPlainTextEdit()
        self.diag.setReadOnly(True)
        self.diag.setMaximumBlockCount(4000)
        self.diag.setFont(QFont("monospace", 9))
        lay.addWidget(self.diag)
        h = QHBoxLayout()
        k = QPushButton("Kopieren")
        k.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.diag.toPlainText()))
        h.addWidget(k)
        k = QPushButton("Leeren")
        k.clicked.connect(self.diag.clear)
        h.addWidget(k)
        h.addStretch(1)
        lay.addLayout(h)
        return w

    def _roh(self, richtung: str, daten: bytes) -> None:
        inhalt = daten.decode(errors="replace") if richtung == "i" else hex_text(daten)
        self.diag.appendPlainText(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" {richtung} {inhalt}")

    # ==================================================================
    def _frage(self, titel: str, text: str) -> bool:
        return QMessageBox.question(self, titel, text) == QMessageBox.Yes

    def closeEvent(self, ereignis) -> None:
        if self.ablauf and self.ablauf.laeuft:
            if not self._frage("Beenden", "Es läuft ein Test. Wirklich beenden?\n\n"
                                          "Die Last wird ausgeschaltet."):
                ereignis.ignore()
                return
            self.ablauf.abbrechen()
        if self.geraet:
            self.geraet.trennen()
        ereignis.accept()


def pruefen() -> int:
    """Für den Bau: lädt alles, spielt eine kurze Simulation durch."""
    print(f"DL24 Akkutest {VERSION}")
    import serial  # noqa: F401
    import bleak   # noqa: F401
    import hid     # noqa: F401  - USB-HID; die native Bibliothek muss im Bündel mit
    hid.enumerate(0x0483, 0x5750)
    print("pyserial, bleak, hidapi, pyqtgraph: da")
    from .simulator import SimAkku, SimulatorVerbindung
    v = SimulatorVerbindung(akku=SimAkku(mah=500), tempo=500, bericht_s=0.02)
    v.oeffnen()
    g = Geraet(v, intervall=0.02)
    print("Simulator spricht:", g.erkennen(warten=0.1))
    fertig = threading.Event()
    ab = Ablauf(Einstellung("liion", 1, 500, 0.5, 3.0), g, bei_ereignis=lambda a, t: a == "fertig" and fertig.set())
    g.bei_messwert = ab.messwert
    g.starten()
    fertig.wait(30)
    g.trennen()
    print(f"Testlauf: {ab.ergebnis.mah:.0f} mAh, {ab.ergebnis.grund}")
    return 0 if ab.zustand == "fertig" and ab.ergebnis.mah > 400 else 1


def main() -> int:
    # Die Windows-Fassung hat keine Konsole: dann sind stdout/stderr None,
    # und jedes print() würde abstürzen
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w"))
    if "--pruefen" in sys.argv:
        return pruefen()
    pfad = protokoll_einrichten()
    log.info("Start %s, Log %s", VERSION, pfad)
    app = QApplication(sys.argv)
    app.setApplicationName("DL24 Akkutest")
    app.setDesktopFileName("dl24-akkutest")
    pg.setConfigOptions(antialias=True, foreground=app.palette().windowText().color())
    f = Fenster()
    f.show()
    if "--fenster-probe" in sys.argv:
        # Für den Bau: öffnet das Fenster wirklich und schließt es wieder
        sichtbar = []
        QTimer.singleShot(800, lambda: (sichtbar.append(f.isVisible() and f.reiter.count() == 3), app.quit()))
        rc = app.exec()
        print("Fenster geöffnet:", sichtbar, f.windowTitle())
        return rc if sichtbar == [True] else 1
    return app.exec()
