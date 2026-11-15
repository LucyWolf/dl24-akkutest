"""Ein nachgebauter DL24 mit Akku dran.

Damit lässt sich die App ohne Gerät ausprobieren (Anschluss "Simulator"),
und die Tests spielen damit ganze Entladungen im Zeitraffer durch. Er spricht
dieselben Bytes wie das echte Gerät - nicht eine Abkürzung daran vorbei.
"""
from __future__ import annotations

import bisect
import threading
import time

from . import protokoll as p
from .verbindung import Verbindung

# Ruhespannung je Zelle über dem Ladestand (0 … 1)
KURVEN = {
    "liion": [(0.0, 2.75), (0.03, 3.20), (0.08, 3.42), (0.2, 3.55), (0.4, 3.68),
              (0.6, 3.80), (0.8, 3.96), (0.95, 4.10), (1.0, 4.18)],
    "lifepo4": [(0.0, 2.40), (0.05, 2.95), (0.1, 3.15), (0.3, 3.25), (0.7, 3.30),
                (0.95, 3.35), (1.0, 3.42)],
    "nimh": [(0.0, 0.95), (0.05, 1.12), (0.2, 1.22), (0.8, 1.28), (0.95, 1.35), (1.0, 1.42)],
}


def ruhespannung(typ: str, soc: float) -> float:
    k = KURVEN[typ]
    soc = min(max(soc, 0.0), 1.0)
    xs = [x for x, _ in k]
    i = bisect.bisect_left(xs, soc)
    if i == 0:
        return k[0][1]
    (x0, y0), (x1, y1) = k[i - 1], k[i]
    return y0 + (y1 - y0) * (soc - x0) / (x1 - x0)


class SimAkku:
    def __init__(self, typ="liion", zellen=1, mah=2500.0, innen_mohm=35.0, ladung=1.0):
        self.typ, self.zellen, self.mah = typ, zellen, mah
        self.innen = innen_mohm / 1000 * zellen
        self.rest_mah = mah * ladung

    def spannung(self, strom: float) -> float:
        return max(ruhespannung(self.typ, self.rest_mah / self.mah) * self.zellen - strom * self.innen, 0.0)


class SimNetzteil:
    """Ein Netzteil statt eines Akkus: Spannung sinkt mit dem Strom, über der
    Abschaltgrenze geht es aus, bis die Last weg ist. Wird mit der Zeit warm."""

    def __init__(self, nenn_v=5.0, innen_mohm=120.0, abschalt_a=3.0, tol_a=None, raum_c=22.0, heiz_c_je_w=4.0):
        self.nenn_v, self.innen = nenn_v, innen_mohm / 1000
        self.abschalt_a = abschalt_a
        self.knick_a = tol_a                 # ab hier sackt die Spannung stark ab
        self.raum, self.heiz = raum_c, heiz_c_je_w
        self.temperatur = raum_c
        self.aus = False
        self.rest_mah = 0.0                  # wie beim Akku - zählt hier nichts

    def spannung(self, strom: float) -> float:
        if strom > self.abschalt_a:
            self.aus = True
        if self.aus:
            if strom <= 0:
                self.aus = False             # Last weg: Netzteil fängt sich
            return 0.0
        u = self.nenn_v + 0.05 - strom * self.innen
        if self.knick_a and strom > self.knick_a:
            u -= (strom - self.knick_a) * 2.0
        return max(u, 0.0)

    def schritt(self, dt: float, strom: float) -> None:
        ziel = self.raum + self.spannung(strom) * strom * self.heiz
        self.temperatur += (ziel - self.temperatur) * min(1.0, dt / 300)


class SimDL24:
    """Das Gerät: Last, Zähler, Abschaltung - und die beiden Protokolle."""

    def __init__(self, akku: SimAkku, protokoll="px100", tempo=1.0, bericht_s=1.0):
        self.akku = akku
        # "px100": beides, "atorch": nur Berichte, "fremd": unbekannt,
        # "hid": USB-HID des DL24/P (antwortet nur auf Fragen, ganze 64-Byte-Pakete)
        self.protokoll = protokoll
        self.hid_adresse = p.HID_ADRESSE
        self.update_modus = False          # darf in keinem Test True werden
        self.tempo = tempo
        self.bericht_s = bericht_s
        self.an = False
        self.soll_a = 1.0
        self.abschalt_v = 0.0
        self.mah = 0.0
        self.wh = 0.0
        self.sek = 0.0
        self.simzeit = 0.0
        self.senden = None
        self._sperre = threading.RLock()
        self._laeuft = False

    # -- Physik --
    def strom(self) -> float:
        return self.soll_a if self.an else 0.0

    def schritt(self, dt: float) -> None:
        with self._sperre:
            self.simzeit += dt
            i = self.strom()
            if hasattr(self.akku, "schritt"):
                self.akku.schritt(dt, i)
            if i > 0:
                u = self.akku.spannung(i)
                if u <= self.abschalt_v or u <= 0.05:
                    self.an = False
                    return
                self.akku.rest_mah -= i * 1000 * dt / 3600
                self.mah += i * 1000 * dt / 3600
                self.wh += u * i * dt / 3600
                self.sek += dt

    def spannung(self) -> float:
        return self.akku.spannung(self.strom())

    # -- Bytes hinein --
    def empfangen(self, daten: bytes) -> None:
        # Befehle kommen als ganze 6-Byte-Stücke (PX100) oder 10 Byte (Atorch)
        with self._sperre:
            if self.protokoll == "hid":
                self._hid(daten)
                return
            i = 0
            while i < len(daten):
                if daten[i:i + 2] == b"\xb1\xb2" and len(daten) - i >= 6:
                    self._px(daten[i:i + 6])
                    i += 6
                elif daten[i:i + 3] == b"\xff\x55\x11" and len(daten) - i >= 10:
                    if daten[i + 4] == p.ATORCH_ALLES_NULL:
                        self.mah = self.wh = self.sek = 0.0
                    i += 10
                else:
                    i += 1

    def _px(self, b: bytes) -> None:
        if self.protokoll != "px100":
            return                         # versteht er nicht - schweigt
        befehl, d1, d2 = b[2], b[3], b[4]
        antwort: bytes
        if befehl == p.PX_EIN_AUS:
            self.an = bool(d1)
            antwort = bytes([p.PX_OK])
        elif befehl == p.PX_STROM_SETZEN:
            self.soll_a = d1 + d2 / 100
            antwort = bytes([p.PX_OK])
        elif befehl == p.PX_ABSCHALT_SETZEN:
            self.abschalt_v = d1 + d2 / 100
            antwort = bytes([p.PX_OK])
        elif befehl == p.PX_ZAEHLER_NULL:
            self.mah = self.wh = self.sek = 0.0
            antwort = bytes([p.PX_OK])
        elif befehl == p.PX_IST_AN:
            antwort = p.px_antwort_bauen(1 if self.an else 0)
        elif befehl == p.PX_SPANNUNG:
            antwort = p.px_antwort_bauen(round(self.spannung() * 1000))
        elif befehl == p.PX_STROM:
            antwort = p.px_antwort_bauen(round(self.strom() * 1000))
        elif befehl == p.PX_AH:
            antwort = p.px_antwort_bauen(round(self.mah))
        elif befehl == p.PX_WH:
            antwort = p.px_antwort_bauen(round(self.wh * 1000))
        elif befehl == p.PX_TEMPERATUR:
            antwort = p.px_antwort_bauen(round(25 + self.strom() * self.spannung() * 0.4))
        elif befehl == p.PX_ZEIT:
            h, r = divmod(int(self.sek), 3600)
            antwort = p.px_antwort_bauen((h << 16) | ((r // 60) << 8) | (r % 60))
        else:
            antwort = bytes([p.PX_FEHLER])
        senden = self.senden
        if senden:
            senden(antwort)

    def _hid(self, b: bytes) -> None:
        if len(b) != p.HID_LAENGE or b[0] != p.HID_HIN or b[1] != p.HID_FAMILIE:
            return
        befehl = p.hid_befehl_lesen(b)
        if befehl and befehl[0] == self.hid_adresse and befehl[1] in (
                p.HID_LAST, p.HID_SOLLWERT, p.HID_ABSCHALT, p.HID_ZAEHLER_NULL):
            import struct
            _, art, d = befehl
            if art == p.HID_LAST:
                self.an = d[0] == 1
            elif art == p.HID_SOLLWERT:
                self.soll_a = struct.unpack(">f", d)[0]
            elif art == p.HID_ABSCHALT:
                self.abschalt_v = struct.unpack(">f", d)[0]
            else:
                self.mah = self.wh = self.sek = 0.0
            return                         # keine Quittung - wie das echte Gerät
        if b[3] == p.HID_UPDATE_START:
            self.update_modus = True       # wie das echte Gerät: ab jetzt Bootloader
            self.an = False
            return
        if self.update_modus:
            return
        if b[3] == p.HID_MESSWERTE and b[2] == self.hid_adresse:
            u, i = self.spannung(), self.strom()
            antwort = p.hid_bauen(p.HidWerte(
                spannung=u, strom=-i, leistung=u * i, widerstand=u / i if i else 9999.991,
                energie_wh=self.wh, kapazitaet_mah=self.mah,
                temp_fuehler=getattr(self.akku, "temperatur", None) or -46.388,
                temp_cpu=28.0, temp_mos=25 + u * i * 0.4, luefter=0, an=self.an, firmware=""),
                self.hid_adresse)
        else:
            return
        senden = self.senden
        if senden:
            senden(antwort)

    def bericht(self) -> bytes:
        with self._sperre:
            return p.atorch_bauen(p.AtorchWerte(
                spannung=self.spannung(), strom=self.strom(), kapazitaet_mah=self.mah,
                energie_wh=self.wh, temperatur=25, laufzeit_s=int(self.sek)))

    # -- Uhr --
    def starten(self) -> None:
        self._laeuft = True
        threading.Thread(target=self._takt, name="simulator", daemon=True).start()

    def anhalten(self) -> None:
        self._laeuft = False

    def _takt(self) -> None:
        vorher = time.monotonic()
        naechster_bericht = vorher
        while self._laeuft:
            time.sleep(0.01)
            jetzt = time.monotonic()
            self.schritt((jetzt - vorher) * self.tempo)
            vorher = jetzt
            if jetzt >= naechster_bericht and self.protokoll != "hid":
                naechster_bericht = jetzt + self.bericht_s
                senden = self.senden          # kann beim Trennen gerade None werden
                if senden:
                    # "fremd": ein Gerät, dessen Format die App nicht kennt
                    paket = b"\xaa\x55\x01" + bytes(range(30)) if self.protokoll == "fremd" else self.bericht()
                    # wie über Bluetooth: in Stücken zu 20 Byte
                    for i in range(0, len(paket), 20):
                        senden(paket[i:i + 20])


class SimulatorVerbindung(Verbindung):
    # Klassenweit einstellbar - so kann der Test den Akku vorgeben, bevor die
    # App ihn über den normalen Weg (verbindung.oeffnen) aufmacht.
    voreinstellung: dict = {}

    def __init__(self, protokoll="px100", akku: SimAkku | None = None, tempo=None, bericht_s=None):
        super().__init__()
        v = dict(self.voreinstellung)
        self.geraet = SimDL24(akku or v.get("akku") or SimAkku(mah=2350, innen_mohm=42),
                              protokoll=v.get("protokoll", protokoll),
                              tempo=tempo or v.get("tempo", 60.0),
                              bericht_s=bericht_s or v.get("bericht_s", 1.0))
        self.pakete = self.geraet.protokoll == "hid"

    def uhr(self) -> float:
        return self.geraet.simzeit

    def oeffnen(self) -> None:
        self.geraet.senden = self._empfangen
        self.geraet.starten()

    def schreiben(self, daten: bytes) -> None:
        # Antwort kommt etwas verzögert, wie über die echte Leitung
        threading.Timer(0.005, self.geraet.empfangen, args=(daten,)).start()

    def schliessen(self) -> None:
        self.geraet.anhalten()
        self.geraet.senden = None
