"""Reiter "Steuerung": den DL24 von Hand bedienen wie in der Atorch-Software -
Strom und Abschaltspannung einstellen, Last ein und aus, Zähler nullen."""
from __future__ import annotations

import logging
import threading

from PySide6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .geraet import Messwert
from .fenster import Anzeige, gedaempft, zahl

log = logging.getLogger("akkutest.steuerung")
DL24_MAX_W = 150.0


class SteuerungReiter(QWidget):
    def __init__(self, fenster) -> None:
        super().__init__()
        self.f = fenster
        self.letzter: Messwert | None = None
        h = QHBoxLayout(self)

        links = QVBoxLayout()
        g = QGroupBox("Last")
        f = QFormLayout(g)
        zeile = QHBoxLayout()
        self.strom = QDoubleSpinBox()
        self.strom.setRange(0.0, 20.0)
        self.strom.setDecimals(3)
        self.strom.setSingleStep(0.1)
        self.strom.setSuffix(" A")
        self.strom.setValue(0.5)
        self.knopf_strom = QPushButton("Setzen")
        self.knopf_strom.clicked.connect(self.strom_setzen)
        zeile.addWidget(self.strom, 1)
        zeile.addWidget(self.knopf_strom)
        f.addRow("Strom:", zeile)
        zeile = QHBoxLayout()
        self.abschalt = QDoubleSpinBox()
        self.abschalt.setRange(0.0, 200.0)
        self.abschalt.setDecimals(2)
        self.abschalt.setSingleStep(0.1)
        self.abschalt.setSuffix(" V")
        self.abschalt.setSpecialValueText("aus")
        self.knopf_abschalt = QPushButton("Setzen")
        self.knopf_abschalt.clicked.connect(self.abschalt_setzen)
        zeile.addWidget(self.abschalt, 1)
        zeile.addWidget(self.knopf_abschalt)
        f.addRow("Abschalten bei:", zeile)
        knoepfe = QHBoxLayout()
        self.knopf_ein = QPushButton("▶  Start")
        self.knopf_ein.setStyleSheet("font-weight: bold; padding: 10px;")
        self.knopf_ein.setMinimumHeight(self.knopf_ein.fontMetrics().height() + 22)   # nie gequetscht
        self.knopf_ein.clicked.connect(lambda: self.last(True))
        self.knopf_aus = QPushButton("■  Stop")
        self.knopf_aus.setStyleSheet("font-weight: bold; padding: 10px;")
        self.knopf_aus.setMinimumHeight(self.knopf_aus.fontMetrics().height() + 22)   # nie gequetscht
        self.knopf_aus.clicked.connect(lambda: self.last(False))
        knoepfe.addWidget(self.knopf_ein)
        knoepfe.addWidget(self.knopf_aus)
        f.addRow(knoepfe)
        self.knopf_null = QPushButton("Zähler nullen (mAh, Wh, Zeit)")
        self.knopf_null.clicked.connect(self.zaehler_null)
        f.addRow(self.knopf_null)
        self.zustand = QLabel()
        self.zustand.setStyleSheet("font-weight: bold; font-size: 14px;")
        f.addRow("Last:", self.zustand)
        self.hinweis = QLabel()
        self.hinweis.setWordWrap(True)
        self.hinweis.setStyleSheet(gedaempft())
        f.addRow(self.hinweis)
        links.addWidget(g)
        links.addStretch(1)
        lw = QWidget()
        lw.setLayout(links)
        lw.setMaximumWidth(430)
        h.addWidget(lw)

        rechts = QVBoxLayout()
        raster = QGridLayout()
        self.anz = {}
        for i, (k, t) in enumerate([("u", "Spannung"), ("i", "Strom"), ("p", "Leistung"), ("r", "Widerstand"),
                                    ("mah", "Kapazität (Gerät)"), ("wh", "Energie (Gerät)"),
                                    ("t", "Temperatur Kühler (MOS)"), ("tf", "Temperatur Fühler"),
                                    ("tc", "Temperatur CPU")]):
            self.anz[k] = Anzeige(t)
            raster.addWidget(self.anz[k], i // 4, i % 4)
        rechts.addLayout(raster)
        self.temp_roh = QLabel()
        self.temp_roh.setStyleSheet(gedaempft())
        self.temp_roh.setToolTip("So schickt das Gerät die drei Temperaturen - zum Prüfen, welcher Wert welcher "
                                 "Fühler ist")
        rechts.addWidget(self.temp_roh)
        rechts.addStretch(1)
        h.addLayout(rechts, 1)

    # ------------------------------------------------------------------
    def zustand_zeigen(self, g, test_laeuft: bool) -> None:
        steuerbar = bool(g and g.kann_steuern and g.protokoll != "unbekannt")
        frei = steuerbar and not test_laeuft
        for w in (self.strom, self.knopf_strom, self.abschalt, self.knopf_abschalt, self.knopf_ein,
                  self.knopf_null):
            w.setEnabled(frei)
        self.knopf_aus.setEnabled(steuerbar)          # Stop geht immer
        if not g:
            self.hinweis.setText("Erst verbinden.")
        elif not steuerbar:
            self.hinweis.setText("Dieses Gerät lässt sich so nicht fernsteuern – DL24 über das USB-Kabel "
                                 "verbinden.")
        elif test_laeuft:
            self.hinweis.setText("Es läuft ein Test – der steuert die Last selbst. Stop bricht ihn ab.")
        else:
            self.hinweis.setText("Werte gelten sofort. Stop schaltet die Last aus.")

    def messwert(self, m: Messwert) -> None:
        self.letzter = m
        stellen = self.f.geraet.spannung_stellen if self.f.geraet else 3
        a = self.anz
        a["u"].setzen(zahl(m.spannung, stellen, "V"))
        a["i"].setzen(zahl(m.strom, 3, "A"))
        a["p"].setzen(zahl(m.leistung, 2, "W"))
        a["r"].setzen(zahl(m.spannung / m.strom, 2, "Ω") if m.strom > 0.005 else "–")
        a["mah"].setzen(zahl(m.mah_geraet, 0, "mAh") if m.mah_geraet is not None else "–")
        a["wh"].setzen(zahl(m.wh_geraet, 3, "Wh") if m.wh_geraet is not None else "–")
        a["t"].setzen(zahl(m.temperatur, 0, "°C") if m.temperatur is not None else "–")
        a["tf"].setzen(zahl(m.temp_fuehler, 1, "°C") if m.temp_fuehler is not None else "kein Fühler")
        a["tc"].setzen(zahl(m.temp_cpu, 1, "°C") if m.temp_cpu is not None else "–")
        if m.temp_roh:
            self.temp_roh.setText("Rohwerte vom Gerät (Byte 32/36/40): " +
                                  " · ".join(zahl(x, 3, "°C") for x in m.temp_roh))
        self.zustand.setText("<span style='color:#2e9e4f'>● an</span>" if m.an
                             else "<span style='color:gray'>○ aus</span>")

    # ------------------------------------------------------------------
    def _befehl(self, name: str, aufruf) -> None:
        g = self.f.geraet
        if not g:
            return

        def los():
            try:
                if aufruf(g) is False:
                    self.f.b.ereignis.emit("warnung", f"{name}: das Gerät hat nicht bestätigt – bitte am "
                                                      "Display prüfen.")
            except Exception as e:
                log.exception(name)
                self.f.b.ereignis.emit("warnung", f"{name}: {e}")

        threading.Thread(target=los, daemon=True).start()

    def strom_setzen(self) -> None:
        a = round(self.strom.value(), 3)
        u = self.letzter.spannung if self.letzter else 0
        if a * u > DL24_MAX_W:
            QMessageBox.warning(self, "Zu viel Leistung", f"{zahl(a)} A × {zahl(u, 1)} V = {zahl(a * u, 0)} W. "
                                                          f"Der DL24 schafft {DL24_MAX_W:.0f} W.")
            return
        log.info("Hand: Strom %.3f A", a)
        self._befehl("Strom setzen", lambda g: g.strom_setzen(a))

    def abschalt_setzen(self) -> None:
        v = round(self.abschalt.value(), 2)
        log.info("Hand: Abschaltspannung %.2f V", v)
        self._befehl("Abschaltspannung setzen", lambda g: g.abschaltung_setzen(v))

    def last(self, ein: bool) -> None:
        if not ein:
            # Stop gewinnt immer - auch gegen einen laufenden Test
            if self.f.ablauf and self.f.ablauf.laeuft:
                self.f.abbrechen(ohne_frage=True)
            if self.f.nt.laeuft:
                self.f.nt.abbrechen(ohne_frage=True)
            log.info("Hand: Last aus")
            self._befehl("Stop", lambda g: g.last(False))
            return
        a = round(self.strom.value(), 3)
        u = self.letzter.spannung if self.letzter else 0
        if a * u > DL24_MAX_W:
            QMessageBox.warning(self, "Zu viel Leistung", f"{zahl(a)} A × {zahl(u, 1)} V = {zahl(a * u, 0)} W. "
                                                          f"Der DL24 schafft {DL24_MAX_W:.0f} W.")
            return
        log.info("Hand: Last ein mit %.3f A", a)
        # Strom immer mitschicken: sonst gilt, was zuletzt im Gerät stand
        self._befehl("Start", lambda g: g.strom_setzen(a) and g.last(True))

    def zaehler_null(self) -> None:
        log.info("Hand: Zähler nullen")
        self._befehl("Zähler nullen", lambda g: g.zaehler_null())
