"""Nachsehen, ob auf GitHub eine neuere Fassung liegt - und sie einspielen.

Nach dem Vorbild der Notizmappe. Nur urllib und hashlib.

  Windows: dl24-akkutest-setup.exe holen, gegen die .sha256 am Release prüfen,
           still installieren (das Setup beendet das laufende Programm) und neu starten.
  Linux:   die neue Programmdatei holen, gegen die Prüfsumme von GitHub prüfen,
           die laufende Datei ersetzen und neu starten.

Aus dem Quellordner (nicht gebündelt) wird nicht aktualisiert - das geht mit git.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("akkutest.update")

QUELLE = os.environ.get("AKKUTEST_QUELLE", "https://api.github.com/repos/LucyWolf/dl24-akkutest")
VERSION = (Path(__file__).resolve().parent / "VERSION").read_text().strip()
MAX_PAKET = 300 * 1024 * 1024
LINUX_DATEI = "dl24-akkutest-linux"
SETUP = "dl24-akkutest-setup.exe"


def version_tupel(roh: str) -> tuple[int, ...]:
    """'v1.0.10' -> (1, 0, 10): stellenweise als Zahl, sonst wäre 1.0.9 größer als 1.0.10."""
    teile = re.findall(r"\d+", str(roh or ""))
    return tuple(int(t) for t in teile[:4]) or (0,)


def aktualisierbar() -> bool:
    """Nur das gebündelte Programm tauscht sich selbst aus."""
    return bool(getattr(sys, "frozen", False))


def _abrufen(url: str, roh: bool = False, grenze: int = MAX_PAKET):
    anfrage = urllib.request.Request(url, headers={
        "Accept": "application/octet-stream" if roh else "application/vnd.github+json",
        "User-Agent": f"DL24-Akkutest/{VERSION}",
    })
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:
        daten = antwort.read(grenze + 1)
    if len(daten) > grenze:
        raise ValueError("Antwort ist größer als erlaubt")
    return daten if roh else json.loads(daten)


def neuestes_release() -> dict:
    r = _abrufen(f"{QUELLE}/releases/latest")
    anhaenge = {a.get("name", ""): a for a in r.get("assets") or []}
    return {
        "version": re.sub(r"^v", "", r.get("tag_name") or ""),
        "notizen": (r.get("body") or "")[:4000],
        "anhaenge": anhaenge,
    }


def pruefen() -> dict:
    """{'installiert', 'verfuegbar', 'neuer', 'fehler'}"""
    stand = {"installiert": VERSION, "verfuegbar": None, "neuer": False, "fehler": None,
             "aktualisierbar": aktualisierbar()}
    try:
        r = neuestes_release()
        stand["verfuegbar"] = r["version"] or None
        stand["neuer"] = version_tupel(r["version"]) > version_tupel(VERSION)
    except urllib.error.HTTPError as f:
        stand["fehler"] = (f"GitHub lässt gerade keine Anfragen zu ({f.code}) – später noch einmal versuchen"
                           if f.code in (403, 429) else f"GitHub antwortet mit {f.code}")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as f:
        stand["fehler"] = f"GitHub nicht erreichbar: {f}"
    return stand


def _soll_summe(anhaenge: dict, name: str) -> str | None:
    """Prüfsumme: aus der .sha256-Datei am Release, sonst die, die GitHub selbst nennt."""
    datei = anhaenge.get(name + ".sha256")
    if datei:
        try:
            text = _abrufen(datei["browser_download_url"], roh=True, grenze=4096).decode("utf-8", "ignore")
            treffer = re.search(r"\b([0-9a-fA-F]{64})\b", text)
            if treffer:
                return treffer.group(1).lower()
        except Exception:
            log.exception("Prüfsummendatei")
    digest = (anhaenge.get(name) or {}).get("digest") or ""
    return digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None


def einspielen() -> str:
    """Neue Fassung holen, prüfen, einspielen und neu starten. Gibt die neue Version zurück;
    danach beendet sich das Programm."""
    if not aktualisierbar():
        raise RuntimeError("Läuft aus dem Quellordner – hier wird mit git aktualisiert.")
    r = neuestes_release()
    if version_tupel(r["version"]) <= version_tupel(VERSION):
        raise RuntimeError(f"Nichts Neueres da (installiert {VERSION}, im Release {r['version'] or '?'})")
    fenster = sys.platform == "win32"
    name = SETUP if fenster else LINUX_DATEI
    anhang = r["anhaenge"].get(name)
    if not anhang:
        raise RuntimeError(f"Am Release hängt keine {name}")
    soll = _soll_summe(r["anhaenge"], name)
    if not soll:
        raise RuntimeError("Für die Datei gibt es keine Prüfsumme – Update abgebrochen")
    daten = _abrufen(anhang["browser_download_url"], roh=True)
    echt = hashlib.sha256(daten).hexdigest()
    if echt != soll:
        raise RuntimeError(f"Prüfsumme passt nicht (erwartet {soll[:12]}…, geladen {echt[:12]}…)")
    log.info("Update %s -> %s, Prüfsumme %s", VERSION, r["version"], echt[:12])

    if fenster:
        ziel = Path(tempfile.mkdtemp(prefix="dl24-update-")) / name
        ziel.write_bytes(daten)
        # Als Stapeldatei: das Setup beendet uns (taskkill), installiert still und danach
        # startet die Datei die neue Fassung. Abgekoppelt, ohne Konsolenfenster.
        mitschrift = ziel.with_name("update.log")
        stapel = ziel.with_suffix(".cmd")
        stapel.write_text(
            "@echo off\r\n"
            f'"{ziel}" /SILENT /SUPPRESSMSGBOXES /NORESTART /LOG="{mitschrift}"\r\n'
            "timeout /t 3 /nobreak >nul\r\n"
            f'"{sys.executable}"\r\n', encoding="ascii", errors="replace")
        subprocess.Popen(["cmd", "/c", str(stapel)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x08000000 | 0x00000200,
                         cwd=str(ziel.parent))
        threading.Timer(1.5, lambda: os._exit(0)).start()
        return r["version"]

    # Linux: die laufende Datei ersetzen - unter Linux geht das, der laufende Prozess
    # behält die alte bis zum Neustart. Erst daneben schreiben, dann in einem Schritt tauschen.
    jetzt = Path(sys.executable).resolve()
    neu = jetzt.with_name(jetzt.name + ".neu")
    try:
        neu.write_bytes(daten)
        neu.chmod(0o755)
        os.replace(neu, jetzt)
    except OSError as f:
        neu.unlink(missing_ok=True)
        raise RuntimeError(f"Programmdatei ließ sich nicht ersetzen ({jetzt}): {f}")
    return r["version"]


def neu_starten() -> None:
    """Nach dem Linux-Update: die neue Datei an Stelle dieses Prozesses starten."""
    os.execv(sys.executable, [sys.executable] + sys.argv[1:])
