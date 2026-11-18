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
# Dauertest "bis stabil": frühestens nach STABIL_MIN_S, wenn die Temperatur sich in den
# letzten STABIL_FENSTER_S um weniger als STABIL_K geändert hat
STABIL_MIN_S = 600.0
STABIL_FENSTER_S = 300.0
STABIL_K = 0.5
STABIL_MAX_S = 2 * 3600.0   # "bis stabil" verlängert den Dauertest höchstens bis hierhin

# Powerbanks
PB_WARTEN_S = 90.0        # so lange auf Spannung warten (Knopf an der Powerbank drücken)
PB_KAP_MAX_S = 48 * 3600  # Kapazitätstest endet spätestens nach 48 h
# Neu kommt am Ausgang etwa 82 % der Zellenergie an (Wandlerverlust) - so rechnet Anker die
# "Rated capacity" auf dem Aufdruck (service.anker.com: "Why Is the Rated Capacity ... Lower").
PB_WIRKUNG = 0.82
PB_ERWARTUNG = 0.8        # für die Restzeit-Schätzung: so viel der Aufdruck-Energie kommt meist an
# Akkuzustand (gemessen gegen neu) - Einschätzung der App, keine Vorgabe. Wie bei Handy-Akkus
# gilt ab etwa 80 % als verbraucht.
PB_ZUSTAND_GRUEN = 80.0
PB_ZUSTAND_GELB = 60.0
PB_AUTOAUS_S = 180.0      # geht sie im Kapazitätstest früher aus, war es vielleicht die Abschaltautomatik
PB_VORLAGEN = [
    # bekannte Modelle: Daten vom Hersteller (Aufdruck am Gerät geht vor)
    ("INIU MegaPower 20000 (B5), USB-C", 5.0, 3.0, {"mah": 20000, "zell_v": 3.7, "wh": 74.0,
                                                   "trigger": [[5.0, True, 3.0], [9.0, True, 2.22],
                                                               [12.0, True, 1.5], [15.0, False, 0.0],
                                                               [20.0, False, 0.0]]}),
    ("Anker 325 PowerCore 20K (A1268), USB-A", 5.0, 2.4, {"mah": 20000, "zell_v": 3.7, "wh": 0.0}),
    ("Powerbank 5 W", 5.0, 1.0),
    ("Powerbank 10 W", 5.0, 2.0),
    ("Powerbank 12 W", 5.0, 2.4),
    ("Powerbank 15 W", 5.0, 3.0),
]

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
    # Step-Down-Modul, Datenblatt "CKCS PD65W Fast Charging Module" (TZT): 5V3A, 9V3A, 12V3A, 20V3.25A,
    # "etc." - 15 V nicht ausdrücklich; gemessen (17.11.2026) bis 3,75 A in der Toleranz, eingetragen
    # sind 3 A (mehr erlaubt ein USB-C-Kabel ohne E-Marker nicht). PPS 3,3-21 V, Ripple < 200 mV.
    ("TZT/CKCS PD65W Step-Down-Modul (Eingang 8–30 V)", 20.0, 3.25,
     {"trigger": [[5.0, True, 3.0], [9.0, True, 3.0], [12.0, True, 3.0], [15.0, True, 3.0],
                  [20.0, True, 3.25], [28.0, False, 0.0]],
      "hinweis": "Step-Down-Modul: Der Eingang muss über der gewünschten Spannung liegen – für 20 V also "
                 "mehr als 20 V (laut Datenblatt; Eingang höchstens 30 V)."}),
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
    temp_grenze: float = 50.0
    trigger: list = field(default_factory=list)   # [[V, A], …] bei Schnellladegeräten
    unbekannt: bool = False   # Strom unbekannt: Leistung ermitteln statt Angabe prüfen
    bis_ende: bool = False    # Abschalttest bis zum Abschalten (höchstens 5 A bei USB / 150 W)
    kabel_mohm: float = 0.0   # Kabel + Adapter: nur zur Angabe und Kabelbewertung, nicht herausgerechnet
    kabel_name: str = ""      # welches Kabel / welcher Adapter - steht im Bericht
    kabel_wann: float = 0.0   # wann der Kabelwert gemessen wurde (0 = von Hand eingetragen)
    kabel_typ: str = ""       # Schlüssel aus KABEL_TYPEN - für die Kabelbewertung
    fuehler: bool = True      # Temperaturfühler des DL24 auswerten (aus: Temperatur ignorieren)
    hub: bool = False         # USB-Hub: geprüft wird nur ein Port
    pd: bool = False          # höhere Spannung über USB-PD/QC: Grenzen nach USB-PD (vSrcNew/vSrcValid)
    powerbank: bool = False   # Powerbank: Last nie unter mindest_a, kein Leerlauf
    mah: float = 0.0          # Aufdruck: Kapazität der Zellen in mAh
    zell_v: float = 3.7       # ... bezogen auf diese Zellspannung
    wh: float = 0.0           # Aufdruck in Wh, falls angegeben (sonst aus mAh gerechnet)
    mindest_a: float = 0.3    # darunter schalten sich viele Powerbanks von selbst ab
    kapazitaet: bool = False  # bis leer entladen und Energie messen
    kap_a: float = 1.0
    nenn_mah_aus: float = 0.0  # "Rated capacity" vom Aufdruck: was neu am Ausgang (5 V) herauskommt
    kabel_raus: bool = False   # vom Nutzer gewählt: Kabel herausrechnen, bewertet wird an der Buchse
    bis_stabil: bool = False   # Dauertest endet, wenn die Temperatur sich nicht mehr ändert (EIA-364-70)

    @property
    def neu_wh(self) -> tuple[float, bool]:
        """Was die Powerbank neu am Ausgang liefern sollte - und ob das nur geschätzt ist."""
        if self.nenn_mah_aus > 0:
            return self.nenn_mah_aus * self.nenn_v / 1000, False
        if self.aufdruck_wh > 0:
            return self.aufdruck_wh * PB_WIRKUNG, True
        return 0.0, True

    @property
    def aufdruck_wh(self) -> float:
        return self.wh if self.wh > 0 else self.mah * self.zell_v / 1000

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
        if self.usb:
            return 4.4
        if self.pd:     # USB-PD vSrcValid: höchstens 0,5 V außerhalb von ±5 %
            return self.untere_v - PD_VALID_V
        return self.nenn_v * (1 - 2 * self.toleranz_proz / 100)

    @property
    def hoechst_v(self) -> float:
        """Darüber im Leerlauf: gefährlich für angeschlossene Geräte."""
        if self.usb:
            return 5.5
        if self.pd:
            return self.obere_v + PD_VALID_V
        return self.nenn_v * (1 + 2 * self.toleranz_proz / 100)

    def grenzen(self) -> tuple[float, float, float, float]:
        """Ampel für die Spannung: (rot unter, gelb unter, gelb über, rot über).
        Zwischen den beiden mittleren ist grün. USB nach der Spezifikation, sonst
        einfache und doppelte Toleranz um die Angabe."""
        if self.usb:
            return USB_SCHWACH_V, USB_MIN_V, USB_MAX_V, GEFAHR_V
        return self.mindest_v, self.untere_v, self.obere_v, self.hoechst_v

    def such_ende_a(self) -> float:
        return max(such_grenze(self.nenn_v, self.usb), self.strom_a) if self.nenn_v > 0 else 0.0

    def hoechster_strom(self) -> float:
        a = self.strom_a
        if self.powerbank and self.kapazitaet:
            a = max(a if (self.stufentest or self.dauertest) else 0, self.kap_a)
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
        if not (self.stufentest or self.dauertest or self.abschalttest or (self.powerbank and self.kapazitaet)):
            return "Bitte mindestens einen Test auswählen."
        if self.powerbank and self.strom_a < self.mindest_a:
            return "Der Nennstrom liegt unter dem Mindeststrom - Mindeststrom senken."
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


def duennen(punkte: list, hoechstens: int = 1500) -> list:
    """Kurve für die Ablage: lange Prüfungen auf höchstens so viele Punkte."""
    if len(punkte) <= hoechstens:
        return [list(p) for p in punkte]
    schritt = len(punkte) / hoechstens
    aus = [list(punkte[int(i * schritt)]) for i in range(hoechstens)]
    aus[-1] = list(punkte[-1])
    return aus


# Kabel: erlaubter Widerstand Hin + Rück, Stecker eingerechnet.
# USB-C (Type-C Cable and Connector Specification §4.4.1): höchstens 500 mV auf VBUS und
# 250 mV auf GND bei vollem Nennstrom -> 750 mV / 3 A = 250 mΩ, / 5 A = 150 mΩ.
# USB 2.0 (§7.2.2): je 125 mV auf VBUS und GND bei 500 mA -> 250 mV / 0,5 A = 500 mΩ.
# Gelb bis zum Doppelten ist eine Einteilung dieser App.
KABEL_TYPEN = {
    "usbc3": ("USB-C (3 A)", 250.0, 3.0, 0.75),
    "usbc5": ("USB-C (5 A, E-Marker)", 150.0, 5.0, 0.75),
    "usb2": ("USB-A / Micro-USB (USB 2.0)", 500.0, 0.5, 0.25),
}


def kabel_bewerten(mohm: float, typ: str) -> tuple[str, str] | None:
    """(Ampel, Satz) für ein Kabel - oder None, wenn Typ oder Wert fehlt."""
    if typ not in KABEL_TYPEN or mohm <= 0:
        return None
    name, grenze, nenn_a, budget_v = KABEL_TYPEN[typ]
    bis_a = budget_v / (mohm / 1000)
    # mehr als der Typ hergibt, ist nie erlaubt - auch wenn der Widerstand es zuließe
    taugt = (f"Taugt für die vollen {_k(nenn_a, None)} A" if bis_a >= nenn_a
             else f"Taugt für bis zu {_k(bis_a, 1)} A")
    if mohm <= grenze:
        return "gruen", f"In Ordnung: {_k(mohm, 0)} mΩ, erlaubt sind {_k(grenze, 0)} mΩ ({name}). {taugt}."
    if mohm <= 2 * grenze:
        return "gelb", (f"Schwach: {_k(mohm, 0)} mΩ, erlaubt sind {_k(grenze, 0)} mΩ ({name}). {taugt} – "
                        f"für die vollen {_k(nenn_a, None)} A zu dünn.")
    return "rot", (f"Schrott: {_k(mohm, 0)} mΩ, mehr als doppelt so viel wie erlaubt ({_k(grenze, 0)} mΩ, {name}). "
                   f"{taugt} – nicht zum Laden oder Prüfen verwenden.")


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
    max_v: float | None = None       # höchster Wert in der Stufe - zusammen mit min_v die Schwankung

    @property
    def leistung(self) -> float:
        return self.spannung * self.strom

    @property
    def schwankung(self) -> float:
        return (self.max_v - self.min_v) if self.max_v is not None else 0.0


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
    laien: list[str] = field(default_factory=list)   # dasselbe in einfachen Sätzen, für den Bericht
    spez_verletzt: bool = False            # USB: Spannung nachweislich außerhalb der Spezifikation
    schwankung_mv: float | None = None     # größte Schwankung einer Stufe bis zum Nennstrom
    kabel_unplausibel: bool = False        # Kabelwert größer als der ganze Widerstand - falsch gemessen
    kabel_kreis: bool = False              # Kabelwert erklärt alles - womöglich mit diesem Netzteil gemessen
    spitze_v: float | None = None          # höchste Spannung der ganzen Prüfung (Leerlauf, Lastwechsel)
    unter_ab_a: float | None = None        # ab diesem Strom unter der gelben Grenze (USB 4,75 V)
    rot_ab_a: float | None = None          # ab diesem Strom unter der roten Grenze (USB 4,40 V)
    energie_wh: float = 0.0                # Powerbank: insgesamt abgegeben (am DL24 gemessen)
    ladung_mah: float = 0.0                # ... als Ladung bei der Ausgangsspannung
    kap_s: float = 0.0                     # Dauer des Kapazitätstests
    kap_leer: bool = False                 # bis zum Abschalten entladen
    kap_anteil: float | None = None        # % der Aufdruck-Energie
    kap_mah_zelle: float | None = None     # abgegebene Energie umgerechnet auf die Zellspannung
    autoaus: bool = False                  # womöglich die Abschaltautomatik statt leer
    temp_stabil: bool = False              # Dauertest endete, weil die Temperatur stabil war
    zustand_proz: float | None = None      # Akkuzustand: gemessen gegen neu
    zustand_geschaetzt: bool = False       # ohne "Rated capacity" aus der Zellenergie geschätzt
    kap_min_v: float | None = None         # tiefste Spannung beim Entladen (ohne die letzte Minute)

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
        if e.powerbank:
            # nie unter den Mindeststrom - sonst schaltet sich die Powerbank ab
            lo = min(e.mindest_a, a)
            s += [Schritt("stufe", round(lo + (a - lo) * (k - 1) / max(1, n - 1), 3), e.stufe_s)
                  for k in range(1, n + 1)]
        else:
            s += [Schritt("stufe", round(a * k / n, 3), e.stufe_s) for k in range(1, n + 1)]
    if e.dauertest:
        s.append(Schritt("dauer", round(max(a * e.dauer_proz / 100, e.mindest_a if e.powerbank else 0), 3),
                         e.dauer_min * 60))
    if e.abschalttest:
        bis = e.such_ende_a() / a if e.bis_ende else e.max_proz / 100
        k = 1.0 + ABSCHALT_SCHRITT
        while k <= bis + 1e-9:
            s.append(Schritt("abschalt", round(a * k, 3), ABSCHALT_STUFE_S))
            k += ABSCHALT_SCHRITT
        if e.bis_ende and (not s or s[-1].soll_a < e.such_ende_a() - 1e-6):
            s.append(Schritt("abschalt", round(e.such_ende_a(), 3), ABSCHALT_STUFE_S))
    if e.powerbank and e.kapazitaet:
        # zum Schluss bis leer - schaltet sie vorher bei Überlast ab, geht es nach dem Knopfdruck weiter
        s.append(Schritt("kapazitaet", round(max(e.kap_a, e.mindest_a), 3), PB_KAP_MAX_S))
    return s


def kap_schaetzung_s(e: NetzteilEinstellung) -> float:
    """Wie lange der Kapazitätstest etwa dauert - aus dem Aufdruck geschätzt."""
    if not (e.powerbank and e.kapazitaet):
        return 0.0
    w = max(e.kap_a, e.mindest_a) * e.nenn_v
    wh = e.aufdruck_wh * PB_ERWARTUNG if e.aufdruck_wh > 0 else 10.0
    return wh / w * 3600 if w > 0 else 0.0


def geplant_s(e: NetzteilEinstellung) -> float:
    """Geplante Dauer - der Kapazitätstest mit seiner Schätzung statt der Höchstdauer."""
    return sum(x.dauer_s for x in plan(e) if x.art != "kapazitaet") + kap_schaetzung_s(e)


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


# USB-Spezifikation 2.0, Abschnitt 7.2.2 (als Norm: IEC/EN 62680-2-1): Spannung an
# einem Port mit eigener Stromversorgung 4,75–5,25 V; 4,40 V nur für Schwachstrom-Ports.
# Keine gesetzliche Vorgabe - eine Spezifikation der Industrie.
USB_MIN_V = 4.75
USB_MAX_V = 5.25
USB_SCHWACH_V = 4.40
GEFAHR_V = 5.5
PD_VALID_V = 0.5      # USB-PD §7.1.8, Tabelle "Source Electrical Parameters": vSrcValid ±0,5 V
SPEZ_PD = "USB-PD-Spezifikation §7.1.8 (±5 %, kurzzeitig höchstens 0,5 V mehr)"
SPEZ = "USB-Spezifikation (USB 2.0, auch als EN 62680-2-1 veröffentlicht)"


SCHWANK_GELB = 0.01     # 1 % der Nennspannung (5 V: 50 mV) - Einschätzung der App,
SCHWANK_ROT = 0.03      # 3 % (5 V: 150 mV) - keine Vorgabe der USB-Spezifikation


def ampel(e: NetzteilEinstellung, volt: float) -> str:
    rot_u, gelb_u, gelb_o, rot_o = e.grenzen()
    if volt < rot_u - 1e-9 or volt > rot_o + 1e-9:
        return "rot"
    if volt < gelb_u - 1e-9 or volt > gelb_o + 1e-9:
        return "gelb"
    return "gruen"


def schwank_ampel(e: NetzteilEinstellung, delta: float) -> str:
    anteil = delta / e.nenn_v if e.nenn_v else 0
    return "rot" if anteil > SCHWANK_ROT else "gelb" if anteil > SCHWANK_GELB else "gruen"


def bewerten(e: NetzteilEinstellung, r: NetzteilErgebnis) -> None:
    """Klare Aussage: empfehlenswert, eingeschränkt, nicht verwenden - oder
    offen, wenn das Kabel nicht herausgerechnet ist. Getrennt davon: liefert
    es den versprochenen Strom?"""
    # Standard: nichts herausrechnen - bewertet wird, was am Kabelende beim Gerät ankommt.
    # Nur wenn ausdrücklich gewählt, gilt die Spannung an der Buchse (gemessen + Strom × Kabel).
    kabel = e.kabel_mohm / 1000 if e.kabel_raus else 0.0
    an_buchse = lambda st, v: v + st.strom * kabel
    bis_nenn = [x for x in r.stufen if x.soll_a <= e.strom_a + 1e-6]
    if r.dauer:
        bis_nenn.append(r.dauer)
    r.widerstand_mohm = widerstand([x for x in r.stufen if x.soll_a <= e.strom_a + 1e-6] or r.stufen)
    # Ist der Kabelwert so groß wie der ganze gemessene Widerstand, wurde er nicht an einem
    # guten Ladegerät bestimmt - dann würde er dem Gerät seinen eigenen Verlust gutschreiben
    r.kabel_unplausibel = bool(kabel and r.widerstand_mohm is not None
                               and e.kabel_mohm > r.widerstand_mohm * 1.05 + 10)
    if r.kabel_unplausibel:
        kabel = 0.0
    untere = USB_MIN_V if e.usb else e.untere_v
    in_tol = [x for x in r.stufen if an_buchse(x, x.min_v) >= untere]
    r.max_w_tol = round(max((x.spannung * x.strom for x in in_tol), default=0), 2) or None
    r.max_w = round(max((x.spannung * x.strom for x in r.stufen), default=0), 2) or None
    gruende: list[str] = []
    r.kabel_kreis = bool(kabel and not r.kabel_unplausibel and r.widerstand_mohm is not None
                         and e.kabel_mohm >= 0.9 * r.widerstand_mohm - 5)
    if r.kabel_kreis:
        gruende.append(f"Kabelwert {_k(e.kabel_mohm, 0)} mΩ erklärt fast den ganzen gemessenen Widerstand "
                       f"({_k(r.widerstand_mohm, 0)} mΩ) – entweder ist das Gerät selbst sehr gut, oder das Kabel "
                       "wurde mit genau diesem Gerät gemessen (dann im Kreis gerechnet)")
    if r.kabel_unplausibel:
        gruende.append(f"Kabelwert {_k(e.kabel_mohm, 0)} mΩ ist größer als der gesamte gemessene Widerstand "
                       f"({_k(r.widerstand_mohm, 0)} mΩ) – nicht herausgerechnet")
    schlimm = knapp = offen = False
    r.spez_verletzt = False
    rot_u, gelb_u, _, _ = e.grenzen()
    nach_strom = sorted(r.stufen, key=lambda x: x.soll_a)
    r.unter_ab_a = next((x.soll_a for x in nach_strom if an_buchse(x, x.min_v) < gelb_u), None)
    r.rot_ab_a = next((x.soll_a for x in nach_strom if an_buchse(x, x.min_v) < rot_u), None)
    if r.unter_ab_a is not None:
        wo = "an der Buchse" if kabel else "am Kabelende"
        gruende.append(f"Unter {_k(gelb_u)} V {wo} ab {_k(r.unter_ab_a)} A"
                       + (f", unter {_k(rot_u)} V ab {_k(r.rot_ab_a)} A" if r.rot_ab_a is not None else ""))
    # Überspannung: der höchste Wert der ganzen Prüfung - Leerlauf und Spitzen beim Lastwechsel
    hoch = max(x for x in (r.leerlauf_v, r.spitze_v) if x is not None) if (r.leerlauf_v or r.spitze_v) else None
    _, _, gelb_o, rot_o = e.grenzen()
    if hoch is not None and hoch > rot_o:
        schlimm = True
        r.spez_verletzt = r.spez_verletzt or e.usb or e.pd
        gruende.append(f"Überspannung: bis {_k(hoch)} V gemessen – über {_k(rot_o)} V"
                       + (f" (USB-Vorgabe höchstens {_k(USB_MAX_V)} V, {SPEZ} §7.2.2)" if e.usb else
                          f" ({SPEZ_PD})" if e.pd else "")
                       + ", kann angeschlossene Geräte beschädigen")
    elif hoch is not None and hoch > gelb_o and not (e.pd and (r.leerlauf_v or 0) <= gelb_o):
        # USB-PD erlaubt beim Lastwechsel kurz bis 0,5 V mehr - dort zählt nur der Leerlauf
        knapp = True
        r.spez_verletzt = r.spez_verletzt or e.usb or e.pd
        gruende.append(f"Überspannung: bis {_k(hoch)} V gemessen – über {_k(gelb_o)} V"
                       + (f" ({SPEZ} §7.2.2)" if e.usb else f" ({SPEZ_PD})" if e.pd else ""))
    tiefst = None
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
        if tiefst is not None and e.usb:
            if tiefst >= USB_MIN_V:
                pass
            elif tiefst < USB_SCHWACH_V:
                schlimm = r.spez_verletzt = True
                gruende.append(f"{'An der Buchse' if kabel else 'Am Kabelende'} {_k(tiefst)} V bei Nennstrom – unter {_k(USB_MIN_V)} V und sogar "
                               f"unter {_k(USB_SCHWACH_V)} V ({SPEZ} §7.2.2)")
            else:
                knapp = r.spez_verletzt = True
                gruende.append(f"{'An der Buchse' if kabel else 'Am Kabelende'} {_k(tiefst)} V bei Nennstrom – unter {_k(USB_MIN_V)} V "
                               f"({SPEZ} §7.2.2)")
        elif tiefst is not None:
            wo = "an der Buchse" if kabel else "am Kabelende"
            quelle = f" – {SPEZ_PD}" if e.pd else ""
            if tiefst < e.mindest_v:
                schlimm = True
                r.spez_verletzt = r.spez_verletzt or e.pd
                gruende.append(f"Spannung fällt bis zum Nennstrom auf {_k(tiefst)} V {wo} "
                               f"(Mindestwert {_k(e.mindest_v)} V{quelle})")
            elif tiefst < e.untere_v:
                knapp = True
                r.spez_verletzt = r.spez_verletzt or e.pd
                gruende.append(f"Spannung fällt bis zum Nennstrom auf {_k(tiefst)} V {wo} – unter der Toleranz "
                               f"({_k(e.untere_v)} V{quelle})")
    mess_tief = min((x.min_v for x in bis_nenn), default=None)
    grenze_u = USB_MIN_V if e.usb else e.untere_v
    if kabel and tiefst is not None and tiefst >= grenze_u and mess_tief is not None and mess_tief < grenze_u:
        gruende.append(f"Am Kabelende nur {_k(mess_tief)} V – unter {_k(grenze_u)} V; bewertet ist die "
                       "Ausgangsbuchse (Kabel herausgerechnet)")
    if not kabel and e.kabel_mohm and tiefst is not None and tiefst < (USB_MIN_V if e.usb else e.untere_v):
        gruende.append(f"Davon entfallen bei {_k(e.strom_a)} A etwa {_k(e.strom_a * e.kabel_mohm, 0)} mV auf das "
                       f"Kabel ({_k(e.kabel_mohm, 0)} mΩ) – ein besseres Kabel hebt die Spannung entsprechend")
    if r.zu_heiss:
        schlimm = True
        gruende.append(f"Wird zu heiß (über {_k(e.temp_grenze, None)} °C)")
    unruhig = max(bis_nenn, key=lambda x: x.schwankung, default=None)
    r.schwankung_mv = round(unruhig.schwankung * 1000) if unruhig and unruhig.max_v is not None else None
    if unruhig and schwank_ampel(e, unruhig.schwankung) == "rot":
        knapp = True
        gruende.append(f"Spannung schwankt bei {_k(unruhig.soll_a)} A um {_k(unruhig.schwankung * 1000, 0)} mV "
                       f"(über {_k(SCHWANK_ROT * 100, 0)} % – Einschätzung der App)")
    pb_gut = False
    if e.powerbank:
        r.kap_anteil = r.kap_mah_zelle = None
        if r.energie_wh > 0 and e.zell_v > 0:
            r.kap_mah_zelle = round(r.energie_wh / e.zell_v * 1000)
        r.zustand_proz, r.zustand_geschaetzt = None, False
        if e.kapazitaet and r.kap_leer and e.aufdruck_wh > 0:
            r.kap_anteil = round(r.energie_wh / e.aufdruck_wh * 100, 1)
        neu, geschaetzt = e.neu_wh
        if e.kapazitaet and r.kap_leer and neu > 0:
            r.zustand_proz = round(r.energie_wh / neu * 100)
            r.zustand_geschaetzt = geschaetzt
            z = kap_ampel(r.zustand_proz)
            text = (f"Akkuzustand etwa {_k(r.zustand_proz, 0)} %: {_k(r.energie_wh, 1)} Wh gemessen, neu "
                    f"{'etwa ' if geschaetzt else ''}{_k(neu, 1)} Wh am Ausgang"
                    + (f" ({_k(PB_WIRKUNG * 100, 0)} % von {_k(e.aufdruck_wh, 1)} Wh laut Aufdruck – geschätzt)"
                       if geschaetzt else f" (laut Aufdruck {_k(e.nenn_mah_aus, 0)} mAh bei {_k(e.nenn_v, None)} V)"))
            if z == "rot":
                schlimm = True
                r.verspricht = False
                gruende.append(text + f" – stark abgenutzt oder Angabe falsch (unter {_k(PB_ZUSTAND_GELB, 0)} %, "
                                      "Einschätzung der App)")
            elif z == "gelb":
                knapp = True
                gruende.append(text + f" – gealtert (unter {_k(PB_ZUSTAND_GRUEN, 0)} %, Einschätzung der App)")
            else:
                pb_gut = True
                gruende.append(text + " – gut")
        # Hält sie die Spannung beim Entladen? Die letzte Minute vor dem Abschalten zählt nicht
        if e.kapazitaet and r.kap_min_v is not None:
            rot_u, gelb_u, _, _ = e.grenzen()
            r.kap_min_v = round(r.kap_min_v, 3)
            if r.kap_min_v + max(e.kap_a, e.mindest_a) * kabel < rot_u:
                schlimm = True
                gruende.append(f"Beim Entladen fiel die Spannung auf {_k(r.kap_min_v)} V – unter {_k(rot_u)} V")
            elif r.kap_min_v + max(e.kap_a, e.mindest_a) * kabel < gelb_u:
                knapp = True
                gruende.append(f"Beim Entladen fiel die Spannung auf {_k(r.kap_min_v)} V – unter {_k(gelb_u)} V")
        if e.kapazitaet and r.autoaus:
            gruende.append(f"Nach nur {dauer_kurz(r.kap_s)} aus – leer oder Abschaltautomatik?")
    if schlimm:
        r.urteil = "nicht"
    elif knapp:
        r.urteil = "eingeschraenkt"
    elif offen:
        r.urteil = "offen"
    elif (r.verspricht or (pb_gut and r.verspricht is None)) and not e.unbekannt:
        r.urteil = "gut"
    else:
        r.urteil = None
    if r.urteil == "gut" and r.verspricht:
        gruende.append("Liefert den angegebenen Strom, Spannung im vorgegebenen Bereich")
    if e.usb and r.urteil in ("gut", "eingeschraenkt", "nicht", "offen"):
        gruende.append("Grenzwerte für einen Port mit eigener Stromversorgung (High-power-Port)")
    r.gruende = gruende
    r.laien = laien_saetze(e, r, tiefst) + pb_saetze(e, r)


def kap_ampel(zustand: float) -> str:
    """Ampel für den Akkuzustand in % (gemessen gegen neu)."""
    return "gruen" if zustand >= PB_ZUSTAND_GRUEN else "gelb" if zustand >= PB_ZUSTAND_GELB else "rot"


def dauer_kurz(s: float) -> str:
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def pb_saetze(e: NetzteilEinstellung, r: NetzteilErgebnis) -> list[str]:
    """Powerbank in einfachen Sätzen: wie viel steckt wirklich drin?"""
    s: list[str] = []
    if not (e.powerbank and e.kapazitaet):
        return s
    if not r.kap_leer:
        if r.energie_wh > 0:
            s.append(f"Bis zum Abbruch gab die Powerbank {_k(r.energie_wh, 1)} Wattstunden ab. Sie war noch nicht "
                     "leer – die Kapazität ist daher nicht vollständig gemessen.")
        return s
    zelle = f"{_k(r.kap_mah_zelle, 0)} mAh" if r.kap_mah_zelle else "–"
    if r.zustand_proz is not None:
        neu, geschaetzt = e.neu_wh
        auf = f"{_k(e.mah, 0)} mAh" if e.mah else f"{_k(e.aufdruck_wh, 1)} Wh"
        s.append(f"Herausgekommen sind {_k(r.energie_wh, 1)} Wattstunden (umgerechnet {zelle} bei "
                 f"{_k(e.zell_v, 1)} V; auf der Powerbank stehen {auf}).")
        s.append(f"Neu sollte sie am Ausgang {'etwa ' if geschaetzt else ''}{_k(neu, 1)} Wattstunden liefern. "
                 f"Sie kann also noch etwa {_k(r.zustand_proz, 0)} % von dem, was sie neu konnte "
                 f"(Akkuzustand).")
        if geschaetzt:
            s.append(f"Der Neuwert ist geschätzt: Beim Umwandeln der Akkuspannung auf 5 Volt gehen auch bei neuen "
                     f"Powerbanks rund {_k(100 - PB_WIRKUNG * 100, 0)} % verloren. Steht auf dem Aufdruck eine "
                     "„Rated Capacity“ (z. B. 12000 mAh bei 5 V), wird es genauer.")
        z = kap_ampel(r.zustand_proz)
        if z == "gruen":
            s.append("Das ist gut – die Powerbank ist kaum oder gar nicht abgenutzt.")
        elif z == "gelb":
            s.append("Die Powerbank ist gealtert: Sie hält spürbar weniger als neu, ist aber noch brauchbar.")
        elif r.zustand_proz >= 40:
            s.append("Die Powerbank ist stark abgenutzt und sollte ersetzt werden.")
        else:
            s.append("Das ist viel zu wenig – entweder ist der Akku kaputt, oder die Angabe auf der Powerbank "
                     "stimmt nicht (typisch für gefälschte oder sehr billige Powerbanks).")
    else:
        s.append(f"Die Powerbank gab {_k(r.energie_wh, 1)} Wattstunden ab ({_k(r.ladung_mah, 0)} mAh bei "
                 f"{_k(e.nenn_v, None)} V, umgerechnet {zelle} bei {_k(e.zell_v, 1)} V). Ohne Angabe auf der "
                 "Powerbank lässt sich nicht vergleichen.")
    if r.kap_min_v is not None:
        rot_u, gelb_u, _, _ = e.grenzen()
        zu = max(e.kap_a, e.mindest_a) * e.kabel_mohm / 1000 if e.kabel_raus else 0.0
        if r.kap_min_v + zu >= gelb_u:
            s.append(f"Die Spannung blieb beim Entladen bis kurz vor leer im erlaubten Bereich (tiefster Wert "
                     f"{_k(r.kap_min_v + zu)} Volt{' an der Buchse' if zu else ''}).")
        else:
            s.append(f"Beim Entladen fiel die Spannung schon vor dem Ende auf {_k(r.kap_min_v)} Volt – unter "
                     f"{_k(gelb_u)} Volt. Angeschlossene Geräte laden dann langsamer oder brechen ab.")
    handy = r.energie_wh / 15 if r.energie_wh else 0
    if handy >= 0.5:
        s.append(f"Zum Vergleich: Ein Handy-Akku hat etwa 15 Wattstunden – das reicht also für etwa "
                 f"{_k(handy, 1)} Ladungen (grob geschätzt).")
    if r.autoaus:
        s.append(f"Achtung: Die Powerbank ging schon nach {dauer_kurz(r.kap_s)} aus. War sie nicht voll "
                 "geladen, ist das Ergebnis zu niedrig. Manche Powerbanks schalten sich auch von selbst ab – "
                 "dann den Strom für den Kapazitätstest erhöhen.")
    return s


def laien_saetze(e: NetzteilEinstellung, r: NetzteilErgebnis, tiefst: float | None) -> list[str]:
    """Für Leute ohne Fachwissen: was heißt das Ergebnis im Alltag?"""
    art = "das Gerät"
    versprochen_w = e.nenn_v * e.strom_a
    kabel = bool(e.kabel_raus and e.kabel_mohm) and not r.kabel_unplausibel
    s: list[str] = []
    if e.unbekannt:
        if r.max_w_tol:
            s.append(f"Auf dem Gerät steht nicht, wie viel es kann. Gemessen: Es liefert bis "
                     f"{_k(r.max_w_tol, 1)} Watt, ohne dass die Spannung zu stark absinkt.")
        else:
            s.append("Auf dem Gerät steht nicht, wie viel es kann. Schon bei kleiner Last sinkt die Spannung "
                     "zu stark ab.")
    elif r.verspricht is True:
        s.append(f"Versprochen sind {_k(e.strom_a)} Ampere ({_k(versprochen_w, 1)} Watt). Diese Leistung "
                 f"liefert {art}, ohne abzuschalten.")
    elif r.verspricht is False and r.abschalt_a is not None:
        s.append(f"Versprochen sind {_k(e.strom_a)} Ampere ({_k(versprochen_w, 1)} Watt). Das Gerät "
                 f"schaltet aber schon bei {_k(r.abschalt_a)} Ampere ab – es schafft also nicht, was draufsteht.")
    if tiefst is not None and e.usb:
        mess = min((x.min_v for x in r.stufen if x.soll_a <= e.strom_a + 1e-6), default=None)
        if tiefst >= USB_MIN_V and kabel and mess is not None and mess < USB_MIN_V:
            # das Gerät hält die Vorgabe - nur mit diesem Kabel kommt zu wenig an
            s.append(f"Das Gerät selbst hält die Vorgabe der {SPEZ}: an seiner Ausgangsbuchse mindestens "
                     f"{_k(tiefst)} Volt (verlangt {_k(USB_MIN_V)} Volt).")
            s.append(f"Am Ende des Kabels kamen aber nur {_k(mess)} Volt an – mit diesem Kabel bekommt ein "
                     "angeschlossenes Gerät weniger, als die Vorgabe verlangt. Ein kürzeres oder dickeres Kabel "
                     "behebt das.")
        elif tiefst >= USB_MIN_V:
            s.append(f"Die Spannung bleibt dabei im Bereich, den die {SPEZ} vorgibt: mindestens "
                     f"{_k(USB_MIN_V)} Volt ({'an der Buchse' if kabel else 'gemessen'}: {_k(tiefst)} Volt). Angeschlossene Geräte werden "
                     "zuverlässig versorgt.")
        else:
            s.append(f"Unter Last {'liegen an der Buchse (Kabel herausgerechnet)' if kabel else 'kommen am Ende des Kabels'} nur {_k(tiefst)} Volt an. Die {SPEZ} verlangt mindestens "
                     f"{_k(USB_MIN_V)} Volt. Das Gerät entspricht damit nicht den Vorgaben für die Spannung.")
            if tiefst < USB_SCHWACH_V:
                s.append("Angeschlossene Geräte können sich deshalb abschalten, abstürzen oder laden nicht "
                         "richtig.")
            else:
                s.append("Zum Laden von Handys reicht das meist; empfindliche Geräte (z. B. Raspberry Pi, externe "
                         "Festplatten) können damit Probleme machen.")
    elif tiefst is not None:
        if tiefst < e.mindest_v:
            s.append(f"Unter Last sinkt die Spannung auf {_k(tiefst)} Volt – deutlich unter den angegebenen "
                     f"{_k(e.nenn_v, None)} Volt. Angeschlossene Geräte können ausfallen.")
        elif tiefst < e.untere_v:
            s.append(f"Unter Last sinkt die Spannung auf {_k(tiefst)} Volt – etwas mehr als üblich "
                     f"(mindestens {_k(e.untere_v)} Volt).")
        else:
            s.append(f"Die Spannung bleibt dabei im erwarteten Bereich (mindestens {_k(tiefst)} Volt).")
    if r.kabel_unplausibel:
        s.append(f"Der eingetragene Kabelwert ({_k(e.kabel_mohm, 0)} mΩ) ist größer als der gesamte gemessene "
                 "Widerstand. Er wurde wahrscheinlich nicht an einem guten Ladegerät gemessen, sondern an diesem "
                 "Gerät – dann würde er dessen eigene Schwäche dem Kabel zuschreiben. Er wurde deshalb nicht "
                 "herausgerechnet.")
    if r.kabel_kreis:
        s.append("Hinweis: Fast der ganze Spannungsverlust entfällt auf das Kabel – das Gerät selbst verliert "
                 "kaum etwas. Das spricht für ein gutes Gerät. Nur falls das Kabel mit genau diesem Gerät gemessen "
                 "wurde, wäre das im Kreis gerechnet; dann das Kabel an einem anderen Ladegerät messen.")
    if r.unter_ab_a is not None and not e.unbekannt:
        rot_u, gelb_u, _, _ = e.grenzen()
        ueber = " – also schon unterhalb der Angabe" if r.unter_ab_a < e.strom_a - 1e-6 else (
            " – erst über der Angabe" if r.unter_ab_a > e.strom_a + 1e-6 else "")
        if True:
            s.append(f"Ab {_k(r.unter_ab_a)} Ampere fiel die Spannung unter {_k(gelb_u)} Volt – der Mindestwert "
                     f"wurde unterschritten{ueber}. Ab dieser Last kann das Gerät keine stabile Spannung mehr "
                     "halten.")
            if r.rot_ab_a is not None:
                s.append(f"Ab {_k(r.rot_ab_a)} Ampere lag sie sogar unter {_k(rot_u)} Volt. Spätestens ab hier "
                         "ist das Gerät für diese Last nicht geeignet.")
        else:
            s.append(f"Am Ende des Kabels fiel die Spannung ab {_k(r.unter_ab_a)} Ampere unter {_k(gelb_u)} Volt"
                     f"{ueber}. Ob das am Gerät oder am Kabel liegt, ist ohne Kabelwert noch offen.")
    hoch = max(x for x in (r.leerlauf_v, r.spitze_v) if x is not None) if (r.leerlauf_v or r.spitze_v) else None
    _, _, gelb_o, rot_o = e.grenzen()
    if hoch is not None and hoch > gelb_o:
        wann = "ohne angeschlossenes Gerät" if r.leerlauf_v and hoch <= r.leerlauf_v + 0.005 else \
            "zeitweise (z. B. wenn die Last wegfällt)"
        vorgabe = f"die {SPEZ} erlaubt höchstens {_k(USB_MAX_V)} Volt" if e.usb else \
            f"angegeben sind {_k(e.nenn_v, None)} Volt"
        s.append(f"Überspannung: Es lieferte {wann} bis zu {_k(hoch)} Volt; {vorgabe}."
                 + (" So viel kann angeschlossene Geräte beschädigen." if hoch > rot_o else ""))
    if r.schwankung_mv is not None and schwank_ampel(e, r.schwankung_mv / 1000) == "rot":
        s.append(f"Die Spannung ist unruhig: Sie schwankt bei gleicher Last um {_k(r.schwankung_mv, 0)} "
                 "Millivolt. Ein gutes Netzteil hält sie deutlich ruhiger.")
    if e.hub:
        s.append(f"Geprüft wurde ein einzelner Port des Hubs. Die Angabe von {_k(e.nenn_v * e.strom_a, None)} Watt "
                 "gilt meist für alle Ports zusammen – mit einem DL24 lässt sich nur ein Port gleichzeitig belasten. "
                 "Andere Ports können sich anders verhalten.")
    if r.zu_heiss:
        s.append(f"Es wird zu heiß (über {_k(e.temp_grenze, None)} °C). Die Prüfung wurde deshalb abgebrochen.")
    if r.abschalt_a is not None and r.verspricht is not False:
        s.append(f"Bei Überlast ({_k(r.abschalt_a)} Ampere) schaltet es sich ab – das ist gut, so schützt es "
                 "sich selbst.")
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
        self._pb_seit: float | None = None
        self._kap_ab = 0
        self._letzt: Messwert | None = None
        self.steuerbar = bool(self.geraet and self.geraet.kann_steuern)

    @property
    def laeuft(self) -> bool:
        return self.zustand in ("leerlauf", "laeuft", "wieder_an")

    @property
    def schritt(self) -> Schritt | None:
        return self.schritte[self.i] if 0 <= self.i < len(self.schritte) else None

    def beschreibung(self) -> str:
        s = self.schritt
        if self.zustand == "leerlauf":
            return ("Powerbank einschalten (Knopf drücken) – warte auf Spannung" if self.einstellung.powerbank
                    else "Leerlaufspannung messen")
        if not s:
            return ""
        if self.zustand == "laeuft" and s.art == "kapazitaet":
            r = self.ergebnis
            return (f"Kapazitätstest: {_k(s.soll_a, 2)} A bis leer · bisher {_k(r.energie_wh, 2)} Wh "
                    f"({_k(r.ladung_mah, 0)} mAh)")
        text = {"stufe": "Stufentest", "dauer": "Dauertest", "abschalt": "Abschalttest"}[s.art]
        anteil = s.soll_a / self.einstellung.strom_a * 100
        return f"{text}: {_k(s.soll_a, 2)} A ({_k(anteil, 0)} %), Schritt {self.i + 1}/{len(self.schritte)}"

    def restzeit(self, jetzt: float) -> tuple[float, float] | None:
        """(noch in diesem Schritt, noch insgesamt) in Sekunden."""
        s = self.schritt
        if self.zustand != "laeuft" or s is None:
            return None
        if s.art == "kapazitaet":
            # aus dem Aufdruck geschätzt: was noch fehlt bis zur üblichen Ausbeute
            e = self.einstellung
            rest_wh = max(0.0, e.aufdruck_wh * PB_ERWARTUNG - self.ergebnis.energie_wh) if e.aufdruck_wh else 0
            im = rest_wh / max(0.1, s.soll_a * e.nenn_v) * 3600
            return im, im
        im = max(0.0, s.dauer_s - (jetzt - self._schritt_t0))
        rest = sum(x.dauer_s if x.art != "kapazitaet" else kap_schaetzung_s(self.einstellung)
                   for x in self.schritte[self.i + 1:])
        return im, im + rest

    def messwert(self, m: Messwert) -> None:
        try:
            if self.zustand == "leerlauf":
                self._leerlauf(m)
            elif self.zustand == "wieder_an":
                self._wieder_an(m)
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
    def _pb_start(self, m: Messwert) -> None:
        """Powerbank: kein Leerlauf - sie schaltet sich ohne Last ab. Gleich mit dem
        Mindeststrom belasten und warten, bis Spannung kommt."""
        e, r = self.einstellung, self.ergebnis
        if self._pb_seit is None:
            self._pb_seit = m.zeit
            self.geraet.abschaltung_setzen(round(e.nenn_v * ZUSAMMENBRUCH, 2))
            self.geraet.strom_setzen(e.mindest_a)
            self.geraet.last(True)
            self.bei_ereignis("info", "Powerbank einschalten (Knopf drücken) – warte auf Spannung …")
            return
        da = m.spannung >= e.nenn_v * ZUSAMMENBRUCH
        if not da:
            self._ll.clear()
            if m.zeit - self._pb_seit > PB_WARTEN_S:
                self._last_aus()
                self._beenden(f"Keine Spannung von der Powerbank ({_k(m.spannung, 2)} V). Ist sie eingeschaltet "
                              "und geladen, und steckt das Kabel am DL24?", False, "abgebrochen")
            return
        if not m.an:
            self.geraet.last(True)          # Spannung kam erst jetzt - Last wieder an
            return
        if m.strom < e.mindest_a * 0.8:
            return
        self._ll.append(m.spannung)
        if len(self._ll) < 3:
            return
        r.leerlauf_v = round(sum(self._ll) / len(self._ll), 3)
        r.spitze_v = max(self._ll)
        r.temp_start = m.temp_fuehler if e.fuehler else None
        if r.leerlauf_v > e.nenn_v * 1.25:
            self._last_aus()
            self._beenden(f"Die Spannung ({_k(r.leerlauf_v, 2)} V) liegt weit über der Angabe ({e.nenn_v:g} V) - "
                          "falsches Gerät oder falsche Angabe?", False, "abgebrochen")
            return
        self.geraet.zaehler_null()
        self._t0 = m.zeit
        self._letzt = m
        self.zustand = "laeuft"
        self.bei_ereignis("info", f"Powerbank liefert {_k(r.leerlauf_v, 3)} V bei {_k(e.mindest_a, 2)} A – "
                                  "Test beginnt")
        self._naechster(m)

    def _wieder_an(self, m: Messwert) -> None:
        """Nach einer Überlast: warten, bis die Powerbank wieder Spannung liefert."""
        e = self.einstellung
        if m.spannung < e.nenn_v * ZUSAMMENBRUCH:
            self._ll.clear()
            if m.zeit - self._pb_seit > 600:
                self._last_aus()
                self._fertig("Nach der Überlast nicht wieder eingeschaltet - Kapazitätstest entfällt")
            return
        if not m.an:
            self.geraet.last(True)
            return
        self._ll.append(m.spannung)
        if len(self._ll) < 3:
            return
        self.geraet.abschaltung_setzen(round(e.nenn_v * ZUSAMMENBRUCH, 2))
        self._letzt = m
        self.zustand = "laeuft"
        self.bei_ereignis("info", "Powerbank liefert wieder – Kapazitätstest beginnt")
        self._naechster(m)

    def _leerlauf(self, m: Messwert) -> None:
        e = self.einstellung
        if e.powerbank:
            self._pb_start(m)
            return
        if m.an or m.strom > STROM_AUS:
            self.geraet.last(False)
            self._ll.clear()
            return
        self._ll.append(m.spannung)
        if len(self._ll) < 3:
            return
        r = self.ergebnis
        r.leerlauf_v = round(sum(self._ll) / len(self._ll), 3)
        r.spitze_v = max(self._ll)
        r.temp_start = m.temp_fuehler if e.fuehler else None
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
        if s.art == "kapazitaet":
            self._kap_ab = len(self.punkte)
        art = {"stufe": "", "dauer": "Dauer ", "abschalt": "↑ ", "kapazitaet": "Kapazität "}[s.art]
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
        temp = m.temp_fuehler if e.fuehler else None    # Fühler abgewählt: Temperatur ignorieren
        r.spitze_v = m.spannung if r.spitze_v is None else max(r.spitze_v, m.spannung)
        self.punkte.append((round(t, 1), m.spannung, m.strom, temp))
        if e.powerbank and self._letzt is not None:
            # abgegebene Energie selbst aufsummieren (Trapez zwischen zwei Messwerten)
            dt = max(0.0, m.zeit - self._letzt.zeit)
            if dt < 30:
                p_mittel = (m.spannung * m.strom + self._letzt.spannung * self._letzt.strom) / 2
                i_mittel = (m.strom + self._letzt.strom) / 2
                r.energie_wh = round(r.energie_wh + p_mittel * dt / 3600, 4)
                r.ladung_mah = round(r.ladung_mah + i_mittel * dt / 3.6, 2)
        self._letzt = m
        if temp is not None:
            r.temp_max = temp if r.temp_max is None else max(r.temp_max, temp)
            if temp >= e.temp_grenze:
                self._last_aus()
                r.hinweise.append(f"Temperaturgrenze {e.temp_grenze:g} °C erreicht.")
                r.zu_heiss = True
                self._werten_schritt()
                self._fertig(f"Abgebrochen: {_k(temp, 0)} °C am Fühler "
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
        if (self._aus >= 2 or self._zu_wenig >= 3) and s.art == "kapazitaet":
            self._last_aus()
            r.kap_s = round(im_schritt, 1)
            # tiefste Spannung beim Entladen - ohne Einschwingen und ohne die letzte Minute vor dem Aus
            ende = self.punkte[-1][0] - 60
            anfang = self.punkte[self._kap_ab][0] if len(self.punkte) > self._kap_ab else ende
            kap = [p for p in self.punkte[self._kap_ab:]
                   if anfang + EINSCHWINGEN_S <= p[0] <= ende and p[2] > 0.01]
            r.kap_min_v = round(min(p[1] for p in kap), 3) if kap else None
            r.kap_leer = True
            r.autoaus = im_schritt < PB_AUTOAUS_S
            self._fertig(f"Powerbank leer: nach {dauer_kurz(r.kap_s)} abgeschaltet")
            return
        kap_i = next((k for k, x in enumerate(self.schritte) if x.art == "kapazitaet"), None)
        if (self._aus >= 2 or self._zu_wenig >= 3) and e.powerbank and kap_i is not None and self.i < kap_i:
            # Überlast vor dem Kapazitätstest: festhalten, Powerbank wieder einschalten lassen, weiter
            art = "abgeschaltet" if self._aus >= 2 else "eingebrochen"
            r.abschalt_a, r.abschalt_art = s.soll_a, art
            r.hinweise.append(f"Bei {_k(s.soll_a, 2)} A {art} – danach wieder eingeschaltet für den "
                              "Kapazitätstest.")
            self.i = kap_i - 1
            self.zustand = "wieder_an"
            self._pb_seit = m.zeit
            self._ll.clear()
            self.geraet.abschaltung_setzen(2.0)
            self.geraet.strom_setzen(e.mindest_a)
            self.geraet.last(True)
            self.bei_ereignis("umschalten", f"Die Powerbank hat bei {_k(s.soll_a, 2)} A {art} (Überlast). "
                                            "Bitte den Knopf an der Powerbank drücken – dann folgt der "
                                            "Kapazitätstest.")
            return
        if self._aus >= 2 or self._zu_wenig >= 3:
            self._last_aus()
            art = "abgeschaltet" if self._aus >= 2 else "eingebrochen"
            r.abschalt_a, r.abschalt_art = s.soll_a, art   # diese Stufe zählt nicht als geschafft
            geraet = "Powerbank" if e.powerbank else "Netzteil"
            text = (f"{geraet} hat bei {_k(s.soll_a, 2)} A abgeschaltet" if art == "abgeschaltet"
                    else f"{geraet} liefert {_k(s.soll_a, 2)} A nicht (nur {_k(m.strom, 2)} A)")
            if e.powerbank and art == "abgeschaltet" and s.soll_a <= e.mindest_a + 1e-6:
                text += (" – schon beim Mindeststrom: Abschaltautomatik (Mindeststrom erhöhen) oder die "
                         "Powerbank ist leer")
            self._fertig(text)
            return
        if not (weg or zu_wenig):
            self._werte.append(m)
        if s.art == "kapazitaet":
            r.kap_s = round(im_schritt, 1)
        if s.art == "dauer" and e.bis_stabil and im_schritt >= STABIL_MIN_S and self._stabil(m):
            r.hinweise.append(f"Temperatur stabil nach {dauer_kurz(im_schritt)} (weniger als "
                              f"{_k(STABIL_K, 1)} °C Änderung in {dauer_kurz(STABIL_FENSTER_S)})")
            r.temp_stabil = True
            self._werten_schritt()
            self._naechster(m)
            return
        if (im_schritt >= s.dauer_s and s.art == "dauer" and e.bis_stabil and not self._stabil(m)
                and im_schritt < STABIL_MAX_S):
            # das Ende zählt: noch nicht stabil - weiterlaufen statt mitten im Anstieg aufhören
            if not getattr(self, "_verlaengert", False):
                self._verlaengert = True
                r.hinweise.append(f"Dauertest über die geplanten {dauer_kurz(s.dauer_s)} hinaus verlängert, weil die "
                                  "Temperatur noch stieg")
                self.bei_ereignis("info", "Temperatur noch nicht stabil – Dauertest läuft weiter")
            return
        if im_schritt >= s.dauer_s:
            if s.art == "kapazitaet":
                self._last_aus()
                self._fertig(f"Nach {dauer_kurz(s.dauer_s)} noch nicht leer - Kapazitätstest beendet")
                return
            self._werten_schritt()
            self._naechster(m)

    def _stabil(self, m: Messwert) -> bool:
        """Hat sich die Temperatur im letzten Fenster kaum noch geändert?"""
        t_jetzt = self.punkte[-1][0] if self.punkte else 0
        fenster = [p[3] for p in self.punkte if p[3] is not None and p[0] >= t_jetzt - STABIL_FENSTER_S]
        return len(fenster) >= 10 and max(fenster) - min(fenster) < STABIL_K

    def _werten_schritt(self) -> None:
        s, e = self.schritt, self.einstellung
        if not s or not self._werte or s.art == "kapazitaet":
            return
        # nur die zweite Hälfte: dann hat sich die Spannung gesetzt
        w = self._werte[len(self._werte) // 2:]
        v = sum(x.spannung for x in w) / len(w)
        i = sum(x.strom for x in w) / len(w)
        tief = min(x.spannung for x in w)
        hoch = max(x.spannung for x in w)
        # nur wenn gewählt: was im Kabel verloren geht, zählt zur Spannung an der Buchse
        kabel = i * e.kabel_mohm / 1000 if e.kabel_raus else 0.0
        sw = StufenWert(s.soll_a, round(v, 3), round(tief, 3), round(i, 3),
                        ok=tief + kabel >= e.grenzen()[1],
                        buchse_v=round(v + kabel, 3) if kabel else None,
                        max_v=round(hoch, 3))
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
TRIGGER_SPANNUNGEN = [5.0, 9.0, 12.0, 15.0, 20.0, 28.0]     # 28 V: USB PD EPR (240-W-Kabel und EPR-Adapter)
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
                               "nenn_v": volt, "nenn_a": ampere, "nenn_w": 0.0, "trigger": [],
                               "kapazitaet": False,      # Powerbank: der Kapazitätstest kommt zum Schluss
                               # über 5 V gelten die Grenzen der USB-PD-Spezifikation: ±5 %
                               **({"pd": True, "toleranz_proz": 5.0} if volt > 5.5 else {})})
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
        # Powerbank: nach allen Spannungen zum Schluss bei 5 V bis leer entladen
        self.kap = bool(basis.powerbank and basis.kapazitaet)
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
        if 0 <= self.i < len(self.stufen):
            return self.stufen[self.i]
        if self.im_kap:
            return 5.0, self.basis.kap_a
        return None

    @property
    def im_kap(self) -> bool:
        return self.kap and self.i == len(self.stufen)

    def einstellung_fuer(self, volt: float, ampere: float) -> NetzteilEinstellung:
        return trigger_einstellung(self.basis, volt, ampere)

    def kap_einstellung(self) -> NetzteilEinstellung:
        """Der Kapazitätstest zum Schluss: 5 V, nur entladen."""
        b = self.basis
        fuenf = next((a for v, a in self.stufen if v == 5.0 and a > 0), b.kap_a)
        return NetzteilEinstellung(**{**b.__dict__, "name": f"{b.name} – Kapazität", "nenn_v": 5.0,
                                      "nenn_a": fuenf, "nenn_w": 0.0, "trigger": [], "unbekannt": False,
                                      "stufentest": False, "dauertest": False, "abschalttest": False,
                                      "pd": False, "toleranz_proz": 5.0, "kapazitaet": True})

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
            if self.basis.powerbank:
                # nicht ohne Last stehen lassen - sonst schläft die Powerbank ein. Abschaltgrenze
                # tief, damit der Wechsel auf eine kleinere Spannung die Last nicht abwirft
                self.geraet.abschaltung_setzen(2.0)
                self.geraet.strom_setzen(self.basis.mindest_a)
                self.geraet.last(True)
            else:
                self.geraet.last(False)
        except Exception:
            log.exception("Last beim Umschalten")
        v = self.ziel[0]
        zusatz = " (zum Schluss: Kapazitätstest bis leer)" if self.im_kap else ""
        knopf = ""
        if self.basis.powerbank and self.ergebnis.teile and \
                self.ergebnis.teile[-1]["ergebnis"].get("abschalt_a") is not None:
            knopf = "Die Powerbank hat wegen Überlast abgeschaltet – Knopf drücken. "
        self.bei_ereignis("umschalten", f"{knopf}Am Trigger-Adapter jetzt {v:g} V einstellen{zusatz} – "
                                        f"die Prüfung beginnt, sobald {v:g} V anliegen.")

    def ueberspringen(self) -> None:
        self._ueberspringen = True

    def messwert(self, m: Messwert) -> None:
        if not self.laeuft:
            return
        if self._t0 is None:
            self._t0 = m.zeit
        self.ergebnis.dauer_s = m.zeit - self._t0
        temp = m.temp_fuehler if self.basis.fuehler else None
        self.punkte.append((round(m.zeit - self._t0, 1), m.spannung, m.strom, temp))
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
        if self.basis.powerbank:
            if not m.an and m.spannung > 1:
                self.geraet.last(True)          # Powerbank wach halten
        elif m.an or m.strom > STROM_AUS:
            self.geraet.last(False)
            return
        if abs(m.spannung - v) <= v * TRIGGER_TREFFER:
            self._treffer += 1
        else:
            self._treffer = 0
        if self._treffer >= 3:
            self.zustand = "laeuft"
            if self.im_kap:
                e = self.kap_einstellung()
                self.teil = NetzteilAblauf(e, self.geraet, bei_ereignis=self._teil_ereignis)
                # Kapazität ab voll: was die Spannungsstufen schon entnommen haben, zählt mit
                vorher = sum(t["ergebnis"].get("energie_wh") or 0 for t in self.ergebnis.teile)
                self.teil.ergebnis.energie_wh = round(vorher, 4)
                if vorher:
                    self.teil.ergebnis.hinweise.append(f"Darin enthalten: {_k(vorher, 2)} Wh aus den Prüfungen der "
                                                       "einzelnen Spannungen davor.")
                self.bei_ereignis("info", "5 V liegen an – Kapazitätstest läuft")
                return
            e = self.einstellung_fuer(v, a)
            self.teil = NetzteilAblauf(e, self.geraet, bei_ereignis=self._teil_ereignis)
            self.bei_ereignis("info", f"{v:g} V liegen an – Prüfung läuft")
            return
        if self.im_kap and m.zeit - self._warten_seit >= TRIGGER_WARTEN_S and not self._ueberspringen:
            return                               # auf 5 V kommt es sicher - weiter warten
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
        self.ergebnis.teile.append({"einstellung": dict(t.einstellung.__dict__), "ergebnis": t.ergebnis.als_dict(),
                                    "kurve": duennen(t.punkte)})          # eigenes Diagramm je Spannung
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
                                        "ergebnis": self.teil.ergebnis.als_dict(),
                                        "kurve": duennen(self.teil.punkte)})
        else:
            try:
                self.geraet.last(False)
            except Exception:
                log.exception("Last aus")
        self._fertig(grund, zustand="abgebrochen")

    def _fertig(self, grund: str = "", zustand: str = "fertig") -> None:
        r = self.ergebnis
        # Nur Spannungen mit Stromangabe haben etwas zu halten
        urteile = [t["ergebnis"]["haelt"] for t in r.teile
                   if not t["einstellung"].get("unbekannt") and not t["einstellung"].get("kapazitaet")]
        angegeben = [a for _, a in self.stufen if a > 0]
        if any(u is False for u in urteile):
            r.haelt = False
        elif any(n["grund"] == "kam nicht" for n in r.nicht) and zustand == "fertig":
            r.haelt = False                  # eine gewählte Spannung kommt gar nicht
        elif urteile and all(u is True for u in urteile) and len(urteile) == len(angegeben) and not r.nicht:
            r.haelt = True
        if not grund:
            da = ["Kapazität" if t["einstellung"].get("kapazitaet") else f"{t['einstellung']['nenn_v']:g} V"
                  for t in r.teile]
            grund = "Geprüft: " + (", ".join(da) if da else "keine Spannung")
            if r.nicht:
                grund += "; nicht unterstützt: " + ", ".join(f"{n['volt']:g} V" for n in r.nicht)
        r.grund = grund
        r.vollstaendig = zustand == "fertig"
        # Gesamturteil: das schlechteste der einzelnen Spannungen
        rang = {"nicht": 4, "eingeschraenkt": 3, "offen": 2, "gut": 1}
        einzeln = [t["ergebnis"].get("urteil") for t in r.teile if t["ergebnis"].get("urteil")]
        r.urteil = max(einzeln, key=rang.get) if einzeln else None
        r.verspricht = False if any(n["grund"] == "kam nicht" for n in r.nicht) or any(
            t["ergebnis"].get("verspricht") is False for t in r.teile) else (
            True if any(t["ergebnis"].get("verspricht") for t in r.teile) else None)
        self.zustand = zustand
        log.info("Triggerprüfung beendet: %s", grund)
        self.bei_ereignis("fertig", grund)
