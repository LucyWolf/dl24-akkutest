"""Reiter "Ladegeräte & Netzteile": Typenschild eingeben, Tests wählen, prüfen."""
from __future__ import annotations

import html
import logging
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from . import netzteil as nt
from .geraet import Messwert
from .fenster import Anzeige, dauer_text, gedaempft, zahl

log = logging.getLogger("akkutest.netzteil")


def _kurz(x: float) -> str:
    return f"{x:g}".replace(".", ",")


AMPEL = {"gruen": "#2e9e4f", "gelb": "#c77700", "rot": "#d03b3b"}


def einstellung_aus(e: dict) -> nt.NetzteilEinstellung:
    """Gespeicherte Einstellung zurück ins Objekt - ältere haben nicht alle Felder."""
    import dataclasses
    namen = {f.name for f in dataclasses.fields(nt.NetzteilEinstellung)}
    return nt.NetzteilEinstellung(**{k: v for k, v in e.items() if k in namen})


URTEILE = {"gut": ("✔ Empfehlenswert", "#2e9e4f"),
           "eingeschraenkt": ("⚠ Eingeschränkt verwendbar", "#c77700"),
           "nicht": ("✘ Nicht verwenden", "#d03b3b"),
           "offen": ("? Noch nicht entscheidbar – Kabel nicht herausgerechnet", "#7a7a7a")}


def urteil_html(r: dict, fach: bool = False) -> list[str]:
    """Die klare Aussage oben im Ergebnis. Alte Prüfungen haben noch keins.
    Auf dem Bildschirm in einfachen Sätzen, für Fachleute mit den Gründen."""
    aus = []
    u = r.get("urteil")
    if u in URTEILE:
        wort, farbe = URTEILE[u]
        aus.append(f"<b style='color:{farbe}; font-size:17px'>{wort}</b>")
    v = r.get("verspricht")
    if v is True:
        aus.append("<b style='color:#2e9e4f'>✔ Schafft, was es verspricht</b>")
    elif v is False:
        aus.append("<b style='color:#d03b3b'>✘ Schafft nicht, was es verspricht</b>")
    saetze = r.get("gruende") if fach or not r.get("laien") else r.get("laien")
    for g in saetze or []:
        aus.append(f"• {html.escape(g)}")
    return aus


def kurz_html(e: dict, r: dict) -> str:
    """„Kurz gesagt“ für den Bericht: Urteil groß, dann einfache Sätze."""
    zeilen = []
    u = r.get("urteil")
    if u in URTEILE:
        wort, farbe = URTEILE[u]
        zeilen.append(f"<p style='font-size:20px; color:{farbe}'><b>{wort}</b></p>")
    if "teile" in r:
        teile, nicht = r.get("teile") or [], r.get("nicht") or []
        hoch = [t for t in teile if t["einstellung"]["nenn_v"] > 5.5]
        if not hoch and any(n["volt"] > 5.5 for n in nicht):
            zeilen.append("<p>Das Ladegerät kann <b>kein Schnellladen</b>: Es kamen immer nur 5 Volt.</p>")
        elif teile:
            zeilen.append("<p>Das Ladegerät kann diese Spannungen liefern: <b>"
                          + ", ".join(f"{_kurz(t['einstellung']['nenn_v'])} V" for t in teile) + "</b>"
                          + (". Nicht dabei: " + ", ".join(f"{_kurz(n['volt'])} V" for n in nicht) if nicht else "")
                          + ".</p>")
        for t in teile:
            te, tr = t["einstellung"], t["ergebnis"]
            wort = URTEILE.get(tr.get("urteil"), ("", ""))[0]
            text = " ".join(tr.get("laien") or [])
            zeilen.append(f"<p><b>Bei {_kurz(te['nenn_v'])} Volt:</b> {html.escape(wort)}. {html.escape(text)}</p>")
    else:
        for satz in r.get("laien") or []:
            zeilen.append(f"<p>{html.escape(satz)}</p>")
    return "".join(zeilen)


def messaufbau_html(e: dict, r: dict) -> str:
    """Womit gemessen wurde - vor allem das Kabel, denn das verfälscht sonst die Spannung."""
    name = html.escape(e.get("kabel_name") or "") or "nicht angegeben"
    zeilen = [("Messgerät", "elektronische Last Atorch DL24P (Messung an ihren Klemmen, Auflösung 1 mV)"),
              ("Kabel / Adapter", name)]
    k = e.get("kabel_mohm", 0)
    if k and not r.get("kabel_unplausibel"):
        wann = e.get("kabel_wann")
        woher = (f"gemessen am {datetime.fromtimestamp(wann):%d.%m.%Y um %H:%M} Uhr an einem guten Ladegerät"
                 if wann else "von Hand eingetragen")
        zeilen.append(("Widerstand Kabel + Adapter", f"{k:.0f} mΩ ({woher}) – herausgerechnet: Die Bewertung gilt "
                                                     "für die Spannung an der Buchse des Geräts"))
    elif k:
        zeilen.append(("Widerstand Kabel + Adapter", f"{k:.0f} mΩ eingetragen, aber unplausibel (größer als der "
                                                     "gesamte gemessene Widerstand) – nicht herausgerechnet"))
    else:
        zeilen.append(("Widerstand Kabel + Adapter", "nicht bekannt – die Spannung wurde am Ende des Kabels "
                                                     "gemessen, Verluste im Kabel sind darin enthalten"))
    b = nt.kabel_bewerten(k, e.get("kabel_typ", "")) if k else None
    if b:
        zeilen.append(("Bewertung Kabel", f"<span style='color:{AMPEL[b[0]]}'>{html.escape(b[1])}</span> "
                                          "<span style='color:gray'>(Grenze nach USB-Spezifikation; gelb/rot ist "
                                          "eine Einteilung dieser Software)</span>"))
    return "<table cellspacing=4>" + "".join(
        f"<tr><td style='color:gray'>{a}</td><td>{b}</td></tr>" for a, b in zeilen) + "</table>"


def geprueft_text(e: dict, r: dict) -> str:
    """Was wurde gemacht - in einem Satz, ohne Fachwörter."""
    stufen = [s for t in (r.get("teile") or [{"ergebnis": r}]) for s in t["ergebnis"].get("stufen") or []]
    if not stufen:
        return ""
    lo, hi = min(s["soll_a"] for s in stufen), max(s["soll_a"] for s in stufen)
    text = (f"Das Gerät wurde mit einer elektronischen Last (Atorch DL24) Schritt für Schritt stärker belastet – "
            f"von {zahl(lo)} bis {zahl(hi)} Ampere – und dabei wurde gemessen, wie viel Spannung noch ankommt. "
            "Ein gutes Netzteil hält die Spannung auch unter Last fast gleich.")
    if e.get("kabel_mohm"):
        text += f" Der Verlust im Kabel ({e['kabel_mohm']:.0f} mΩ) ist herausgerechnet."
    return text


def ergebnis_html(e: dict, r: dict, fach: bool = False) -> str:
    """Aus gespeicherten Werten (dict), damit es auch für alte Tests geht."""
    if "teile" in r:
        return trigger_html(e, r, fach)
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
    if "urteil" in r:
        zeilen += urteil_html(r, fach)
    elif unbekannt:
        pass
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
        text = f"<b>{zahl(s['spannung'], 3)} V</b> bei {zahl(s['strom'], 2)} A (−{abfall:.0f} mV)"
        if s.get("buchse_v"):
            text = (f"<b>{zahl(s['buchse_v'], 3)} V an der Buchse</b>, {zahl(s['spannung'], 3)} V am Kabelende "
                    f"bei {zahl(s['strom'], 2)} A")
        tab.append(("Bei Nennstrom", text))
    if r.get("widerstand_mohm"):
        w_ges, kabel = r["widerstand_mohm"], e.get("kabel_mohm", 0)
        if kabel:
            text = (f"{w_ges:.0f} mΩ gesamt, davon Kabel {kabel:.0f} mΩ → Netzteil ≈ "
                    f"<b>{max(0, w_ges - kabel):.0f} mΩ</b>")
        else:
            text = f"<b>{w_ges:.0f} mΩ</b> (Netzteil + Kabel + Adapter)"
        tab.append(("Widerstand", text))
    if r.get("max_w") is not None:
        text = f"in der Toleranz <b>{zahl(r['max_w_tol'], 1) + ' W' if r.get('max_w_tol') else '–'}</b>"
        text += f" · höchstens {zahl(r['max_w'], 1)} W"
        if r.get("abschalt_a") is not None:
            text += " (danach Abschaltung)"
        tab.append(("Leistung", text))
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
    elif e.get("fuehler", True):
        tab.append(("Temperatur", "– (kein Fühler am DL24)"))
    tab.append(("Dauer", dauer_text(r.get("dauer_s", 0))))
    tab.append(("Ende", html.escape(r.get("grund", ""))))
    zeilen.append("<table cellspacing=4>" + "".join(
        f"<tr><td style='color:gray'>{k}</td><td>{v}</td></tr>" for k, v in tab) + "</table>")
    if stufen:
        buchse = any(s.get("buchse_v") for s in stufen)
        kopf = "<tr><td style='color:gray'>Strom</td><td style='color:gray'>Spannung</td>" \
               "<td style='color:gray'>tiefster</td>" + \
               ("<td style='color:gray'>an der Buchse</td>" if buchse else "") + \
               "<td style='color:gray'>Leistung</td><td></td></tr>"
        ee = einstellung_aus(e)
        rot_u, gelb_u, gelb_o, rot_o = ee.grenzen()
        kabel = e.get("kabel_mohm", 0) / 1000

        def zustand(s: dict) -> str:
            v = s["min_v"] + s["strom"] * kabel
            z = nt.ampel(ee, v)
            text = {"gruen": "✔", "gelb": f"⚠ unter {zahl(gelb_u)} V" if v < gelb_u else f"⚠ über {zahl(gelb_o)} V",
                    "rot": f"✘ unter {zahl(rot_u)} V" if v < rot_u else f"✘ über {zahl(rot_o)} V"}[z]
            return f"<td style='color:{AMPEL[z]}'>{text}</td>"

        def schwank(s: dict) -> str:
            if s.get("max_v") is None:
                return "<td>–</td>"
            d = s["max_v"] - s["min_v"]
            return f"<td style='color:{AMPEL[nt.schwank_ampel(ee, d)]}'>{d * 1000:.0f} mV</td>"
        kopf = kopf.replace("<td></td></tr>", "<td style='color:gray'>Schwankung</td><td></td></tr>")
        reihen = "".join(
            f"<tr><td>{zahl(s['soll_a'], 2)} A</td><td>{zahl(s['spannung'], 3)} V</td>"
            f"<td>{zahl(s['min_v'], 3)} V</td>"
            + (f"<td>{zahl(s.get('buchse_v'), 3)} V</td>" if buchse else "") +
            f"<td>{zahl(s['spannung'] * s['strom'], 1)} W</td>" + schwank(s) + zustand(s) + "</tr>"
            for s in stufen)
        zeilen.append("<b>Kennlinie</b><table cellspacing=6>" + kopf + reihen + "</table>")
    for h in r.get("hinweise") or []:
        zeilen.append(f"<span style='color:#b07a00'>⚠ {html.escape(h)}</span>")
    return "<br>".join(zeilen)


def trigger_html(e: dict, r: dict, fach: bool = False) -> str:
    zeilen = [f"<b style='font-size:15px'>{html.escape(e['name'] or 'Ladegerät')}</b> – Schnellladen über "
              "Trigger-Adapter"]
    if "urteil" in r:
        zeilen += urteil_html(r, fach)
    elif r.get("haelt") is True:
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
        zeilen.append("<hr>" + ergebnis_html(t["einstellung"], t["ergebnis"], fach))
    return "<br>".join(zeilen)


class NetzteilReiter(QWidget):
    def __init__(self, fenster) -> None:
        super().__init__()
        self.f = fenster
        self.ablauf: nt.NetzteilAblauf | None = None
        self._marken: list = []
        self._marken_unten: list = []
        self._geplant_s: float | None = None
        self._teil_ab = 0                  # Schnellladen: ab diesem Punkt gehört die Kurve zur aktuellen Spannung
        self._teil_gezeigt = None
        self._nenn_v: float | None = None
        self._bauen()
        self.vorlagen_laden()
        self._vorlage(0)
        self.verlauf_laden()

    # ------------------------------------------------------------------
    def _bauen(self) -> None:
        h = QHBoxLayout(self)
        links = QVBoxLayout()

        g = QGroupBox("Typenschild")
        f = QFormLayout(g)
        self.vorlage = QComboBox()
        self.vorlage.activated.connect(self._vorlage)
        zeile = QHBoxLayout()
        zeile.addWidget(self.vorlage, 1)
        self.knopf_vorlage_neu = QPushButton("Speichern")
        self.knopf_vorlage_neu.setToolTip("Die Angaben vom Typenschild unter dem Gerätenamen als eigene Vorlage "
                                          "speichern")
        self.knopf_vorlage_neu.clicked.connect(self.vorlage_speichern)
        self.knopf_vorlage_weg = QPushButton("Löschen")
        self.knopf_vorlage_weg.setToolTip("Die gewählte eigene Vorlage (★) löschen")
        self.knopf_vorlage_weg.clicked.connect(self.vorlage_loeschen)
        zeile.addWidget(self.knopf_vorlage_neu)
        zeile.addWidget(self.knopf_vorlage_weg)
        f.addRow("Vorlage:", zeile)
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. Anker 20W, Hub Port 3, Netzteil Lötstation")
        f.addRow("Gerät:", self.name)
        self.nenn_v = self._zahlfeld(0, 60, 2, 0.1, " V")
        f.addRow("Ausgangsspannung:", self.nenn_v)
        self.nenn_a = self._zahlfeld(0, 20, 2, 0.1, " A", "nicht angegeben")
        f.addRow("Ausgangsstrom:", self.nenn_a)
        self.nenn_w = self._zahlfeld(0, 200, 1, 1, " W", "nicht angegeben")
        f.addRow("Leistung:", self.nenn_w)
        self.unbekannt = QCheckBox("Strom/Leistung steht nicht drauf – ermitteln")
        self.unbekannt.setToolTip("Dann steigert die App den Strom, bis das Gerät abschaltet, und sagt, "
                                  "wie viel es wirklich liefert")
        self.unbekannt.toggled.connect(self._unbekannt_umschalten)
        f.addRow(self.unbekannt)
        self.toleranz = self._zahlfeld(1, 20, 1, 1, " %")
        self.toleranz.setValue(5)
        f.addRow("Toleranz Spannung:", self.toleranz)
        self.kabel = self._zahlfeld(0, 3000, 0, 10, " mΩ", "nicht bekannt")
        self.kabel.setToolTip("Widerstand von USB-Kabel und Adapter (Hin- und Rückleitung). Wird herausgerechnet, "
                              "damit das Kabel nicht dem Netzteil angelastet wird.\n\nSo bekommst du ihn: dasselbe "
                              "Kabel an einem guten Ladegerät prüfen und im Ergebnis „als Kabelwert übernehmen“.")
        self.kabel.valueChanged.connect(self._angabe_zeigen)
        zeile = QHBoxLayout()
        zeile.addWidget(self.kabel, 1)
        self.knopf_kabel_messen = QPushButton("Kabel messen …")
        self.knopf_kabel_messen.setToolTip("Misst den Widerstand von Kabel und Adapter an einem guten Ladegerät "
                                           "und trägt ihn hier ein")
        self.knopf_kabel_messen.clicked.connect(self.kabel_messen)
        zeile.addWidget(self.knopf_kabel_messen)
        f.addRow("Kabel + Adapter:", zeile)
        self.kabel_name = QLineEdit()
        self.kabel_name.setPlaceholderText("welches Kabel / welcher Adapter, z. B. Anker USB-C 1 m + Trigger-Adapter")
        f.addRow("Kabel (Bezeichnung):", self.kabel_name)
        zeile = QHBoxLayout()
        self.kabel_typ = QComboBox()
        self.kabel_typ.addItem("– Typ wählen für die Bewertung –", "")
        for schluessel, (name, grenze, *_rest) in nt.KABEL_TYPEN.items():
            self.kabel_typ.addItem(f"{name} – erlaubt {grenze:.0f} mΩ", schluessel)
        zeile.addWidget(self.kabel_typ, 1)
        f.addRow("Kabeltyp:", zeile)
        self.kabel_urteil = QLabel()
        self.kabel_urteil.setWordWrap(True)
        f.addRow(self.kabel_urteil)
        # Kabel bleibt zwischen zwei Programmstarts eingetragen
        from PySide6.QtCore import QSettings
        self._einst = QSettings("dl24-akkutest", "dl24-akkutest")
        self._kabel_wann = float(self._einst.value("kabel/wann", 0) or 0)
        self.kabel_name.setText(str(self._einst.value("kabel/name", "") or ""))
        self.kabel_typ.setCurrentIndex(max(0, self.kabel_typ.findData(str(self._einst.value("kabel/typ", "") or ""))))
        self.kabel_typ.currentIndexChanged.connect(self._kabel_merken)
        self.kabel.setValue(float(self._einst.value("kabel/mohm", 0) or 0))
        self.kabel.valueChanged.connect(self._kabel_merken)
        self.kabel_name.textChanged.connect(self._kabel_merken)
        self._kabel_urteil_zeigen()
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
            haken.toggled.connect(self._angabe_zeigen)
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
        self.tests_gruppe = g
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
        self.bis_ende = QCheckBox("bis zur Abschaltung ⚠")
        self.bis_ende.setToolTip("Weiter steigern, bis das Netzteil abschaltet oder die Spannung einbricht - "
                                 "höchstens 5 A bei USB und 150 W. Zeigt die größte Leistung.")
        self.bis_ende.toggled.connect(self._bis_ende_umschalten)
        f.addWidget(self.mit_abschalt, 2, 0)
        f.addWidget(self.max_proz, 2, 1)
        f.addWidget(self.bis_ende, 2, 2)
        self.warnung_ende = QLabel("⚠ Das Netzteil wird bis zum Abschalten überlastet. Ein Gerät ohne "
                                   "Schutzschaltung kann dabei kaputtgehen oder sehr heiß werden. Nur unter "
                                   "Aufsicht prüfen, nichts Brennbares in der Nähe.")
        self.warnung_ende.setWordWrap(True)
        self.warnung_ende.setStyleSheet("color:#d03b3b; font-weight:bold;")
        self.warnung_ende.hide()
        f.addWidget(self.warnung_ende, 3, 0, 1, 3)
        self.mit_fuehler = QCheckBox("Temperaturfühler, Grenze:")
        self.mit_fuehler.setToolTip("Den externen Fühler des DL24 auswerten - abschalten bei der Grenze")
        self.mit_fuehler.toggled.connect(self._fuehler_umschalten)
        f.addWidget(self.mit_fuehler, 4, 0)
        self.temp_grenze = QSpinBox()
        self.temp_grenze.setRange(30, 120)
        self.temp_grenze.setValue(70)
        self.temp_grenze.setSuffix(" °C")
        self.temp_grenze.setToolTip("Gilt für den Temperaturfühler des DL24 - am Netzteil festkleben")
        f.addWidget(self.temp_grenze, 4, 1)
        hinweis = QLabel("Den Fühler des DL24 mit Klebeband ans Gehäuse des Netzteils kleben. Bei der Grenze "
                         "wird abgebrochen.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        f.addWidget(hinweis, 5, 0, 1, 3)
        self.fuehler_hinweis = hinweis
        hinweis.hide()
        self.temp_grenze.setEnabled(False)
        self.dauer = QLabel()
        f.addWidget(self.dauer, 6, 0, 1, 3)
        knoepfe = QHBoxLayout()
        self.knopf_start = QPushButton("▶  Prüfen")
        self.knopf_start.setStyleSheet("font-weight: bold; padding: 8px;")
        self.knopf_start.clicked.connect(lambda: self.starten())
        self.knopf_abbruch = QPushButton("■  Abbrechen")
        self.knopf_abbruch.setStyleSheet("padding: 8px;")
        self.knopf_abbruch.clicked.connect(lambda: self.abbrechen())
        for k in (self.knopf_start, self.knopf_abbruch):
            k.setMinimumHeight(k.fontMetrics().height() + 22)
            k.setSizePolicy(k.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        knoepfe.addWidget(self.knopf_start, 2)
        knoepfe.addWidget(self.knopf_abbruch, 1)
        f.addLayout(knoepfe, 7, 0, 1, 3)
        self.steuer_hinweis = QLabel()
        self.steuer_hinweis.setWordWrap(True)
        self.steuer_hinweis.setStyleSheet(gedaempft())
        f.addWidget(self.steuer_hinweis, 8, 0, 1, 3)
        links.addWidget(g)
        self.sperr_hinweis = QLabel("⬆  Erst oben die Angaben vom Typenschild eintragen oder eine Vorlage wählen – "
                                    "dann lassen sich die Tests einstellen.")
        self.sperr_hinweis.setWordWrap(True)
        self.sperr_hinweis.setStyleSheet("color:#c77700; font-weight:bold;")
        links.insertWidget(links.indexOf(g), self.sperr_hinweis)
        links.addStretch(1)
        lw = QWidget()
        lw.setLayout(links)
        # Rollbar statt gequetscht: sonst schneidet Qt bei kleinem Fenster die Knöpfe ab
        rolle = QScrollArea()
        rolle.setWidgetResizable(True)
        rolle.setFrameShape(QFrame.NoFrame)
        rolle.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rolle.setWidget(lw)
        # So breit wie der Inhalt braucht - schmaler würde Qt rechts abschneiden
        rolle.setMinimumWidth(lw.sizeHint().width() + rolle.verticalScrollBar().sizeHint().width() + 8)
        h.addWidget(rolle)

        # Strom und Leistung hängen zusammen: wer eins einträgt, bekommt das andere
        self.nenn_v.valueChanged.connect(lambda _: self._abgleich("v"))
        self.nenn_a.valueChanged.connect(lambda _: self._abgleich("a"))
        self.nenn_w.valueChanged.connect(lambda _: self._abgleich("w"))
        self.toleranz.valueChanged.connect(self._angabe_zeigen)
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
                                    ("t", "Temperatur (Fühler)"), ("r", "Widerstand (Netzteil + Kabel)")]):
            self.anz[k] = Anzeige(t)
            raster.addWidget(self.anz[k], 0, i)
        self._text_kabel_zu_gross = ("⚠ Kabelwert zu groß – er ist größer als der ganze Spannungsverlust. Bitte "
                                     "mit „Kabel messen …“ an einem anderen, guten Ladegerät neu bestimmen.")
        self._text_kabel_alles = ("⚠ Der Kabelwert erklärt den ganzen Spannungsverlust. Wurde das Kabel mit genau "
                                  "diesem Netzteil gemessen? Dann ist das kein Prüfergebnis – das Kabel mit einem "
                                  "anderen Ladegerät messen.")
        self.kabel_warnung = QLabel(self._text_kabel_zu_gross)
        self.kabel_warnung.setWordWrap(True)
        self.kabel_warnung.setStyleSheet("color:#d03b3b; font-weight:bold;")
        self.kabel_warnung.hide()
        self.schritt = QLabel()
        self.schritt.setWordWrap(True)
        self.schritt.setMinimumHeight(40)
        self.schritt.setStyleSheet("font-weight: bold;")
        raster.addWidget(self.schritt, 1, 0, 1, 4)
        self.knopf_weiter = QPushButton("Kommt nicht – überspringen")
        self.knopf_weiter.setToolTip("Diese Spannung liefert das Ladegerät nicht")
        self.knopf_weiter.clicked.connect(self._ueberspringen)
        self.knopf_weiter.hide()
        raster.addWidget(self.knopf_weiter, 1, 4)
        raster.addWidget(self.kabel_warnung, 2, 0, 1, 5)
        ol.addLayout(raster)
        # Ein Diagramm in drei Streifen mit gemeinsamer Zeitachse:
        # Spannung · Strom und Leistung · Temperatur (nur mit Fühler)
        self.flaeche = pg.GraphicsLayoutWidget()
        self.flaeche.setBackground(None)
        self.flaeche.setMinimumHeight(380)
        self.bild = self.flaeche.addPlot(row=0, col=0)
        self.bild.setLabel("left", "Spannung (V)")
        self.legende = self.bild.addLegend(offset=(-10, 10))
        self.linie = self.bild.plot([], [], pen=pg.mkPen("#2f80ed", width=2), name="gemessen (am DL24)")
        # Mit Kabelwert: die Grenzen ans Kabelende umgerechnet (Grenze minus Kabelverlust) -
        # dann liest man an der gemessenen Kurve direkt ab, ob das Netzteil reicht
        self.linie_b = self.bild.plot([], [], pen=pg.mkPen("#c77700", width=2, style=Qt.DashLine))
        self.linie_r = self.bild.plot([], [], pen=pg.mkPen("#d03b3b", width=2, style=Qt.DashLine))
        self.grenze = pg.InfiniteLine(angle=0, pen=pg.mkPen("#c77700", width=1, style=Qt.DashLine))
        self.grenze.hide()
        self.bild.addItem(self.grenze)
        # Ampel hinter der Kurve: rot · gelb · grün · gelb · rot
        self.baender = []
        for farbe in ((208, 59, 59), (199, 119, 0), (46, 158, 79), (199, 119, 0), (208, 59, 59)):
            band = pg.LinearRegionItem(values=(0, 1), orientation="horizontal", movable=False,
                                       brush=pg.mkBrush(*farbe, 38), pen=pg.mkPen(None))
            band.setZValue(-20)
            band.hide()
            self.bild.addItem(band, ignoreBounds=True)
            self.baender.append(band)
        self._kabel_ohm = 0.0
        self.bild_i = self.flaeche.addPlot(row=1, col=0)
        self.bild_i.setLabel("left", "Strom (A)", color="#2e9e4f")
        self.bild_i.setLabel("right", "Leistung (W)", color="#e08a00")
        self.linie_i = self.bild_i.plot([], [], pen=pg.mkPen("#2e9e4f", width=2))
        self.box_p = pg.ViewBox()                      # zweite Skala rechts für die Leistung
        self.bild_i.scene().addItem(self.box_p)
        self.bild_i.getAxis("right").linkToView(self.box_p)
        self.box_p.setXLink(self.bild_i)
        self.linie_p = pg.PlotCurveItem([], [], pen=pg.mkPen("#e08a00", width=1.5, style=Qt.DashLine))
        self.box_p.addItem(self.linie_p)
        self.bild_i.vb.sigResized.connect(lambda: self.box_p.setGeometry(self.bild_i.vb.sceneBoundingRect()))
        self.bild_t = pg.PlotItem()
        self.bild_t.setLabel("left", "Temperatur (°C)", color="#d03b3b")
        self.linie_t = self.bild_t.plot([], [], pen=pg.mkPen("#d03b3b", width=2))
        self._mit_temp = False
        for b in (self.bild, self.bild_i, self.bild_t):
            b.showGrid(x=True, y=True, alpha=0.25)
            self.f._ohne_vorsatz(b)
            b.getAxis("left").setWidth(62)              # Streifen bündig untereinander
        self.bild_i.getAxis("right").enableAutoSIPrefix(False)
        for b in (self.bild, self.bild_i, self.bild_t):   # rechts gleich breit, sonst nicht bündig
            b.showAxis("right")
            b.getAxis("right").setWidth(48)
        for b in (self.bild, self.bild_t):
            b.getAxis("right").setStyle(showValues=False)
        self.bild_i.setXLink(self.bild)
        self.bild_t.setXLink(self.bild)
        self.bild.hideAxis("bottom")
        self.bild_i.setLabel("bottom", "Zeit (min)")
        lay = self.flaeche.ci.layout
        lay.setRowStretchFactor(0, 3)
        lay.setRowStretchFactor(1, 2)
        ol.addWidget(self.flaeche, 1)
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
        knoepfe = QHBoxLayout()
        self.knopf_kabel = QPushButton("Widerstand als Kabelwert übernehmen")
        self.knopf_kabel.setToolTip("Nur bei einem guten Ladegerät sinnvoll: dann ist fast der ganze "
                                    "Widerstand das Kabel")
        self.knopf_kabel.clicked.connect(self._kabel_uebernehmen)
        self.knopf_pdf = QPushButton("Bericht speichern (PDF) …")
        self.knopf_pdf.clicked.connect(self.bericht_speichern)
        knoepfe.addWidget(self.knopf_kabel)
        knoepfe.addStretch(1)
        self.knopf_gross = QPushButton("Ergebnis groß anzeigen")
        self.knopf_gross.clicked.connect(self.ergebnis_fenster)
        self.knopf_gross.setEnabled(False)
        knoepfe.addWidget(self.knopf_gross)
        knoepfe.addWidget(self.knopf_pdf)
        self.knopf_kabel.setEnabled(False)
        self.knopf_pdf.setEnabled(False)
        ul.addLayout(knoepfe)
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
        self.tabelle.itemDoubleClicked.connect(lambda _: self.ergebnis_fenster())
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
    def _abgleich(self, geaendert: str) -> None:
        v, a, w = self.nenn_v.value(), self.nenn_a.value(), self.nenn_w.value()
        for feld in (self.nenn_a, self.nenn_w):
            feld.blockSignals(True)
        if geaendert == "w":
            self.nenn_a.setValue(w / v if v > 0 and w > 0 else 0)
        elif geaendert == "a" or a > 0:
            self.nenn_w.setValue(v * a if a > 0 else 0)
        elif geaendert == "v" and w > 0:
            self.nenn_a.setValue(w / v if v > 0 else 0)
        for feld in (self.nenn_a, self.nenn_w):
            feld.blockSignals(False)
        self._angabe_zeigen()

    def vorlagen_laden(self, auswaehlen: str | None = None) -> None:
        self.vorlage.blockSignals(True)
        self.vorlage.clear()
        self.vorlage.addItem("– wählen oder unten selbst eintragen –", None)
        for name, daten in self.f.speicher.vorlagen():
            self.vorlage.addItem(f"★ {name}", {"eigen": name, **daten})
        for name, v, a in nt.VORLAGEN:
            self.vorlage.addItem(nt.vorlage_text(name, v, a), (v, a, name))
        if auswaehlen:
            i = self.vorlage.findText(f"★ {auswaehlen}")
            self.vorlage.setCurrentIndex(max(0, i))
        self.vorlage.blockSignals(False)
        self._vorlage_knoepfe()

    def _vorlage_knoepfe(self) -> None:
        d = self.vorlage.currentData()
        self.knopf_vorlage_weg.setEnabled(isinstance(d, dict) and not self.laeuft)

    def _typenschild(self) -> dict:
        """Alles aus dem Typenschild, was eine eigene Vorlage braucht."""
        return {"nenn_v": self.nenn_v.value(), "nenn_a": self.nenn_a.value(), "nenn_w": self.nenn_w.value(),
                "toleranz": self.toleranz.value(), "unbekannt": self.unbekannt.isChecked(),
                "schnell": self.schnell.isChecked(),
                "trigger": [[v, haken.isChecked(), a.value()] for v, haken, a in self.trigger]}

    def vorlage_speichern(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.information(self, "Vorlage speichern", "Bitte zuerst bei „Gerät“ einen Namen eintragen – "
                                                               "unter diesem Namen wird die Vorlage gespeichert.")
            return
        if not self.bereit():
            QMessageBox.information(self, "Vorlage speichern", "Bitte zuerst die Angaben vom Typenschild "
                                                               "eintragen.")
            return
        if name in {n for n, _ in self.f.speicher.vorlagen()} and not self.f._frage(
                "Vorlage speichern", f"Es gibt schon eine Vorlage „{name}“. Überschreiben?"):
            return
        self.f.speicher.vorlage_speichern(name, self._typenschild())
        self.vorlagen_laden(auswaehlen=name)
        self.f.b.ereignis.emit("info", f"Vorlage „{name}“ gespeichert")

    def vorlage_loeschen(self) -> None:
        d = self.vorlage.currentData()
        if not isinstance(d, dict):
            return
        if not self.f._frage("Vorlage löschen", f"Eigene Vorlage „{d['eigen']}“ löschen?"):
            return
        self.f.speicher.vorlage_loeschen(d["eigen"])
        self.vorlagen_laden()

    def _vorlage(self, _=None) -> None:
        d = self.vorlage.currentData()
        self._vorlage_knoepfe()
        if isinstance(d, dict):
            # eigene Vorlage: alles so eintragen, wie es gespeichert wurde
            self.schnell.setChecked(d.get("schnell", False))
            for (v, haken, a), (v2, an, strom) in zip(self.trigger, d.get("trigger", [])):
                haken.setChecked(an)
                a.setValue(strom)
            self.unbekannt.setChecked(d.get("unbekannt", False))
            for feld, wert in ((self.nenn_v, d.get("nenn_v", 0)), (self.nenn_a, d.get("nenn_a", 0)),
                               (self.nenn_w, d.get("nenn_w", 0))):
                feld.blockSignals(True)
                feld.setValue(wert)
                feld.blockSignals(False)
            self.toleranz.setValue(d.get("toleranz", 5))
            self.name.setText(d["eigen"])
        elif d:
            self.schnell.setChecked(False)
            v, a, name = d
            self.unbekannt.setChecked(False)
            self.nenn_v.setValue(v)
            self.nenn_a.setValue(a)
            self.name.setPlaceholderText(name)
        self._angabe_zeigen()

    def _bis_ende_umschalten(self, an: bool) -> None:
        if an and not self.f._frage(
                "Bis zur Abschaltung prüfen",
                "Achtung: Bei diesem Test wird das Netzteil absichtlich überlastet, bis es abschaltet oder die "
                "Spannung zusammenbricht.\n\n"
                "• Gute Netzteile schalten sich dabei einfach ab – das ist ihr Schutz.\n"
                "• Billige Netzteile ohne Schutzschaltung können dabei kaputtgehen, sehr heiß werden oder im "
                "schlimmsten Fall brennen.\n\n"
                "Nur unter Aufsicht prüfen, nichts Brennbares in der Nähe, und abbrechen, wenn es riecht oder "
                "knistert.\n\nTrotzdem bis zur Abschaltung prüfen?"):
            self.bis_ende.blockSignals(True)
            self.bis_ende.setChecked(False)
            self.bis_ende.blockSignals(False)
            an = False
        if an and not self.mit_abschalt.isChecked():
            self.mit_abschalt.setChecked(True)
        self.warnung_ende.setVisible(an)
        self.max_proz.setEnabled(not an and not self.laeuft)
        self._dauer_zeigen()

    def _fuehler_umschalten(self, an: bool) -> None:
        self.temp_grenze.setEnabled(an and not self.laeuft)
        self.fuehler_hinweis.setVisible(an)

    def _felder_sperren(self) -> None:
        frei = not self.laeuft and not self.schnell.isChecked()
        # Vorlagen gehen immer - auch eigene für Schnellladegeräte
        for w in (self.vorlage, self.knopf_vorlage_neu):
            w.setEnabled(not self.laeuft)
        self._vorlage_knoepfe()
        for w in (self.nenn_v, self.unbekannt):
            w.setEnabled(frei)
        for w in (self.nenn_a, self.nenn_w):
            w.setEnabled(frei and not self.unbekannt.isChecked())

    def _schnell_umschalten(self, an: bool) -> None:
        self.schnell_box.setVisible(an)
        self._felder_sperren()
        self._angabe_zeigen()

    def _trigger_stufen(self) -> list[tuple[float, float]]:
        return [(v, round(a.value(), 2)) for v, haken, a in self.trigger if haken.isChecked()]

    def _ueberspringen(self) -> None:
        if isinstance(self.ablauf, nt.TriggerAblauf):
            self.ablauf.ueberspringen()

    def _ist_hub(self) -> bool:
        d = self.vorlage.currentData()
        name = (self.name.text() or self.name.placeholderText()).lower()
        return bool(isinstance(d, tuple) and d[2].startswith("USB-Hub")) or "hub" in name.split("z. b.")[0]

    def einstellung(self) -> nt.NetzteilEinstellung:
        return nt.NetzteilEinstellung(
            name=self.name.text().strip() or self.name.placeholderText().split("z. B.")[0].strip()
            or "Netzteil",
            nenn_v=round(self.nenn_v.value(), 2), nenn_a=round(self.nenn_a.value(), 2),
            nenn_w=round(self.nenn_w.value(), 1), toleranz_proz=self.toleranz.value(),
            stufentest=self.mit_stufen.isChecked(), stufen=self.stufen.value(), stufe_s=self.stufe_s.value(),
            dauertest=self.mit_dauer.isChecked(), dauer_proz=self.dauer_proz.value(),
            dauer_min=self.dauer_min.value(), abschalttest=self.mit_abschalt.isChecked(),
            max_proz=self.max_proz.value(), temp_grenze=self.temp_grenze.value(),
            fuehler=self.mit_fuehler.isChecked(), hub=self._ist_hub(),
            bis_ende=self.bis_ende.isChecked(), kabel_mohm=self.kabel.value(),
            kabel_name=self.kabel_name.text().strip(), kabel_wann=self._kabel_wann,
            kabel_typ=self.kabel_typ.currentData() or "")

    def _unbekannt_umschalten(self, an: bool) -> None:
        if an:
            for feld in (self.nenn_a, self.nenn_w):
                feld.blockSignals(True)
                feld.setValue(0)
                feld.blockSignals(False)
        self._felder_sperren()
        self._angabe_zeigen()

    def bereit(self) -> bool:
        """Sind genug Angaben da, um zu prüfen?"""
        if self.schnell.isChecked():
            return bool(self._trigger_stufen())
        if self.nenn_v.value() <= 0:
            return False
        return self.nenn_a.value() > 0 or self.unbekannt.isChecked()

    def _freigeben(self) -> None:
        ok = self.bereit()
        self.tests_gruppe.setEnabled(ok or self.laeuft)
        self.sperr_hinweis.setVisible(not ok and not self.laeuft)
        self.knopf_start.setEnabled(getattr(self, "_steuer_ok", False) and ok and not self.laeuft)

    def _angabe_zeigen(self) -> None:
        self._freigeben()
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
        if self.unbekannt.isChecked():
            teile.append("Die App ermittelt, wie viel es liefert")
        if self._ist_hub():
            teile.append("USB-Hub: Geprüft wird nur der Port, an dem der DL24 steckt – den Port am besten in den "
                         "Namen schreiben, z. B. „Hub Port 1“")
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
        if not self.bereit():
            return []
        if self.unbekannt.isChecked() or e.strom_a <= 0:
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
        self._steuer_ok = steuerbar and not anderer_test
        self.knopf_start.setEnabled(self._steuer_ok and not self.laeuft and self.bereit())
        self.knopf_abbruch.setEnabled(self.laeuft)
        self.knopf_kabel_messen.setEnabled(self._steuer_ok and not self.laeuft)
        for w in (self.trigger_felder() + [self.schnell]):
            w.setEnabled(not self.laeuft)
        self._felder_sperren()
        self._freigeben()
        self.max_proz.setEnabled(not self.laeuft and not self.bis_ende.isChecked())
        self.temp_grenze.setEnabled(not self.laeuft and self.mit_fuehler.isChecked())
        for w in (self.name, self.toleranz,
                  self.mit_stufen, self.stufen, self.stufe_s, self.mit_dauer, self.dauer_proz,
                  self.dauer_min, self.mit_abschalt, self.mit_fuehler, self.kabel, self.bis_ende,
                  self.kabel_name, self.kabel_typ):
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

    def _kabel_setzen(self, mohm: float) -> None:
        """Gemessener Kabelwert: mit Zeitpunkt merken (von Hand eingetragen hat keinen)."""
        self._kabel_wann = time.time()
        self.kabel.blockSignals(True)
        self.kabel.setValue(mohm)
        self.kabel.blockSignals(False)
        self._kabel_merken()
        self._angabe_zeigen()

    def _kabel_merken(self, *_) -> None:
        if self.sender() is self.kabel:
            self._kabel_wann = 0.0              # von Hand geändert - nicht mehr "gemessen am"
        self._einst.setValue("kabel/mohm", self.kabel.value())
        self._einst.setValue("kabel/name", self.kabel_name.text())
        self._einst.setValue("kabel/wann", self._kabel_wann)
        self._einst.setValue("kabel/typ", self.kabel_typ.currentData())
        self._kabel_urteil_zeigen()

    def _kabel_urteil_zeigen(self) -> None:
        b = nt.kabel_bewerten(self.kabel.value(), self.kabel_typ.currentData())
        if not b:
            self.kabel_urteil.setText("")
            self.kabel_urteil.hide()
            return
        ampel, text = b
        self.kabel_urteil.setText(f"<span style='color:{AMPEL[ampel]}; font-weight:bold'>"
                                  f"{ {'gruen': '🟢', 'gelb': '🟡', 'rot': '🔴'}[ampel]} {html.escape(text)}</span>")
        self.kabel_urteil.show()

    def kabel_messen(self) -> None:
        """Kabel + Adapter an einem guten Ladegerät messen: kurzer Stufentest, die
        Steigung der Kennlinie ist der Widerstand. Ein gutes Ladegerät hat selbst
        kaum Widerstand - was es hat, wird dem Kabel zugerechnet, also eher zu
        Gunsten des später geprüften Geräts."""
        g = self.f.geraet
        if not g or not g.kann_steuern or self.laeuft:
            QMessageBox.information(self, "Kabel messen", "Erst den DL24 über USB verbinden.")
            return
        if not self.f._frage(
                "Kabel messen",
                "So wird der Widerstand von Kabel und Adapter gemessen:\n\n"
                "1. Ein gutes Ladegerät nehmen (z. B. Original-Handyladegerät, mindestens 2 A).\n"
                "2. Genau das Kabel und den Adapter, mit denen du prüfst, dazwischen stecken.\n"
                "3. Auf „Ja“ drücken – die Messung dauert etwa 40 Sekunden.\n\n"
                "Der Wert wird danach im Feld „Kabel + Adapter“ eingetragen. Ist alles angeschlossen?"):
            return
        e = nt.NetzteilEinstellung("Kabelmessung", 5.0, 2.0, stufen=4, stufe_s=10, dauertest=False,
                                   abschalttest=False, fuehler=False)
        self._kabel_messung = True
        self.ablauf = nt.NetzteilAblauf(e, g, bei_ereignis=lambda a, t: self.f.b.ereignis.emit("nt:" + a, t))
        self._nenn_v, self._geplant_s = 5.0, sum(x.dauer_s for x in self.ablauf.schritte) + 5
        self.ergebnis.hide()
        self.ergebnis_rahmen.hide()
        self._grenzen_zeigen(None)
        self._teil_ab, self._teil_gezeigt = 0, None
        self._kurven([])
        self._marken_zeichnen([], neu=True)
        self.bild.setXRange(0, self._geplant_s / 60, padding=0.02)
        self.schritt.setText("Kabel wird gemessen …")
        self.f._zustand_zeigen()

    def _kabel_fertig(self, ab) -> None:
        r = ab.ergebnis
        self.f._zustand_zeigen()
        if ab.zustand != "fertig" or not r.widerstand_mohm:
            self.schritt.setText("")
            QMessageBox.warning(self, "Kabel messen", "Die Messung hat nicht geklappt: " + (r.grund or "kein Wert") +
                                "\n\nIst das Ladegerät eingesteckt und schafft es 2 A?")
            return
        self._kabel_setzen(r.widerstand_mohm)
        self.schritt.setText(f"Kabel + Adapter: {r.widerstand_mohm:.0f} mΩ – eingetragen")
        log.info("Kabel gemessen: %.0f mΩ", r.widerstand_mohm)
        QMessageBox.information(self, "Kabel messen",
                                f"Kabel + Adapter: {r.widerstand_mohm:.0f} mΩ.\n\n"
                                + ((nt.kabel_bewerten(r.widerstand_mohm, self.kabel_typ.currentData()) or ("", ""))[1]
                                   or "Für eine Bewertung oben den Kabeltyp wählen.") + "\n\nDer Wert ist eingetragen und wird "
                                "bei den nächsten Prüfungen herausgerechnet. Jetzt das zu prüfende Gerät anschließen.")

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
            self._grenzen_zeigen(None)
        else:
            e = plan[0]
            self.ablauf = nt.NetzteilAblauf(e, g, bei_ereignis=melden)
            self._grenzen_zeigen(e)
        self.ergebnis.hide()
        self.ergebnis_rahmen.hide()
        self._teil_ab, self._teil_gezeigt = 0, None
        self._kurven([])
        self._marken_zeichnen([], neu=True)
        # Zeitachse gleich über die ganze geplante Dauer
        self._nenn_v = self.ablauf.einstellung.nenn_v if isinstance(self.ablauf, nt.NetzteilAblauf) else None
        if isinstance(self.ablauf, nt.NetzteilAblauf):
            self._geplant_s = sum(x.dauer_s for x in self.ablauf.schritte) + 5
            self.bild.setXRange(0, self._geplant_s / 60, padding=0.02)
        else:
            self._geplant_s = None
            self.bild.enableAutoRange(x=True)
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

    def _grenzen_zeigen(self, e: nt.NetzteilEinstellung | None) -> None:
        """Ampelbänder und gelbe Linie für diese Einstellung - oder alles weg."""
        self.kabel_warnung.hide()
        if e is None:
            for b in self.baender:
                b.hide()
            self.grenze.hide()
            self._kabel_ohm = 0.0
            self.bild.setLabel("left", "Spannung (V)")
            self.legende.removeItem(self.linie_b)
            self.legende.removeItem(self.linie_r)
            return
        rot_u, gelb_u, gelb_o, rot_o = e.grenzen()
        weit = e.nenn_v * 10 + 50
        for b, (lo, hi) in zip(self.baender, ((-weit, rot_u), (rot_u, gelb_u), (gelb_u, gelb_o), (gelb_o, rot_o),
                                              (rot_o, weit))):
            b.setRegion((lo, hi))
            b.show()
        self.grenze.setValue(gelb_u)
        self.grenze.show()
        self._kabel_ohm = e.kabel_mohm / 1000
        self._gelb_u, self._rot_u = gelb_u, rot_u
        self.bild.setLabel("left", "Spannung (V)")
        self.legende.removeItem(self.linie_b)
        self.legende.removeItem(self.linie_r)
        if e.kabel_mohm:
            # Bänder gelten an der Buchse - am Kabelende verschieben sie sich mit dem Strom.
            # Statt Bändern die umgerechneten Grenzlinien.
            for b in self.baender:
                b.hide()
            self.grenze.hide()
            self.legende.addItem(self.linie_b, f"Mindestwert {zahl(gelb_u)} V, ans Kabelende umgerechnet")
            self.legende.addItem(self.linie_r, f"Untergrenze {zahl(rot_u)} V, ans Kabelende umgerechnet")

    def _kurven(self, punkte: list) -> None:
        """Alle Streifen aus den Punkten (s, V, A, °C oder None)."""
        x = [p[0] / 60 for p in punkte]
        # Gezeigt wird nur, was gemessen wurde. Mit Kabelwert kommen die Grenzen dazu,
        # ans Kabelende umgerechnet: liegt Blau darüber, reicht das Netzteil.
        gemessen = [p[1] for p in punkte]
        self.linie.setData(x, gemessen)
        v = list(gemessen)
        self.linie_b.setData([], [])
        self.linie_r.setData([], [])
        self.kabel_warnung.hide()
        if self._kabel_ohm and punkte:
            buchse = [p[1] + p[2] * self._kabel_ohm for p in punkte]
            leer = max((p[1] for p in punkte if p[2] < 0.01), default=None)
            belastet = [(b, p[2]) for b, p in zip(buchse, punkte) if p[2] > 0.3]
            if leer is not None and max(buchse) > leer + 0.02:
                # mehr als ohne Last geht an der Buchse nicht - Kabelwert falsch
                self.kabel_warnung.setText(self._text_kabel_zu_gross)
                self.kabel_warnung.show()
            else:
                if leer is not None and belastet and max(i for _, i in belastet) > 0.8 and \
                        all(abs(b - leer) < 0.015 for b, _ in belastet):
                    # das Kabel erklärt den ganzen Abfall - meist mit diesem Netzteil gemessen
                    self.kabel_warnung.setText(self._text_kabel_alles)
                    self.kabel_warnung.show()
                gelb = [self._gelb_u - p[2] * self._kabel_ohm for p in punkte]
                rot = [self._rot_u - p[2] * self._kabel_ohm for p in punkte]
                self.linie_b.setData(x, gelb)
                self.linie_r.setData(x, rot)
                v += [g for g, p in zip(gelb, punkte) if p[2] > 0.01]
                v += [g for g, p in zip(rot, punkte) if p[2] > 0.01]
        # Spannungsachse nach dem Betrieb, nicht nach dem Einbruch auf 0 beim Abschalten -
        # sonst werden die Stufen platt
        if self._nenn_v and v:
            # bei Schnellladen nur die aktuelle Spannung - sonst reicht die Achse von 5 bis 20 V
            if self._teil_ab and len(punkte) > self._teil_ab:
                v = [p[1] for p in punkte[self._teil_ab:]]
            gut = [u for u in v if u >= self._nenn_v * nt.ZUSAMMENBRUCH] or v
            lo, hi = min(gut), max(gut)
            if self.grenze.isVisible():
                lo = min(lo, self.grenze.value())
            rand = max(0.02, (hi - lo) * 0.12)
            self.bild.setYRange(lo - rand, hi + rand, padding=0)
        else:
            self.bild.enableAutoRange(y=True)
        self.linie_i.setData(x, [p[2] for p in punkte])
        self.linie_p.setData(x, [p[1] * p[2] for p in punkte])
        mit = [(xx, p[3]) for xx, p in zip(x, punkte) if len(p) > 3 and p[3] is not None]
        if mit and not self._mit_temp:
            self.flaeche.addItem(self.bild_t, row=2, col=0)
            self.flaeche.ci.layout.setRowStretchFactor(2, 2)
            self.bild_i.setLabel("bottom", "")
            self.bild_i.hideAxis("bottom")
            self.bild_t.setLabel("bottom", "Zeit (min)")
            self._mit_temp = True
        elif not mit and self._mit_temp:
            self.flaeche.removeItem(self.bild_t)
            self.bild_i.showAxis("bottom")
            self.bild_i.setLabel("bottom", "Zeit (min)")
            self._mit_temp = False
        self.linie_t.setData([a for a, _ in mit], [b for _, b in mit])
        self.box_p.enableAutoRange(y=True)

    def _marken_zeichnen(self, marken: list, neu: bool = False) -> None:
        """Senkrechte Linien an jedem Stufenwechsel, beschriftet mit dem Strom."""
        if neu:
            for linie in getattr(self, "_marken", []):
                self.bild.removeItem(linie)
            for b, linie in getattr(self, "_marken_unten", []):
                b.removeItem(linie)
            self._marken = []
            self._marken_unten = []
        for t, text in marken[len(self._marken):]:
            for b in (self.bild_i, self.bild_t):
                unten = pg.InfiniteLine(pos=t / 60, angle=90, movable=False,
                                        pen=pg.mkPen((128, 128, 128, 110), width=1, style=Qt.DashLine))
                b.addItem(unten)
                self._marken_unten.append((b, unten))
            linie = pg.InfiniteLine(pos=t / 60, angle=90, movable=False,
                                    pen=pg.mkPen((128, 128, 128, 140), width=1, style=Qt.DashLine),
                                    label=text, labelOpts={"position": 0.04, "rotateAxis": (1, 0),
                                                           "anchors": [(0, 1), (0, 1)],
                                                           "color": (140, 140, 140)})
            self.bild.addItem(linie)
            self._marken.append(linie)

    def messwert(self, m: Messwert) -> None:
        stellen = self.f.geraet.spannung_stellen if self.f.geraet else 3
        self.anz["u"].setzen(zahl(m.spannung, stellen, "V"))
        self.anz["i"].setzen(zahl(m.strom, 3, "A"))
        self.anz["p"].setzen(zahl(m.leistung, 2, "W"))
        # Widerstand laufend: Spannungsverlust gegenüber dem Leerlauf durch den Strom
        ab = self.ablauf
        teil = ab.teil if isinstance(ab, nt.TriggerAblauf) else ab
        leer = teil.ergebnis.leerlauf_v if isinstance(teil, nt.NetzteilAblauf) else None
        if leer and m.strom > 0.1 and ab and ab.laeuft:
            self.anz["r"].setzen(f"{max(0.0, (leer - m.spannung) / m.strom) * 1000:.0f} mΩ")
        elif not (ab and ab.laeuft):
            r = getattr(self, "_angezeigt", (None, {}))[1] or {}
            self.anz["r"].setzen(f"{r['widerstand_mohm']:.0f} mΩ" if r.get("widerstand_mohm") else "–")
        if not self.mit_fuehler.isChecked():
            self.anz["t"].setzen("aus")
        else:
            self.anz["t"].setzen(zahl(m.temp_fuehler, 1, "°C") if m.temp_fuehler is not None else "kein Fühler")
        ab = self.ablauf
        teil = ab.teil if isinstance(ab, nt.TriggerAblauf) else ab
        if isinstance(ab, nt.TriggerAblauf) and teil is not None and teil is not self._teil_gezeigt:
            # neue Spannung am Adapter: Ampel und Achse für diese Spannung
            self._teil_gezeigt = teil
            self._teil_ab = len(ab.punkte)
            self._nenn_v = teil.einstellung.nenn_v
            self._grenzen_zeigen(teil.einstellung)
        if ab and ab.laeuft and isinstance(teil, nt.NetzteilAblauf):
            rest = teil.restzeit(m.zeit)
            if rest:
                vorn = self.schritt.text().split(" · noch")[0]
                gesamt = "gesamt noch"
                if isinstance(ab, nt.TriggerAblauf):
                    # die weiteren Spannungen kommen danach - sonst sieht es aus, als käme nur diese
                    weiter = [v for v, _ in ab.stufen[ab.i + 1:]]
                    rest = (rest[0], rest[1] + sum(sum(x.dauer_s for x in nt.plan(ab.einstellung_fuer(v, a)))
                                                   for v, a in ab.stufen[ab.i + 1:]))
                    gesamt = (f"Spannung {ab.i + 1} von {len(ab.stufen)}"
                              + (", danach " + ", ".join(f"{_kurz(v)} V" for v in weiter) if weiter else "")
                              + " · alle zusammen noch etwa")
                self.schritt.setText(f"{vorn} · noch {dauer_text(rest[0])[2:]} · {gesamt} "
                                     f"{dauer_text(rest[1])}")
        if ab:
            punkte = list(ab.punkte)
            if punkte:
                self._kurven(punkte)
                if self._geplant_s and punkte[-1][0] > self._geplant_s:
                    self.bild.enableAutoRange(x=True)   # länger als geplant: mitwachsen
            self._marken_zeichnen(list(ab.ergebnis.marken))

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
        if getattr(self, "_kabel_messung", False):
            self._kabel_messung = False
            self._kabel_fertig(ab)
            return
        if ab.ergebnis.dauer_s >= 5:
            self.f.speicher.netzteil_speichern(ab.einstellung, ab.ergebnis, ab.punkte, ab.start_wann)
            self.verlauf_laden()
        self._zeigen(ab.einstellung.__dict__, ab.ergebnis.als_dict(), ab.start_wann)
        self.ergebnis.show()
        self.ergebnis_rahmen.show()
        self.f._zustand_zeigen()
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
        QApplication.alert(self.f)
        if ab.ergebnis.dauer_s >= 5 and ab.zustand == "fertig":
            self.ergebnis_fenster()            # das ganze Ergebnis gleich groß zeigen

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
            if r.get("urteil") in URTEILE:
                wort, farbe = URTEILE[r["urteil"]]
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
                if haelt is None and r.get("urteil") not in URTEILE:
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
        self._zeigen(d["einstellung"], d["ergebnis"], d["wann"])
        self.ergebnis.show()
        self.ergebnis_rahmen.show()
        k = d["kurve"]
        self._nenn_v = None if d["einstellung"].get("trigger") else d["einstellung"]["nenn_v"]
        self._kurven(k)
        self.bild.enableAutoRange(x=True)
        self._marken_zeichnen([], neu=True)
        self._marken_zeichnen(d["ergebnis"].get("marken") or [])
        e = d["einstellung"]
        self._grenzen_zeigen(None if e.get("trigger") else einstellung_aus(e))
        self._kurven(k)                     # Achse mit der Toleranzlinie neu setzen
        self.bild.enableAutoRange(x=True)

    def _zeigen(self, e: dict, r: dict, wann: float | None = None) -> None:
        self._angezeigt = (dict(e), dict(r))
        self._angezeigt_wann = wann
        self.ergebnis.setText(ergebnis_html(e, r))
        self.knopf_pdf.setEnabled(True)
        self.knopf_gross.setEnabled(True)
        # Gemessen wird immer der ganze Weg - auch mit eingetragenem Kabelwert
        self.knopf_kabel.setEnabled(bool(r.get("widerstand_mohm")) and not e.get("trigger"))

    def _kabel_uebernehmen(self) -> None:
        e, r = getattr(self, "_angezeigt", ({}, {}))
        if r.get("widerstand_mohm"):
            self._kabel_setzen(r["widerstand_mohm"])
            self.f.b.ereignis.emit("info", f"Kabelwert {r['widerstand_mohm']:.0f} mΩ übernommen – gilt ab der "
                                           "nächsten Prüfung")

    def _bericht_dokument(self, e: dict, r: dict):
        """Derselbe Inhalt fürs Fenster und fürs PDF."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.addResource(QTextDocument.ImageResource, QUrl("kurve.png"), self._hell_abfotografieren())
        doc.setHtml(self._bericht_html(e, r))
        return doc

    def _bericht_html(self, e: dict, r: dict) -> str:
        breite = 640
        name = html.escape(e.get("name") or "Netzteil")
        if e.get("trigger"):
            angabe = "Schnellladegerät (über Trigger-Adapter)"
        elif e.get("unbekannt"):
            angabe = f"{_kurz(e['nenn_v'])} V, Leistung nicht angegeben"
        else:
            strom = e["nenn_a"] or (e["nenn_w"] / e["nenn_v"] if e["nenn_v"] else 0)
            angabe = f"{_kurz(e['nenn_v'])} V / {_kurz(round(strom, 2))} A ({_kurz(round(e['nenn_v'] * strom, 1))} W)"
        wann = datetime.fromtimestamp(self._angezeigt_wann) if getattr(self, "_angezeigt_wann", None) \
            else datetime.now()
        return (
            f"<h2>Prüfbericht: {name}</h2>"
            f"<p style='color:gray'>Angabe auf dem Gerät: {angabe} · geprüft am {wann:%d.%m.%Y um %H:%M} Uhr</p>"
            f"<h3>Kurz gesagt</h3>{kurz_html(e, r)}"
            f"<h3>Was wurde geprüft?</h3><p>{geprueft_text(e, r)}</p>"
            f"<h3>Messaufbau</h3>{messaufbau_html(e, r)}"
            f"<p><img src='kurve.png' width='{breite}'></p>"
            "<p style='color:gray'>Oben: Spannung mit Farbbereichen – <span style='color:#2e9e4f'>grün</span> = "
            "in Ordnung, <span style='color:#c77700'>gelb</span> = außerhalb der Vorgabe, aber nutzbar, "
            "<span style='color:#d03b3b'>rot</span> = zu niedrig bzw. zu hoch. Mitte: Strom und Leistung. "
            "Unten: Temperatur, wenn ein Fühler angebracht war.</p>"
            f"<h3>Messwerte für Fachleute</h3>{ergebnis_html(e, r, fach=True)}"
            "<p style='color:gray'><b>Schwankung</b> = Unterschied zwischen höchstem und tiefstem Wert innerhalb "
            "einer Stufe. Grün bis 1 %, gelb bis 3 %, rot darüber – das ist eine Einschätzung dieser Software, keine "
            "Vorgabe der USB-Spezifikation. Der DL24 misst etwa zweimal pro Sekunde: Er erfasst langsame "
            "Schwankungen, nicht das schnelle Brummen (Ripple) eines Netzteils – dafür braucht es ein "
            "Oszilloskop.</p>")

    def ergebnis_fenster(self) -> None:
        """Das ganze Ergebnis in einem eigenen Fenster - unten im Reiter ist dafür zu wenig Platz."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser
        e, r = getattr(self, "_angezeigt", (None, None))
        if not e:
            return
        dlg = QDialog(self)
        dlg.setWindowFlag(Qt.Window)
        dlg.setWindowTitle(f"Prüfergebnis: {e.get('name') or 'Netzteil'}")
        dlg.resize(900, 1000)
        lay = QVBoxLayout(dlg)
        anzeige = QTextBrowser()
        anzeige.setDocument(self._bericht_dokument(e, r))
        anzeige.document().setParent(anzeige)
        lay.addWidget(anzeige)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Close)
        pdf = knoepfe.addButton("Bericht speichern (PDF) …", QDialogButtonBox.ActionRole)
        pdf.clicked.connect(lambda: self.bericht_speichern())
        knoepfe.rejected.connect(dlg.close)
        lay.addWidget(knoepfe)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        self._fenster = dlg
        dlg.show()

    def bericht_speichern(self, pfad: str | None = None) -> str | None:
        """Ergebnis als PDF: Urteil, Werte, Kennlinie und das Diagramm."""
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
        from PySide6.QtWidgets import QFileDialog
        e, r = getattr(self, "_angezeigt", (None, None))
        if not e:
            return None
        if not pfad:
            name = "".join(c if c.isalnum() or c in " -_" else "_" for c in e.get("name") or "Netzteil").strip()
            pfad, _ = QFileDialog.getSaveFileName(self, "Bericht speichern",
                                                  f"Prüfbericht {name} {datetime.now():%Y-%m-%d}.pdf", "PDF (*.pdf)")
            if not pfad:
                return None
        doc = self._bericht_dokument(e, r)
        w = QPdfWriter(pfad)
        w.setPageSize(QPageSize(QPageSize.A4))
        w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
        w.setResolution(110)
        doc.setPageSize(w.pageLayout().paintRectPixels(w.resolution()).size().toSizeF())
        doc.print_(w)
        log.info("Bericht gespeichert: %s", pfad)
        return pfad

    def _hell_abfotografieren(self):
        """Das Diagramm fürs PDF immer hell - dunkel lässt es sich schlecht drucken."""
        vorne = pg.getConfigOption("foreground")
        achsen = [b.getAxis(a) for b in (self.bild, self.bild_i, self.bild_t)
                  for a in ("left", "bottom", "right")]
        self.flaeche.setBackground("w")
        for a in achsen:
            a.setPen("k")
            a.setTextPen("k")
        try:
            return self.flaeche.grab().toImage()
        finally:
            self.flaeche.setBackground(None)
            for a in achsen:
                a.setPen(vorne)
                a.setTextPen(vorne)

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
