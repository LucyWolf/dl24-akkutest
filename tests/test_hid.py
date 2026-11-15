"""USB-HID-Weg mit nachgebautem hidapi: Gerätesuche, Öffnen, Anmelden,
Abfragen - dieselben Aufrufe, die das echte Paket bekommt."""
import queue
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import protokoll as p
from akkutest import verbindung
from akkutest.geraet import Geraet
from akkutest.simulator import SimAkku, SimDL24

PFAD = b"\\\\?\\hid#vid_0483&pid_5750#7&abc"
TOT = b"\\\\?\\hid#vid_0483&pid_5750&mi_01#7&tot"     # zweite Schnittstelle, antwortet nie
geschlossen = []
gesendet = []


class FalschesGeraet:
    """hid.device() aus hidapi: open_path, read(n, timeout_ms), write, close."""

    def __init__(self):
        self.sim = SimDL24(SimAkku(mah=2000), protokoll="hid", tempo=1)
        self.sim.an, self.sim.soll_a = True, 0.5
        self.raus = queue.Queue()
        self.sim.senden = self.raus.put

    def open_path(self, pfad):
        assert pfad in (PFAD, TOT), pfad
        self.pfad = pfad

    def get_manufacturer_string(self):
        return "ATORCH"

    def get_product_string(self):
        return "ATORCH_USB_TESTER"

    def read(self, n, timeout_ms=0):
        try:
            return list(self.raus.get(timeout=timeout_ms / 1000))[:n]
        except queue.Empty:
            return []

    def write(self, daten):
        # wie der Windows-Treiber bei einem Gerät mit Report-ID 55: eine 00
        # davor wird abgelehnt
        if len(daten) != 64 or daten[0] != 0x55:
            return -1
        if self.pfad == TOT:
            return 64
        gesendet.append(bytes(daten))
        self.sim.empfangen(bytes(daten))
        return len(daten)

    def close(self):
        geschlossen.append(self.pfad)


def test_suchen_oeffnen_messen():
    hid = types.ModuleType("hid")
    hid.device = FalschesGeraet
    hid.enumerate = lambda vid, pid: ([{"path": TOT, "product_string": "ATORCH_USB_TESTER"},
                                       {"path": PFAD, "product_string": "ATORCH_USB_TESTER"},
                                       {"path": PFAD, "product_string": "ATORCH_USB_TESTER"}]
                                      if (vid, pid) == (0x0483, 0x5750) else [])
    sys.modules["hid"] = hid

    liste = verbindung.hid_anschluesse()
    assert len(liste) == 1 and liste[0].art == "hid", liste      # ein Gerät, ein Eintrag
    assert liste[0].geraet == [TOT, PFAD], liste[0].geraet
    v = verbindung.oeffnen(liste[0])
    assert v.pakete and any("ATORCH" in z for z in v.info), v.info
    g = Geraet(v, intervall=0.05)
    g.antwortzeit = 0.2
    assert g.erkennen() == "hid"
    assert v.wege[v.weg] == (PFAD, "roh"), v.wege[v.weg]          # die tote Schnittstelle übersprungen
    assert TOT in geschlossen
    assert g.spannung_stellen == 3 and not g.kann_steuern and g.firmware == "1.1"
    assert gesendet[0] == p.hid_anmelden()
    assert gesendet[1] == p.hid_abfrage(3), gesendet[1].hex(" ")      # Adresse vom Gerät übernommen
    werte = []
    g.bei_messwert = werte.append
    g.starten()
    time.sleep(0.6)
    g.trennen()
    assert geschlossen[-1] == PFAD and v._faden is None              # Lesefaden vor dem Schließen beendet
    assert len(werte) >= 5, werte
    m = werte[-1]
    assert m.strom == 0.5 and m.an and 3.5 < m.spannung < 4.2, m      # Strom positiv, obwohl negativ gemeldet


if __name__ == "__main__":
    test_suchen_oeffnen_messen()
    print("ok test_suchen_oeffnen_messen")
