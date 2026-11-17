"""Woher die Grenzwerte für die Spannung kommen - für den Bericht, mit QR-Code zur Quelle.

Wichtig: Die Grenzen stammen aus Normen (USB-Spezifikationen, als IEC/EN übernommen).
Ein Gesetz schreibt sie für Netzteile, Ladegeräte und Powerbanks nicht vor. Die
EU-Richtlinie zum einheitlichen Ladegerät verweist auf dieselben Normen - richtet sich
aber an die geladenen Geräte (Handy, Tablet, Kamera, ...), nicht an die Stromquelle.
"""
from __future__ import annotations

USB2_URL = "https://www.usb.org/document-library/usb-20-specification"
PD_URL = "https://www.usb.org/document-library/usb-power-delivery"
EU_URL = "https://eur-lex.europa.eu/eli/dir/2022/2380/oj"


def _k(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def quelle(volt: float, toleranz: float = 5.0) -> dict:
    """Herkunft der Ampel-Grenzen für eine Spannung."""
    if volt <= 5.5:
        return {
            "titel": "5 V (USB)",
            "norm": "USB 2.0 Specification, Abschnitt 7.2.2 – international übernommen als IEC 62680-2-1, "
                    "in Europa als EN 62680-2-1",
            "werte": "grün 4,75–5,25 V an der Buchse eines Ports mit eigener Stromversorgung (High-power-Port); "
                     "gelb bis 4,40 V (Untergrenze für Low-power-Ports, ebenda) bzw. bis 5,50 V; darüber/darunter rot. "
                     "Die Einteilung in gelb oberhalb von 5,25 V ist eine Einteilung dieser Software.",
            "url": USB2_URL,
        }
    unten, oben = volt * 0.95, volt * 1.05
    epr = volt > 20.5
    return {
        "titel": f"{volt:g} V (USB Power Delivery{', EPR' if epr else ''})",
        "norm": "USB Power Delivery Specification, Abschnitt 7.1.8 und Tabelle „Source Electrical Parameters“ – "
                "in Europa als EN IEC 62680-1-2",
        "werte": f"grün {_k(unten)}–{_k(oben)} V (vSrcNew: ±5 %); gelb bis 0,5 V darüber hinaus, also "
                 f"{_k(unten - 0.5)}–{_k(oben + 0.5)} V (vSrcValid, nur kurzzeitig erlaubt); sonst rot."
                 + (" Für 28 V (Extended Power Range) sind die ±5 % belegt; die 0,5-V-Zone ist aus der allgemeinen "
                    "Regel übernommen und für EPR nicht eigens nachgewiesen." if epr else ""),
        "url": PD_URL,
    }


def gesetz() -> dict:
    return {
        "titel": "Gesetzlicher Bezug",
        "norm": "Richtlinie 2014/53/EU (Funkanlagen), geändert durch Richtlinie (EU) 2022/2380 "
                "(„einheitliches Ladegerät“), Anhang Ia",
        "werte": "Schreibt für Handys, Tablets, Kameras, Kopfhörer, Spielkonsolen, Lautsprecher, E-Reader, "
                 "Tastaturen, Mäuse, Navigationsgeräte und Laptops eine USB-C-Buchse vor und – wenn sie mit mehr als "
                 "5 V, 3 A oder 15 W laden – USB Power Delivery nach EN IEC 62680-1-2. Sie gilt für diese Geräte, "
                 "nicht für Netzteile, Ladegeräte oder Powerbanks: Für die schreibt kein Gesetz vor, die "
                 "Spannungsgrenzen einzuhalten. Die Grenzwerte in diesem Bericht stammen aus den Normen oben.",
        "url": EU_URL,
    }


def eintraege(spannungen: list[float]) -> list[dict]:
    """Je geprüfter Spannungsart ein Eintrag (5 V, jede PD-Spannung), dazu der gesetzliche Bezug."""
    aus, gesehen = [], set()
    for v in sorted(set(spannungen)):
        if v <= 5.5:
            schluessel = "usb"
        else:
            schluessel = v
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        aus.append(quelle(v))
    aus.append(gesetz())
    return aus


def qr_bild(text: str, groesse: int = 120):
    """QR-Code als QImage (schwarz auf weiß) - ohne Bildbibliothek, nur die Matrix."""
    import qrcode
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    zelle = max(1, groesse // n)
    bild = QImage(n * zelle, n * zelle, QImage.Format_RGB32)
    bild.fill(QColor("white"))
    p = QPainter(bild)
    for y, zeile in enumerate(m):
        for x, an in enumerate(zeile):
            if an:
                p.fillRect(x * zelle, y * zelle, zelle, zelle, Qt.black)
    p.end()
    return bild
