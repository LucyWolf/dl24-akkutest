"""Ein Akkutest von Anfang bis Ende.

Läuft mit jedem Messwert einen Schritt weiter. Kann das Gerät ferngesteuert
werden (PX100), schaltet die App die Last selbst: erst Leerlaufspannung messen,
dann Zähler auf null, Abschaltspannung und Strom setzen, Last an. Kann es das
nicht, wartet sie, bis am Gerät gestartet wird, und misst ab dann mit.

Die Kapazität rechnet die App selbst aus Strom × Zeit. Der Zähler im Gerät
wird im Atorch-Bericht nur in 10-mAh-Schritten übertragen, die Energie sogar
nur in 10-Wh-Schritten - für eine 18650 nutzlos.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from . import akkus
from .geraet import Geraet, Messwert

log = logging.getLogger("akkutest.ablauf")

STROM_AUS = 0.005          # darunter gilt die Last als aus (A)


@dataclass
class Einstellung:
    typ: str
    zellen: int
    nenn_mah: int            # 0 = unbekannt
    strom_a: float
    abschalt_v: float


@dataclass
class Ergebnis:
    mah: float = 0.0
    wh: float = 0.0
    dauer_s: float = 0.0
    leerlauf_v: float | None = None
    ende_v: float | None = None          # letzte Spannung unter Last
    innen_mohm: float | None = None
    mah_geraet: float | None = None
    grund: str = ""
    vollstaendig: bool = False

    def prozent(self, nenn_mah: int) -> float | None:
        return self.mah / nenn_mah * 100 if nenn_mah > 0 else None


@dataclass
class Ablauf:
    einstellung: Einstellung
    geraet: Geraet | None
    bei_ereignis: Callable[[str, str], None] = lambda art, text: None
    zustand: str = "leerlauf"     # leerlauf → (warten) → laeuft → fertig | abgebrochen
    ergebnis: Ergebnis = field(default_factory=Ergebnis)
    punkte: list[tuple[float, float, float]] = field(default_factory=list)   # (s, V, A)
    start_wann: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._ll_werte: list[float] = []
        self._vorher: Messwert | None = None
        self._t0: float | None = None
        self._mah_rechnung = 0.0
        self._zaehler_vorher: float | None = None
        self._zaehler_start: float | None = None
        self._unter: int = 0
        self._aus: int = 0
        self._min_v: float | None = None
        self._ir_gemessen = False
        self._warnung_gegeben = False
        self.steuerbar = bool(self.geraet and self.geraet.kann_steuern)
        typ = akkus.TYPEN[self.einstellung.typ]
        self.grenze_tief = typ.min_abschalt_v * self.einstellung.zellen

    # ------------------------------------------------------------------
    @property
    def laeuft(self) -> bool:
        return self.zustand in ("leerlauf", "warten", "laeuft")

    @property
    def sekunden(self) -> float:
        return self.ergebnis.dauer_s

    def messwert(self, m: Messwert) -> None:
        if self._t0 is None and m.mah_geraet is not None:
            self._zaehler_vorher = m.mah_geraet      # Stand kurz vor dem Start
        try:
            getattr(self, f"_{self.zustand}", lambda m: None)(m)
        except Exception as e:                     # nie still sterben
            log.exception("Ablauf")
            self._beenden(f"Fehler: {e}", vollstaendig=False, zustand="abgebrochen")

    def abbrechen(self) -> None:
        if not self.laeuft:
            return
        self._last_aus()
        self._beenden("von Hand abgebrochen", vollstaendig=False, zustand="abgebrochen")

    # ------------------------------------------------------------------
    def _leerlauf(self, m: Messwert) -> None:
        if self.steuerbar:
            if m.an or m.strom > STROM_AUS:
                self.geraet.last(False)
                self._ll_werte.clear()
                return
            self._ll_werte.append(m.spannung)
            if len(self._ll_werte) < 2:
                return
            self.ergebnis.leerlauf_v = round(sum(self._ll_werte) / len(self._ll_werte), 3)
            e = self.einstellung
            if self.ergebnis.leerlauf_v <= e.abschalt_v:
                self._beenden("Der Akku ist schon leer (Spannung unter der Abschaltgrenze). Erst laden.",
                              vollstaendig=False, zustand="abgebrochen")
                return
            self.geraet.zaehler_null()
            ok = self.geraet.abschaltung_setzen(e.abschalt_v) & self.geraet.strom_setzen(e.strom_a)
            if not ok:
                self.bei_ereignis("warnung", "Das Gerät hat eine Einstellung nicht bestätigt - bitte am Display prüfen.")
            self.geraet.last(True)
            self.zustand = "laeuft"
            self.bei_ereignis("info", f"Leerlauf {self.ergebnis.leerlauf_v:.3f} V – Last eingeschaltet "
                                      f"({e.strom_a:.2f} A, Ende bei {e.abschalt_v:.2f} V)")
        else:
            if self.geraet:
                self.geraet.zaehler_null()
            self.zustand = "warten"
            self.bei_ereignis("info", f"Am Gerät einstellen: Strom {self.einstellung.strom_a:.2f} A, "
                                      f"Abschaltspannung {self.einstellung.abschalt_v:.2f} V – dann dort starten.")
            self._warten(m)

    def _warten(self, m: Messwert) -> None:
        if m.strom <= STROM_AUS:
            self.ergebnis.leerlauf_v = m.spannung       # letzter Wert vor dem Start
            return
        self.zustand = "laeuft"
        self.bei_ereignis("info", "Last läuft – Messung gestartet.")
        self._laeuft(m)

    def _laeuft(self, m: Messwert) -> None:
        e, erg = self.einstellung, self.ergebnis
        if self._t0 is None:
            if m.strom <= STROM_AUS:
                return                   # Befehl unterwegs, Last noch nicht an
            self._t0 = m.zeit
            self._zaehler_start = self._zaehler_vorher
            self.start_wann = time.time()
        v = self._vorher
        if v is not None:
            dt = m.zeit - v.zeit
            # Auch über Lücken (Bluetooth-Aussetzer) weiterzählen: bei konstantem
            # Strom stimmt die Fläche trotzdem, Auslassen würde mAh verschlucken
            if dt > 0:
                self._mah_rechnung += (v.strom + m.strom) / 2 * dt / 3.6
                erg.wh += (v.leistung + m.leistung) / 2 * dt / 3600
        self._vorher = m
        erg.dauer_s = m.zeit - self._t0
        erg.mah_geraet = m.mah_geraet
        # Maßgeblich ist der Zähler im Gerät: er zählt im Gerät selbst und hängt
        # nicht davon ab, wann Messwerte ankommen (Bluetooth-Aussetzer, langsamer
        # Rechner). Die eigene Rechnung nur, wenn das Gerät keinen Zähler meldet.
        if m.mah_geraet is not None:
            start = self._zaehler_start or 0.0
            if m.mah_geraet < start:              # Gerät hat beim Start selbst genullt
                start = self._zaehler_start = 0.0
            erg.mah = m.mah_geraet - start
        else:
            erg.mah = self._mah_rechnung

        belastet = m.strom > STROM_AUS
        if belastet:
            self.punkte.append((round(erg.dauer_s, 1), m.spannung, m.strom))
            erg.ende_v = m.spannung
            self._min_v = m.spannung if self._min_v is None else min(self._min_v, m.spannung)
            # Innenwiderstand: Spannungsabfall gegenüber dem Leerlauf, nach 2 s,
            # wenn sich die Spannung gesetzt hat
            if not self._ir_gemessen and erg.dauer_s >= 2 and erg.leerlauf_v:
                self._ir_gemessen = True
                abfall = erg.leerlauf_v - m.spannung
                # Der Atorch-Bericht hat nur 0,1 V Auflösung - kleinere Abfälle sind Rauschen
                mindest = 0.005 if self.steuerbar else 0.25
                if abfall >= mindest and m.strom > 0.05:
                    erg.innen_mohm = round(abfall / m.strom * 1000, 1)

        # 1) Tiefentladung: sofort raus
        if belastet and m.spannung < self.grenze_tief:
            if self.steuerbar:
                self._last_aus()
                self._beenden("Notabschaltung: Spannung unter der Schutzgrenze", vollstaendig=True)
                return
            if not self._warnung_gegeben:
                self.bei_ereignis("warnung", "ACHTUNG: Spannung zu tief – Last am Gerät sofort ausschalten!")
                self._warnung_gegeben = True

        # 2) Abschaltspannung erreicht
        if belastet and m.spannung <= e.abschalt_v:
            self._unter += 1
            if self._unter >= 3:
                if self.steuerbar:
                    self._last_aus()
                    self._beenden("Abschaltspannung erreicht", vollstaendig=True)
                    return
                if not self._warnung_gegeben:
                    self.bei_ereignis("warnung", "Abschaltspannung erreicht – Last am Gerät ausschalten!")
                    self._warnung_gegeben = True
        else:
            self._unter = 0

        # 3) Last ist aus (Gerät hat selbst abgeschaltet, oder am Gerät gestoppt)
        if not belastet:
            self._aus += 1
            if self._aus >= 3:
                # Am Ende fällt die Spannung steil: der letzte Wert vor dem Abschalten
                # kann je nach Strom und Takt ein gutes Stück über der Grenze liegen
                fast_leer = self._min_v is not None and self._min_v <= e.abschalt_v * 1.06
                # Haben wir die Abschaltspannung selbst ans Gerät gegeben und es hat
                # von sich aus aufgehört, war es genau diese Grenze - auch wenn der
                # letzte Messwert vor dem steilen Abfall noch höher lag
                if self.steuerbar and self._min_v is not None and self._min_v <= e.abschalt_v * 1.25:
                    fast_leer = True
                self._beenden("Gerät hat bei der Abschaltspannung beendet" if fast_leer
                              else "Last wurde vorzeitig ausgeschaltet", vollstaendig=fast_leer)
        else:
            self._aus = 0

    # ------------------------------------------------------------------
    def _last_aus(self) -> None:
        if self.steuerbar:
            try:
                self.geraet.last(False)
            except Exception:
                log.exception("Last aus")

    def _beenden(self, grund: str, vollstaendig: bool, zustand: str = "fertig") -> None:
        self.ergebnis.grund = grund
        self.ergebnis.vollstaendig = vollstaendig
        self.zustand = zustand
        log.info("Test beendet: %s, %.0f mAh", grund, self.ergebnis.mah)
        self.bei_ereignis("fertig", grund)
