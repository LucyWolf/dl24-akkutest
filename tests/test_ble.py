"""Bluetooth mit einem nachgebauten Modul: lauscht die App auf allen Kanälen,
schreibt sie nie in Standard-Dienste (Gerätename!), und steht alles in der Diagnose?"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

B = "-0000-1000-8000-00805f9b34fb"


class E:
    def __init__(self, kurz, props):
        self.uuid, self.properties = f"0000{kurz}{B}", props


class D:
    def __init__(self, kurz, eig):
        self.uuid, self.characteristics = f"0000{kurz}{B}", eig


class FalscherClient:
    letzter = None

    def __init__(self, adresse, disconnected_callback=None):
        FalscherClient.letzter = self
        self.lauscht, self.geschrieben = {}, []
        # Gerätename beschreibbar (darf nie benutzt werden), Daten auf FFF1, Schreiben auf FFF2
        self.services = [D("1800", [E("2a00", ["read", "write"])]),
                         D("180f", [E("2a19", ["read", "notify"])]),
                         D("fff0", [E("fff1", ["notify"]), E("fff2", ["write-without-response"])])]

    async def connect(self, timeout):
        pass

    async def start_notify(self, e, rueckruf):
        self.lauscht[e.uuid[4:8]] = rueckruf

    async def write_gatt_char(self, e, daten, response):
        self.geschrieben.append((e.uuid[4:8], daten))

    async def disconnect(self):
        pass


sys.modules["bleak"] = types.SimpleNamespace(BleakClient=FalscherClient)
from akkutest.verbindung import Bluetooth  # noqa: E402


def test_alle_kanaele_und_nie_in_standarddienste():
    v = Bluetooth("AA:BB")
    empfangen = []
    v.bei_daten = empfangen.append
    v.oeffnen()
    c = FalscherClient.letzter
    assert set(c.lauscht) == {"fff1"}, c.lauscht          # Akku-Dienst 180F nicht
    c.lauscht["fff1"](None, bytearray(b"\xff\x55"))
    assert empfangen == [b"\xff\x55"]
    v.schreiben(b"\xb1\xb2\x11\x00\x00\xb6")
    assert c.geschrieben == [("fff2", b"\xb1\xb2\x11\x00\x00\xb6")], c.geschrieben
    text = "\n".join(v.info)
    for erwartet in ("Dienst 1800 (Standard)", "Eigenschaft 2A00: read, write", "Dienst FFF0",
                     "lausche auf FFF1", "schreibe auf FFF2"):
        assert erwartet in text, text
    print(text)


if __name__ == "__main__":
    test_alle_kanaele_und_nie_in_standarddienste()
    print("ok")
