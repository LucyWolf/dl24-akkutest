"""Der Draht zum Gerät: USB-HID (DL24/P), USB seriell, Bluetooth LE oder der
eingebaute Simulator.

Alle sehen nach oben gleich aus: öffnen, schreiben, schließen - und wer
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
    art: str        # "hid", "usb", "ble", "sim"
    adresse: str    # /dev/ttyUSB0, COM3, BLE-Adresse, "sim"
    name: str       # was in der Liste steht
    geraet: object = None   # BLE: das Gerät aus der Suche (bleak.BLEDevice)

    def __str__(self) -> str:
        return self.name


class Verbindung:
    # True: jedes Stück bei `bei_daten` ist ein ganzes Paket (USB-HID).
    # Sonst ein Datenstrom, den geraet.py erst zerlegen muss.
    pakete = False

    def __init__(self) -> None:
        self.info: list[str] = []        # Textzeilen für den Diagnose-Reiter
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
# USB-HID (DL24/P mit Farbdisplay: am Kabel kein COM-Anschluss, sondern HID)
# --------------------------------------------------------------------------

def hid_hinweis() -> str:
    if sys.platform.startswith("linux"):
        return ("Kein Zugriff auf den DL24 über USB.\n\n"
                "Linux lässt normale Benutzer nicht an HID-Geräte. Einmal im Terminal:\n\n"
                "    echo 'KERNEL==\"hidraw*\", ATTRS{idVendor}==\"0483\", ATTRS{idProduct}==\"5750\", "
                "TAG+=\"uaccess\"' | sudo tee /etc/udev/rules.d/70-dl24.rules\n"
                "    sudo udevadm control --reload && sudo udevadm trigger\n\n"
                "Danach das USB-Kabel einmal ab- und wieder anstecken.")
    return ("Der DL24 lässt sich über USB nicht öffnen.\n\n"
            "Ist die Atorch-PC-Software noch offen? Sie hält das Gerät fest - erst schließen.")


class UsbHid(Verbindung):
    """Der DL24/P am USB-Kabel.

    Die Atorch-Software spricht ihn über libusb an und schickt die 64 Byte
    roh, beginnend mit 55. Über den Windows-HID-Treiber kommt es darauf an,
    ob das Gerät Report-IDs benutzt: ohne braucht es eine 00 davor, mit ist
    die 55 selbst die ID. Und ein Gerät kann mehrere HID-Schnittstellen
    haben. Deshalb gibt es mehrere "Wege" (Schnittstelle × Schreibweise);
    geraet.py probiert sie durch, bis einer antwortet, und das Log sagt,
    welcher es war.
    """
    pakete = True

    def __init__(self, pfad, alle_pfade=None) -> None:
        super().__init__()
        pfade = list(alle_pfade or [pfad])
        if pfad in pfade:
            pfade.remove(pfad)
        pfade.insert(0, pfad)
        self.wege = [(pf, art) for pf in pfade for art in ("null", "roh")]
        self.weg = 0
        self._d = None
        self._faden: threading.Thread | None = None
        self._laeuft = False
        self._sperre = threading.Lock()

    @property
    def weg_text(self) -> str:
        pfad, art = self.wege[self.weg]
        return f"Schnittstelle {self._pfad_kurz(pfad)}, " + ("mit 00 davor" if art == "null" else "roh wie libusb")

    @staticmethod
    def _pfad_kurz(pfad) -> str:
        t = pfad.decode(errors="replace") if isinstance(pfad, bytes) else str(pfad)
        return t if len(t) < 60 else "…" + t[-50:]

    def oeffnen(self) -> None:
        try:
            import hid  # noqa: F401
        except ImportError as e:
            raise VerbindungsFehler("USB-HID fehlt in dieser Fassung (Paket „hidapi“).") from e
        fehler = None
        for i in range(0, len(self.wege), 2):          # je Schnittstelle einmal öffnen
            self.weg = i
            try:
                self._aufmachen()
                return
            except Exception as e:
                fehler = e
                log.warning("USB-HID: %s lässt sich nicht öffnen: %s", self._pfad_kurz(self.wege[i][0]), e)
        raise VerbindungsFehler(hid_hinweis() + f"\n\n({fehler})")

    def _aufmachen(self) -> None:
        import hid
        pfad = self.wege[self.weg][0]
        d = hid.device()
        d.open_path(pfad.encode() if isinstance(pfad, str) else pfad)
        self._d = d
        try:
            zeile = f"USB-HID: {d.get_manufacturer_string() or '?'} / {d.get_product_string() or '?'}"
            if zeile not in self.info:
                self.info.append(zeile)
        except Exception:
            pass
        self._laeuft = True
        self._faden = threading.Thread(target=self._lesen, args=(d,), name="hid", daemon=True)
        self._faden.start()
        log.info("USB-HID: Weg %d/%d – %s", self.weg + 1, len(self.wege), self.weg_text)

    def _zumachen(self) -> None:
        # Erst den Lesefaden auslaufen lassen, dann schließen: ein close() unter
        # einem laufenden read() bringt hidapi unter Windows zum Absturz
        self._laeuft = False
        f, self._faden = self._faden, None
        if f and f is not threading.current_thread():
            f.join(2)
        d, self._d = self._d, None
        if d:
            try:
                d.close()
            except Exception:
                pass

    def naechster_weg(self) -> bool:
        """Auf den nächsten Weg wechseln. False, wenn alle probiert sind."""
        while self.weg + 1 < len(self.wege):
            neue_schnittstelle = self.wege[self.weg + 1][0] != self.wege[self.weg][0]
            self.weg += 1
            if not neue_schnittstelle:
                log.info("USB-HID: Weg %d/%d – %s", self.weg + 1, len(self.wege), self.weg_text)
                return True
            self._zumachen()
            try:
                self._aufmachen()
                return True
            except Exception as e:
                log.warning("USB-HID: %s lässt sich nicht öffnen: %s", self._pfad_kurz(self.wege[self.weg][0]), e)
        return False

    def _lesen(self, d) -> None:
        while self._laeuft:
            try:
                daten = d.read(64, 200)
            except Exception as e:
                if self._laeuft:
                    self._laeuft = False
                    self._abgerissen(f"USB-Verbindung getrennt ({e})")
                return
            if daten and self._laeuft:
                self._empfangen(bytes(daten))

    def schreiben(self, daten: bytes) -> None:
        with self._sperre:
            if not self._d:
                raise VerbindungsFehler("nicht verbunden")
            from .protokoll import HID_HIN, VERBOTEN
            if len(daten) >= 4 and daten[0] == HID_HIN and daten[3] in VERBOTEN:
                raise VerbindungsFehler(f"Befehl {daten[3]:02X} ist gesperrt (Update/Werkseinstellung)")
            art = self.wege[self.weg][1]
            paket = (b"\x00" + bytes(daten)) if art == "null" else bytes(daten)
            try:
                n = self._d.write(paket)
            except Exception as e:
                n = -1
                log.info("USB-HID: schreiben (%s) ging nicht: %s", self.weg_text, e)
            if n is None or n < 0:
                # Kein Abbruch: geraet.py merkt es an der fehlenden Antwort
                # und probiert den nächsten Weg
                log.info("USB-HID: schreiben (%s) -> %s", self.weg_text, n)

    def schliessen(self) -> None:
        self._zumachen()


def hid_anschluesse() -> list[Anschluss]:
    try:
        import hid
        from .protokoll import HID_PID, HID_VID
        geraete = hid.enumerate(HID_VID, HID_PID)
    except Exception as e:
        log.info("USB-HID: Suche ging nicht: %s", e)
        return []
    pfade = []
    for g in geraete:
        log.info("USB-HID gefunden: Schnittstelle %s, Usage %04X/%04X, %s, %r",
                 g.get("interface_number"), g.get("usage_page") or 0, g.get("usage") or 0,
                 g.get("product_string"), g.get("path"))
        if g.get("path") and g["path"] not in pfade:
            pfade.append(g["path"])
    if not pfade:
        return []
    name = geraete[0].get("product_string") or "DL24"
    return [Anschluss("hid", pfade[0], f"USB: {name} (genau, 1 mV)", pfade)]


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
                    Anschluss("ble", adresse, f"Bluetooth: {name} ({adresse})", geraet)))
    aus.sort(key=lambda x: (x[0], x[1]))          # DL24 zuerst
    return [a for *_, a in aus]


def _standard(uuid: str) -> bool:
    """Von der Bluetooth-Norm festgelegte Dienste (Gerätename, Akku, …): 0x18xx."""
    u = uuid.lower()
    return u.endswith("-0000-1000-8000-00805f9b34fb") and u[4:6] == "18"


def _kurz(uuid: str) -> str:
    u = uuid.lower()
    return u[4:8].upper() if u.endswith("-0000-1000-8000-00805f9b34fb") and u.startswith("0000") else u


class Bluetooth(Verbindung):
    def __init__(self, adresse: str, geraet=None) -> None:
        super().__init__()
        self.adresse = adresse
        self.geraet = geraet
        self._client = None
        self._schreib = None
        self._getrennt_gewollt = False
        self.info: list[str] = []
        self._quellen: set[str] = set()

    def _von(self, uuid: str, daten: bytes) -> None:
        if uuid not in self._quellen:          # einmal sagen, woher die Daten kommen
            self._quellen.add(uuid)
            log.info("BLE: erste Daten über %s", uuid)
        self._empfangen(daten)

    def oeffnen(self) -> None:
        from bleak import BleakClient

        def getrennt(_c):
            if not self._getrennt_gewollt:
                self._abgerissen("Bluetooth-Verbindung getrennt")

        async def verbinden():
            # Das Gerät aus der Suche nehmen statt der Adresse: mit der Adresse sucht
            # bleak noch einmal, und sendet das Modul gerade nicht, heißt es
            # "was not found" - so bei Lucy unter Windows. Klappt es nicht, einmal
            # frisch suchen und noch einmal.
            ziel = self.geraet or self.adresse
            try:
                client = BleakClient(ziel, disconnected_callback=getrennt)
                await client.connect(timeout=20)
            except Exception as erster:
                log.warning("BLE: erster Versuch: %s - suche neu", erster)
                self.info.append(f"erster Versuch ging nicht ({erster}), suche neu")
                from bleak import BleakScanner
                neu = await BleakScanner.find_device_by_address(self.adresse, timeout=15)
                if neu is None:
                    raise VerbindungsFehler(
                        f"Der DL24 ({self.adresse}) sendet gerade nicht.\n\n"
                        "• DL24 kurz aus- und wieder einschalten\n"
                        "• Ist er noch mit dem Handy oder mit Windows verbunden? "
                        "Dann dort trennen bzw. unter Bluetooth-Geräte entfernen.") from erster
                client = BleakClient(neu, disconnected_callback=getrennt)
                await client.connect(timeout=20)
            # Alles auflisten, was das Modul anbietet - landet im Diagnose-Reiter.
            # Auf jeder Eigenschaft lauschen, die melden kann: welche der DL24
            # wirklich benutzt, ist je nach Modul verschieden.
            melden, schreiben = [], None
            for dienst in client.services:
                self.info.append(f"Dienst {_kurz(dienst.uuid)}" + (" (Standard)" if _standard(dienst.uuid) else ""))
                for e in dienst.characteristics:
                    self.info.append(f"   Eigenschaft {_kurz(e.uuid)}: {', '.join(e.properties)}")
                    if _standard(dienst.uuid):
                        continue          # Gerätename, Akku usw. - nie hineinschreiben
                    if "notify" in e.properties or "indicate" in e.properties:
                        melden.append(e)
                    kann_schreiben = "write-without-response" in e.properties or "write" in e.properties
                    if kann_schreiben and (schreiben is None or e.uuid.lower() == BLE_EIGENSCHAFT):
                        schreiben = e
            if not melden:
                await client.disconnect()
                raise VerbindungsFehler("Das Gerät bietet keine Bluetooth-Eigenschaft zum Melden an.\n\n"
                                        + "\n".join(self.info))
            for e in melden:
                try:
                    await client.start_notify(e, lambda _h, d, u=_kurz(e.uuid): self._von(u, bytes(d)))
                    self.info.append(f"lausche auf {_kurz(e.uuid)}")
                except Exception as fehler:
                    self.info.append(f"lauschen auf {_kurz(e.uuid)} ging nicht: {fehler}")
            self.info.append(f"schreibe auf {_kurz(schreiben.uuid) if schreiben else '– (keine gefunden)'}")
            for zeile in self.info:
                log.info("BLE: %s", zeile)
            return client, schreiben

        try:
            self._client, self._schreib = _AsyncSchleife.ausfuehren(verbinden(), 70)
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
    if anschluss.art == "hid":
        v: Verbindung = UsbHid(anschluss.adresse, anschluss.geraet)
    elif anschluss.art == "usb":
        v = Seriell(anschluss.adresse)
    elif anschluss.art == "ble":
        v = Bluetooth(anschluss.adresse, anschluss.geraet)
    elif anschluss.art == "sim":
        from .simulator import SimNetzteil, SimulatorVerbindung
        art = anschluss.adresse.split(":")[1] if ":" in anschluss.adresse else "px100"
        if art == "netzteil":
            # USB-Ladegerät 5 V / 2 A, das bei 2,6 A abschaltet - über USB-HID wie der echte DL24
            v = SimulatorVerbindung(protokoll="hid", akku=SimNetzteil(5.0, innen_mohm=120, abschalt_a=2.6))
        else:
            v = SimulatorVerbindung(protokoll=art)
    else:
        raise VerbindungsFehler(f"unbekannte Art {anschluss.art}")
    v.oeffnen()
    return v
