"""Der DL24 als Objekt: erkennt beim Verbinden, welche Sprache das Gerät
spricht, liefert laufend Messwerte und nimmt Befehle an.

Alles, was über die Leitung geht, landet auch bei `bei_roh` - der
Diagnose-Reiter zeigt es an. Wenn ein Gerät anders antwortet als erwartet,
sieht man dort, was es wirklich schickt.
"""
from __future__ import annotations

import logging
import re
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from . import protokoll as p
from .verbindung import Verbindung, VerbindungsFehler

log = logging.getLogger("akkutest.geraet")

# Abfrage-Takt in Sekunden. Die Tests stellen ihn für den Zeitraffer kürzer,
# bevor das Fenster verbindet - sonst gilt bis zur ersten Abfrage noch 1 s.
INTERVALL = 1.0
# Über USB-HID fragt die App selbst - so oft, wie das Gerät neue Werte hat
HID_INTERVALL = 0.5


@dataclass
class Messwert:
    zeit: float              # Sekunden, fortlaufend (nicht Uhrzeit)
    spannung: float          # V
    strom: float             # A
    an: bool                 # Last eingeschaltet?
    mah_geraet: float | None = None
    wh_geraet: float | None = None
    temperatur: float | None = None
    temp_fuehler: float | None = None   # Fühler am Kabel (USB); None = keiner angesteckt

    @property
    def leistung(self) -> float:
        return self.spannung * self.strom


class Entwirrer:
    """Trennt den Datenstrom in Atorch-Berichte, PX100-Antworten und Quittungen.
    Manche Geräte schicken beides durcheinander."""

    def __init__(self) -> None:
        self.puffer = bytearray()

    def hinein(self, daten: bytes) -> list[tuple[str, object]]:
        self.puffer += daten
        aus: list[tuple[str, object]] = []
        b = self.puffer
        while b:
            if b[0] == 0xFF:
                if len(b) < 2:
                    break
                if b[1] == 0x55:
                    if len(b) < p.ATORCH_LAENGE:
                        break
                    # Fängt mittendrin schon das nächste Paket an, war dieses
                    # ein Bruchstück - ohne Prüfsumme merkt man es nur so
                    weiter = b.find(b"\xff\x55\x01", 1, p.ATORCH_LAENGE)
                    if weiter > 0:
                        del b[:1]        # nur den Kopf verwerfen: dazwischen kann eine Antwort stecken
                        continue
                    w = p.atorch_lesen(bytes(b[:p.ATORCH_LAENGE]))
                    if w is not None:
                        aus.append(("atorch", w))
                        del b[:p.ATORCH_LAENGE]
                        continue
                del b[:1]
            elif b[0] == 0xCA:
                if len(b) < 7:
                    break
                wert = p.px_antwort_wert(bytes(b[:7]))
                if wert is not None:
                    aus.append(("px", wert))
                    del b[:7]
                    continue
                del b[:1]
            elif b[0] in (p.PX_OK, p.PX_FEHLER):
                aus.append(("quittung", b[0] == p.PX_OK))
                del b[:1]
            else:
                del b[:1]
        return aus


class Geraet:
    def __init__(self, verbindung: Verbindung, intervall: float | None = None,
                 bei_roh: Callable[[str, bytes], None] | None = None) -> None:
        self.v = verbindung
        self.intervall = intervall or INTERVALL
        self.bei_roh = bei_roh
        self.bei_messwert: Callable[[Messwert], None] | None = None
        self.bei_fehler: Callable[[str], None] | None = None
        self.protokoll: str | None = None          # "px100", "atorch", "hid" oder "unbekannt"
        self.firmware: str | None = None
        self._letzte_hid = 0.0
        self._soll_a: float | None = None       # USB: zuletzt gesetzter Strom
        self._zu_viel = 0
        self._hid_adresse = p.HID_ADRESSE
        self._entwirrer = Entwirrer()
        self._antworten: queue.Queue = queue.Queue()
        self._atorch_gesehen = 0
        self._empfangen_bytes = 0
        self._roh_im_log = 0
        self._sperre = threading.Lock()            # eine Frage zur Zeit
        self._laeuft = False
        self.antwortzeit = 0.8
        v = verbindung
        v.bei_daten = self._daten
        v.bei_ende = lambda grund: self._fehler(grund)

    @property
    def kann_steuern(self) -> bool:
        return self.protokoll in ("px100", "hid")

    @property
    def spannung_stellen(self) -> int:
        """Nachkommastellen, die das Gerät wirklich liefert: der Atorch-Bericht
        über Bluetooth nur 0,1 V, PX100 und USB-HID 1 mV."""
        return 1 if self.protokoll == "atorch" else 3

    # ---- hinein ----
    def _daten(self, daten: bytes) -> None:
        self._empfangen_bytes += len(daten)
        # Die ersten paar hundert Stücke auch in die Logdatei: die lässt sich
        # leichter verschicken als der Diagnose-Reiter
        if self._roh_im_log < 300:
            self._roh_im_log += 1
            log.info("< %s", p.hex_text(daten))
        if self.bei_roh:
            self.bei_roh("<", daten)
        if self.v.pakete:
            self._hid_paket(daten)
            return
        for art, inhalt in self._entwirrer.hinein(daten):
            if art == "atorch":
                self._atorch_gesehen += 1
                if self.protokoll == "atorch" and self.bei_messwert:
                    w: p.AtorchWerte = inhalt
                    self.bei_messwert(Messwert(self.v.uhr(), w.spannung, w.strom, w.strom > 0.0005,
                                               w.kapazitaet_mah, w.energie_wh, w.temperatur))
            else:
                self._antworten.put((art, inhalt))

    def _hid_paket(self, daten: bytes) -> None:
        w = p.hid_lesen(daten, self._hid_adresse)
        if w is None:
            return
        self._letzte_hid = time.monotonic()
        if w.firmware:
            self.firmware = w.firmware
        if self.protokoll == "hid":
            strom = abs(w.strom)              # das Gerät meldet Entladen negativ
            self._strom_pruefen(w.an, strom)
            if self.bei_messwert:
                self.bei_messwert(Messwert(self.v.uhr(), w.spannung, strom, w.an,
                                           w.kapazitaet_mah, w.energie_wh, w.temp_mos,
                                           w.temp_fuehler if w.temp_fuehler > -40 else None))
        else:
            self._antworten.put(("hid", w))

    def _strom_pruefen(self, an: bool, strom: float) -> None:
        """Sicherung: fließt deutlich mehr als eingestellt, sofort aus. Die
        USB-Befehle sind aus der Atorch-Software gelesen, nicht vom Hersteller
        beschrieben - verstünde das Gerät eine Zahl anders, soll das keinen
        Akku kosten."""
        if not an or self._soll_a is None or strom <= self._soll_a * 1.3 + 0.1:
            self._zu_viel = 0
            return
        self._zu_viel += 1
        if self._zu_viel == 2:
            log.error("USB: %.3f A statt %.3f A - schalte ab", strom, self._soll_a)
            try:
                self._senden(p.hid_befehl(self._hid_adresse, p.HID_LAST))
            except Exception:
                log.exception("Notabschaltung")
            self._fehler(f"Sicherheitsabschaltung: Es flossen {strom:.3f} A statt {self._soll_a:.3f} A. "
                         "Die Last wurde ausgeschaltet - bitte am Gerät prüfen.")

    def _fehler(self, text: str) -> None:
        self._laeuft = False
        log.warning(text)
        if self.bei_fehler:
            self.bei_fehler(text)

    # ---- hinaus ----
    def _senden(self, daten: bytes) -> None:
        if self.bei_roh:
            self.bei_roh(">", daten)
        self.v.schreiben(daten)

    def _frage(self, befehl: int, d1: int = 0, d2: int = 0, art: str = "px",
               paket: bytes | None = None) -> object | None:
        with self._sperre:
            while not self._antworten.empty():
                self._antworten.get_nowait()
            self._senden(paket if paket is not None else p.px_befehl(befehl, d1, d2))
            ende = time.monotonic() + self.antwortzeit
            while (rest := ende - time.monotonic()) > 0:
                try:
                    a, inhalt = self._antworten.get(timeout=rest)
                except queue.Empty:
                    break
                if a == art:
                    return inhalt
            return None

    # ---- Erkennen ----
    def erkennen(self, warten: float = 1.5) -> str:
        """Welche Sprache spricht das Gerät? Erst kurz zuhören, dann fragen."""
        if self.v.pakete:
            return self._hid_erkennen()
        time.sleep(warten)
        for _ in range(3):
            if self._frage(p.PX_SPANNUNG) is not None:
                self.protokoll = "px100"
                log.info("Gerät antwortet auf PX100-Befehle")
                return self.protokoll
        ende = time.monotonic() + 3
        while self._atorch_gesehen == 0 and time.monotonic() < ende:
            time.sleep(0.1)
        if self._atorch_gesehen:
            self.protokoll = "atorch"
            log.info("Gerät schickt Atorch-Berichte, antwortet aber nicht auf PX100")
            return self.protokoll
        if self._empfangen_bytes:
            # Es kommt etwas an, nur in einem Format, das wir nicht kennen.
            # Verbunden bleiben und mitschreiben - daraus lässt sich das Format
            # nachbauen. Trennen hilft niemandem.
            self.protokoll = "unbekannt"
            log.warning("Gerät sendet %d Bytes in unbekanntem Format - bleibe verbunden", self._empfangen_bytes)
            return self.protokoll
        raise VerbindungsFehler(
            "Das Gerät antwortet nicht.\n\n"
            "• Ist der DL24 eingeschaltet (Spannung an den Klemmen oder am USB-Netzteil)?\n"
            "• Richtiger Anschluss gewählt?\n"
            "• Ist die Atorch-App am Handy noch verbunden? Bluetooth geht nur mit einem Gerät.\n\n"
            "Im Reiter „Diagnose“ steht, was über die Leitung kam.")

    def _hid_erkennen(self) -> str:
        """USB-HID: Messwerte abfragen, wie die Atorch-Software es im Takt tut.
        Antwortet es nicht, den nächsten Weg probieren (siehe UsbHid).
        Kein "Anmelden" vorweg - das vermeintliche Anmeldepaket war der
        Update-Start (siehe protokoll.py)."""
        while True:
            for _ in range(3):
                w = self._frage(0, art="hid", paket=p.hid_abfrage(self._hid_adresse))
                if w is not None:
                    self.protokoll = "hid"
                    if not self.firmware:
                        # Gerätename, z. B. "ATORCH DL24 V1.1.0"
                        for zeile in getattr(self.v, "info", []):
                            m = re.search(r"\bV(\d+(?:\.\d+)+)", zeile)
                            if m:
                                self.firmware = m.group(1)
                    log.info("USB-HID: Messwerte kommen (Firmware %s) über %s",
                             self.firmware, getattr(self.v, "weg_text", "?"))
                    return self.protokoll
            if self._empfangen_bytes:
                break
            weiter = getattr(self.v, "naechster_weg", None)
            if not weiter or not weiter():
                break
        if self._empfangen_bytes:
            self.protokoll = "unbekannt"
            log.warning("USB-HID: %d Bytes in unbekanntem Format - bleibe verbunden", self._empfangen_bytes)
            return self.protokoll
        raise VerbindungsFehler(
            "Der DL24 antwortet über USB nicht – auf keinem Weg.\n\n"
            "• Ist die Atorch-PC-Software noch offen? Erst schließen.\n"
            "• USB-Kabel einmal ab- und wieder anstecken.\n\n"
            "Was probiert wurde, steht in der Logdatei (Reiter „Diagnose“).")

    # ---- Messen ----
    def starten(self) -> None:
        self._laeuft = True
        if self.protokoll == "px100":
            threading.Thread(target=self._abfragen, name="abfrage", daemon=True).start()
        elif self.protokoll == "hid":
            threading.Thread(target=self._hid_abfragen, name="hid-abfrage", daemon=True).start()

    def anhalten(self) -> None:
        self._laeuft = False

    def _abfragen(self) -> None:
        fehlschlaege = 0
        while self._laeuft:
            beginn = time.monotonic()
            m = self.messen()
            if m is None:
                fehlschlaege += 1
                if fehlschlaege >= 5:
                    self._fehler("Das Gerät antwortet nicht mehr.")
                    return
            else:
                fehlschlaege = 0
                if self.bei_messwert:
                    self.bei_messwert(m)
            time.sleep(max(0.0, self.intervall - (time.monotonic() - beginn)))

    def _hid_abfragen(self) -> None:
        # Nicht auf jede Antwort warten: fragen, und was kommt, geht über
        # _hid_paket direkt an die Anzeige. Bleibt es zu lange still, ist das
        # Gerät weg.
        takt = min(self.intervall, HID_INTERVALL)
        self._letzte_hid = time.monotonic()
        while self._laeuft:
            try:
                self._senden(p.hid_abfrage(self._hid_adresse))
            except Exception as e:
                self._fehler(f"USB: {e}")
                return
            time.sleep(takt)
            if time.monotonic() - self._letzte_hid > max(5.0, takt * 10):
                self._fehler("Der DL24 antwortet über USB nicht mehr.")
                return

    def messen(self) -> Messwert | None:
        werte = {}
        for name, befehl in (("an", p.PX_IST_AN), ("u", p.PX_SPANNUNG), ("i", p.PX_STROM),
                             ("ah", p.PX_AH), ("wh", p.PX_WH), ("t", p.PX_TEMPERATUR)):
            w = self._frage(befehl)
            if w is None:
                if name in ("an", "u", "i"):
                    return None
                continue
            werte[name] = w
        return Messwert(self.v.uhr(), werte["u"] / 1000, werte["i"] / 1000, bool(werte["an"]),
                        werte.get("ah"), werte["wh"] / 1000 if "wh" in werte else None, werte.get("t"))

    # ---- Steuern ----
    def _hid_setzen(self, befehl: int, daten: bytes = b"\0\0\0\0") -> bool:
        # Das Gerät quittiert nicht. Ob es ankam, zeigt die nächste Abfrage
        # (Last an/aus) bzw. das Display. Nicht warten: das hier läuft oft im
        # Lesefaden, der die Antwort erst liefern müsste.
        for _ in range(2):          # zweimal - ein verlorenes Paket fällt sonst nicht auf
            self._senden(p.hid_befehl(self._hid_adresse, befehl, daten))
        return True

    def _setzen(self, befehl: int, d1: int = 0, d2: int = 0) -> bool:
        if not self.kann_steuern:
            raise VerbindungsFehler("Dieses Gerät lässt sich nicht fernsteuern - bitte am Gerät bedienen.")
        for _ in range(3):
            q = self._frage(befehl, d1, d2, art="quittung")
            if q is not None:
                return bool(q)
        return False

    def last(self, ein: bool) -> bool:
        if self.protokoll == "hid":
            self._zu_viel = 0
            return self._hid_setzen(p.HID_LAST, bytes([1 if ein else 0, 0, 0, 0]))
        return self._setzen(p.PX_EIN_AUS, 1 if ein else 0)

    def strom_setzen(self, ampere: float) -> bool:
        if self.protokoll == "hid":
            self._soll_a = ampere
            return self._hid_setzen(p.HID_SOLLWERT, p.hid_zahl(ampere))
        return self._setzen(p.PX_STROM_SETZEN, *p.px_zahl_mit_hundertsteln(ampere))

    def abschaltung_setzen(self, volt: float) -> bool:
        if self.protokoll == "hid":
            return self._hid_setzen(p.HID_ABSCHALT, p.hid_zahl(volt))
        return self._setzen(p.PX_ABSCHALT_SETZEN, *p.px_zahl_mit_hundertsteln(volt))

    def zaehler_null(self) -> None:
        if self.protokoll == "hid":
            self._hid_setzen(p.HID_ZAEHLER_NULL)
            return
        if self.kann_steuern:
            self._setzen(p.PX_ZAEHLER_NULL)
        else:
            self._senden(p.atorch_befehl(p.ATORCH_ALLES_NULL))

    def trennen(self) -> None:
        self._laeuft = False
        self.v.schliessen()
