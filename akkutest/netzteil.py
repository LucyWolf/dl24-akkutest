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
    ("USB 2.0 Port", 5.0, 0.5),
    ("USB 3.0 Port", 5.0, 0.9),
    ("USB-Hub 10 W", 5.0, 2.0),
    ("USB-Hub 15 W", 5.0, 3.0),
    ("USB-Hub 20 W", 5.0, 4.0),
    ("USB-Ladegerät 5 W", 5.0, 1.0),
    ("USB-Ladegerät 10 W", 5.0, 2.0),
    ("USB-Ladegerät 12 W", 5.0, 2.4),
    ("USB-C 15 W", 5.0, 3.0),
    ("Netzteil 9 V", 9.0, 2.0),
    ("Netzteil 12 V", 12.0, 1.0),
    ("Netzteil 12 V", 12.0, 2.0),
    ("Netzteil 12 V", 12.0, 5.0),
    ("Laptop-Netzteil 65 W", 19.0, 3.42),
    ("Netzteil 24 V", 24.0, 2.5),
]


def vorlage_text(name: str, v: float, a: float) -> str:
    """So steht es in der Liste: Name, Spannung, Strom und Leistung."""
    z = lambda x: f"{x:g}".replace(".", ",")
    return f"{name} – {z(v)} V / {z(a)} A ({z(round(v * a, 1))} W)"


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
    bis_ende: bool = False    # Abschalttest bis zum Abschalten (höchstens 5 A bei USB / 150 W)
    kabel_mohm: float = 0.0   # Kabel + Adapter: wird herausgerechnet (Spannung an der Buchse)

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

    @property
    def usb(self) -> bool:
        return self.nenn_v <= 5.5

    @property
    def mindest_v(self) -> float:
        """Darunter: nicht verwenden. USB: 4,4 V am Gerät; sonst die doppelte Toleranz."""
        return 4.4 if self.usb else self.nenn_v * (1 - 2 * self.toleranz_proz / 100)

    @property
    def hoechst_v(self) -> float:
        """Darüber im Leerlauf: gefährlich für angeschlossene Geräte."""
        return 5.5 if self.usb else self.nenn_v * (1 + 2 * self.toleranz_proz / 100)

    def such_ende_a(self) -> float:
        return max(such_grenze(self.nenn_v, self.usb), self.strom_a) if self.nenn_v > 0 else 0.0

    def hoechster_strom(self) -> float:
        a = self.strom_a
        if self.abschalttest and self.bis_ende:
            return self.such_ende_a()
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
            return (f"Der Test bräuchte bis zu {_k(w, 0)} W ({_k(self.hoechster_strom(), 2)} A × {self.nenn_v:g} V). "
                    f"Der DL24 schafft {_k(DL24_MAX_W, 0)} W - Grenze oder Dauerstrom senken.")
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
    buchse_v: float | None = None    # um das Kabel berichtigt (nur mit Kabelwert)

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
    marken: list = field(default_factory=list)       # [(Sekunde, "0,40 A"), …] - Stufenwechsel fürs Diagramm
    zu_heiss: bool = False
    widerstand_mohm: float | None = None   # Steigung der Kennlinie: Netzteil + Kabel
    urteil: str | None = None              # "gut" | "eingeschraenkt" | "nicht" | None
    gruende: list[str] = field(default_factory=list)
    verspricht: bool | None = None         # liefert den angegebenen Strom ohne abzuschalten?
    max_w_tol: float | None = None         # höchste Leistung mit Spannung in der Toleranz
    max_w: float | None = None             # höchste Leistung überhaupt (vor dem Abschalten)

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
        bis = e.such_ende_a() / a if e.bis_ende else e.max_proz / 100
        k = 1.0 + ABSCHALT_SCHRITT
        while k <= bis + 1e-9:
            s.append(Schritt("abschalt", round(a * k, 3), ABSCHALT_STUFE_S))
            k += ABSCHALT_SCHRITT
        if e.bis_ende and (not s or s[-1].soll_a < e.such_ende_a() - 1e-6):
            s.append(Schritt("abschalt", round(e.such_ende_a(), 3), ABSCHALT_STUFE_S))
    return s


def widerstand(stufen: list) -> float | None:
    """Ausgleichsgerade durch die Kennlinie: wie viel Volt pro Ampere verloren gehen."""
    p = [(s.strom, s.spannung) for s in stufen if s.strom > 0.01]
    if len(p) < 2:
        return None
    mx = sum(x for x, _ in p) / len(p)
    my = sum(y for _, y in p) / len(p)
    nenner = sum((x - mx) ** 2 for x, _ in p)
    if nenner < 1e-9:
        return None
    steigung = sum((x - mx) * (y - my) for x, y in p) / nenner
    return round(max(0.0, -steigung) * 1000, 0)


def _k(x: float, stellen: int | None = 2) -> str:
    """Zahl mit Komma - die Gründe stehen so im Ergebnis."""
    t = f"{x:g}" if stellen is None else f"{x:.{stellen}f}"
    return t.replace(".", ",")


def bewerten(e: NetzteilEinstellung, r: NetzteilErgebnis) -> None:
    """Klare Aussage: empfehlenswert, eingeschränkt oder nicht verwenden - und
    getrennt davon, ob es den versprochenen Strom liefert."""
    kabel = e.kabel_mohm / 1000
    an_buchse = lambda st, v: v + st.strom * kabel
    bis_nenn = [x for x in r.stufen if x.soll_a <= e.strom_a + 1e-6]
    if r.dauer:
        bis_nenn.append(r.dauer)
    r.widerstand_mohm = widerstand([x for x in r.stufen if x.soll_a <= e.strom_a + 1e-6] or r.stufen)
    in_tol = [x for x in r.stufen if an_buchse(x, x.min_v) >= e.untere_v]
    r.max_w_tol = round(max((x.spannung * x.strom for x in in_tol), default=0), 2) or None
    r.max_w = round(max((x.spannung * x.strom for x in r.stufen), default=0), 2) or None
    gruende: list[str] = []
    schlimm = False
    knapp = False
    if r.leerlauf_v is not None and r.leerlauf_v > e.hoechst_v:
        schlimm = True
        gruende.append(f"Zu hohe Spannung im Leerlauf ({_k(r.leerlauf_v)} V, höchstens {_k(e.hoechst_v)} V) – "
                       "kann angeschlossene Geräte beschädigen")
    if e.unbekannt:
        r.verspricht = None
    else:
        ausgefallen = r.abschalt_a is not None and r.abschalt_a <= e.strom_a + 1e-6
        nenn_da = any(x.soll_a >= e.strom_a - 1e-6 for x in bis_nenn)
        r.verspricht = False if ausgefallen else (True if nenn_da else None)
        if ausgefallen:
            schlimm = True
            gruende.append(f"Schaltet schon bei {_k(r.abschalt_a)} A ab – angegeben sind {_k(e.strom_a)} A")
        tiefst = min((an_buchse(x, x.min_v) for x in bis_nenn), default=None)
        if tiefst is not None:
            wo = "an der Buchse" if kabel else "am Kabelende"
            if tiefst < e.mindest_v:
                schlimm = True
                gruende.append(f"Spannung fällt bis zum Nennstrom auf {_k(tiefst)} V {wo} "
                               f"(Mindestwert {_k(e.mindest_v)} V)")
            elif tiefst < e.untere_v:
                knapp = True
                gruende.append(f"Spannung fällt bis zum Nennstrom auf {_k(tiefst)} V {wo} – unter der Toleranz "
                               f"({_k(e.untere_v)} V), aber über dem Mindestwert")
    if r.zu_heiss:
        schlimm = True
        gruende.append(f"Wird zu heiß (über {_k(e.temp_grenze, None)} °C)")
    if e.unbekannt and not schlimm:
        r.urteil = None
    elif schlimm:
        r.urteil = "nicht"
    elif knapp:
        r.urteil = "eingeschraenkt"
    elif r.verspricht:
        r.urteil = "gut"
    else:
        r.urteil = None
    if r.urteil == "gut":
        gruende.append("Liefert den angegebenen Strom, Spannung in der Toleranz")
    if r.widerstand_mohm and not kabel and r.widerstand_mohm > 150 and e.usb:
        gruende.append(f"Hoher Widerstand ({_k(r.widerstand_mohm, 0)} mΩ) – oft ist es das Kabel. Kabelwert "
                       "eintragen, dann wird es herausgerechnet")
    r.gruende = gruende


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
        return f"{text}: {_k(s.soll_a, 2)} A ({_k(anteil, 0)} %), Schritt {self.i + 1}/{len(self.schritte)}"

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
            self._beenden(f"Keine Spannung am Eingang ({_k(r.leerlauf_v, 2)} V statt {e.nenn_v:g} V). "
                          "Ist das Netzteil eingesteckt und am DL24 angeschlossen?", False, "abgebrochen")
            return
        if r.leerlauf_v > e.nenn_v * 1.25:
            self._beenden(f"Die Spannung ({_k(r.leerlauf_v, 2)} V) liegt weit über der Angabe ({e.nenn_v:g} V) - "
                          "falsches Gerät oder falsche Angabe?", False, "abgebrochen")
            return
        if r.leerlauf_v > e.obere_v:
            r.hinweise.append(f"Leerlaufspannung {_k(r.leerlauf_v, 3)} V liegt über der Toleranz "
                              f"(bis {_k(e.obere_v, 2)} V).")
        # Schutz im Gerät: bricht die Spannung zusammen, schaltet der DL24 selbst ab
        self.geraet.abschaltung_setzen(round(e.nenn_v * ZUSAMMENBRUCH, 2))
        self.geraet.zaehler_null()
        self._t0 = m.zeit
        self.zustand = "laeuft"
        self.bei_ereignis("info", f"Leerlauf {_k(r.leerlauf_v, 3)} V – Test beginnt")
        self._naechster(m)

    def _naechster(self, m: Messwert) -> None:
        self.i += 1
        s = self.schritt
        if s is None:
            self._last_aus()
            self._fertig()
            return
        self._schritt_t0 = m.zeit
        art = {"stufe": "", "dauer": "Dauer ", "abschalt": "↑ "}[s.art]
        self.ergebnis.marken.append((round(m.zeit - (self._t0 or m.zeit), 1),
                                     f"{art}{_k(s.soll_a, 2)} A".replace(".", ",")))
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
                r.zu_heiss = True
                self._werten_schritt()
                self._fertig(f"Abgebrochen: {_k(m.temp_fuehler, 0)} °C am Fühler "
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
            text = (f"Netzteil hat bei {_k(s.soll_a, 2)} A abgeschaltet" if art == "abgeschaltet"
                    else f"Netzteil liefert {_k(s.soll_a, 2)} A nicht (nur {_k(m.strom, 2)} A)")
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
        i = sum(x.strom for x in w) / len(w)
        tief = min(x.spannung for x in w)
        kabel = i * e.kabel_mohm / 1000            # was im Kabel verloren geht
        sw = StufenWert(s.soll_a, round(v, 3), round(tief, 3), round(i, 3),
                        ok=tief + kabel >= e.untere_v,
                        buchse_v=round(v + kabel, 3) if e.kabel_mohm else None)
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
        bewerten(e, r)
        if not grund and e.unbekannt:
            grund = f"Bis {_k(r.max_getestet_a, 2)} A ohne Abschaltung - Grenze der Suche"
        if not grund:
            grund = "Alle Schritte durchlaufen"
            if e.abschalttest and e.bis_ende and r.abschalt_a is None:
                grund = (f"Bis {_k(r.max_getestet_a, 2)} A keine Abschaltung - mehr lässt der Test nicht zu "
                         f"({'5 A bei USB' if e.usb else 'Grenze des DL24'})")
            elif e.abschalttest and r.abschalt_a is None:
                grund = (f"Bis {_k(r.max_getestet_a, 2)} A ({_k(r.max_getestet_a / e.strom_a * 100, 0)} %) "
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
    marken: list = field(default_factory=list)
    urteil: str | None = None
    verspricht: bool | None = None

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
                teil, v = self.teil, self.ziel[0]       # nach messwert() kann schon der nächste dran sein
                vorher = len(teil.ergebnis.marken)
                teil.messwert(m)
                for _, text in teil.ergebnis.marken[vorher:]:
                    self.ergebnis.marken.append((round(m.zeit - self._t0, 1), f"{v:g} V {text}"))
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
            self.bei_ereignis("info", f"{v:g} V {grund} (gemessen {_k(m.spannung, 2)} V)")
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
        # Gesamturteil: das schlechteste der einzelnen Spannungen
        rang = {"nicht": 3, "eingeschraenkt": 2, "gut": 1}
        einzeln = [t["ergebnis"].get("urteil") for t in r.teile if t["ergebnis"].get("urteil")]
        r.urteil = max(einzeln, key=rang.get) if einzeln else None
        r.verspricht = False if any(n["grund"] == "kam nicht" for n in r.nicht) or any(
            t["ergebnis"].get("verspricht") is False for t in r.teile) else (
            True if any(t["ergebnis"].get("verspricht") for t in r.teile) else None)
        self.zustand = zustand
        log.info("Triggerprüfung beendet: %s", grund)
        self.bei_ereignis("fertig", grund)
