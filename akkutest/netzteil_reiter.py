"""Reiter "Ladegeräte & Netzteile": Typenschild eingeben, Tests wählen, prüfen."""
from __future__ import annotations

import html
import logging
import threading
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from . import netzteil as nt
from .geraet import Messwert
from .fenster import Anzeige, dauer_text, gedaempft, zahl

log = logging.getLogger("akkutest.netzteil")


def _kurz(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def ergebnis_html(e: dict, r: dict) -> str:
    """Aus gespeicherten Werten (dict), damit es auch für alte Tests geht."""
    if "teile" in r:
        return trigger_html(e, r)
    strom = e["nenn_a"] if e["nenn_a"] > 0 else (e["nenn_w"] / e["nenn_v"] if e["nenn_v"] else 0)
    angabe = f"{_kurz(e['nenn_v'])} V / {_kurz(round(strom, 2))} A"
    w = e["nenn_w"] or e["nenn_v"] * strom
    angabe += f" ({_kurz(round(w, 1))} W)"
    unten = e["nenn_v"] * (1 - e["toleranz_proz"] / 100)
    oben = e["nenn_v"] * (1 + e["toleranz_proz"] / 100)
    unbekannt = e.get("unbekannt", False)
    if unbekannt:
        angabe = f"{_kurz(e['nenn_v'])} V, Strom unbekannt"
    zeilen = [f"<b style='font-size:15px'>{html.escape(e['name'] or 'Netzteil')}</b> – {angabe}"]
    if unbekannt:
        best = nt.bestleistung(r)
        if best:
            zeilen.append(f"<b style='font-size:14px'>Liefert bis {zahl(best[0], 1)} W</b> "
                          f"({zahl(best[1], 2)} A, Spannung noch in der Toleranz)")
        else:
            zeilen.append("<b style='color:#d03b3b; font-size:14px'>Schon bei der ersten Stufe "
                          "außerhalb der Toleranz</b>")
    elif r.get("haelt") is True:
        zeilen.append("<b style='color:#2e9e4f; font-size:14px'>✔ Hält die Angabe</b>")
    elif r.get("haelt") is False:
        zeilen.append("<b style='color:#d03b3b; font-size:14px'>✘ Hält die Angabe nicht</b>")
    else:
        zeilen.append("<b style='color:gray; font-size:14px'>Nicht entschieden</b> – der Nennstrom wurde nicht "
                      "vollständig geprüft")
    tab = []
    if r.get("leerlauf_v") is not None:
        tab.append(("Leerlauf", f"{zahl(r['leerlauf_v'], 3)} V (erlaubt {zahl(unten)}–{zahl(oben)} V)"))
    stufen = r.get("stufen") or []
    nenn = [s for s in stufen if abs(s["soll_a"] - strom) < 1e-6]
    if nenn and r.get("leerlauf_v") is not None and not unbekannt:
        s = nenn[0]
        abfall = (r["leerlauf_v"] - s["spannung"]) * 1000
        tab.append(("Bei Nennstrom", f"<b>{zahl(s['spannung'], 3)} V</b> bei {zahl(s['strom'], 2)} A "
                                     f"(−{abfall:.0f} mV)"))
    d = r.get("dauer")
    if d:
        farbe = "#2e9e4f" if d["ok"] else "#d03b3b"
        tab.append(("Dauertest", f"{zahl(d['soll_a'], 2)} A: Ø {zahl(d['spannung'], 3)} V, "
                                 f"tiefster Wert <b style='color:{farbe}'>{zahl(d['min_v'], 3)} V</b>"))
    if unbekannt and r.get("abschalt_a") is None:
        m = r.get("max_getestet_a", 0)
        tab.append(("Grenze", f"bis {zahl(m, 2)} A keine Abschaltung (Ende der Suche)"))
    elif e.get("abschalttest") or r.get("abschalt_a") is not None:
        a = r.get("abschalt_a")
        if a is not None:
            wort = "schaltet ab" if r.get("abschalt_art") == "abgeschaltet" else "bricht ein"
            anteil = "" if unbekannt else f", {a / strom * 100:.0f} % der Angabe"
            tab.append(("Grenze", f"<b>{wort} bei {zahl(a, 2)} A</b> (≈ {zahl(a * e['nenn_v'], 1)} W{anteil})"))
        else:
            m = r.get("max_getestet_a", 0)
            tab.append(("Grenze", f"bis {zahl(m, 2)} A ({m / strom * 100:.0f} %) keine Abschaltung"))
    if r.get("temp_max") is not None:
        t = f"höchstens <b>{zahl(r['temp_max'], 0)} °C</b>"
        if r.get("temp_start") is not None:
            t += f" (Start {zahl(r['temp_start'], 0)} °C, +{r['temp_max'] - r['temp_start']:.0f} K)"
        tab.append(("Temperatur", t))
    else:
        tab.append(("Temperatur", "– (kein Fühler am DL24)"))
    tab.append(("Dauer", dauer_text(r.get("dauer_s", 0))))
    tab.append(("Ende", html.escape(r.get("grund", ""))))
    zeilen.append("<table cellspacing=4>" + "".join(
        f"<tr><td style='color:gray'>{k}</td><td>{v}</td></tr>" for k, v in tab) + "</table>")
    if stufen:
        kopf = "<tr><td style='color:gray'>Strom</td><td style='color:gray'>Spannung</td>" \
               "<td style='color:gray'>tiefster</td><td style='color:gray'>Leistung</td><td></td></tr>"
        reihen = "".join(
            f"<tr><td>{zahl(s['soll_a'], 2)} A</td><td>{zahl(s['spannung'], 3)} V</td>"
            f"<td>{zahl(s['min_v'], 3)} V</td><td>{zahl(s['spannung'] * s['strom'], 1)} W</td>"
            f"<td style='color:{'#2e9e4f' if s['ok'] else '#d03b3b'}'>{'✔' if s['ok'] else '✘ unter ' + zahl(unten) + ' V'}</td></tr>"
            for s in stufen)
        zeilen.append("<b>Kennlinie</b><table cellspacing=6>" + kopf + reihen + "</table>")
    for h in r.get("hinweise") or []:
        zeilen.append(f"<span style='color:#b07a00'>⚠ {html.escape(h)}</span>")
    return "<br>".join(zeilen)


def trigger_html(e: dict, r: dict) -> str:
    zeilen = [f"<b style='font-size:15px'>{html.escape(e['name'] or 'Ladegerät')}</b> – Schnellladen über "
              "Trigger-Adapter"]
    if r.get("haelt") is True:
        zeilen.append("<b style='color:#2e9e4f; font-size:14px'>✔ Hält alle Angaben</b>")
    elif r.get("haelt") is False:
        zeilen.append("<b style='color:#d03b3b; font-size:14px'>✘ Hält nicht alles, was angegeben ist</b>")
    teile, nicht = r.get("teile") or [], r.get("nicht") or []
    hoch_da = [t for t in teile if t["einstellung"]["nenn_v"] > 5.5]
    hoch_fehlt = [n for n in nicht if n["volt"] > 5.5 and n["grund"] == "kam nicht"]
    if not hoch_da and hoch_fehlt:
        zeilen.append("<b style='color:#d03b3b'>Kein Schnellladen: über den Adapter kamen nur "
                      f"{zahl(hoch_fehlt[0]['gemessen'], 2)} V.</b>")
    elif teile:
        zeilen.append("Unterstützt: " + ", ".join(f"{_kurz(t['einstellung']['nenn_v'])} V" for t in teile)
                      + ("  ·  nicht: " + ", ".join(f"{_kurz(n['volt'])} V ({n['grund']})" for n in nicht)
                         if nicht else ""))
    kopf = "".join(f"<td style='color:gray'>{k}</td>" for k in ("Spannung", "Angabe", "Ergebnis", "liefert bis",
                                                                 "Grenze"))
    reihen = ""
    for t in teile:
        te, tr = t["einstellung"], t["ergebnis"]
        best = nt.bestleistung(tr)
        if te.get("unbekannt"):
            urteil, farbe, angabe = "ermittelt", "gray", "unbekannt"
        else:
            urteil, farbe = {True: ("✔ hält", "#2e9e4f"), False: ("✘ hält nicht", "#d03b3b")}.get(
                tr.get("haelt"), ("– offen", "gray"))
            angabe = f"{_kurz(te['nenn_a'])} A"
        grenze = f"{zahl(tr['abschalt_a'], 2)} A" if tr.get("abschalt_a") is not None else "–"
        reihen += (f"<tr><td><b>{_kurz(te['nenn_v'])} V</b></td><td>{angabe}</td>"
                   f"<td style='color:{farbe}'>{urteil}</td>"
                   f"<td>{zahl(best[0], 1) + ' W' if best else '–'}</td><td>{grenze}</td></tr>")
    for n in nicht:
        reihen += (f"<tr><td><b>{_kurz(n['volt'])} V</b></td><td></td><td style='color:#d03b3b'>{n['grund']}"
                   f"</td><td colspan=2>gemessen {zahl(n['gemessen'], 2)} V</td></tr>")
    zeilen.append(f"<table cellspacing=6><tr>{kopf}</tr>{reihen}</table>")
    zeilen.append(f"<span style='color:gray'>Dauer {dauer_text(r.get('dauer_s', 0))} · "
                  f"{html.escape(r.get('grund', ''))}</span>")
    for t in teile:
        zeilen.append("<hr>" + ergebnis_html(t["einstellung"], t["ergebnis"]))
    return "<br>".join(zeilen)


class NetzteilReiter(QWidget):
    def __init__(self, fenster) -> None:
        super().__init__()
        self.f = fenster
        self.ablauf: nt.NetzteilAblauf | None = None
        self._bauen()
        self._vorlage(0)
        self.verlauf_laden()

    # ------------------------------------------------------------------
    def _bauen(self) -> None:
        h = QHBoxLayout(self)
        links = QVBoxLayout()

        g = QGroupBox("Typenschild")
        f = QFormLayout(g)
        self.vorlage = QComboBox()
        self.vorlage.addItem("– eigene Angabe –", None)
        for name, v, a in nt.VORLAGEN:
            self.vorlage.addItem(name, (v, a))
        self.vorlage.activated.connect(self._vorlage)
        f.addRow("Vorlage:", self.vorlage)
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. Anker 20W, Hub Port 3, Netzteil Lötstation")
        f.addRow("Gerät:", self.name)
        self.nenn_v = self._zahlfeld(0, 60, 2, 0.1, " V")
        f.addRow("Ausgangsspannung:", self.nenn_v)
        self.nenn_a = self._zahlfeld(0, 20, 2, 0.1, " A", "nicht angegeben")
        f.addRow("Ausgangsstrom:", self.nenn_a)
        self.nenn_w = self._zahlfeld(0, 200, 1, 1, " W", "nicht angegeben")
        f.addRow("Leistung:", self.nenn_w)
        self.toleranz = self._zahlfeld(1, 20, 1, 1, " %")
        self.toleranz.setValue(5)
        f.addRow("Toleranz Spannung:", self.toleranz)
        self.schnell = QCheckBox("Schnellladegerät (USB-PD / QC / Fast Charging)")
        self.schnell.setToolTip("9 V, 12 V, 15 V, 20 V gibt das Ladegerät nur über einen Trigger-Adapter heraus")
        self.schnell.toggled.connect(self._schnell_umschalten)
        f.addRow(self.schnell)
        self.schnell_box = QWidget()
        sb = QGridLayout(self.schnell_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.addWidget(QLabel("<span style='color:gray'>prüfen</span>"), 0, 0)
        sb.addWidget(QLabel("<span style='color:gray'>Strom laut Aufdruck</span>"), 0, 1)
        self.trigger: list[tuple[float, QCheckBox, QDoubleSpinBox]] = []
        for i, v in enumerate(nt.TRIGGER_SPANNUNGEN):
            haken = QCheckBox(f"{_kurz(v)} V")
            haken.setChecked(v <= 12)
            haken.toggled.connect(self._dauer_zeigen)
            a = self._zahlfeld(0, 5, 2, 0.25, " A", "unbekannt – ermitteln")
            sb.addWidget(haken, i + 1, 0)
            sb.addWidget(a, i + 1, 1)
            self.trigger.append((v, haken, a))
        hinweis = QLabel("Dafür den <b>Trigger-Adapter</b> zwischen Ladegerät und DL24 stecken. Die App sagt "
                         "dir, wann du welche Spannung am Adapter einstellst. Steht kein Strom drauf: "
                         "„unbekannt“ lassen – dann wird ermittelt, wie viel es liefert.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        sb.addWidget(hinweis, len(nt.TRIGGER_SPANNUNGEN) + 1, 0, 1, 2)
        self.schnell_box.hide()
        f.addRow(self.schnell_box)
        self.angabe_hinweis = QLabel()
        self.angabe_hinweis.setWordWrap(True)
        self.angabe_hinweis.setStyleSheet(gedaempft())
        f.addRow(self.angabe_hinweis)
        links.addWidget(g)

        g = QGroupBox("Tests")
        f = QGridLayout(g)
        self.mit_stufen = QCheckBox("Stufentest")
        self.mit_stufen.setChecked(True)
        self.mit_stufen.setToolTip("Strom in Stufen bis zum Nennstrom: wie stark sinkt die Spannung?")
        self.stufen = QSpinBox()
        self.stufen.setRange(2, 20)
        self.stufen.setValue(10)
        self.stufen.setSuffix(" Stufen")
        self.stufe_s = QSpinBox()
        self.stufe_s.setRange(5, 600)
        self.stufe_s.setValue(30)
        self.stufe_s.setSuffix(" s je Stufe")
        f.addWidget(self.mit_stufen, 0, 0)
        f.addWidget(self.stufen, 0, 1)
        f.addWidget(self.stufe_s, 0, 2)
        self.mit_dauer = QCheckBox("Dauertest")
        self.mit_dauer.setChecked(True)
        self.mit_dauer.setToolTip("Fester Strom über längere Zeit - wird es warm, sackt die Spannung ab?")
        self.dauer_proz = QSpinBox()
        self.dauer_proz.setRange(10, 150)
        self.dauer_proz.setValue(100)
        self.dauer_proz.setSuffix(" % Strom")
        self.dauer_min = QSpinBox()
        self.dauer_min.setRange(1, 480)
        self.dauer_min.setValue(10)
        self.dauer_min.setSuffix(" min")
        f.addWidget(self.mit_dauer, 1, 0)
        f.addWidget(self.dauer_proz, 1, 1)
        f.addWidget(self.dauer_min, 1, 2)
        self.mit_abschalt = QCheckBox("Abschalttest")
        self.mit_abschalt.setToolTip("Über den Nennstrom hinaus, bis das Netzteil abschaltet "
                                     "oder die Spannung einbricht - höchstens bis zur Grenze")
        self.max_proz = QSpinBox()
        self.max_proz.setRange(105, 250)
        self.max_proz.setSingleStep(5)
        self.max_proz.setValue(130)
        self.max_proz.setPrefix("bis ")
        self.max_proz.setSuffix(" %")
        f.addWidget(self.mit_abschalt, 2, 0)
        f.addWidget(self.max_proz, 2, 1)
        f.addWidget(QLabel("Temperaturgrenze:"), 3, 0)
        self.temp_grenze = QSpinBox()
        self.temp_grenze.setRange(30, 120)
        self.temp_grenze.setValue(70)
        self.temp_grenze.setSuffix(" °C")
        self.temp_grenze.setToolTip("Gilt für den Temperaturfühler des DL24 - am Netzteil festkleben")
        f.addWidget(self.temp_grenze, 3, 1)
        hinweis = QLabel("Temperatur: den Fühler des DL24 mit Klebeband ans Gehäuse des Netzteils kleben. "
                         "Ohne Fühler wird sie nicht gemessen.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        f.addWidget(hinweis, 4, 0, 1, 3)
        self.dauer = QLabel()
        f.addWidget(self.dauer, 5, 0, 1, 3)
        knoepfe = QHBoxLayout()
        self.knopf_start = QPushButton("▶  Prüfen")
        self.knopf_start.setStyleSheet("font-weight: bold; padding: 8px;")
        self.knopf_start.clicked.connect(lambda: self.starten())
        self.knopf_abbruch = QPushButton("■  Abbrechen")
        self.knopf_abbruch.setStyleSheet("padding: 8px;")
        self.knopf_abbruch.clicked.connect(lambda: self.abbrechen())
        knoepfe.addWidget(self.knopf_start, 2)
        knoepfe.addWidget(self.knopf_abbruch, 1)
        f.addLayout(knoepfe, 6, 0, 1, 3)
        self.steuer_hinweis = QLabel()
        self.steuer_hinweis.setWordWrap(True)
        self.steuer_hinweis.setStyleSheet(gedaempft())
        f.addWidget(self.steuer_hinweis, 7, 0, 1, 3)
        links.addWidget(g)
        links.addStretch(1)
        lw = QWidget()
        lw.setLayout(links)
        lw.setMaximumWidth(450)
        h.addWidget(lw)

        for w in (self.nenn_v, self.nenn_a, self.nenn_w, self.toleranz):
            w.valueChanged.connect(self._angabe_zeigen)
        for w in (self.stufen, self.stufe_s, self.dauer_min, self.max_proz):
            w.valueChanged.connect(self._dauer_zeigen)
        for w in (self.mit_stufen, self.mit_dauer, self.mit_abschalt):
            w.toggled.connect(self._dauer_zeigen)

        rechts = QSplitter(Qt.Vertical)
        oben = QWidget()
        ol = QVBoxLayout(oben)
        ol.setContentsMargins(0, 0, 0, 0)
        raster = QGridLayout()
        self.anz = {}
        for i, (k, t) in enumerate([("u", "Spannung"), ("i", "Strom"), ("p", "Leistung"),
                                    ("t", "Temperatur (Fühler)")]):
            self.anz[k] = Anzeige(t)
            raster.addWidget(self.anz[k], 0, i)
        self.schritt = QLabel()
        self.schritt.setWordWrap(True)
        self.schritt.setMinimumHeight(40)
        self.schritt.setStyleSheet("font-weight: bold;")
        raster.addWidget(self.schritt, 1, 0, 1, 3)
        self.knopf_weiter = QPushButton("Kommt nicht – überspringen")
        self.knopf_weiter.setToolTip("Diese Spannung liefert das Ladegerät nicht")
        self.knopf_weiter.clicked.connect(self._ueberspringen)
        self.knopf_weiter.hide()
        raster.addWidget(self.knopf_weiter, 1, 3)
        ol.addLayout(raster)
        self.bild = pg.PlotWidget()
        self.bild.setBackground(None)
        self.bild.showGrid(x=True, y=True, alpha=0.25)
        self.bild.setLabel("left", "Spannung (V)")
        self.bild.setLabel("bottom", "Zeit (min)")
        self.linie = self.bild.plot([], [], pen=pg.mkPen("#2f80ed", width=2))
        self.grenze = pg.InfiniteLine(angle=0, pen=pg.mkPen("#d03b3b", width=1, style=Qt.DashLine))
        self.grenze.hide()
        self.bild.addItem(self.grenze)
        self.bild.setMinimumHeight(200)
        self.f._ohne_vorsatz(self.bild)
        ol.addWidget(self.bild, 1)
        self.ergebnis = QLabel()
        self.ergebnis.setWordWrap(True)
        self.ergebnis.setTextFormat(Qt.RichText)
        self.ergebnis.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ergebnis.setFrameShape(QFrame.StyledPanel)
        self.ergebnis.setMargin(10)
        # Bei mehreren Spannungen wird das Ergebnis lang - rollbar statt abgeschnitten
        self.ergebnis_rahmen = QScrollArea()
        self.ergebnis_rahmen.setWidgetResizable(True)
        self.ergebnis_rahmen.setFrameShape(QFrame.NoFrame)
        self.ergebnis_rahmen.setWidget(self.ergebnis)
        self.ergebnis_rahmen.setMinimumHeight(220)
        self.ergebnis_rahmen.hide()
        self.ergebnis.hide()
        ol.addWidget(self.ergebnis_rahmen, 1)
        rechts.addWidget(oben)

        unten = QWidget()
        ul = QVBoxLayout(unten)
        ul.setContentsMargins(0, 0, 0, 0)
        kopf = QHBoxLayout()
        kopf.addWidget(QLabel("<b>Bisherige Prüfungen</b>"))
        kopf.addStretch(1)
        self.knopf_loeschen = QPushButton("Löschen")
        self.knopf_loeschen.clicked.connect(self.loeschen)
        kopf.addWidget(self.knopf_loeschen)
        ul.addLayout(kopf)
        self.tabelle = QTableWidget(0, 6)
        self.tabelle.setHorizontalHeaderLabels(["Datum", "Gerät", "Angabe", "Ergebnis", "Grenze", "Temp. max"])
        self.tabelle.verticalHeader().hide()
        self.tabelle.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabelle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabelle.itemSelectionChanged.connect(self._alten_zeigen)
        ul.addWidget(self.tabelle)
        rechts.addWidget(unten)
        rechts.setSizes([560, 180])
        h.addWidget(rechts, 1)

    @staticmethod
    def _zahlfeld(lo, hi, stellen, schritt, einheit, null_text=None) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setDecimals(stellen)
        w.setSingleStep(schritt)
        w.setSuffix(einheit)
        if null_text:
            w.setSpecialValueText(null_text)
        return w

    # ------------------------------------------------------------------
    def _vorlage(self, _=None) -> None:
        d = self.vorlage.currentData()
        if d:
            v, a = d
            self.nenn_v.setValue(v)
            self.nenn_a.setValue(a)
            self.nenn_w.setValue(0)
            if not self.name.text().strip():
                self.name.setPlaceholderText(self.vorlage.currentText())
        elif self.nenn_v.value() == 0:
            self.nenn_v.setValue(5.0)
            self.nenn_a.setValue(1.0)
        self._angabe_zeigen()

    def _schnell_umschalten(self, an: bool) -> None:
        self.schnell_box.setVisible(an)
        for w in (self.vorlage, self.nenn_v, self.nenn_a, self.nenn_w):
            w.setEnabled(not an and not self.laeuft)
        self._angabe_zeigen()

    def _trigger_stufen(self) -> list[tuple[float, float]]:
        return [(v, round(a.value(), 2)) for v, haken, a in self.trigger if haken.isChecked()]

    def _ueberspringen(self) -> None:
        if isinstance(self.ablauf, nt.TriggerAblauf):
            self.ablauf.ueberspringen()

    def einstellung(self) -> nt.NetzteilEinstellung:
        return nt.NetzteilEinstellung(
            name=self.name.text().strip() or self.name.placeholderText().split("z. B.")[0].strip()
            or "Netzteil",
            nenn_v=round(self.nenn_v.value(), 2), nenn_a=round(self.nenn_a.value(), 2),
            nenn_w=round(self.nenn_w.value(), 1), toleranz_proz=self.toleranz.value(),
            stufentest=self.mit_stufen.isChecked(), stufen=self.stufen.value(), stufe_s=self.stufe_s.value(),
            dauertest=self.mit_dauer.isChecked(), dauer_proz=self.dauer_proz.value(),
            dauer_min=self.dauer_min.value(), abschalttest=self.mit_abschalt.isChecked(),
            max_proz=self.max_proz.value(), temp_grenze=self.temp_grenze.value())

    def _angabe_zeigen(self) -> None:
        e = self.einstellung()
        teile = []
        if self.schnell.isChecked():
            self.angabe_hinweis.setText("USB-PD/QC: erlaubt ±5 % um die jeweilige Spannung")
            self._dauer_zeigen()
            return
        if e.nenn_v > 0:
            teile.append(f"Erlaubt: {zahl(e.untere_v)}–{zahl(e.obere_v)} V")
        if e.nenn_a == 0 and e.nenn_w > 0 and e.nenn_v > 0:
            teile.append(f"Strom aus der Leistung: {zahl(e.strom_a)} A")
        if e.nenn_a == 0 and e.nenn_w == 0 and e.nenn_v > 0:
            teile.append("Strom unbekannt: die App ermittelt, wie viel es liefert")
        if e.nenn_v > 5.5:
            teile.append("USB-C/Schnellladen: höhere Spannungen gibt das Ladegerät nur mit einem "
                         "Trigger-Adapter heraus (PD/QC) - sonst kommen nur 5 V")
        self.angabe_hinweis.setText(".  ".join(teile))
        self._dauer_zeigen()

    def _plan(self) -> list[nt.NetzteilEinstellung]:
        """Was tatsächlich geprüft wird - je Spannung eine Einstellung."""
        e = self.einstellung()
        if self.schnell.isChecked():
            return [nt.trigger_einstellung(e, v, a) for v, a in self._trigger_stufen()]
        if e.nenn_v > 0 and e.strom_a <= 0:
            return [nt.ermitteln(e, usb=e.nenn_v <= 5.5)]
        return [e]

    def _dauer_zeigen(self) -> None:
        plan = self._plan()
        if not plan:
            self.dauer.setText("<span style='color:#d03b3b'>Bitte mindestens eine Spannung wählen.</span>")
            return
        if len(plan) > 1 or self.schnell.isChecked():
            s = sum(x.dauer_s for e in plan for x in nt.plan(e))
            fehler = next((f for f in (e.pruefen() for e in plan) if f), None)
            text = f"Dauer etwa {dauer_text(s + 30 * len(plan))} plus Umschalten am Adapter"
            self.dauer.setText(f"<span style='color:#d03b3b'>{fehler}</span>" if fehler else text)
            return
        e = plan[0]
        if e.nenn_v <= 0 or e.strom_a <= 0:
            self.dauer.setText("")
            return
        s = sum(x.dauer_s for x in nt.plan(e))
        fehler = e.pruefen()
        text = f"Dauer höchstens etwa {dauer_text(s + 5)}, Strom bis {zahl(e.hoechster_strom())} A"
        self.dauer.setText(f"<span style='color:#d03b3b'>{fehler}</span>" if fehler else text)

    # ------------------------------------------------------------------
    @property
    def laeuft(self) -> bool:
        return bool(self.ablauf and self.ablauf.laeuft)

    def zustand_zeigen(self, g, anderer_test: bool) -> None:
        steuerbar = bool(g and g.kann_steuern and g.protokoll != "unbekannt")
        self.knopf_start.setEnabled(steuerbar and not self.laeuft and not anderer_test)
        self.knopf_abbruch.setEnabled(self.laeuft)
        for w in (self.trigger_felder() + [self.schnell]):
            w.setEnabled(not self.laeuft)
        for w in (self.vorlage, self.nenn_v, self.nenn_a, self.nenn_w):
            w.setEnabled(not self.laeuft and not self.schnell.isChecked())
        for w in (self.name, self.toleranz,
                  self.mit_stufen, self.stufen, self.stufe_s, self.mit_dauer, self.dauer_proz,
                  self.dauer_min, self.mit_abschalt, self.max_proz, self.temp_grenze):
            w.setEnabled(not self.laeuft)
        if not g:
            self.steuer_hinweis.setText("Erst verbinden.")
        elif not steuerbar:
            self.steuer_hinweis.setText("Dafür muss die App die Last stellen können: DL24 über das "
                                        "USB-Kabel verbinden (oder ein PX100).")
        elif anderer_test:
            self.steuer_hinweis.setText("Es läuft gerade ein Akkutest.")
        else:
            self.steuer_hinweis.setText("Netzteil an den Eingang des DL24 anschließen – bei USB über "
                                        "einen USB-Adapter.")

    def trigger_felder(self) -> list:
        return [w for _, haken, a in self.trigger for w in (haken, a)]

    def starten(self) -> None:
        g = self.f.geraet
        if not g or not g.kann_steuern:
            return
        plan = self._plan()
        if not plan:
            QMessageBox.warning(self, "Prüfen", "Bitte mindestens eine Spannung wählen.")
            return
        for e in plan:
            fehler = e.pruefen()
            if fehler:
                QMessageBox.warning(self, "Prüfen", f"{_kurz(e.nenn_v)} V: {fehler}")
                return
        melden = lambda a, t: self.f.b.ereignis.emit("nt:" + a, t)
        if self.schnell.isChecked():
            self.ablauf = nt.TriggerAblauf(self.einstellung(), self._trigger_stufen(), g, bei_ereignis=melden)
            self.grenze.hide()
        else:
            e = plan[0]
            self.ablauf = nt.NetzteilAblauf(e, g, bei_ereignis=melden)
            self.grenze.setValue(e.untere_v)
            self.grenze.show()
        self.ergebnis.hide()
        self.ergebnis_rahmen.hide()
        self.bild.enableAutoRange()
        self.linie.setData([], [])
        if not self.schnell.isChecked():
            self.schritt.setText("Leerlaufspannung messen …")
        log.info("Netzteiltest gestartet: %s", plan)
        self.f._zustand_zeigen()

    def abbrechen(self, ohne_frage: bool = False) -> None:
        ab = self.ablauf
        if not ab or not ab.laeuft:
            return
        if not ohne_frage and not self.f._frage("Abbrechen", "Prüfung wirklich abbrechen?"):
            return
        threading.Thread(target=ab.abbrechen, daemon=True).start()

    def messwert_faden(self, m: Messwert) -> None:
        ab = self.ablauf
        if ab and ab.laeuft:
            ab.messwert(m)

    def messwert(self, m: Messwert) -> None:
        stellen = self.f.geraet.spannung_stellen if self.f.geraet else 3
        self.anz["u"].setzen(zahl(m.spannung, stellen, "V"))
        self.anz["i"].setzen(zahl(m.strom, 3, "A"))
        self.anz["p"].setzen(zahl(m.leistung, 2, "W"))
        self.anz["t"].setzen(zahl(m.temp_fuehler, 1, "°C") if m.temp_fuehler is not None else "kein Fühler")
        ab = self.ablauf
        if ab:
            punkte = list(ab.punkte)
            if punkte:
                self.linie.setData([x[0] / 60 for x in punkte], [x[1] for x in punkte])

    def ereignis(self, art: str, text: str) -> None:
        umschalten = art == "umschalten"
        self.knopf_weiter.setVisible(umschalten)
        self.schritt.setStyleSheet("font-weight: bold;" + (
            " background:#fff1d6; color:#7a4b00; padding:8px; border-radius:4px;" if umschalten else ""))
        if art == "fertig":
            self.fertig()
        elif art in ("schritt", "info", "umschalten"):
            self.schritt.setText(text)
        if umschalten:
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
            QApplication.alert(self.f)

    def fertig(self) -> None:
        ab = self.ablauf
        if not ab:
            return
        self.schritt.setText("")
        self.schritt.setStyleSheet("font-weight: bold;")
        self.knopf_weiter.hide()
        if ab.ergebnis.dauer_s >= 5:
            self.f.speicher.netzteil_speichern(ab.einstellung, ab.ergebnis, ab.punkte, ab.start_wann)
            self.verlauf_laden()
        self.ergebnis.setText(ergebnis_html(ab.einstellung.__dict__, ab.ergebnis.als_dict()))
        self.ergebnis.show()
        self.ergebnis_rahmen.show()
        self.f._zustand_zeigen()
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
        QApplication.alert(self.f)

    def verbindung_weg(self, grund: str) -> None:
        ab = self.ablauf
        if ab and ab.laeuft:
            ab.zustand = "abgebrochen"
            ab.ergebnis.grund = f"Verbindung verloren: {grund}"
            self.fertig()

    # ------------------------------------------------------------------
    def verlauf_laden(self) -> None:
        self._alle = self.f.speicher.netzteil_tests()
        t = self.tabelle
        t.setRowCount(len(self._alle))
        for i, d in enumerate(self._alle):
            r = d["ergebnis"]
            haelt = d["haelt"]
            wort, farbe = ({1: ("✔ hält", "#2e9e4f"), 0: ("✘ hält nicht", "#d03b3b")}
                           .get(haelt, ("– offen", None)))
            strom = d["nenn_a"] or (d["nenn_w"] / d["nenn_v"] if d["nenn_v"] else 0)
            ee = d["einstellung"]
            angabe = f"{_kurz(d['nenn_v'])} V / {_kurz(round(strom, 2))} A"
            grenze = "–"
            if "teile" in r:
                volt = [t["einstellung"]["nenn_v"] for t in r["teile"]]
                angabe = "PD/QC " + "/".join(_kurz(v) for v in volt) + " V" if volt else "PD/QC –"
                best = [nt.bestleistung(t["ergebnis"]) for t in r["teile"]]
                best = [b[0] for b in best if b]
                grenze = f"bis {zahl(max(best), 1)} W" if best else "–"
            elif ee.get("unbekannt"):
                angabe = f"{_kurz(d['nenn_v'])} V / unbekannt"
                b = nt.bestleistung(r)
                grenze = f"bis {zahl(b[0], 1)} W" if b else "–"
                if haelt is None:
                    wort, farbe = "ermittelt", None
            elif r.get("abschalt_a") is not None:
                grenze = f"{zahl(r['abschalt_a'], 2)} A"
            elif ee.get("abschalttest"):
                grenze = f"> {zahl(r.get('max_getestet_a', 0), 2)} A"
            temps = [t["ergebnis"].get("temp_max") for t in r.get("teile", [])] + [r.get("temp_max")]
            temps = [t for t in temps if t is not None]
            temp = max(temps) if temps else None
            werte = [datetime.fromtimestamp(d["wann"]).strftime("%d.%m.%Y %H:%M"), d["name"],
                     angabe, wort, grenze,
                     zahl(temp, 0, "°C") if temp is not None else "–"]
            for k, text in enumerate(werte):
                z = QTableWidgetItem(text)
                z.setData(Qt.UserRole, d["id"])
                if k == 3 and farbe:
                    from PySide6.QtGui import QColor
                    z.setForeground(QColor(farbe))
                t.setItem(i, k, z)

    def _gewaehlt(self) -> dict | None:
        zeilen = self.tabelle.selectionModel().selectedRows() if self.tabelle.selectionModel() else []
        if not zeilen:
            return None
        return self._alle[zeilen[0].row()]

    def _alten_zeigen(self) -> None:
        d = self._gewaehlt()
        if not d or self.laeuft:
            return
        self.ergebnis.setText(ergebnis_html(d["einstellung"], d["ergebnis"]))
        self.ergebnis.show()
        self.ergebnis_rahmen.show()
        k = d["kurve"]
        self.linie.setData([x[0] / 60 for x in k], [x[1] for x in k])
        e = d["einstellung"]
        if e.get("trigger"):
            self.grenze.hide()
        else:
            self.grenze.setValue(e["nenn_v"] * (1 - e["toleranz_proz"] / 100))
            self.grenze.show()
        self.bild.enableAutoRange()

    def loeschen(self) -> None:
        d = self._gewaehlt()
        if not d:
            return
        if not self.f._frage("Löschen", f"Prüfung „{d['name']}“ vom "
                                        f"{datetime.fromtimestamp(d['wann']):%d.%m.%Y %H:%M} löschen?"):
            return
        self.f.speicher.netzteil_loeschen(d["id"])
        self.ergebnis.hide()
        self.ergebnis_rahmen.hide()
        self.verlauf_laden()
