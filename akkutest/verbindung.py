"""Der Draht zum Gerät: USB (seriell), Bluetooth LE oder der eingebaute Simulator.

Alle drei sehen nach oben gleich aus: öffnen, schreiben, schließen - und wer
Daten empfangen will, setzt `bei_daten`. Was in den Bytes steht, weiß erst
geraet.py.

Bluetooth "klassisch" (ältere DL24 mit Kopplung per PIN 1234) erscheint nach
dem Koppeln als serieller Anschluss (Windows: COMx, Linux: /dev/rfcomm0) und
läuft damit über den USB-Weg.
"""
from __future__ import annotations

import asyncio
import getpass
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("akkutest.verbindung")

BAUD = 9600


class VerbindungsFehler(Exception):
    pass


@dataclass
class Anschluss:
    art: str        # "usb", "ble", "sim"
    adresse: str    # /dev/ttyUSB0, COM3, BLE-Adresse, "sim"
    name: str       # was in der Liste steht

    def __str__(self) -> str:
        return self.name


class Verbindung:
    def __init__(self) -> None:
        self.bei_daten: Callable[[bytes], None] | None = None
        self.bei_ende: Callable[[str], None] | None = None

    def _empfangen(self, daten: bytes) -> None:
        if self.bei_daten and daten:
            self.bei_daten(daten)

    def _abgerissen(self, grund: str) -> None:
        if self.bei_ende:
            self.bei_ende(grund)

    def uhr(self) -> float:
        """Zeitbasis der Messwerte. Der Simulator hat eine eigene (Zeitraffer)."""
        return time.monotonic()

    def oeffnen(self) -> None: ...
    def schreiben(self, daten: bytes) -> None: ...
    def schliessen(self) -> None: ...


# --------------------------------------------------------------------------
# USB / seriell
# --------------------------------------------------------------------------

def berechtigung_hinweis(port: str) -> str:
    if sys.platform.startswith("linux"):
        gruppe = "dialout"
        try:
            import grp
            gid = os.stat(port).st_gid
            gruppe = grp.getgrgid(gid).gr_name
        except Exception:
            if os.path.exists("/etc/arch-release"):
                gruppe = "uucp"
        return (f"Kein Zugriff auf {port}.\n\n"
                f"Dein Benutzer muss in der Gruppe „{gruppe}“ sein. Einmal im Terminal:\n\n"
                f"    sudo usermod -aG {gruppe} {getpass.getuser()}\n\n"
                "Danach ab- und wieder anmelden (oder neu starten).")
    return f"Kein Zugriff auf {port}. Ist er schon in einem anderen Programm offen (z. B. der Atorch-Software)?"


class Seriell(Verbindung):
    def __init__(self, port: str) -> None:
        super().__init__()
        self.port = port
        self._s = None
        self._laeuft = False

    def oeffnen(self) -> None:
        import serial
        try:
            self._s = serial.Serial(self.port, BAUD, timeout=0.1)
        except serial.SerialException as e:
            if isinstance(e.__context__, PermissionError) or "Permission denied" in str(e) or "Zugriff" in str(e):
                raise VerbindungsFehler(berechtigung_hinweis(self.port)) from e
            raise VerbindungsFehler(f"{self.port} lässt sich nicht öffnen: {e}") from e
        self._laeuft = True
        threading.Thread(target=self._lesen, name="seriell", daemon=True).start()

    def _lesen(self) -> None:
        while self._laeuft:
            try:
                daten = self._s.read(256)
            except Exception as e:
                if self._laeuft:
                    self._laeuft = False
                    self._abgerissen(f"USB-Verbindung getrennt ({e})")
                return
            self._empfangen(daten)

    def schreiben(self, daten: bytes) -> None:
        if not self._s:
            raise VerbindungsFehler("nicht verbunden")
        self._s.write(daten)

    def schliessen(self) -> None:
        self._laeuft = False
        if self._s:
            try:
                self._s.close()
            except Exception:
                pass
            self._s = None


def serielle_anschluesse() -> list[Anschluss]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    aus = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        # Die eingebauten /dev/ttyS* gibt es auf jedem PC, sie sind nie der DL24
        if p.device.startswith("/dev/ttyS") and not p.vid:
            continue
        beschreibung = p.description if p.description and p.description != "n/a" else ""
        if p.vid == 0x1A86:
            beschreibung = beschreibung or "CH340"
        name = f"USB: {p.device}" + (f" – {beschreibung}" if beschreibung else "")
        aus.append(Anschluss("usb", p.device, name))
    if sys.platform.startswith("linux"):
        for n in range(4):
            pfad = f"/dev/rfcomm{n}"
            if os.path.exists(pfad):
                aus.append(Anschluss("usb", pfad, f"Bluetooth (gekoppelt): {pfad}"))
    return aus


# --------------------------------------------------------------------------
# Bluetooth LE
# --------------------------------------------------------------------------

# Die Bluetooth-Module der Atorch-Geräte sind HM-10-artig: ein Dienst FFE0
# mit einer Eigenschaft FFE1 für beide Richtungen.
BLE_EIGENSCHAFT = "0000ffe1-0000-1000-8000-00805f9b34fb"


class _AsyncSchleife:
    """Eine asyncio-Schleife in einem eigenen Faden - bleak braucht eine,
    Qt hat seine eigene."""
    _schleife: asyncio.AbstractEventLoop | None = None
    _sperre = threading.Lock()

    @classmethod
    def holen(cls) -> asyncio.AbstractEventLoop:
        with cls._sperre:
            if cls._schleife is None:
                cls._schleife = asyncio.new_event_loop()
                threading.Thread(target=cls._schleife.run_forever, name="ble", daemon=True).start()
            return cls._schleife

    @classmethod
    def ausfuehren(cls, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, cls.holen()).result(timeout)


def ble_suchen(dauer: float = 6.0) -> list[Anschluss]:
    from bleak import BleakScanner

    async def suchen():
        return await BleakScanner.discover(timeout=dauer, return_adv=True)

    try:
        gefunden = _AsyncSchleife.ausfuehren(suchen(), dauer + 10)
    except Exception as e:
        raise VerbindungsFehler(f"Bluetooth-Suche ging nicht: {e}\n\nIst Bluetooth eingeschaltet?") from e
    aus = []
    for adresse, (geraet, werbung) in gefunden.items():
        name = werbung.local_name or geraet.name or ""
        if not name:
            continue
        aus.append((("dl24" not in name.lower() and "atorch" not in name.lower()), name,
                    Anschluss("ble", adresse, f"Bluetooth: {name} ({adresse})")))
    aus.sort(key=lambda x: (x[0], x[1]))          # DL24 zuerst
    return [a for *_, a in aus]


class Bluetooth(Verbindung):
    def __init__(self, adresse: str) -> None:
        super().__init__()
        self.adresse = adresse
        self._client = None
        self._schreib = None
        self._getrennt_gewollt = False

    def oeffnen(self) -> None:
        from bleak import BleakClient

        def getrennt(_c):
            if not self._getrennt_gewollt:
                self._abgerissen("Bluetooth-Verbindung getrennt")

        async def verbinden():
            client = BleakClient(self.adresse, disconnected_callback=getrennt)
            await client.connect(timeout=15)
            # FFE1 nehmen, wenn es da ist; sonst die erste, die melden kann
            melden = schreiben = None
            for dienst in client.services:
                for e in dienst.characteristics:
                    if e.uuid.lower() == BLE_EIGENSCHAFT:
                        melden = schreiben = e
                    if melden is None and "notify" in e.properties:
                        melden = e
                    if schreiben is None and ("write-without-response" in e.properties or "write" in e.properties):
                        schreiben = e
            if melden is None:
                await client.disconnect()
                raise VerbindungsFehler("Das Gerät bietet keine Bluetooth-Eigenschaft zum Melden an.")
            log.info("BLE: melden über %s, schreiben über %s", melden.uuid, schreiben and schreiben.uuid)
            await client.start_notify(melden, lambda _h, d: self._empfangen(bytes(d)))
            return client, schreiben

        try:
            self._client, self._schreib = _AsyncSchleife.ausfuehren(verbinden(), 30)
        except VerbindungsFehler:
            raise
        except Exception as e:
            raise VerbindungsFehler(f"Bluetooth-Verbindung zu {self.adresse} ging nicht: {e}") from e

    def schreiben(self, daten: bytes) -> None:
        if not self._client or not self._schreib:
            raise VerbindungsFehler("nicht verbunden")
        ohne_antwort = "write-without-response" in self._schreib.properties

        async def senden():
            for i in range(0, len(daten), 20):
                await self._client.write_gatt_char(self._schreib, daten[i:i + 20], response=not ohne_antwort)

        _AsyncSchleife.ausfuehren(senden(), 5)

    def schliessen(self) -> None:
        self._getrennt_gewollt = True
        if self._client:
            try:
                _AsyncSchleife.ausfuehren(self._client.disconnect(), 5)
            except Exception:
                pass
            self._client = None


# --------------------------------------------------------------------------

def oeffnen(anschluss: Anschluss) -> Verbindung:
    if anschluss.art == "usb":
        v: Verbindung = Seriell(anschluss.adresse)
    elif anschluss.art == "ble":
        v = Bluetooth(anschluss.adresse)
    elif anschluss.art == "sim":
        from .simulator import SimulatorVerbindung
        v = SimulatorVerbindung(protokoll=anschluss.adresse.split(":")[1] if ":" in anschluss.adresse else "px100")
    else:
        raise VerbindungsFehler(f"unbekannte Art {anschluss.art}")
    v.oeffnen()
    return v
