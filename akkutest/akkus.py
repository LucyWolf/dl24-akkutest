"""Was man über Akkus wissen muss, um sie zu testen: Typen, bekannte Zellen,
Erkennung aus der Spannung und die Bewertung des Ergebnisses."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AkkuTyp:
    schluessel: str
    name: str
    nenn_v: float        # Nennspannung je Zelle
    voll_v: tuple[float, float]   # Ruhespannung frisch geladen, je Zelle (von, bis)
    abschalt_v: float    # übliche Entladeschluss-Spannung je Zelle
    min_abschalt_v: float  # darunter wird die Zelle geschädigt
    hinweis: str = ""


TYPEN: dict[str, AkkuTyp] = {t.schluessel: t for t in [
    AkkuTyp("liion", "Li-Ion (18650, 21700 …)", 3.6, (4.05, 4.22), 3.0, 2.5),
    AkkuTyp("lipo", "LiPo (Flachzelle, Modellbau)", 3.7, (4.05, 4.22), 3.0, 3.0),
    AkkuTyp("lihv", "LiPo HV (4,35 V)", 3.8, (4.25, 4.37), 3.0, 3.0),
    AkkuTyp("lifepo4", "LiFePO4", 3.2, (3.32, 3.65), 2.5, 2.0,
             "LiFePO4 hat eine sehr flache Kurve - die Spannung sagt wenig über den Ladestand."),
    AkkuTyp("nimh", "NiMH (AA, AAA, Eneloop)", 1.2, (1.33, 1.48), 1.0, 0.9),
    AkkuTyp("blei", "Blei / Autobatterie / AGM", 2.0, (2.08, 2.17), 1.75, 1.75,
             "Bleiakkus nie ganz leeren. Für Autobatterien ist 10,5 V das Ende; "
             "üblich ist ein Test mit 1/20 der Kapazität (C20)."),
]}


@dataclass(frozen=True)
class Zelle:
    name: str
    typ: str
    mah: int
    bauform: str


# Herstellerangaben (Mindest- bzw. Nennkapazität). Wer den Akku nicht findet,
# trägt die mAh vom Aufdruck selbst ein.
ZELLEN: list[Zelle] = [
    Zelle("Samsung INR18650-25R", "liion", 2500, "18650"),
    Zelle("Samsung INR18650-29E", "liion", 2900, "18650"),
    Zelle("Samsung INR18650-30Q", "liion", 3000, "18650"),
    Zelle("Samsung INR18650-35E", "liion", 3500, "18650"),
    Zelle("Samsung INR21700-40T", "liion", 4000, "21700"),
    Zelle("Samsung INR21700-50E", "liion", 5000, "21700"),
    Zelle("Samsung INR21700-50S", "liion", 5000, "21700"),
    Zelle("LG INR18650-HG2", "liion", 3000, "18650"),
    Zelle("LG INR18650-MJ1", "liion", 3500, "18650"),
    Zelle("LG INR18650-M36", "liion", 3600, "18650"),
    Zelle("LG INR21700-M50LT", "liion", 5000, "21700"),
    Zelle("Sony/Murata US18650VTC4", "liion", 2100, "18650"),
    Zelle("Sony/Murata US18650VTC5A", "liion", 2600, "18650"),
    Zelle("Sony/Murata US18650VTC6", "liion", 3000, "18650"),
    Zelle("Molicel INR18650-P26A", "liion", 2600, "18650"),
    Zelle("Molicel INR18650-P28A", "liion", 2800, "18650"),
    Zelle("Molicel INR21700-P42A", "liion", 4200, "21700"),
    Zelle("Molicel INR21700-P45B", "liion", 4500, "21700"),
    Zelle("Panasonic NCR18650B", "liion", 3400, "18650"),
    Zelle("Panasonic NCR18650GA", "liion", 3450, "18650"),
    Zelle("Panasonic NCR18650PF", "liion", 2900, "18650"),
    Zelle("A123 ANR26650M1B", "lifepo4", 2500, "26650"),
    Zelle("Eneloop AA (weiß)", "nimh", 1900, "AA"),
    Zelle("Eneloop Pro AA (schwarz)", "nimh", 2450, "AA"),
    Zelle("Eneloop AAA (weiß)", "nimh", 750, "AAA"),
    Zelle("Eneloop Pro AAA (schwarz)", "nimh", 930, "AAA"),
]


def zelle_finden(name: str) -> Zelle | None:
    return next((z for z in ZELLEN if z.name == name), None)


@dataclass
class Vorschlag:
    typ: str
    zellen: int
    sicher: bool          # passt die Spannung eindeutig?
    text: str


def erkennen(spannung: float, max_zellen: int = 24) -> list[Vorschlag]:
    """Typ und Zellenzahl aus der Leerlaufspannung eines **voll geladenen**
    Akkus raten. Gibt alle passenden Möglichkeiten zurück, die beste zuerst.

    Das ist ein Vorschlag, keine Messung: 12,6 V können ein voller 3S-Li-Ion-
    oder ein voller Bleiakku sein. Deshalb immer bestätigen lassen.
    """
    if spannung < 0.8:
        return []
    treffer: list[tuple[float, Vorschlag]] = []
    for t in TYPEN.values():
        if t.schluessel in ("lipo", "lihv"):
            continue                       # elektrisch wie Li-Ion; HV unten extra
        # Bleiakkus gibt es praktisch nur als 6-V- und 12-V-Block (3/6 Zellen)
        moegliche = (3, 6, 12) if t.schluessel == "blei" else range(1, max_zellen + 1)
        for n in moegliche:
            von, bis = t.voll_v[0] * n, t.voll_v[1] * n
            mitte = (von + bis) / 2
            # etwas Spielraum: halb leer ist nicht "falscher Typ"
            if von - 0.12 * n <= spannung <= bis + 0.03 * n:
                abstand = abs(spannung - mitte) / n
                treffer.append((abstand, Vorschlag(t.schluessel, n, von <= spannung <= bis,
                                                   f"{n}× {t.name.split(' (')[0]}" if n > 1 else t.name.split(' (')[0])))
    # bei gleich guter Passung: weniger Zellen ist wahrscheinlicher
    treffer.sort(key=lambda x: (not x[1].sicher, x[1].zellen, x[0]))
    # gleiche Kombination nicht doppelt
    gesehen, aus = set(), []
    for _, v in treffer:
        if (v.typ, v.zellen) not in gesehen:
            gesehen.add((v.typ, v.zellen))
            aus.append(v)
    return aus[:4]


def abschaltspannung(typ: str, zellen: int) -> float:
    return round(TYPEN[typ].abschalt_v * zellen, 2)


def strom_vorschlag(nenn_mah: int, c_rate: float = 0.5, max_a: float = 20.0) -> float:
    """0,5C ist ein guter Kompromiss: ein Test dauert gut zwei Stunden, und
    das Ergebnis liegt nah an der Herstellerangabe (die meist bei 0,2C gemessen ist)."""
    if nenn_mah <= 0:
        return 1.0
    return round(min(max(nenn_mah / 1000 * c_rate, 0.05), max_a), 2)


def bewertung(prozent: float) -> tuple[str, str]:
    """(Wort, Farbe) zum Zustand in Prozent der Nennkapazität."""
    if prozent >= 95:
        return "wie neu", "#2e9d4a"
    if prozent >= 85:
        return "gut", "#5aa83a"
    if prozent >= 75:
        return "gebraucht, noch brauchbar", "#c9a227"
    if prozent >= 60:
        return "schwach", "#e07b24"
    return "verbraucht - austauschen", "#d03b3b"
