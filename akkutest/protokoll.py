"""Die beiden Sprachen, die ein Atorch DL24 spricht.

1. **Atorch-Bericht** (FF 55 ...): das Gerät schickt von sich aus einmal je
   Sekunde ein Paket mit allen Messwerten. So redet es auch mit der Handy-App
   "E-test". Steuern lässt es sich darüber nur eingeschränkt.

2. **PX100-Befehle** (B1 B2 ... B6): Frage-Antwort. Damit lässt sich die Last
   ein- und ausschalten, der Strom und die Abschaltspannung setzen. Die Werte
   kommen in mV/mA-Auflösung statt 0,1 V.

Welche davon ein Gerät versteht, hängt von Fassung und Firmware ab. Deshalb
probiert geraet.py beim Verbinden beide und zeigt im Diagnose-Reiter roh, was
hin- und herging.
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Atorch-Bericht
# --------------------------------------------------------------------------

ATORCH_KOPF = b"\xff\x55"
ATORCH_BERICHT = 0x01
ATORCH_BEFEHL = 0x11
GERAET_DC = 0x02          # 1 = AC-Messgerät, 2 = DC (DL24), 3 = USB-Messgerät
ATORCH_LAENGE = 36


def atorch_pruefsumme(daten: bytes) -> int:
    """Summe ab Byte 2 (ohne Kopf, ohne Prüfbyte), XOR 0x44."""
    return (sum(daten[2:-1]) & 0xFF) ^ 0x44


@dataclass
class AtorchWerte:
    spannung: float      # V   (Auflösung 0,1 V)
    strom: float         # A   (0,001 A)
    kapazitaet_mah: float  # mAh (10 mAh)
    energie_wh: float    # Wh  (10 Wh - zu grob, die App rechnet selbst)
    temperatur: int      # °C
    laufzeit_s: int


def atorch_lesen(paket: bytes) -> AtorchWerte | None:
    """Ein 36-Byte-Bericht vom DC-Gerät; None, wenn es keiner ist."""
    if len(paket) != ATORCH_LAENGE or not paket.startswith(ATORCH_KOPF):
        return None
    if paket[2] != ATORCH_BERICHT or paket[3] != GERAET_DC:
        return None
    # Keine Prüfsumme verlangen: Lucys DL24 (2,4"-Farbdisplay) schickt immer 23
    # als letztes Byte, egal was drinsteht. Gegen Bruchstücke schützt der
    # Entwirrer, indem er auf einen zweiten Kopf innerhalb des Pakets achtet.
    u24 = lambda i: int.from_bytes(paket[i:i + 3], "big")
    return AtorchWerte(
        spannung=u24(4) / 10,
        strom=u24(7) / 1000,
        kapazitaet_mah=u24(10) * 10,
        energie_wh=int.from_bytes(paket[13:17], "big") * 10,
        temperatur=int.from_bytes(paket[24:26], "big"),
        laufzeit_s=int.from_bytes(paket[26:28], "big") * 3600 + paket[28] * 60 + paket[29],
    )


def atorch_bauen(w: AtorchWerte) -> bytes:
    """Gegenstück zu atorch_lesen - für den Simulator und die Tests."""
    p = bytearray(ATORCH_LAENGE)
    p[0:2] = ATORCH_KOPF
    p[2], p[3] = ATORCH_BERICHT, GERAET_DC
    p[4:7] = round(w.spannung * 10).to_bytes(3, "big")
    p[7:10] = round(w.strom * 1000).to_bytes(3, "big")
    p[10:13] = round(w.kapazitaet_mah / 10).to_bytes(3, "big")
    p[13:17] = round(w.energie_wh / 10).to_bytes(4, "big")
    p[24:26] = int(w.temperatur).to_bytes(2, "big")
    h, rest = divmod(int(w.laufzeit_s), 3600)
    p[26:28] = h.to_bytes(2, "big")
    p[28], p[29] = divmod(rest, 60)
    p[-1] = atorch_pruefsumme(p)
    return bytes(p)


# Befehle im Atorch-Format. Nur das Zurücksetzen der Zähler ist hier belegt;
# Last ein/aus geht über PX100.
ATORCH_ALLES_NULL = 0x05


def atorch_befehl(befehl: int, wert: int = 0) -> bytes:
    p = bytearray(b"\xff\x55\x11\x02") + bytes([befehl]) + wert.to_bytes(4, "big") + b"\x00"
    p[-1] = atorch_pruefsumme(p)
    return bytes(p)


class AtorchSammler:
    """Setzt Berichte aus dem Datenstrom zusammen. Über Bluetooth kommen sie
    in Stücken zu 20 Byte an, über USB auch mal zwei auf einmal."""

    def __init__(self) -> None:
        self.puffer = bytearray()

    def hinein(self, daten: bytes) -> list[AtorchWerte]:
        self.puffer += daten
        gefunden = []
        while True:
            i = self.puffer.find(ATORCH_KOPF)
            if i < 0:
                # Ein einzelnes FF am Ende könnte der Anfang des nächsten sein
                del self.puffer[:max(0, len(self.puffer) - 1)]
                return gefunden
            del self.puffer[:i]
            if len(self.puffer) < 4:
                return gefunden
            if self.puffer[2] != ATORCH_BERICHT:
                del self.puffer[:2]
                continue
            if len(self.puffer) < ATORCH_LAENGE:
                return gefunden
            w = atorch_lesen(bytes(self.puffer[:ATORCH_LAENGE]))
            if w is None:
                del self.puffer[:2]          # kaputt: nach dem nächsten Kopf suchen
                continue
            gefunden.append(w)
            del self.puffer[:ATORCH_LAENGE]


# --------------------------------------------------------------------------
# PX100
# --------------------------------------------------------------------------

PX_EIN_AUS = 0x01
PX_STROM_SETZEN = 0x02
PX_ABSCHALT_SETZEN = 0x03
PX_ZAEHLER_NULL = 0x05

PX_IST_AN = 0x10
PX_SPANNUNG = 0x11
PX_STROM = 0x12
PX_ZEIT = 0x13
PX_AH = 0x14
PX_WH = 0x15
PX_TEMPERATUR = 0x16

PX_OK = 0x6F
PX_FEHLER = 0x70
PX_ANTWORT_KOPF = b"\xca\xcb"
PX_ANTWORT_ENDE = b"\xce\xcf"


def px_befehl(befehl: int, d1: int = 0, d2: int = 0) -> bytes:
    return bytes([0xB1, 0xB2, befehl, d1 & 0xFF, d2 & 0xFF, 0xB6])


def px_zahl_mit_hundertsteln(wert: float) -> tuple[int, int]:
    """1,25 -> (1, 25). So erwartet das Gerät Strom und Spannung."""
    hundertstel = round(wert * 100)
    return hundertstel // 100, hundertstel % 100


def px_antwort_wert(antwort: bytes) -> int | None:
    """CA CB d1 d2 d3 CE CF -> d1<<16 | d2<<8 | d3"""
    if len(antwort) != 7 or not antwort.startswith(PX_ANTWORT_KOPF) or not antwort.endswith(PX_ANTWORT_ENDE):
        return None
    return int.from_bytes(antwort[2:5], "big")


def px_antwort_bauen(wert: int) -> bytes:
    return PX_ANTWORT_KOPF + int(wert).to_bytes(3, "big") + PX_ANTWORT_ENDE


def hex_text(daten: bytes) -> str:
    return daten.hex(" ").upper()


# --------------------------------------------------------------------------
# USB-HID (DL24/P über das USB-Kabel)
# --------------------------------------------------------------------------
# Herausgelesen aus der Atorch-PC-Software "Load_Application" V1.0.8
# (15.11.2026). Der DL24/P meldet sich am USB nicht als COM-Anschluss, sondern
# als HID-Gerät 0483:5750. Es spricht nur, wenn es gefragt wird: 64-Byte-Pakete,
# das erste Byte ist die Report-ID (hin 55, zurück AA).
#
#   Abfragen:  55 05 01 05 0B 00 8C EE FF    -> AA 05 01 05 + 60 Byte Messwerte
#
# ACHTUNG: 55 05 09 02 ... schickt die Atorch-Software NUR beim Knopf
# "Firmware-Update starten" - der DL24 geht davon in den Update-Modus.
# 1.0.11/1.0.12 hielten es für ein "Anmelden" und schickten es beim Verbinden.
# Es darf nie wieder gesendet werden; hid_befehl() und hid_paket() weisen es ab.
#
# Die Messwerte sind 32-Bit-Zahlen (little endian) in Tausendsteln, ab Byte 8:
# Spannung, Strom, Leistung, Widerstand, Wh, mAh, Fühler-, CPU-, MOSFET-Temperatur,
# Lüfter. Vorzeichen stehen getrennt in Byte 60. Über USB kommt die Spannung
# damit auf 1 mV genau - über Bluetooth nur auf 0,1 V.

HID_VID = 0x0483
HID_PID = 0x5750
HID_LAENGE = 64
HID_HIN = 0x55
HID_ZURUECK = 0xAA
HID_FAMILIE = 0x05
HID_UPDATE_START = 0x02     # nie senden (siehe oben)
HID_MESSWERTE = 0x05
HID_ADRESSE = 0x01          # fest, wie in der Atorch-Software

# Befehle: 55 05 <adr> <befehl> d0 d1 d2 d3 EE FF. Zahlen als float32, höchstes
# Byte zuerst - so baut sie die Atorch-Software aus dem Eingabefeld.
HID_SOLLWERT = 0x21         # Strom in A (Knopf "value")
HID_LAST = 0x25             # 01 = ein, 00 = aus (Knopf "Run")
HID_ABSCHALT = 0x29         # Abschaltspannung in V ("zero_v")
HID_LADESCHLUSS_V = 0x2A    # "full_v" - nicht benutzt
HID_LADESCHLUSS_A = 0x2B    # "full_a" - nicht benutzt
HID_ZEITGRENZE = 0x31       # d0 = 01 Stunden / 02 Minuten - nicht benutzt
HID_STROM_LOESCHEN = 0x32   # "clearcurrent" - nicht benutzt
HID_WERKSEINSTELLUNG = 0x33 # nie senden
HID_ZAEHLER_NULL = 0x34     # "datazero": mAh, Wh, Zeit auf 0


VERBOTEN = (HID_UPDATE_START, HID_WERKSEINSTELLUNG)


def hid_paket(inhalt: bytes) -> bytes:
    inhalt = bytes(inhalt)
    if len(inhalt) >= 4 and inhalt[0] == HID_HIN and inhalt[3] in VERBOTEN:
        raise ValueError(f"Befehl {inhalt[3]:02X} wird nie gesendet (Update/Werkseinstellung)")
    return inhalt.ljust(HID_LAENGE, b"\x00")


def hid_abfrage(adresse: int = HID_ADRESSE) -> bytes:
    return hid_paket(bytes([HID_HIN, HID_FAMILIE, adresse & 0xFF, HID_MESSWERTE, 0x0B, 0x00, 0x8C, 0xEE, 0xFF]))


def hid_befehl(adresse: int, befehl: int, daten: bytes = b"\0\0\0\0") -> bytes:
    assert len(daten) == 4 and befehl not in VERBOTEN
    return hid_paket(bytes([HID_HIN, HID_FAMILIE, adresse & 0xFF, befehl]) + daten + b"\xee\xff")


def hid_zahl(wert: float) -> bytes:
    import struct
    return struct.pack(">f", float(wert))


def hid_befehl_lesen(paket: bytes) -> tuple[int, int, bytes] | None:
    """Gegenstück für den Simulator: (Adresse, Befehl, 4 Datenbytes)."""
    if len(paket) < 10 or paket[0] != HID_HIN or paket[1] != HID_FAMILIE or paket[8:10] != b"\xee\xff":
        return None
    return paket[2], paket[3], bytes(paket[4:8])


@dataclass
class HidWerte:
    spannung: float      # V   (0,001 V)
    strom: float         # A   (0,001 A; das Gerät meldet Entladen negativ)
    leistung: float      # W
    widerstand: float    # Ω
    energie_wh: float    # Wh
    kapazitaet_mah: float  # mAh
    temp_fuehler: float  # °C - ohne angesteckten Fühler unsinnig (-46)
    temp_cpu: float
    temp_mos: float
    luefter: float       # U/min
    an: bool
    firmware: str


def _hid_anfang(paket: bytes) -> bytes | None:
    """Manche HID-Wege liefern die Report-ID mit, manche nicht."""
    if len(paket) >= 4 and paket[0] == HID_ZURUECK and paket[1] == HID_FAMILIE:
        return paket
    if len(paket) >= 4 and paket[0] == HID_FAMILIE:
        return bytes([HID_ZURUECK]) + paket
    return None


def hid_lesen(paket: bytes, adresse: int | None = None) -> HidWerte | None:
    p = _hid_anfang(paket)
    if p is None or len(p) < HID_LAENGE or p[3] != HID_MESSWERTE:
        return None
    if adresse is not None and p[2] != adresse:
        return None
    w = [int.from_bytes(p[i:i + 4], "little") / 1000 for i in range(8, 48, 4)]
    zeichen = p[0x3C]
    if zeichen & 0x80:
        w[1] = -w[1]
    for bit, i in ((0x40, 6), (0x20, 7), (0x10, 8)):
        if zeichen & bit:
            w[i] = -w[i]
    return HidWerte(*w, an=p[0x34] != 0, firmware=f"{p[0x36] // 10}.{p[0x36] % 10}" if p[0x36] else "")
    # Byte 0x36 ist bei Firmware v1.1.0 leer (0) - dann steht die Fassung nur im Gerätenamen


def hid_bauen(w: HidWerte, adresse: int = HID_ADRESSE) -> bytes:
    """Gegenstück zu hid_lesen - für den Simulator und die Tests."""
    p = bytearray(HID_LAENGE)
    p[0:4] = bytes([HID_ZURUECK, HID_FAMILIE, adresse, HID_MESSWERTE])
    werte = [w.spannung, w.strom, w.leistung, w.widerstand, w.energie_wh, w.kapazitaet_mah,
             w.temp_fuehler, w.temp_cpu, w.temp_mos, w.luefter]
    zeichen = 0
    for n, (i, wert) in enumerate(zip(range(8, 48, 4), werte)):
        if wert < 0:
            zeichen |= {1: 0x80, 6: 0x40, 7: 0x20, 8: 0x10}.get(n, 0)
        p[i:i + 4] = round(abs(wert) * 1000).to_bytes(4, "little")
    p[0x34] = 1 if w.an else 0
    if w.firmware:
        haupt, neben = w.firmware.split(".")
        p[0x36] = int(haupt) * 10 + int(neben)
    p[0x3C] = zeichen
    return bytes(p)

