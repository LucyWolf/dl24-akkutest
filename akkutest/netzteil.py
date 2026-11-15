"""Netzteile, Ladegeräte und USB-Hubs prüfen: hält das Gerät, was draufsteht?

Der DL24 zieht einen eingestellten Strom. Die App steigert ihn nach Plan und
schaut, was die Spannung macht:

  Stufentest   10 % … 100 % des Nennstroms, je Stufe einige Sekunden
  Dauertest    ein fester Anteil über längere Zeit, mit Temperatur (Fühler)
  Abschalttest über den Nennstrom hinaus, bis das Netzteil abschaltet
               oder die Spannung einbricht - höchstens bis zur eigenen Grenze

Geht nur, wenn die App die Last selbst stellen kann (USB oder PX100).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from .geraet import Geraet, Messwert

log = logging.getLogger("akkutest.netzteil")

DL24_MAX_W = 150.0
STROM_AUS = 0.005
EINSCHWINGEN_S = 2.0      # so lange nach jedem Stromwechsel nicht bewerten
ABSCHALT_SCHRITT = 0.05   # Abschalttest: +5 % des Nennstroms je Schritt
ABSCHALT_STUFE_S = 10.0
ZUSAMMENBRUCH = 0.5       # unter 50 % der Nennspannung gilt das Netzteil als aus

# Typenschild-Vorlagen: Name, Volt, Ampere
VORLAGEN = [
    ("USB 2.0 Port (5 V / 0,5 A)", 5.0, 0.5),
    ("USB 3.0 Port (5 V / 0,9 A)", 5.0, 0.9),
    ("USB-Ladegerät 5 V / 1 A", 5.0, 1.0),
    ("USB-Ladegerät 5 V / 2 A", 5.0, 2.0),
    ("USB-Ladegerät 5 V / 2,4 A", 5.0, 2.4),
    ("USB-C 5 V / 3 A", 5.0, 3.0),
    ("Netzteil 9 V / 2 A", 9.0, 2.0),
    ("Netzteil 12 V / 1 A", 12.0, 1.0),
    ("Netzteil 12 V / 2 A", 12.0, 2.0),
    ("Netzteil 12 V / 5 A", 12.0, 5.0),
    ("Netzteil 19 V / 3,42 A", 19.0, 3.42),
    ("Netzteil 24 V / 2,5 A", 24.0, 2.5),
]


@dataclass
class NetzteilEinstellung:
    name: str
    nenn_v: float
    nenn_a: float
    nenn_w: float = 0.0              # 0 = nicht angegeben
    toleranz_proz: float = 5.0
    stufentest: bool = True
    stufen: int = 10
    stufe_s: float = 30.0
    dauertest: bool = True
    dauer_proz: float = 100.0
    dauer_min: float = 10.0
    abschalttest: bool = False
    max_proz: float = 130.0
    temp_grenze: float = 70.0
    trigger: list = field(default_factory=list)   # [[V, A], …] bei Schnellladegeräten
    unbekannt: bool = False   # Strom unbekannt: Leistung ermitteln statt Angabe prüfen

    @property
    def strom_a(self) -> float:
        """Nennstrom - steht nur die Leistung drauf, daraus gerechnet."""
        if self.nenn_a > 0:
            return self.nenn_a
        return self.nenn_w / self.nenn_v if self.nenn_v > 0 else 0.0

    @property
    def untere_v(self) -> float:
        return self.nenn_v * (1 - self.toleranz_proz / 100)

    @property
    def obere_v(self) -> float:
        return self.nenn_v * (1 + self.toleranz_proz / 100)

    def hoechster_strom(self) -> float:
        a = self.strom_a
        if self.abschalttest:
            return a * self.max_proz / 100
        if self.dauertest:
            a = max(a * self.dauer_proz / 100, a if self.stufentest else 0)
        return a

    def pruefen(self) -> str | None:
        """Fehlertext oder None."""
        if self.nenn_v <= 0:
            return "Bitte die Nennspannung vom Typenschild eintragen."
        if self.strom_a <= 0:
            return "Bitte Nennstrom oder Nennleistung vom Typenschild eintragen."
        if not (self.stufentest or self.dauertest or self.abschalttest):
            return "Bitte mindestens einen Test auswählen."
        w = self.hoechster_strom() * self.nenn_v
        if w > DL24_MAX_W:
            return (f"Der Test bräuchte bis zu {w:.0f} W ({self.hoechster_strom():.2f} A × {self.nenn_v:g} V). "
                    f"Der DL24 schafft {DL24_MAX_W:.0f} W - Grenze oder Dauerstrom senken.")
        return None


SUCH_SCHRITT_A = 0.25
SUCH_STUFE_S = 10.0


def such_grenze(volt: float, usb: bool) -> float:
    """Bis wohin beim Ermitteln gesteigert wird: USB-C-Kabel tragen 5 A, der DL24 150 W."""
    return round(min(5.0 if usb else 10.0, DL24_MAX_W / volt * 0.98), 2)


def ermitteln(e: NetzteilEinstellung, usb: bool) -> NetzteilEinstellung:
    """Aus einer Einstellung ohne Stromangabe eine Suche machen: in kleinen
    Stufen hoch, bis es abschaltet oder einbricht."""
    grenze = such_grenze(e.nenn_v, usb)
    return NetzteilEinstellung(**{**e.__dict__, "nenn_a": grenze, "nenn_w": 0.0, "unbekannt": True,
                                  "stufentest": True, "stufen": max(2, round(grenze / SUCH_SCHRITT_A)),
                                  "stufe_s": SUCH_STUFE_S, "dauertest": False, "abschalttest": False})


@dataclass
class Schritt:
    art: str          # "stufe" | "dauer" | "abschalt"
    soll_a: float
    dauer_s: float


@dataclass
class StufenWert:
    soll_a: float
    spannung: float       # Mittel nach dem Einschwingen
    min_v: float
    strom: float
    ok: bool

    @property
    def leistung(self) -> float:
        return self.spannung * self.strom


@dataclass
class NetzteilErgebnis:
    leerlauf_v: float | None = None
    stufen: list[StufenWert] = field(default_factory=list)
    dauer: StufenWert | None = None
    dauer_s: float = 0.0
    abschalt_a: float | None = None      # hier ging es aus / brach ein
    abschalt_art: str = ""               # "abgeschaltet" | "eingebrochen" | ""
    max_getestet_a: float = 0.0
    temp_max: float | None = None
    temp_start: float | None = None
    grund: str = ""
    vollstaendig: bool = False
    haelt: bool | None = None            # hält es die Angabe? None = nicht entscheidbar
    hinweise: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        d = dict(self.__dict__)
        d["stufen"] = [s.__dict__ for s in self.stufen]
        d["dauer"] = self.dauer.__dict__ if self.dauer else None
        return d


def plan(e: NetzteilEinstellung) -> list[Schritt]:
    a = e.strom_a
    s: list[Schritt] = []
    if e.stufentest:
        n = max(1, e.stufen)
        s += [Schritt("stufe", round(a * k / n, 3), e.stufe_s) for k in range(1, n + 1)]
    if e.dauertest:
        s.append(Schritt("dauer", round(a * e.dauer_proz / 100, 3), e.dauer_min * 60))
    if e.abschalttest:
        k = 1.0 + ABSCHALT_SCHRITT
        while k <= e.max_proz / 100 + 1e-9:
            s.append(Schritt("abschalt", round(a * k, 3), ABSCHALT_STUFE_S))
            k += ABSCHALT_SCHRITT
    return s


@dataclass
class NetzteilAblauf:
    einstellung: NetzteilEinstellung
    geraet: Geraet
    bei_ereignis: Callable[[str, str], None] = lambda art, text: None
    zustand: str = "leerlauf"           # leerlauf → laeuft → fertig | abgebrochen
    ergebnis: NetzteilErgebnis = field(default_factory=NetzteilErgebnis)
    punkte: list[tuple] = field(default_factory=list)     # (s, V, A, °C oder None)
    start_wann: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.schritte = plan(self.einstellung)
        self.i = -1
        self._t0: float | None = None
        self._schritt_t0 = 0.0
        self._werte: list[Messwert] = []
        self._ll: list[float] = []
        self._aus = 0
        self._zu_wenig = 0
        self.steuerbar = bool(self.geraet and self.geraet.kann_steuern)

    @property
    def laeuft(self) -> bool:
        return self.zustand in ("leerlauf", "laeuft")

    @property
    def schritt(self) -> Schritt | None:
        return self.schritte[self.i] if 0 <= self.i < len(self.schritte) else None

    def beschreibung(self) -> str:
        s = self.schritt
        if self.zustand == "leerlauf":
            return "Leerlaufspannung messen"
        if not s:
            return ""
        text = {"stufe": "Stufentest", "dauer": "Dauertest", "abschalt": "Abschalttest"}[s.art]
        anteil = s.soll_a / self.einstellung.strom_a * 100
        return f"{text}: {s.soll_a:.2f} A ({anteil:.0f} %), Schritt {self.i + 1}/{len(self.schritte)}"

    def messwert(self, m: Messwert) -> None:
        try:
            if self.zustand == "leerlauf":
                self._leerlauf(m)
            elif self.zustand == "laeuft":
                self._laeuft(m)
        except Exception as ex:
            log.exception("Netzteiltest")
            self._last_aus()
            self._beenden(f"Fehler: {ex}", False, "abgebrochen")

    def abbrechen(self) -> None:
        if not self.laeuft:
            return
        self._last_aus()
        self._beenden("von Hand abgebrochen", False, "abgebrochen")

    # ------------------------------------------------------------------
    def _leerlauf(self, m: Messwert) -> None:
        e = self.einstellung
        if m.an or m.strom > STROM_AUS:
            self.geraet.last(False)
            self._ll.clear()
            return
        self._ll.append(m.spannung)
        if len(self._ll) < 3:
            return
        r = self.ergebnis
        r.leerlauf_v = round(sum(self._ll) / len(self._ll), 3)
        r.temp_start = m.temp_fuehler
        if r.leerlauf_v < e.nenn_v * ZUSAMMENBRUCH:
            self._beenden(f"Keine Spannung am Eingang ({r.leerlauf_v:.2f} V statt {e.nenn_v:g} V). "
                          "Ist das Netzteil eingesteckt und am DL24 angeschlossen?", False, "abgebrochen")
            return
        if r.leerlauf_v > e.nenn_v * 1.25:
            self._beenden(f"Die Spannung ({r.leerlauf_v:.2f} V) liegt weit über der Angabe ({e.nenn_v:g} V) - "
                          "falsches Gerät oder falsche Angabe?", False, "abgebrochen")
            return
        if r.leerlauf_v > e.obere_v:
            r.hinweise.append(f"Leerlaufspannung {r.leerlauf_v:.3f} V liegt über der Toleranz "
                              f"(bis {e.obere_v:.2f} V).")
        # Schutz im Gerät: bricht die Spannung zusammen, schaltet der DL24 selbst ab
        self.geraet.abschaltung_setzen(round(e.nenn_v * ZUSAMMENBRUCH, 2))
        self.geraet.zaehler_null()
        self._t0 = m.zeit
        self.zustand = "laeuft"
        self.bei_ereignis("info", f"Leerlauf {r.leerlauf_v:.3f} V – Test beginnt")
        self._naechster(m)

    def _naechster(self, m: Messwert) -> None:
        self.i += 1
        s = self.schritt
        if s is None:
            self._last_aus()
            self._fertig()
            return
        self._schritt_t0 = m.zeit
        self._werte = []
        self._aus = self._zu_wenig = 0
        self.geraet.strom_setzen(s.soll_a)
        self.geraet.last(True)
        self.ergebnis.max_getestet_a = max(self.ergebnis.max_getestet_a, s.soll_a)
        self.bei_ereignis("schritt", self.beschreibung())

    def _laeuft(self, m: Messwert) -> None:
        e, r, s = self.einstellung, self.ergebnis, self.schritt
        t = m.zeit - (self._t0 or m.zeit)
        r.dauer_s = t
        self.punkte.append((round(t, 1), m.spannung, m.strom, m.temp_fuehler))
        if m.temp_fuehler is not None:
            r.temp_max = m.temp_fuehler if r.temp_max is None else max(r.temp_max, m.temp_fuehler)
            if m.temp_fuehler >= e.temp_grenze:
                self._last_aus()
                r.hinweise.append(f"Temperaturgrenze {e.temp_grenze:g} °C erreicht.")
                self._werten_schritt()
                self._fertig(f"Abgebrochen: {m.temp_fuehler:.0f} °C am Fühler "
                             f"(Grenze {e.temp_grenze:g} °C)", haelt_moeglich=False)
                return
        im_schritt = m.zeit - self._schritt_t0
        if im_schritt < EINSCHWINGEN_S:
            return

        # Netzteil aus? Spannung weg oder Last vom Gerät abgeschaltet
        weg = m.spannung < e.nenn_v * ZUSAMMENBRUCH or (not m.an and m.strom <= STROM_AUS)
        self._aus = self._aus + 1 if weg else 0
        # Kommt der Strom nicht an, liefert das Netzteil ihn nicht
        zu_wenig = m.strom < s.soll_a * 0.9 - 0.01
        self._zu_wenig = self._zu_wenig + 1 if zu_wenig and not weg else 0
        if self._aus >= 2 or self._zu_wenig >= 3:
            self._last_aus()
            art = "abgeschaltet" if self._aus >= 2 else "eingebrochen"
            r.abschalt_a, r.abschalt_art = s.soll_a, art   # diese Stufe zählt nicht als geschafft
            text = (f"Netzteil hat bei {s.soll_a:.2f} A abgeschaltet" if art == "abgeschaltet"
                    else f"Netzteil liefert {s.soll_a:.2f} A nicht (nur {m.strom:.2f} A)")
            self._fertig(text)
            return
        if not (weg or zu_wenig):
            self._werte.append(m)
        if im_schritt >= s.dauer_s:
            self._werten_schritt()
            self._naechster(m)

    def _werten_schritt(self) -> None:
        s, e = self.schritt, self.einstellung
        if not s or not self._werte:
            return
        # nur die zweite Hälfte: dann hat sich die Spannung gesetzt
        w = self._werte[len(self._werte) // 2:]
        v = sum(x.spannung for x in w) / len(w)
        sw = StufenWert(s.soll_a, round(v, 3), round(min(x.spannung for x in w), 3),
                        round(sum(x.strom for x in w) / len(w), 3),
                        ok=min(x.spannung for x in w) >= e.untere_v)
        if s.art == "dauer":
            self.ergebnis.dauer = sw
        else:
            self.ergebnis.stufen.append(sw)

    def _fertig(self, grund: str = "", haelt_moeglich: bool = True) -> None:
        e, r = self.einstellung, self.ergebnis
        bis_nenn = [x for x in r.stufen if x.soll_a <= e.strom_a + 1e-6]
        nenn_erreicht = any(abs(x.soll_a - e.strom_a) < 1e-6 for x in r.stufen) or (
            r.dauer is not None and r.dauer.soll_a >= e.strom_a - 1e-6)
        haelt: bool | None = None
        if e.unbekannt:
            pass                             # nichts angegeben, nichts zu halten
        elif r.abschalt_a is not None and r.abschalt_a <= e.strom_a + 1e-6:
            haelt = False                    # vor dem Nennstrom ausgefallen
        elif any(not x.ok for x in bis_nenn) or (r.dauer is not None and not r.dauer.ok):
            haelt = False                    # Spannung unter der Toleranz
        elif nenn_erreicht and haelt_moeglich:
            haelt = True
        r.haelt = haelt
        if not grund and e.unbekannt:
            grund = f"Bis {r.max_getestet_a:.2f} A ohne Abschaltung - Grenze der Suche"
        if not grund:
            grund = "Alle Schritte durchlaufen"
            if e.abschalttest and r.abschalt_a is None:
                grund = (f"Bis {r.max_getestet_a:.2f} A ({r.max_getestet_a / e.strom_a * 100:.0f} %) "
                         "keine Abschaltung - Grenze erreicht")
        self._beenden(grund, haelt is not None or e.unbekannt)

    def _last_aus(self) -> None:
        try:
            self.geraet.last(False)
        except Exception:
            log.exception("Last aus")

    def _beenden(self, grund: str, vollstaendig: bool, zustand: str = "fertig") -> None:
        self.ergebnis.grund = grund
        self.ergebnis.vollstaendig = vollstaendig
        self.zustand = zustand
        log.info("Netzteiltest beendet: %s", grund)
        self.bei_ereignis("fertig", grund)



# ----------------------------------------------------------------------
# Schnellladegeräte (USB-PD / QC) über einen Trigger-Adapter
# ----------------------------------------------------------------------
TRIGGER_SPANNUNGEN = [5.0, 9.0, 12.0, 15.0, 20.0]
TRIGGER_TREFFER = 0.08        # ±8 % um die gewünschte Spannung gilt als "kommt an"
TRIGGER_WARTEN_S = 120.0      # so lange auf das Umschalten warten, dann "nicht unterstützt"


@dataclass
class TriggerErgebnis:
    teile: list[dict] = field(default_factory=list)    # je Spannung {"einstellung", "ergebnis"}
    nicht: list[dict] = field(default_factory=list)    # {"volt", "gemessen", "grund"}
    dauer_s: float = 0.0
    grund: str = ""
    vollstaendig: bool = False
    haelt: bool | None = None

    def als_dict(self) -> dict:
        return dict(self.__dict__)


def trigger_einstellung(basis: NetzteilEinstellung, volt: float, ampere: float) -> NetzteilEinstellung:
    e = NetzteilEinstellung(**{**basis.__dict__, "name": f"{basis.name} – {volt:g} V",
                               "nenn_v": volt, "nenn_a": ampere, "nenn_w": 0.0, "trigger": []})
    return ermitteln(e, usb=True) if ampere <= 0 else e


def bestleistung(r: dict) -> tuple[float, float] | None:
    """Höchste Leistung (W, A) einer Stufe, bei der die Spannung noch in der Toleranz lag."""
    ok = [s for s in r.get("stufen") or [] if s["ok"]]
    if not ok:
        return None
    s = max(ok, key=lambda s: s["spannung"] * s["strom"])
    return s["spannung"] * s["strom"], s["strom"]


class TriggerAblauf:
    """Prüft nacheinander jede gewählte Spannung. Umschalten muss der Mensch am
    Adapter - die App sagt, welche, und wartet, bis sie ankommt."""

    def __init__(self, basis: NetzteilEinstellung, stufen: list[tuple[float, float]], geraet: Geraet,
                 bei_ereignis: Callable[[str, str], None] = lambda a, t: None) -> None:
        self.basis = basis
        self.stufen = sorted(stufen)
        self.geraet = geraet
        self.bei_ereignis = bei_ereignis
        hoch = self.stufen[-1]
        self.einstellung = NetzteilEinstellung(**{**basis.__dict__, "nenn_v": hoch[0],
                                                  "nenn_a": hoch[1] or such_grenze(hoch[0], True),
                                                  "nenn_w": 0.0, "unbekannt": hoch[1] <= 0})
        self.einstellung.trigger = [list(s) for s in self.stufen]
        self.ergebnis = TriggerErgebnis()
        self.punkte: list[tuple] = []
        self.start_wann = time.time()
        self.zustand = "umschalten"
        self.steuerbar = bool(geraet and geraet.kann_steuern)
        self.i = -1
        self.teil: NetzteilAblauf | None = None
        self._t0: float | None = None
        self._warten_seit: float | None = None
        self._treffer = 0
        self._ueberspringen = False
        self._weiter()

    @property
    def laeuft(self) -> bool:
        return self.zustand in ("umschalten", "laeuft")

    @property
    def ziel(self) -> tuple[float, float] | None:
        return self.stufen[self.i] if 0 <= self.i < len(self.stufen) else None

    def einstellung_fuer(self, volt: float, ampere: float) -> NetzteilEinstellung:
        return trigger_einstellung(self.basis, volt, ampere)

    def _weiter(self) -> None:
        self.i += 1
        self.teil = None
        if self.ziel is None:
            self._fertig()
            return
        self.zustand = "umschalten"
        self._warten_seit = None
        self._treffer = 0
        self._ueberspringen = False
        try:
            self.geraet.last(False)
        except Exception:
            log.exception("Last aus")
        v = self.ziel[0]
        self.bei_ereignis("umschalten", f"Am Trigger-Adapter jetzt {v:g} V einstellen – "
                                        f"die Prüfung beginnt, sobald {v:g} V anliegen.")

    def ueberspringen(self) -> None:
        self._ueberspringen = True

    def messwert(self, m: Messwert) -> None:
        if not self.laeuft:
            return
        if self._t0 is None:
            self._t0 = m.zeit
        self.ergebnis.dauer_s = m.zeit - self._t0
        self.punkte.append((round(m.zeit - self._t0, 1), m.spannung, m.strom, m.temp_fuehler))
        try:
            if self.zustand == "umschalten":
                self._umschalten(m)
            elif self.teil is not None:
                self.teil.messwert(m)
        except Exception as ex:
            log.exception("Triggerprüfung")
            self.abbrechen(f"Fehler: {ex}")

    def _umschalten(self, m: Messwert) -> None:
        v, a = self.ziel
        if self._warten_seit is None:
            self._warten_seit = m.zeit
        if m.an or m.strom > STROM_AUS:
            self.geraet.last(False)
            return
        if abs(m.spannung - v) <= v * TRIGGER_TREFFER:
            self._treffer += 1
        else:
            self._treffer = 0
        if self._treffer >= 3:
            self.zustand = "laeuft"
            e = self.einstellung_fuer(v, a)
            self.teil = NetzteilAblauf(e, self.geraet, bei_ereignis=self._teil_ereignis)
            self.bei_ereignis("info", f"{v:g} V liegen an – Prüfung läuft")
            return
        if self._ueberspringen or m.zeit - self._warten_seit >= TRIGGER_WARTEN_S:
            grund = "übersprungen" if self._ueberspringen else "kam nicht"
            self.ergebnis.nicht.append({"volt": v, "gemessen": round(m.spannung, 2), "grund": grund})
            self.bei_ereignis("info", f"{v:g} V {grund} (gemessen {m.spannung:.2f} V)")
            self._weiter()

    def _teil_ereignis(self, art: str, text: str) -> None:
        v = self.ziel[0] if self.ziel else 0
        if art != "fertig":
            self.bei_ereignis(art, f"{v:g} V – {text}")
            return
        t = self.teil
        self.ergebnis.teile.append({"einstellung": dict(t.einstellung.__dict__), "ergebnis": t.ergebnis.als_dict()})
        if t.zustand == "abgebrochen" and t.ergebnis.leerlauf_v is not None:
            # von Hand oder Fehler: alles beenden
            self.zustand = "abgebrochen"
            self._fertig(t.ergebnis.grund, zustand="abgebrochen")
            return
        self._weiter()

    def abbrechen(self, grund: str = "von Hand abgebrochen") -> None:
        if not self.laeuft:
            return
        if self.teil is not None and self.teil.laeuft:
            self.teil.bei_ereignis = lambda a, t: None
            self.teil.abbrechen()
            self.ergebnis.teile.append({"einstellung": dict(self.teil.einstellung.__dict__),
                                        "ergebnis": self.teil.ergebnis.als_dict()})
        else:
            try:
                self.geraet.last(False)
            except Exception:
                log.exception("Last aus")
        self._fertig(grund, zustand="abgebrochen")

    def _fertig(self, grund: str = "", zustand: str = "fertig") -> None:
        r = self.ergebnis
        # Nur Spannungen mit Stromangabe haben etwas zu halten
        urteile = [t["ergebnis"]["haelt"] for t in r.teile if not t["einstellung"].get("unbekannt")]
        angegeben = [a for _, a in self.stufen if a > 0]
        if any(u is False for u in urteile):
            r.haelt = False
        elif any(n["grund"] == "kam nicht" for n in r.nicht) and zustand == "fertig":
            r.haelt = False                  # eine gewählte Spannung kommt gar nicht
        elif urteile and all(u is True for u in urteile) and len(urteile) == len(angegeben) and not r.nicht:
            r.haelt = True
        if not grund:
            da = [f"{t['einstellung']['nenn_v']:g} V" for t in r.teile]
            grund = "Geprüft: " + (", ".join(da) if da else "keine Spannung")
            if r.nicht:
                grund += "; nicht unterstützt: " + ", ".join(f"{n['volt']:g} V" for n in r.nicht)
        r.grund = grund
        r.vollstaendig = zustand == "fertig"
        self.zustand = zustand
        log.info("Triggerprüfung beendet: %s", grund)
        self.bei_ereignis("fertig", grund)
