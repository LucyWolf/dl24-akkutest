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
