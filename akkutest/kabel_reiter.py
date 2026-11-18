"""Reiter „Kabel“: wie gut ist ein USB-Kabel wirklich?

Der DL24 misst nur an seinen eigenen Klemmen. Deshalb in zwei Schritten:
  1. Referenz: das Netzteil über einen kurzen Adapter direkt am DL24 - sein eigener
     Widerstand.
  2. Dasselbe Netzteil mit dem Kabel dazwischen - Netzteil + Kabel.
Die Differenz ist das Kabel. Danach auf Wunsch ein Dauertest beim Nennstrom mit dem
Temperaturfühler am Stecker.

Grenzen für den Widerstand: USB Type-C Cable and Connector Specification §4.4.1 bzw.
USB 2.0 §7.2.2 (siehe netzteil.KABEL_TYPEN). Erwärmung: USB Type-C Compliance Document,
Prüfung B-6-1 (EIA-364-70): beim Nennstrom höchstens 30 °C über der Raumtemperatur, gemessen
außen am Steckergehäuse über den VBUS-/GND-Kontakten, gewartet bis die Temperatur stabil ist.
"""
from __future__ import annotations

import dataclasses
import html
import json
import logging
import time
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from . import netzteil as nt
from .fenster import Anzeige, gedaempft, zahl
from .geraet import Messwert
from .speicher import datenordner

log = logging.getLogger("akkutest.kabel")

AMPEL = {"gruen": "#2e9e4f", "gelb": "#c77700", "rot": "#d03b3b"}
ERWAERMUNG_MAX_K = 30.0      # USB Type-C Compliance Document B-6-1
# Hinweise im Schritt-Feld: normal - und auffällig, wenn etwas von Hand zu tun ist
NORMAL = "font-weight: bold;"
AUFFAELLIG = ("font-weight: bold; font-size: 15px; background:#fff1d6; color:#7a4b00; padding:10px; "
              "border: 2px solid #e0a000; border-radius:6px;")
REF_GUT_MOHM = 80.0          # Netzteil + Referenzkabel sollten darunter liegen, sonst taugt die Referenz kaum


def auswerten(ref_mohm: float | None, gesamt_mohm: float, typ: str, temp_start: float | None = None,
              temp_max: float | None = None, nenn_a: float | None = None) -> dict:
    """Aus Referenz und Messung mit Kabel: Widerstand, Verluste, Bewertung."""
    kabel = max(0.0, gesamt_mohm - (ref_mohm or 0.0))
    name, grenze, typ_a, budget_v = nt.KABEL_TYPEN.get(typ, ("unbekannt", 0.0, nenn_a or 3.0, 0.75))
    nenn = nenn_a or typ_a
    r = kabel / 1000
    tabelle = [(a, a * r, a * a * r) for a in (1.0, 2.0, 3.0, 4.0, 5.0) if a <= max(nenn, 3.0) + 1e-9]
    bewertung = nt.kabel_bewerten(kabel, typ) if typ in nt.KABEL_TYPEN else None
    return {
        "kabel_mohm": round(kabel, 0), "ref_mohm": ref_mohm, "gesamt_mohm": gesamt_mohm, "typ": typ,
        "typ_name": name, "grenze_mohm": grenze, "nenn_a": nenn,
        "bis_a": round(budget_v / r, 2) if r > 0 else None,      # Strom, bei dem der Abfall das Budget erreicht
        "tabelle": tabelle, "ampel": bewertung[0] if bewertung else None,
        "satz": bewertung[1] if bewertung else "Für eine Bewertung den Kabeltyp wählen.",
        "temp_start": temp_start, "temp_max": temp_max, "ohne_referenz": ref_mohm is None,
        "erwaermung_k": (round(temp_max - temp_start, 1) if temp_max is not None and temp_start is not None
                         else None),
    }


def bedingungen(punkte: list) -> dict:
    """Womit geprüft wurde: höchste Leistung, höchster Strom, Spannung dabei, Dauer."""
    last = [p for p in punkte if len(p) > 2 and p[2] > 0.01]
    if not last:
        return {}
    hoch = max(last, key=lambda p: p[1] * p[2])
    return {"max_w": round(hoch[1] * hoch[2], 1), "max_a": round(max(p[2] for p in last), 2),
            "bei_v": round(hoch[1], 2), "dauer_s": round(punkte[-1][0] - punkte[0][0], 0)}


def kritisch(d: dict) -> tuple[float, str] | None:
    """Ab welchem Strom das Kabel kritisch wird - die kleinere der beiden Grenzen:
    Wärme (Erwärmung wächst mit I², hochgerechnet auf +30 K) oder Spannungsabfall (750 mV)."""
    kandidaten = []
    k, strom = d.get("erwaermung_k"), d.get("pruef_a")
    if k is not None and strom and k > 0.5 and not abgebrochen(d):
        kandidaten.append((strom * (ERWAERMUNG_MAX_K / k) ** 0.5,
                           "durch Wärme (+30 K)" if d.get("stabil", True) else
                           "durch Wärme (+30 K) – vorläufig: die Temperatur war noch nicht stabil, für einen "
                           "verlässlichen Wert den Dauertest laufen lassen"))
    if d.get("bis_a"):
        kandidaten.append((d["bis_a"], "durch Spannungsabfall (750 mV)"))
    return min(kandidaten) if kandidaten else None


def _min(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d} min"


# Was auf Kabeln steht: Watt -> (Strom, höchste Spannung, Kabeltyp)
ANGABEN = {60: (3.0, 20.0, "usbc3"), 100: (5.0, 20.0, "usbc5"), 140: (5.0, 28.0, "usbc5"),
           240: (5.0, 48.0, "usbc5")}


def zu_warm(d: dict) -> bool:
    """Erwärmung über der Grenze der Norm."""
    k = d.get("erwaermung_k")
    return k is not None and k > ERWAERMUNG_MAX_K


KNAPP_ANTEIL = 0.8           # nicht stabil und schon über 80 % der Grenze: kein „bestanden“


def knapp(d: dict) -> bool:
    """Temperatur stieg noch und lag schon nahe an der Grenze - bestanden wäre zu optimistisch."""
    k = d.get("erwaermung_k")
    return (k is not None and not zu_warm(d) and not d.get("stabil", True)
            and k >= ERWAERMUNG_MAX_K * KNAPP_ANTEIL and not abgebrochen(d))


def abgebrochen(d: dict) -> bool:
    """An der eingestellten Fühler-Grenze abgebrochen, bevor die Norm-Grenze erreicht war."""
    return bool(d.get("zu_heiss")) and not zu_warm(d)


def angabe_pruefen(d: dict) -> tuple[str, list[tuple[str, str, str]]] | None:
    """Hält das Kabel die Angabe? (Gesamt, [(Zeichen, Punkt, Begründung)]) - Zeichen ✔ ✘ ?"""
    w = d.get("angabe_w")
    if not w or w not in ANGABEN:
        return None
    a, v, typ = ANGABEN[w]
    grenze = nt.KABEL_TYPEN[typ][1]
    r = d["kabel_mohm"]
    punkte = []
    punkte.append(("✔" if r <= grenze else "✘", "Widerstand",
                   f"{zahl(r, 0)} mΩ – erlaubt höchstens {zahl(grenze, 0)} mΩ für {zahl(a, 0)} A "
                   "(USB Type-C §4.4.1)" + ("" if r <= grenze else f", also {zahl(r - grenze, 0)} mΩ zu viel")))
    abfall = a * r / 1000
    punkte.append(("✔" if abfall <= 0.75 else "✘", f"Spannungsabfall bei {zahl(a, 0)} A",
                   f"{zahl(abfall, 2)} V – erlaubt höchstens 0,75 V (500 mV VBUS + 250 mV GND)"))
    k, strom = d.get("erwaermung_k"), d.get("pruef_a") or 0
    if k is None:
        punkte.append(("?", f"Erwärmung bei {zahl(a, 0)} A", "nicht gemessen – ohne Temperaturfühler"))
    elif abgebrochen(d):
        punkte.append(("✘", f"Eigene Grenze {zahl(d.get('temp_grenze'), 0)} °C",
                       f"erreicht bei {zahl(strom, 1)} A – das Kabel wurde zu heiß (+{zahl(k, 1)} K bis dahin)"))
        punkte.append(("?", f"Erwärmung bei {zahl(a, 0)} A (Norm +30 K)",
                       "nicht zu Ende gemessen – vorher an deiner Grenze abgebrochen"))
    elif strom < a - 1e-6:
        hoch = k * (a / strom) ** 2 if strom else None
        punkte.append(("?", f"Erwärmung bei {zahl(a, 0)} A",
                       f"nur mit {zahl(strom, 1)} A geprüft (+{zahl(k, 1)} K) – bei {zahl(a, 0)} A wären es "
                       f"hochgerechnet etwa +{zahl(hoch, 0)} K" + (" – das wäre über +30 K" if hoch and hoch > 30
                                                                  else "") +
                       f". Für den Nachweis mit {zahl(a, 0)} A prüfen."))
    elif knapp(d):
        punkte.append(("?", f"Erwärmung bei {zahl(a, 0)} A",
                       f"+{zahl(k, 1)} K und noch steigend – knapp unter +30 K, wird sie wahrscheinlich überschreiten"))
    else:
        ok = k <= ERWAERMUNG_MAX_K
        punkte.append(("✔" if ok else "✘", f"Erwärmung bei {zahl(a, 0)} A",
                       f"+{zahl(k, 1)} K – erlaubt höchstens +30 K (Prüfung B-6-1)"
                       + ("" if d.get("stabil", True) else " – Temperatur war noch nicht stabil")))
    gepr_v = max([x[0] for x in d.get("je_spannung") or []] or [5.0])
    punkte.append(("✔" if gepr_v >= v - 0.5 else "?", f"Spannung bis {zahl(v, 0)} V",
                   f"geprüft bis {zahl(gepr_v, 0)} V" + ("" if gepr_v >= v - 0.5 else
                                                      f" – die Angabe von {zahl(v, 0)} V ist damit nicht nachgewiesen. "
                                                      "Die Isolation für hohe Spannung misst der DL24 nicht.")))
    if a > 3:
        punkte.append(("?", "E-Marker (für mehr als 3 A nötig)",
                       "kann der DL24 nicht auslesen – ohne E-Marker liefert ein Netzteil höchstens 3 A"))
    if any(p[0] == "✘" for p in punkte):
        gesamt = "nicht"
    elif any(p[0] == "?" and not p[1].startswith("E-Marker") for p in punkte):
        gesamt = "offen"
    else:
        gesamt = "ja"
    return gesamt, punkte


def angabe_html(d: dict) -> str:
    erg = angabe_pruefen(d)
    if not erg:
        return ""
    gesamt, punkte = erg
    w = d["angabe_w"]
    a, v, _ = ANGABEN[w]
    gruende = [f"{p[1]}: {p[2]}" for p in punkte if p[0] == "✘"]
    offen = [p[1] for p in punkte if p[0] == "?" and not p[1].startswith("E-Marker")]
    kopf = {"ja": ("#2e9e4f", "✔ Erfüllt die Angabe"),
            "nicht": ("#d03b3b", "✘ Erfüllt die Angabe nicht"),
            "offen": ("#c77700", "? Nicht vollständig geprüft")}[gesamt]
    z = [f"<h3>Hält das Kabel, was angegeben ist? ({w} W = {zahl(a, 0)} A bei bis zu {zahl(v, 0)} V)</h3>",
         f"<p style='font-size:16px; color:{kopf[0]}'><b>{kopf[1]}</b></p>"]
    if gruende:
        z.append("<p><b>Warum nicht:</b><br>" + "<br>".join("• " + html.escape(g) for g in gruende) + "</p>")
    elif offen:
        z.append("<p><b>Was noch fehlt:</b> " + html.escape(", ".join(offen)) + "</p>")
    farbe = {"✔": "#2e9e4f", "✘": "#d03b3b", "?": "#c77700"}
    z.append("<table cellspacing=5>" + "".join(
        f"<tr><td style='color:{farbe[p[0]]}'><b>{p[0]}</b></td><td>{html.escape(p[1])}</td>"
        f"<td>{html.escape(p[2])}</td></tr>" for p in punkte) + "</table>")
    return "".join(z)


def bericht_html(d: dict) -> str:
    z = [f"<h2>Kabel: {html.escape(d.get('name') or 'ohne Namen')}</h2>",
         f"<p style='color:gray'>geprüft am {datetime.fromtimestamp(d.get('wann', time.time())):%d.%m.%Y um %H:%M} "
         f"Uhr · Typ: {html.escape(d.get('typ_name', ''))}"
         + (f" · Angabe: {d['angabe_w']} W" if d.get("angabe_w") else "") + "</p>"]
    z.append(angabe_html(d))
    if abgebrochen(d):
        z.append(f"<p style='font-size:17px; color:{AMPEL['rot']}'><b>Nicht in Ordnung: zu heiß – deine Grenze von "
                 f"{zahl(d.get('temp_grenze'), 0)} °C erreicht"
                 + (f" (nach {_min(d['bedingungen']['dauer_s'])})" if d.get("bedingungen") else "")
                 + (f" – der Widerstand selbst ist in Ordnung ({zahl(d['kabel_mohm'], 0)} mΩ)"
                    if d.get("ampel") == "gruen" else "") + "</b></p>")
    elif knapp(d):
        z.append(f"<p style='font-size:17px; color:{AMPEL['gelb']}'><b>Knapp: +{zahl(d['erwaermung_k'], 1)} K "
                 f"(am Stecker {zahl(d['temp_max'], 1)} °C, erlaubt bis {zahl(d['temp_start'] + ERWAERMUNG_MAX_K, 1)} °C)"
                 " und die Temperatur stieg noch – das Kabel überschreitet die +30 K wahrscheinlich. Widerstand "
                 f"{zahl(d['kabel_mohm'], 0)} mΩ.</b></p>")
    elif zu_warm(d):
        # die Wärme entscheidet - ein guter Widerstand allein macht das Kabel nicht in Ordnung
        z.append(f"<p style='font-size:17px; color:{AMPEL['rot']}'><b>Nicht in Ordnung: zu warm "
                 f"(+{zahl(d['erwaermung_k'], 1)} K, erlaubt +{zahl(ERWAERMUNG_MAX_K, 0)} K) – der Widerstand selbst "
                 f"ist in Ordnung ({zahl(d['kabel_mohm'], 0)} mΩ)</b></p>" if d.get("ampel") == "gruen" else
                 f"<p style='font-size:17px; color:{AMPEL['rot']}'><b>Nicht in Ordnung: zu warm "
                 f"(+{zahl(d['erwaermung_k'], 1)} K) und {html.escape(d['satz'])}</b></p>")
    elif d.get("ampel"):
        z.append(f"<p style='font-size:17px; color:{AMPEL[d['ampel']]}'><b>{html.escape(d['satz'])}</b></p>")
    else:
        z.append(f"<p>{html.escape(d['satz'])}</p>")
    tab = [("Widerstand Kabel", f"<b>{zahl(d['kabel_mohm'], 0)} mΩ</b> (Hin- und Rückleitung, Stecker eingerechnet)")]
    b = d.get("bedingungen") or {}
    if b:
        from .fenster import dauer_text
        tab.append(("Geprüft mit", f"höchstens <b>{zahl(b['max_w'], 1)} W</b> ({zahl(b['max_a'], 2)} A bei "
                                   f"{zahl(b['bei_v'], 2)} V) · Dauer <b>{dauer_text(b['dauer_s'])}</b>"))
    if d.get("ohne_referenz"):
        tab.append(("", "<span style='color:#c77700'>ohne Referenzmessung – der Wert enthält auch den Widerstand "
                        "des Netzteils und ist daher etwas zu hoch</span>"))
    else:
        if d.get("ref_name"):
            tab.append(("Gemessen", f"{zahl(d['gesamt_mohm'], 0)} mΩ mit Kabel − {zahl(d['ref_mohm'], 0)} mΩ Referenz "
                                    f"(Netzteil + Referenzkabel „{html.escape(d['ref_name'])}“)<br><span "
                                    "style='color:gray'>Das Referenzkabel steckt in der Referenz mit drin – deshalb ist "
                                    "das Ergebnis um seinen Widerstand zu klein (bei einem kurzen, guten Kabel etwa "
                                    "20–40 mΩ).</span>"))
        else:
            tab.append(("Gemessen", f"{zahl(d['gesamt_mohm'], 0)} mΩ mit Kabel − {zahl(d['ref_mohm'], 0)} mΩ ohne "
                                    "Kabel (Referenz)"))
        if (d.get("ref_mohm") or 0) > REF_GUT_MOHM:
            tab.append(("", f"<span style='color:#c77700'>Die Referenz ist mit {zahl(d['ref_mohm'], 0)} mΩ recht hoch. "
                            "Meist liegt das am Netzteil (z. B. einem Step-Down-Modul) – das wird abgezogen und "
                            "verfälscht das Ergebnis nicht. Nur wenn das Referenzkabel selbst schlecht ist, fällt das "
                            f"Ergebnis zu gut aus: Das geprüfte Kabel hätte dann mehr als "
                            f"{zahl(d['kabel_mohm'], 0)} mΩ.</span>"))
    if d.get("grenze_mohm"):
        tab.append(("Erlaubt", f"höchstens {zahl(d['grenze_mohm'], 0)} mΩ für {html.escape(d['typ_name'])} "
                               "(USB Type-C §4.4.1 bzw. USB 2.0 §7.2.2)"))
    if d.get("bis_a") and zu_warm(d) and kritisch(d):
        tab.append(("Taugt bis", f"etwa {zahl(kritisch(d)[0], 1)} A – darüber wird es zu warm "
                                 "(siehe „Kritisch ab“)"))
    elif d.get("bis_a"):
        if d["bis_a"] >= d["nenn_a"]:
            tab.append(("Taugt bis", f"{zahl(d['nenn_a'], 0)} A – mehr ist für {html.escape(d['typ_name'])} nicht "
                                     f"vorgesehen (vom Widerstand her ginge es bis {zahl(min(d['bis_a'], 99), 1)} A)"))
        else:
            tab.append(("Taugt bis", f"{zahl(d['bis_a'], 1)} A – darüber fällt am Kabel mehr Spannung ab, als die "
                                     "USB-Vorgabe zulässt"))
    if d.get("temp_max") is not None:
        t = f"höchstens {zahl(d['temp_max'], 1)} °C"
        if d.get("temp_start") is not None:
            t += f" (Start {zahl(d['temp_start'], 1)} °C, +{zahl(d['temp_max'] - d['temp_start'], 1)} K)"
        tab.append(("Temperatur am Stecker", t))
        k = d.get("erwaermung_k")
        if k is not None and abgebrochen(d):
            soll = (d["temp_start"] + ERWAERMUNG_MAX_K) if d.get("temp_start") is not None else None
            tab.append(("Eigene Grenze", f"<b style='color:{AMPEL['rot']}'>✘ {zahl(d.get('temp_grenze'), 0)} °C erreicht"
                                         f"</b> – zu heiß nach deiner Vorgabe (+{zahl(k, 1)} K über dem Start)"))
            tab.append(("Erwärmung (Norm)", f"<b style='color:{AMPEL['gelb']}'>? nicht zu Ende gemessen</b> – vorher an "
                                            "deiner Grenze abgebrochen."
                                            + (f" Nach Norm wäre erst über {zahl(soll, 0)} °C (Start + 30 K) zu "
                                               "warm." if soll else "")))
        elif k is not None and knapp(d):
            tab.append(("Erwärmung", f"<b style='color:{AMPEL['gelb']}'>? knapp</b>: +{zahl(k, 1)} K, erlaubt +30 K "
                                     f"(am Stecker {zahl(d['temp_max'], 1)} °C, erlaubt bis "
                                     f"{zahl(d['temp_start'] + ERWAERMUNG_MAX_K, 1)} °C) "
                                     "– die Temperatur stieg beim Ende noch. Sie wird die Grenze wahrscheinlich "
                                     "überschreiten. Für eine klare Aussage den Dauertest bis „stabil“ laufen lassen."))
        elif k is not None:
            ok = k <= ERWAERMUNG_MAX_K
            strom = d.get("pruef_a")
            voll = strom is None or strom >= d.get("nenn_a", 0) - 1e-6
            text = (f"<b style='color:{AMPEL['gruen' if ok else 'rot']}'>{'✔ bestanden' if ok else '✘ nicht bestanden'}"
                    f"</b>: +{zahl(k, 1)} K über der Raumtemperatur, erlaubt höchstens +{zahl(ERWAERMUNG_MAX_K, 0)} K "
                    f"– am Stecker {zahl(d['temp_max'], 1)} °C, erlaubt bis "
                    f"{zahl(d['temp_start'] + ERWAERMUNG_MAX_K, 1)} °C (USB Type-C Compliance Document, "
                    "Prüfung B-6-1 / EIA-364-70)")
            if not voll:
                text += (f"<br><span style='color:#c77700'>Geprüft mit {zahl(strom, 1)} A – die Norm prüft beim "
                         f"Nennstrom ({zahl(d['nenn_a'], 0)} A). Das Ergebnis gilt nur für {zahl(strom, 1)} A.</span>")
            if not d.get("stabil"):
                text += ("<br><span style='color:gray'>Die Temperatur war beim Ende noch nicht stabil – "
                         "mit längerem Dauertest wird sie noch etwas höher.</span>")
            tab.append(("Erwärmung", text))
    krit = kritisch(d)
    if krit:
        a, grund = krit
        ueber = a < d.get("nenn_a", 0)
        tab.append(("Kritisch ab", f"<b style='color:{AMPEL['rot' if ueber else 'gruen']}'>etwa {zahl(min(a, 99), 1)} A"
                                   f"</b> {grund}" + (f" – <b>unter dem Nennstrom von {zahl(d['nenn_a'], 0)} A</b>"
                                                      if ueber else "")
                                   + "<br><span style='color:gray'>Schätzung aus der Messung: Die Erwärmung wächst "
                                     "mit dem Quadrat des Stroms. Warmes Kupfer leitet etwas schlechter – der echte "
                                     "Wert liegt eher etwas darunter. Am genauesten nahe am Nennstrom geprüft."
                                     "</span>"))
    z.append("<table cellspacing=4>" + "".join(f"<tr><td style='color:gray'>{a}</td><td>{b}</td></tr>"
                                                 for a, b in tab) + "</table>")
    if d.get("je_spannung"):
        z.append("<p><b>Je Spannung</b> (über den Trigger-Adapter)</p><table cellspacing=6><tr>"
                 "<td style='color:gray'>Spannung</td><td style='color:gray'>ohne Kabel</td>"
                 "<td style='color:gray'>mit Kabel</td><td style='color:gray'>Kabel</td>"
                 "<td style='color:gray'>bis</td><td style='color:gray'>Leistung</td>"
                 "<td style='color:gray'>Dauer</td><td style='color:gray'>Stecker max.</td></tr>" + "".join(
                     f"<tr><td><b>{zahl(x[0], 0)} V</b></td><td>{zahl(x[1], 0) if x[1] is not None else '–'} mΩ</td>"
                     f"<td>{zahl(x[2], 0)} mΩ</td><td><b>{zahl(x[3], 0)} mΩ</b></td><td>{zahl(x[4], 2)} A</td>"
                     f"<td>{zahl(x[6], 1) + ' W' if len(x) > 6 and x[6] else '–'}</td>"
                     f"<td>{_min(x[7]) if len(x) > 7 and x[7] else '–'}</td>"
                     f"<td>{zahl(x[5], 1, '°C') if len(x) > 5 and x[5] is not None else '–'}</td></tr>"
                     for x in d["je_spannung"]) + "</table>")
        if d.get("fehlt"):
            z.append(f"<p style='color:#c77700'>Nicht geprüft: {html.escape(', '.join(d['fehlt']))}</p>")
    z.append("<p><b>Was das Kabel kostet</b></p><table cellspacing=6><tr><td style='color:gray'>Strom</td>"
             "<td style='color:gray'>Spannungsabfall</td><td style='color:gray'>Verlust</td>"
             "<td style='color:gray'>bei 5 V</td></tr>" + "".join(
                 f"<tr><td>{zahl(a, 0)} A</td><td>{zahl(v, 2)} V</td><td>{zahl(w, 2)} W</td>"
                 f"<td>kommen {zahl(5 - v, 2)} V an</td></tr>" for a, v, w in d["tabelle"]) + "</table>")
    z.append("<p style='color:gray'>Der DL24 kann nicht auslesen, ob ein Kabel einen E-Marker hat (5 A) oder "
             "welche Datenleitungen es hat – geprüft wird nur, wie gut es Strom leitet.</p>")
    return "".join(z)


def diagramm_bild(d: dict, breite: int = 900, hoehe: int = 520):
    """Diagramm für den Bericht: eigens gezeichnet, hell, feste Größe - Spannung, Strom,
    und Temperatur am Stecker, wenn gemessen. Nicht vom Bildschirm abfotografiert."""
    k = d.get("kurve") or []
    x = [p[0] / 60 for p in k]
    w = pg.GraphicsLayoutWidget()
    w.setBackground("w")
    w.resize(breite, hoehe)
    stift = pg.mkPen("k")
    streifen = []
    b_u = w.addPlot(row=0, col=0)
    b_u.setLabel("left", "Spannung (V)")
    b_u.plot(x, [p[1] for p in k], pen=pg.mkPen("#2f80ed", width=2))
    streifen.append(b_u)
    b_i = w.addPlot(row=1, col=0)
    b_i.setLabel("left", "Strom (A)")
    b_i.plot(x, [p[2] for p in k], pen=pg.mkPen("#2e9e4f", width=2))
    b_i.setXLink(b_u)
    streifen.append(b_i)
    temp = [(a, p[3]) for a, p in zip(x, k) if len(p) > 3 and p[3] is not None]
    if temp:
        b_t = w.addPlot(row=2, col=0)
        b_t.setLabel("left", "Stecker (°C)")
        b_t.plot([a for a, _ in temp], [c for _, c in temp], pen=pg.mkPen("#d03b3b", width=2))
        if d.get("temp_start") is not None:
            grenze = pg.InfiniteLine(pos=d["temp_start"] + ERWAERMUNG_MAX_K, angle=0,
                                     pen=pg.mkPen("#d03b3b", width=1, style=Qt.DashLine),
                                     label="Grenze +30 K", labelOpts={"color": "#d03b3b", "position": 0.95})
            b_t.addItem(grenze)
        b_t.setXLink(b_u)
        streifen.append(b_t)
    w.ci.layout.setRowStretchFactor(0, 3)
    for i, b in enumerate(streifen):
        b.showGrid(x=True, y=True, alpha=0.3)
        for achse in ("left", "bottom"):
            a = b.getAxis(achse)
            a.setPen(stift)
            a.setTextPen(stift)
            a.enableAutoSIPrefix(False)
        b.getAxis("left").setWidth(60)
        if i < len(streifen) - 1:
            b.hideAxis("bottom")
    streifen[-1].setLabel("bottom", "Zeit (min)")
    if x:
        b_u.setXRange(0, max(x), padding=0.01)
    w.show()                       # Qt rechnet das Layout erst beim Zeigen
    w.hide()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    bild = w.grab().toImage()
    w.deleteLater()
    return bild


class KabelReiter(QWidget):
    kennung = "kt"
    powerbank = False

    def __init__(self, fenster) -> None:
        super().__init__()
        self.f = fenster
        self.ablauf: nt.NetzteilAblauf | None = None
        self.phase = ""                  # "ref" | "kabel"
        self._ref: float | None = None
        self._steuer_ok = False
        self._letztes: dict | None = None
        self._bauen()
        self.liste_laden()

    # ------------------------------------------------------------------
    def _bauen(self) -> None:
        h = QHBoxLayout(self)
        links = QVBoxLayout()
        g = QGroupBox("Kabel")
        f = QFormLayout(g)
        self.name = QLineEdit()
        self.name.setPlaceholderText("z. B. Anker USB-C 1 m schwarz")
        f.addRow("Bezeichnung:", self.name)
        self.angabe = QComboBox()
        self.angabe.addItem("nicht angegeben", 0)
        for w, (a, v, _) in ANGABEN.items():
            self.angabe.addItem(f"{w} W ({a:g} A, bis {v:g} V)", w)
        self.angabe.setToolTip("Was auf dem Kabel oder der Verpackung steht. Der Bericht sagt dann, ob das Kabel "
                               "das hält – und wenn nicht, warum.")
        self.angabe.currentIndexChanged.connect(self._angabe_gewaehlt)
        f.addRow("Angabe auf dem Kabel:", self.angabe)
        self.typ = QComboBox()
        for k, (n, grenze, a, _) in nt.KABEL_TYPEN.items():
            self.typ.addItem(f"{n} – erlaubt {grenze:.0f} mΩ", k)
        self.typ.currentIndexChanged.connect(self._typ_gewaehlt)
        f.addRow("Typ:", self.typ)
        self.strom = QDoubleSpinBox()
        self.strom.setRange(0.5, 5.0)
        self.strom.setSingleStep(0.5)
        self.strom.setDecimals(1)
        self.strom.setSuffix(" A")
        self.strom.setToolTip("Bis zu diesem Strom wird gemessen. Das Netzteil muss ihn liefern können.")
        f.addRow("Prüfstrom bis:", self.strom)
        self.mit_ref = QCheckBox("Referenz ohne Kabel messen (empfohlen)")
        self.mit_ref.setChecked(True)
        self.mit_ref.setToolTip("Zuerst das Netzteil über einen kurzen Adapter direkt am DL24 - dann wird sein "
                                "eigener Widerstand vom Ergebnis abgezogen.")
        f.addRow(self.mit_ref)
        self.ref_name = QLineEdit()
        self.ref_name.setPlaceholderText("z. B. Anker USB-C 15 cm – leer lassen bei Adapter mit Stecker")
        self.ref_name.setToolTip("Das kürzeste, beste Kabel, das du hast. Damit wird die Referenz gemessen – das "
                                 "Ergebnis ist um seinen Widerstand zu klein. Immer dasselbe nehmen.")
        f.addRow("Referenzkabel:", self.ref_name)
        # Auswahl aus den gespeicherten Netzteilen - und frei zu tippen
        self.netzteil_wahl = QComboBox()
        self.netzteil_wahl.setEditable(True)
        self.netzteil_wahl.setInsertPolicy(QComboBox.NoInsert)
        self.netzteil = self.netzteil_wahl.lineEdit()
        self.netzteil.setPlaceholderText("z. B. TZT-Modul an 20-V-Netzteil")
        self.netzteil.setToolTip("Die Referenz misst Netzteil + Referenzkabel. Eine gespeicherte Referenz stimmt "
                                 "nur mit demselben Netzteil und Adapter.")
        f.addRow("Netzteil:", self.netzteil_wahl)
        zeile = QHBoxLayout()
        self.ref_wahl = QComboBox()
        self.ref_wahl.setToolTip("Gespeicherte Referenz: Schritt 1 entfällt – gleich das zu prüfende Kabel stecken.")
        zeile.addWidget(self.ref_wahl, 1)
        self.knopf_ref_weg = QPushButton("Löschen")
        self.knopf_ref_weg.setToolTip("Gewählte gespeicherte Referenz löschen")
        self.knopf_ref_weg.clicked.connect(self.referenz_loeschen)
        zeile.addWidget(self.knopf_ref_weg)
        f.addRow("Referenz:", zeile)
        self.ref_wahl.currentIndexChanged.connect(self._ref_gewaehlt)
        self.mit_ref.toggled.connect(lambda an: [w.setEnabled(an) for w in
                                                 (self.ref_name, self.netzteil_wahl, self.ref_wahl,
                                                  self.knopf_ref_weg)])
        self.alle_v = QCheckBox("Alle Spannungen über den Trigger-Adapter prüfen:")
        self.alle_v.setToolTip("Referenz und Kabel werden bei jeder gewählten Spannung gemessen – die App sagt, "
                               "wann am Trigger-Adapter umgeschaltet wird.")
        f.addRow(self.alle_v)
        zeile = QHBoxLayout()
        self.spannungen = []
        for v in nt.TRIGGER_SPANNUNGEN:
            haken = QCheckBox(f"{v:g} V")
            haken.setChecked(v <= 20)
            if v > 20.5:
                haken.setToolTip("28 V nur mit EPR: Netzteil, Trigger-Adapter und ein 5-A-/240-W-Kabel")
            zeile.addWidget(haken)
            self.spannungen.append((v, haken))
        zeile.addStretch(1)
        f.addRow(zeile)
        self.alle_v.toggled.connect(lambda an: [hk.setEnabled(an) for _, hk in self.spannungen])
        for _, hk in self.spannungen:
            hk.setEnabled(False)
        self.mit_dauer = QCheckBox("Dauertest bis stabil, mindestens Minuten:")
        self.mit_dauer.setToolTip("Erst bei Dauerlast wird ein Kabel warm. Endet, sobald die Temperatur stabil ist. "
                                  "Über den Trigger-Adapter nur einmal – bei der niedrigsten Spannung.")
        self.dauer_min = QSpinBox()
        self.dauer_min.setRange(1, 120)
        self.dauer_min.setValue(30)
        self.dauer_min.setToolTip("Geplante Dauer. Endet früher, sobald die Temperatur stabil ist (frühestens nach "
                                  "10 Minuten, weniger als 0,5 °C Änderung in 5 Minuten). Steigt sie danach noch, "
                                  "läuft der Test weiter bis stabil – höchstens 2 Stunden. So misst auch die Norm.")
        zeile = QHBoxLayout()
        zeile.addWidget(self.mit_dauer)
        zeile.addWidget(self.dauer_min)
        f.addRow(zeile)
        self.dauer_jede = QCheckBox("Dauertest bei jeder Spannung (sonst nur bei der niedrigsten)")
        self.dauer_jede.setToolTip("Über den Trigger-Adapter: an = bei jeder gewählten Spannung bis stabil. "
                                   "Aus = nur einmal bei der niedrigsten - die Wärme im Kabel hängt nur vom Strom ab.")
        f.addRow(self.dauer_jede)
        self.mit_fuehler = QCheckBox("Temperaturfühler am Stecker, zu heiß ab:")
        self.temp_grenze = QSpinBox()
        self.temp_grenze.setRange(30, 90)
        self.temp_grenze.setValue(50)
        self.temp_grenze.setSuffix(" °C")
        zeile = QHBoxLayout()
        zeile.addWidget(self.mit_fuehler)
        zeile.addWidget(self.temp_grenze)
        f.addRow(zeile)
        # Wärme am Stecker ist beim Kabel das Wichtigste - Fühler standardmäßig an, Einstellung gemerkt
        from PySide6.QtCore import QSettings
        self._einst = QSettings("dl24-akkutest", "dl24-akkutest")
        self.mit_fuehler.setChecked(str(self._einst.value("kt/fuehler", "true")).lower() == "true")
        self.temp_grenze.setValue(int(float(self._einst.value("kt/temp_grenze2", 60) or 60)))
        self.mit_fuehler.toggled.connect(lambda an: self._einst.setValue("kt/fuehler", an))
        # ohne Dauertest sieht man keinen Temperaturanstieg - standardmäßig an, gemerkt
        self.mit_dauer.setChecked(str(self._einst.value("kt/dauer", "true")).lower() == "true")
        self.mit_dauer.toggled.connect(lambda an: self._einst.setValue("kt/dauer", an))
        self.dauer_jede.setChecked(str(self._einst.value("kt/dauer_jede", "true")).lower() == "true")
        self.dauer_jede.toggled.connect(lambda an: self._einst.setValue("kt/dauer_jede", an))
        self.ref_name.setText(str(self._einst.value("kt/ref_name", "") or ""))
        self.ref_name.textChanged.connect(lambda s: self._einst.setValue("kt/ref_name", s))
        self.netzteile_laden()
        self.netzteil.setText(str(self._einst.value("kt/netzteil", "") or ""))
        self.netzteil.textChanged.connect(lambda s: self._einst.setValue("kt/netzteil", s))
        self.referenzen_laden()
        self.temp_grenze.valueChanged.connect(lambda w: self._einst.setValue("kt/temp_grenze2", w))
        hinweis = QLabel("<b>Ablauf:</b> 1. Netzteil <b>ohne</b> das Kabel am DL24 (Adapter mit USB-C-Stecker "
                         "oder kürzestes Kabel) – Referenz. 2. Das Kabel dazwischen stecken – Messung. Die "
                         "Differenz ist das Kabel.<br><br>So prüft auch die USB-Norm: beim <b>Nennstrom</b> des Kabels (5-A-Kabel mit 5 A), "
                         "Fühler außen auf das Steckergehäuse kleben, ruhige Luft, Dauertest bis die Temperatur "
                         "stabil ist. Erlaubt sind höchstens 30 °C über Raumtemperatur. Die Spannung spielt für die "
                         "Erwärmung keine Rolle – nur der Strom. Den Fühler vor dem Start nicht anfassen: die "
                         "Starttemperatur gilt als Raumtemperatur.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        f.addRow(hinweis)
        links.addWidget(g)
        knoepfe = QHBoxLayout()
        self.knopf_start = QPushButton("▶  Kabel prüfen")
        self.knopf_start.setStyleSheet("font-weight: bold; padding: 8px;")
        self.knopf_start.clicked.connect(self.starten)
        self.knopf_weiter = QPushButton("Kabel ist angesteckt – weiter")
        self.knopf_weiter.clicked.connect(self._kabel_phase)
        self.knopf_weiter.hide()
        self.knopf_abbruch = QPushButton("■  Abbrechen")
        self.knopf_abbruch.clicked.connect(lambda: self.abbrechen())
        knoepfe.addWidget(self.knopf_start, 2)
        knoepfe.addWidget(self.knopf_weiter, 2)
        knoepfe.addWidget(self.knopf_abbruch, 1)
        links.addLayout(knoepfe)
        self.schritt = QLabel()
        self.schritt.setWordWrap(True)
        self.schritt.setStyleSheet(NORMAL)
        links.addWidget(self.schritt)
        self.zeit = QLabel()                  # Prüfdauer: wie lange schon, wie lange noch
        self.zeit.setWordWrap(True)
        self.zeit.setStyleSheet(gedaempft())
        links.addWidget(self.zeit)
        links.addStretch(1)
        lw = QWidget()
        lw.setLayout(links)
        lw.setMaximumWidth(520)
        h.addWidget(lw)

        rechts = QVBoxLayout()
        raster = QHBoxLayout()
        self.anz = {}
        for k, t in (("u", "Spannung"), ("i", "Strom"), ("t", "Temperatur (Fühler)"), ("r", "Widerstand Kabel")):
            self.anz[k] = Anzeige(t)
            raster.addWidget(self.anz[k])
        rechts.addLayout(raster)
        self.bild = pg.PlotWidget()
        self.bild.setLabel("left", "Spannung (V)")
        self.bild.setLabel("bottom", "Zeit (min)")
        self.bild.showGrid(x=True, y=True, alpha=0.25)
        self.bild.setMouseEnabled(x=False, y=False)
        self.bild.setMenuEnabled(False)
        self.bild.hideButtons()
        self.linie = self.bild.plot([], [], pen=pg.mkPen("#2f80ed", width=2))
        self.bild_t = pg.PlotWidget()
        self.bild_t.setLabel("left", "Temperatur (°C)")
        self.bild_t.setMouseEnabled(x=False, y=False)
        self.bild_t.setMenuEnabled(False)
        self.bild_t.hideButtons()
        self.bild_t.setXLink(self.bild)
        self.bild_t.setMaximumHeight(160)
        self.bild_t.hide()                    # nur mit Fühler
        for b in (self.bild, self.bild_t):
            b.setBackground(None)
            self.f._ohne_vorsatz(b.getPlotItem())
            b.getAxis("left").setWidth(56)
        self.linie_t = self.bild_t.plot([], [], pen=pg.mkPen("#d03b3b", width=2))
        rechts.addWidget(self.bild, 3)
        rechts.addWidget(self.bild_t, 1)
        self.ergebnis = QLabel()
        self.ergebnis.setWordWrap(True)
        self.ergebnis.setTextFormat(Qt.RichText)
        self.ergebnis.setFrameShape(QFrame.StyledPanel)
        self.ergebnis.setMargin(10)
        self.ergebnis.hide()
        rechts.addWidget(self.ergebnis)
        zeile = QHBoxLayout()
        self.knopf_uebernehmen = QPushButton("Als Kabelwert übernehmen (Netzteile und Powerbanks)")
        self.knopf_uebernehmen.clicked.connect(self.uebernehmen)
        self.knopf_uebernehmen.setEnabled(False)
        self.knopf_pdf = QPushButton("Bericht speichern (PDF) …")
        self.knopf_pdf.clicked.connect(lambda: self.bericht_speichern())
        self.knopf_pdf.setEnabled(False)
        zeile.addWidget(self.knopf_uebernehmen)
        zeile.addStretch(1)
        zeile.addWidget(self.knopf_pdf)
        rechts.addLayout(zeile)
        kopf = QHBoxLayout()
        kopf.addWidget(QLabel("<b>Geprüfte Kabel</b>"))
        kopf.addStretch(1)
        self.knopf_loeschen = QPushButton("Löschen")
        self.knopf_loeschen.clicked.connect(self.loeschen)
        kopf.addWidget(self.knopf_loeschen)
        rechts.addLayout(kopf)
        self.tabelle = QTableWidget(0, 5)
        self.tabelle.setHorizontalHeaderLabels(["Datum", "Kabel", "Widerstand", "Bewertung", "Temp. max"])
        self.tabelle.verticalHeader().hide()
        self.tabelle.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabelle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabelle.itemSelectionChanged.connect(self._alten_zeigen)
        self.tabelle.setMaximumHeight(170)
        rechts.addWidget(self.tabelle)
        h.addLayout(rechts, 1)
        self._typ_gewaehlt()

    def _typ_gewaehlt(self, *_) -> None:
        self.strom.setValue(nt.KABEL_TYPEN[self.typ.currentData()][2])

    def _angabe_gewaehlt(self, *_) -> None:
        w = self.angabe.currentData()
        d = self._letztes
        if d and not self.laeuft and self.ergebnis.isVisible() and d.get("angabe_w", 0) != (w or 0) and \
                self.f._frage("Angabe ändern", f"Die Angabe auch für das angezeigte Ergebnis "
                                               f"„{d.get('name') or 'ohne Namen'}“ ändern?\n\n"
                                               "Ja: Das Ergebnis wird neu bewertet (ohne neue Messung).\n"
                                               "Nein: gilt nur für die nächste Prüfung."):
            # falsch eingestellt? Angabe nachträglich ändern - neu bewerten, ohne neu zu messen
            typ = ANGABEN[w][2] if w in ANGABEN else d.get("typ")
            neu = auswerten(0.0, d["kabel_mohm"], typ, d.get("temp_start"), d.get("temp_max"))
            for k in ("typ", "typ_name", "grenze_mohm", "nenn_a", "bis_a", "tabelle", "ampel", "satz"):
                d[k] = neu[k]
            d["angabe_w"] = w or 0
            self._zeigen(d)
            liste = self._liste()
            for x in liste:
                if x.get("wann") == d.get("wann"):
                    x.update(d)
            self._datei().write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
            self.liste_laden()
            return
        if w in ANGABEN:
            a, v, typ = ANGABEN[w]
            self.typ.setCurrentIndex(self.typ.findData(typ))
            self.strom.setValue(a)
            # bis zur angegebenen Spannung prüfen - höhere gibt das Kabel nicht her
            for sp, hk in self.spannungen:
                hk.setChecked(sp <= v + 0.5)

    # ------------------------------------------------------------------
    @property
    def laeuft(self) -> bool:
        return bool(self.ablauf and self.ablauf.laeuft) or self.knopf_weiter.isVisible()

    def zustand_zeigen(self, g, anderer_test: bool) -> None:
        self._steuer_ok = bool(g and g.kann_steuern and g.protokoll != "unbekannt") and not anderer_test
        frei = not self.laeuft
        self.knopf_start.setEnabled(self._steuer_ok and frei)
        self.knopf_abbruch.setEnabled(not frei)
        for w in (self.name, self.angabe, self.typ, self.strom, self.mit_ref, self.netzteil_wahl, self.mit_dauer, self.dauer_min,
                  self.mit_fuehler, self.temp_grenze, self.alle_v, self.dauer_jede):
            w.setEnabled(frei)
        for _, hk in self.spannungen:
            hk.setEnabled(frei and self.alle_v.isChecked())

    def _einstellung(self, ref: bool) -> nt.NetzteilEinstellung:
        a = round(self.strom.value(), 2)
        if ref:
            # Temperatur auch hier aufzeichnen - sonst fehlt der Streifen während der Referenz
            return nt.NetzteilEinstellung("Referenz ohne Kabel", 5.0, a, stufen=4, stufe_s=10, dauertest=False,
                                          abschalttest=False, fuehler=self.mit_fuehler.isChecked(),
                                          temp_grenze=self.temp_grenze.value())
        return nt.NetzteilEinstellung(self.name.text().strip() or "Kabel", 5.0, a, stufen=5, stufe_s=15,
                                      dauertest=self.mit_dauer.isChecked(), dauer_proz=100, bis_stabil=True,
                                      dauer_min=self.dauer_min.value(), abschalttest=False,
                                      fuehler=self.mit_fuehler.isChecked(), temp_grenze=self.temp_grenze.value())

    def _volt(self) -> list[float]:
        return [v for v, h in self.spannungen if h.isChecked()] if self.alle_v.isChecked() else []

    def _lauf(self, e: nt.NetzteilEinstellung) -> None:
        melden = lambda a, t: self.f.b.ereignis.emit(self.kennung + ":" + a, t)
        volt = self._volt()
        if volt:
            # jede Spannung bis zum Prüfstrom - höchstens so viel, wie der DL24 an Leistung schafft
            stufen = [(v, round(min(e.nenn_a, nt.DL24_MAX_W / v * 0.98), 2)) for v in volt]
            self.ablauf = nt.TriggerAblauf(e, stufen, self.f.geraet, bei_ereignis=melden)
            if e.dauertest and not self.dauer_jede.isChecked():
                # Dauertest nur einmal, bei der niedrigsten Spannung: die Wärme im Kabel hängt nur vom
                # Strom ab, und das Netzteil heizt den Stecker dort am wenigsten mit
                tief = min(volt)
                ablauf = self.ablauf
                ablauf.einstellung_fuer = lambda v, a, _alt=ablauf.einstellung_fuer: (
                    _alt(v, a) if v == tief else dataclasses.replace(_alt(v, a), dauertest=False))
        else:
            self.ablauf = nt.NetzteilAblauf(e, self.f.geraet, bei_ereignis=melden)
        self.linie.setData([], [])
        self.linie_t.setData([], [])
        self.f._zustand_zeigen()

    def starten(self) -> None:
        g = self.f.geraet
        if not g or not g.kann_steuern:
            return
        if self.alle_v.isChecked() and not self._volt():
            QMessageBox.information(self, "Kabel prüfen", "Bitte mindestens eine Spannung wählen.")
            return
        self.ergebnis.hide()
        self._ref = None
        ref = self.ref_name.text().strip()
        pruefling = self.name.text().strip() or "das zu prüfende Kabel"
        gespeichert = self.ref_wahl.currentData() if self.mit_ref.isChecked() else None
        if gespeichert:
            werte = gespeichert["werte"]
            if isinstance(werte, dict):
                werte = {float(v): m for v, m in werte.items()}
                fehlt = [v for v in self._volt() if v not in werte]
                if not self._volt() or fehlt:
                    QMessageBox.information(self, "Kabel prüfen", "Die gespeicherte Referenz passt nicht zu den "
                                            "gewählten Spannungen" + (f" (fehlt: {', '.join(f'{v:g} V' for v in fehlt)})"
                                                                      if fehlt else "") +
                                            ". Andere Referenz wählen oder neu messen.")
                    return
            elif self._volt():
                QMessageBox.information(self, "Kabel prüfen", "Diese Referenz wurde nur bei einer Spannung gemessen – "
                                        "für alle Spannungen neu messen.")
                return
            if not self.f._frage("Gespeicherte Referenz",
                                 f"Referenz: {self._ref_text(gespeichert)}\n\nDie gilt nur mit demselben Netzteil "
                                 f"(„{gespeichert.get('netzteil') or '?'}“) und demselben Adapter.\n\n"
                                 f"Jetzt „{pruefling}“ einstecken:\n    Netzteil → {pruefling} → Trigger-Adapter → "
                                 "DL24\n\nSteckt es so?"):
                return
            self._ref = werte
            self._kabel_phase()
            return
        if self.mit_ref.isChecked() and not self.f._frage(
                "Schritt 1: Referenz",
                ("Zuerst die Referenz – dafür das REFERENZKABEL einstecken:\n\n"
                 f"    Netzteil → {ref} → Trigger-Adapter → DL24\n\n"
                 f"Noch NICHT „{pruefling}“.\n\n" if ref else
                 "Zuerst die Referenz – das Netzteil OHNE Kabel am DL24:\n\n"
                 "    Netzteil → Trigger-Adapter mit Stecker → DL24\n\n"
                 "Hast du keinen Adapter mit Stecker, oben bei „Referenzkabel“ dein kürzestes, bestes Kabel "
                 "eintragen und das einstecken.\n\n")
                + "Danach sagt die App, wann das Kabel gewechselt wird.\n\nSteckt alles so?"):
            return
        if self.mit_ref.isChecked():
            self.phase = "ref"
            ref = self.ref_name.text().strip()
            self.schritt.setText("Schritt 1 von 2: Referenz " + (f"mit dem Referenzkabel „{ref}“" if ref else
                                                                  "ohne Kabel") + " wird gemessen …")
            self._lauf(self._einstellung(ref=True))
        else:
            self._kabel_phase()

    def _kabel_phase(self) -> None:
        self.schritt.setStyleSheet(NORMAL)
        self.knopf_weiter.hide()
        self.knopf_start.show()
        self.phase = "kabel"
        self.schritt.setText(("Schritt 2 von 2: " if self._ref is not None else "") +
                             "mit Kabel – Messung läuft …")
        self._lauf(self._einstellung(ref=False))

    def abbrechen(self, ohne_frage: bool = False) -> None:
        if self.knopf_weiter.isVisible():
            self.knopf_weiter.hide()
            self.knopf_start.show()
            self.schritt.setText("Abgebrochen.")
            self.f._zustand_zeigen()
            return
        if self.ablauf and self.ablauf.laeuft:
            self.ablauf.abbrechen()

    def verbindung_weg(self, grund: str) -> None:
        self.knopf_weiter.hide()
        self.knopf_start.show()
        if self.ablauf and self.ablauf.laeuft:
            self.ablauf.zustand = "abgebrochen"
        self.schritt.setText(f"Verbindung verloren: {grund}")

    def messwert_faden(self, m: Messwert) -> None:
        ab = self.ablauf
        if ab and ab.laeuft:
            ab.messwert(m)

    def messwert(self, m: Messwert) -> None:
        self.anz["u"].setzen(zahl(m.spannung, 3, "V"))
        self.anz["i"].setzen(zahl(m.strom, 3, "A"))
        if not self.mit_fuehler.isChecked():
            self.anz["t"].setzen("aus ⚠" if m.temp_fuehler is not None else "aus")
            self.anz["t"].setToolTip("Der Fühler steckt, wird aber nicht ausgewertet – Haken „Temperaturfühler am "
                                     "Stecker“ setzen." if m.temp_fuehler is not None else "")
        else:
            self.anz["t"].setzen(zahl(m.temp_fuehler, 1, "°C") if m.temp_fuehler is not None else "kein Fühler")
        ab = self.ablauf
        if not ab or not ab.punkte:
            return
        teil = ab.teil if isinstance(ab, nt.TriggerAblauf) else ab
        stufen = teil.ergebnis.stufen if isinstance(teil, nt.NetzteilAblauf) else []
        if ab.laeuft and len(stufen) >= 2:
            w = nt.widerstand(stufen)
            if w is not None:
                ref = self._ref
                if isinstance(ref, dict):
                    ref = ref.get(teil.einstellung.nenn_v, 0)
                kabel = w - (ref or 0) if self.phase == "kabel" else w
                self.anz["r"].setzen(f"{max(0, kabel):.0f} mΩ" + (" (Netzteil)" if self.phase == "ref" else ""))
        self._zeit_zeigen(ab, teil, m)
        p = list(ab.punkte)
        self.linie.setData([x[0] / 60 for x in p], [x[1] for x in p])
        mit = [(x[0] / 60, x[3]) for x in p if x[3] is not None]
        self.linie_t.setData([a for a, _ in mit], [b for _, b in mit])
        self.bild_t.setVisible(bool(mit))

    def _zeit_zeigen(self, ab, teil, m: Messwert) -> None:
        """Wie lange läuft die Prüfung schon, was kommt noch, wie lange noch etwa."""
        from .fenster import dauer_text
        if not ab.laeuft:
            self.zeit.setText("")
            return
        seit = ab.punkte[-1][0] if ab.punkte else 0
        teile = [f"Läuft seit {dauer_text(seit)}"]
        rest = None
        if isinstance(teil, nt.NetzteilAblauf) and teil.laeuft:
            r = teil.restzeit(m.zeit)
            if r:
                rest = r[1]
                s = teil.schritt
                if s:
                    teile.append(f"Stufe {teil.i + 1} von {len(teil.schritte)} · {s.soll_a:.2f} A".replace(".", ","))
        if isinstance(ab, nt.TriggerAblauf):
            weiter = ab.stufen[ab.i + 1:] if ab.i >= 0 else ab.stufen
            if ab.ziel:
                teile.append(f"Spannung {min(ab.i + 1, len(ab.stufen))} von {len(ab.stufen)} ({ab.ziel[0]:g} V)")
            rest = (rest or 0) + sum(nt.geplant_s(ab.einstellung_fuer(v, a)) + 30 for v, a in weiter)
        if self.phase == "ref" and rest is not None:
            # danach kommt noch der ganze Durchgang mit Kabel
            e = self._einstellung(ref=False)
            n = len(self._volt()) or 1
            ohne = e if self.dauer_jede.isChecked() else dataclasses.replace(e, dauertest=False)
            rest += nt.geplant_s(e) + (n - 1) * nt.geplant_s(ohne) + (30 * n if self._volt() else 0) + 30
        if rest is not None:
            teile.append(f"noch etwa {dauer_text(rest)} gesamt")
        self.zeit.setText(" · ".join(teile))

    def ereignis(self, art: str, text: str) -> None:
        if art == "umschalten":
            self._handeln(("⚠ Referenz: " if self.phase == "ref" else "⚠ Mit Kabel: ") + text)
            return
        self.schritt.setStyleSheet(NORMAL)
        if art in ("schritt", "info"):
            vorn = "Schritt 1 von 2 (Referenz): " if self.phase == "ref" else (
                "Schritt 2 von 2 (mit Kabel): " if self._ref is not None else "Mit Kabel: ")
            self.schritt.setText(vorn + text)
        elif art == "fertig":
            self._fertig()

    def _fertig(self) -> None:
        ab = self.ablauf
        if isinstance(ab, nt.TriggerAblauf):
            self._fertig_spannungen(ab)
            return
        r = ab.ergebnis
        if ab.zustand != "fertig" and not (self.phase == "kabel" and r.zu_heiss and r.widerstand_mohm):
            self.schritt.setText(f"Nicht geklappt: {r.grund}")
            self.f._zustand_zeigen()
            return
        if self.phase == "ref":
            if not r.widerstand_mohm and r.widerstand_mohm != 0:
                self.schritt.setText("Referenz ohne Ergebnis – schafft das Netzteil den Prüfstrom?")
                self.f._zustand_zeigen()
                return
            self._ref = r.widerstand_mohm
            self._referenz_speichern(self._ref)
            self._handeln("⚠ " + self._wechsel_text(f"{self._ref:.0f} mΩ", self._ref))
            self.knopf_start.hide()
            self.knopf_weiter.show()
            self.f._zustand_zeigen()
            return
        if r.widerstand_mohm is None:
            self.schritt.setText("Kein Widerstand ermittelt – zu wenige Stufen geschafft.")
            self.f._zustand_zeigen()
            return
        d = auswerten(self._ref, r.widerstand_mohm, self.typ.currentData(), r.temp_start, r.temp_max)
        d["pruef_a"] = self.strom.value()
        d["stabil"] = r.temp_stabil
        d["ref_name"] = self.ref_name.text().strip() if self._ref is not None else ""
        d["bedingungen"] = bedingungen(ab.punkte)
        d["angabe_w"] = self.angabe.currentData() or 0
        d["temp_grenze"] = self.temp_grenze.value()
        d.update(name=self.name.text().strip(), wann=time.time(), zu_heiss=r.zu_heiss,
                 kurve=[list(p) for p in nt.duennen(ab.punkte, 600)])
        self._zeigen(d)
        self._speichern(d)
        self.schritt.setText(f"Fertig: Kabel {d['kabel_mohm']:.0f} mΩ")
        self.zeit.setText(f"Prüfdauer {_min(d['bedingungen']['dauer_s'])}" if d.get("bedingungen") else "")
        self.f._zustand_zeigen()

    def _handeln(self, text: str) -> None:
        """Jetzt muss der Mensch etwas tun: groß, farbig, mit Ton und Blinken in der Taskleiste."""
        from PySide6.QtWidgets import QApplication
        self.schritt.setText(text)
        self.schritt.setStyleSheet(AUFFAELLIG)
        QApplication.beep()
        QApplication.alert(self.f)

    def _wechsel_text(self, wert: str, hoechst: float) -> str:
        ref = self.ref_name.text().strip()
        pruefling = self.name.text().strip() or "das zu prüfende Kabel"
        text = (f"Referenz ({'Netzteil + ' + ref if ref else 'Netzteil + Adapter'}): {wert}.\n\n"
                + (f"Jetzt „{ref}“ HERAUSZIEHEN und „{pruefling}“ einstecken: " if ref else
                   f"Jetzt „{pruefling}“ dazwischen stecken: ")
                + f"Netzteil → {pruefling} → Trigger-Adapter → DL24. Dann auf „weiter“ drücken.")
        if hoechst > REF_GUT_MOHM:
            text += (f"\n\nHinweis: Die Referenz ist mit {hoechst:.0f} mΩ recht hoch. Liegt das am Netzteil (z. B. "
                     "einem Step-Down-Modul), ist das kein Problem – es wird abgezogen. Ist dagegen das Referenzkabel "
                     "schlecht, fällt das Ergebnis zu gut aus; dann besser mit einem kürzeren Kabel neu starten.")
        return text

    def _fertig_spannungen(self, ab: nt.TriggerAblauf) -> None:
        """Über den Trigger-Adapter: je Spannung ein Widerstand."""
        werte = {t["einstellung"]["nenn_v"]: t["ergebnis"].get("widerstand_mohm") for t in ab.ergebnis.teile}
        werte = {v: w for v, w in werte.items() if w is not None}
        if not werte:
            self.schritt.setText(f"Nicht geklappt: {ab.ergebnis.grund}")
            self.f._zustand_zeigen()
            return
        if self.phase == "ref":
            self._ref = werte
            self._referenz_speichern(werte)
            self._handeln("⚠ " + self._wechsel_text(", ".join(f"{v:g} V: {w:.0f} mΩ" for v, w in werte.items()),
                                                    max(werte.values()))
                          + f" Den Trigger-Adapter wieder auf {min(werte):g} V stellen.")
            self.knopf_start.hide()
            self.knopf_weiter.show()
            self.f._zustand_zeigen()
            return
        ref = self._ref if isinstance(self._ref, dict) else {}
        je, fehlt = [], [f"{n['volt']:g} V ({n['grund']})" for n in ab.ergebnis.nicht]
        for t in ab.ergebnis.teile:
            v = t["einstellung"]["nenn_v"]
            ges = t["ergebnis"].get("widerstand_mohm")
            if ges is None:
                continue
            r0 = ref.get(v) if ref else None
            if ref and r0 is None:
                fehlt.append(f"{v:g} V (keine Referenz)")
                continue
            st = t["ergebnis"].get("stufen") or []
            if t["ergebnis"].get("dauer"):
                st = st + [t["ergebnis"]["dauer"]]
            max_w = max((s["spannung"] * s["strom"] for s in st), default=None)
            je.append((v, r0, ges, max(0.0, ges - (r0 or 0)), t["ergebnis"].get("max_getestet_a", 0),
                       t["ergebnis"].get("temp_max"), round(max_w, 1) if max_w else None,
                       t["ergebnis"].get("dauer_s")))
        if not je:
            self.schritt.setText("Kein Wert – keine Spannung mit Referenz und Kabel gemessen.")
            self.f._zustand_zeigen()
            return
        kabel = sum(x[3] for x in je) / len(je)
        temps = [t["ergebnis"].get("temp_max") for t in ab.ergebnis.teile if t["ergebnis"].get("temp_max")]
        starts = [t["ergebnis"].get("temp_start") for t in ab.ergebnis.teile if t["ergebnis"].get("temp_start")]
        d = auswerten(None if not ref else 0.0, kabel, self.typ.currentData(), min(starts) if starts else None,
                      max(temps) if temps else None)
        d["ohne_referenz"] = not ref
        d["gesamt_mohm"] = sum(x[2] for x in je) / len(je)
        d["ref_mohm"] = d["gesamt_mohm"] - kabel
        d["stabil"] = any(t["ergebnis"].get("temp_stabil") for t in ab.ergebnis.teile)
        d["ref_name"] = self.ref_name.text().strip() if ref else ""
        d["bedingungen"] = bedingungen(ab.punkte)
        d["angabe_w"] = self.angabe.currentData() or 0
        d["temp_grenze"] = self.temp_grenze.value()
        d["zu_heiss"] = any(t["ergebnis"].get("zu_heiss") for t in ab.ergebnis.teile)
        d.update(name=self.name.text().strip(), wann=time.time(), je_spannung=je, fehlt=fehlt,
                 pruef_a=self.strom.value(), kurve=[list(p) for p in nt.duennen(ab.punkte, 900)])
        self._zeigen(d)
        self._speichern(d)
        self.schritt.setText(f"Fertig: Kabel {d['kabel_mohm']:.0f} mΩ (Mittel über {len(je)} Spannungen)")
        self.zeit.setText(f"Prüfdauer {_min(d['bedingungen']['dauer_s'])}" if d.get("bedingungen") else "")
        self.f._zustand_zeigen()

    # ------------------------------------------------------------------
    def _zeigen(self, d: dict) -> None:
        self._letztes = d
        self.ergebnis.setText(bericht_html(d))
        self.ergebnis.show()
        self.knopf_uebernehmen.setEnabled(True)
        self.knopf_pdf.setEnabled(True)
        k = d.get("kurve") or []
        self.linie.setData([x[0] / 60 for x in k], [x[1] for x in k])
        mit = [(x[0] / 60, x[3]) for x in k if len(x) > 3 and x[3] is not None]
        self.linie_t.setData([a for a, _ in mit], [b for _, b in mit])
        self.bild_t.setVisible(bool(mit))

    def uebernehmen(self) -> None:
        d = self._letztes
        if not d:
            return
        for r in (getattr(self.f, "nt", None), getattr(self.f, "pb", None)):
            if r is None:
                continue
            r._kabel_setzen(d["kabel_mohm"])
            if d.get("name"):
                r.kabel_name.setText(d["name"])
            i = r.kabel_typ.findData(d.get("typ"))
            if i >= 0:
                r.kabel_typ.setCurrentIndex(i)
        self.f.b.ereignis.emit("info", f"Kabelwert {d['kabel_mohm']:.0f} mΩ übernommen – gilt für Netzteile und "
                                       "Powerbanks")

    def netzteile_laden(self) -> None:
        """Eigene Vorlagen, schon geprüfte Netzteile und die mitgelieferten Vorlagen."""
        jetzt = self.netzteil.text()
        namen: list[str] = []
        try:
            namen += [n for n, d in self.f.speicher.vorlagen() if not d.get("powerbank")]
            namen += [d["name"] for d in self.f.speicher.netzteil_tests()
                      if not d["einstellung"].get("powerbank") and d.get("name")]
        except Exception:
            log.exception("Netzteile für die Auswahl")
        namen += [n for n, *_ in nt.VORLAGEN]
        gesehen, liste = set(), []
        for n in namen:
            if n and n not in gesehen:
                gesehen.add(n)
                liste.append(n)
        self.netzteil_wahl.blockSignals(True)
        self.netzteil_wahl.clear()
        self.netzteil_wahl.addItems(liste)
        self.netzteil_wahl.setCurrentIndex(-1)
        self.netzteil.setText(jetzt)
        self.netzteil_wahl.blockSignals(False)

    def showEvent(self, ereignis) -> None:
        super().showEvent(ereignis)
        if hasattr(self, "netzteil_wahl"):
            self.netzteile_laden()               # inzwischen geprüfte Netzteile mit aufnehmen

    # -- gespeicherte Referenzen -------------------------------------------
    def _ref_datei(self):
        return datenordner() / "kabel_referenzen.json"

    def _referenzen(self) -> list:
        try:
            return json.loads(self._ref_datei().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    @staticmethod
    def _ref_text(r: dict) -> str:
        werte = r["werte"]
        w = (", ".join(f"{float(v):g} V: {m:.0f} mΩ" for v, m in sorted(werte.items(), key=lambda x: float(x[0])))
             if isinstance(werte, dict) else f"{werte:.0f} mΩ")
        return (f"{r.get('ref_name') or 'ohne Kabel'} · {r.get('netzteil') or 'Netzteil ?'} · "
                f"{datetime.fromtimestamp(r['wann']):%d.%m.%Y} – {w}")

    def referenzen_laden(self) -> None:
        self.ref_wahl.blockSignals(True)
        self.ref_wahl.clear()
        self.ref_wahl.addItem("Neu messen (Schritt 1)", None)
        for r in self._referenzen():
            self.ref_wahl.addItem(self._ref_text(r), r)
        self.ref_wahl.blockSignals(False)
        self._ref_gewaehlt()

    def _ref_gewaehlt(self, *_) -> None:
        r = self.ref_wahl.currentData()
        self.knopf_ref_weg.setEnabled(r is not None)
        if r:
            self.ref_name.setText(r.get("ref_name") or "")
            self.netzteil.setText(r.get("netzteil") or "")

    def _referenz_speichern(self, werte) -> None:
        eintrag = {"wann": time.time(), "ref_name": self.ref_name.text().strip(),
                   "netzteil": self.netzteil.text().strip(), "strom": self.strom.value(),
                   "werte": {str(v): w for v, w in werte.items()} if isinstance(werte, dict) else werte}
        liste = [eintrag] + self._referenzen()
        self._ref_datei().write_text(json.dumps(liste[:30], ensure_ascii=False), encoding="utf-8")
        self.referenzen_laden()

    def referenz_loeschen(self) -> None:
        r = self.ref_wahl.currentData()
        if not r or not self.f._frage("Referenz löschen", f"Gespeicherte Referenz löschen?\n\n{self._ref_text(r)}"):
            return
        liste = [x for x in self._referenzen() if x["wann"] != r["wann"]]
        self._ref_datei().write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
        self.referenzen_laden()

    def _datei(self):
        return datenordner() / "kabel.json"

    def _liste(self) -> list:
        try:
            return json.loads(self._datei().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _speichern(self, d: dict) -> None:
        liste = [d] + self._liste()
        self._datei().write_text(json.dumps(liste[:200], ensure_ascii=False), encoding="utf-8")
        self.liste_laden()

    def liste_laden(self) -> None:
        self._alle = self._liste()
        t = self.tabelle
        t.blockSignals(True)
        t.setRowCount(len(self._alle))
        from PySide6.QtGui import QColor
        for i, d in enumerate(self._alle):
            ampel = d.get("ampel")
            bewertung = {"gruen": "✔ in Ordnung", "gelb": "⚠ schwach", "rot": "✘ Schrott"}.get(ampel, "–")
            if zu_warm(d) or abgebrochen(d):
                bewertung, ampel = "✘ zu heiß", "rot"
            elif knapp(d) and ampel != "rot":
                bewertung, ampel = "? knapp (Wärme)", "gelb"
            erg = angabe_pruefen(d)
            if erg:
                # mit Angabe zählt, ob es die hält
                bewertung = {"ja": f"✔ hält {d['angabe_w']} W", "nicht": f"✘ hält {d['angabe_w']} W nicht",
                             "offen": f"? {d['angabe_w']} W nicht ganz geprüft"}[erg[0]]
                ampel = {"ja": "gruen", "nicht": "rot", "offen": "gelb"}[erg[0]]
            werte = [datetime.fromtimestamp(d.get("wann", 0)).strftime("%d.%m.%Y %H:%M"), d.get("name") or "–",
                     f"{d['kabel_mohm']:.0f} mΩ", bewertung,
                     zahl(d["temp_max"], 0, "°C") if d.get("temp_max") is not None else "–"]
            for k, text in enumerate(werte):
                z = QTableWidgetItem(text)
                if k == 3 and ampel:
                    z.setForeground(QColor(AMPEL[ampel]))
                t.setItem(i, k, z)
        t.blockSignals(False)

    def _alten_zeigen(self) -> None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        if zeilen and not self.laeuft:
            self._zeigen(self._alle[zeilen[0].row()])

    def loeschen(self) -> None:
        zeilen = self.tabelle.selectionModel().selectedRows()
        if not zeilen:
            return
        d = self._alle[zeilen[0].row()]
        if not self.f._frage("Löschen", f"Kabel „{d.get('name') or 'ohne Namen'}“ aus der Liste löschen?"):
            return
        liste = [x for x in self._liste() if x.get("wann") != d.get("wann")]
        self._datei().write_text(json.dumps(liste, ensure_ascii=False), encoding="utf-8")
        self.ergebnis.hide()
        self.liste_laden()

    def bericht_speichern(self, pfad: str | None = None) -> str | None:
        from PySide6.QtCore import QMarginsF, QUrl
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
        from PySide6.QtWidgets import QFileDialog
        d = self._letztes
        if not d:
            return None
        if not pfad:
            name = "".join(c if c.isalnum() or c in " -_" else "_" for c in d.get("name") or "Kabel").strip()
            pfad, _ = QFileDialog.getSaveFileName(self, "Bericht speichern",
                                                  f"Kabelbericht {name} {datetime.now():%Y-%m-%d}.pdf", "PDF (*.pdf)")
            if not pfad:
                return None
        from . import normen
        from .netzteil_reiter import normen_html
        doc = QTextDocument()
        doc.addResource(QTextDocument.ImageResource, QUrl("kurve.png"), diagramm_bild(d))
        quellen = normen.kabel_eintraege()
        for i, n in enumerate(quellen):
            try:
                doc.addResource(QTextDocument.ImageResource, QUrl(f"qr{i}.png"), normen.qr_bild(n["url"]))
            except Exception:
                log.exception("QR-Code")
        doc.setHtml(bericht_html(d) + "<p><b>Verlauf</b></p><p><img src='kurve.png' width='640'></p>"
                    "<p style='color:gray'>Oben die Spannung am DL24, in der Mitte der Strom, unten die Temperatur "
                    "am Stecker mit der Grenze der Norm (+30 K über der Starttemperatur).</p>"
                    + normen_html(quellen))
        w = QPdfWriter(pfad)
        w.setPageSize(QPageSize(QPageSize.A4))
        w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
        w.setResolution(110)
        doc.setPageSize(w.pageLayout().paintRectPixels(w.resolution()).size().toSizeF())
        doc.print_(w)
        return pfad
