"""Akkus und ihre Tests, in einer SQLite-Datei im Benutzerordner.

Linux:   ~/.local/share/dl24-akkutest/akkus.db
Windows: %APPDATA%\\dl24-akkutest\\akkus.db
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def datenordner() -> Path:
    if os.environ.get("AKKUTEST_DATEN"):
        p = Path(os.environ["AKKUTEST_DATEN"])
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home())) / "dl24-akkutest"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "dl24-akkutest"
    p.mkdir(parents=True, exist_ok=True)
    return p


# Neue Spalten nur hinten anhängen, mit Standardwert - alte Dateien müssen
# nach einem Update weiter funktionieren.
SCHEMA = """
CREATE TABLE IF NOT EXISTS akkus (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    typ TEXT NOT NULL,
    zellen INTEGER NOT NULL DEFAULT 1,
    nenn_mah INTEGER NOT NULL DEFAULT 0,
    modell TEXT NOT NULL DEFAULT '',
    notiz TEXT NOT NULL DEFAULT '',
    angelegt REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY,
    akku_id INTEGER NOT NULL REFERENCES akkus(id) ON DELETE CASCADE,
    wann REAL NOT NULL,
    strom_a REAL NOT NULL,
    abschalt_v REAL NOT NULL,
    nenn_mah INTEGER NOT NULL DEFAULT 0,
    mah REAL NOT NULL,
    wh REAL NOT NULL,
    dauer_s REAL NOT NULL,
    leerlauf_v REAL,
    ende_v REAL,
    innen_mohm REAL,
    vollstaendig INTEGER NOT NULL DEFAULT 1,
    grund TEXT NOT NULL DEFAULT '',
    kurve TEXT NOT NULL DEFAULT '[]'
);
"""


@dataclass
class Akku:
    id: int
    name: str
    typ: str
    zellen: int
    nenn_mah: int
    modell: str
    notiz: str
    angelegt: float


class Speicher:
    def __init__(self, pfad: Path | None = None) -> None:
        self.pfad = pfad or datenordner() / "akkus.db"
        self.db = sqlite3.connect(self.pfad, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- Akkus ----
    def akkus(self) -> list[Akku]:
        return [Akku(**dict(r)) for r in self.db.execute("SELECT * FROM akkus ORDER BY name COLLATE NOCASE")]

    def akku(self, akku_id: int) -> Akku | None:
        r = self.db.execute("SELECT * FROM akkus WHERE id=?", (akku_id,)).fetchone()
        return Akku(**dict(r)) if r else None

    def akku_anlegen(self, name: str, typ: str, zellen: int, nenn_mah: int, modell: str = "", notiz: str = "") -> int:
        c = self.db.execute("INSERT INTO akkus (name, typ, zellen, nenn_mah, modell, notiz, angelegt) "
                            "VALUES (?,?,?,?,?,?,?)", (name, typ, zellen, nenn_mah, modell, notiz, time.time()))
        self.db.commit()
        return c.lastrowid

    def akku_aendern(self, akku_id: int, **felder) -> None:
        erlaubt = {"name", "typ", "zellen", "nenn_mah", "modell", "notiz"}
        felder = {k: v for k, v in felder.items() if k in erlaubt}
        if felder:
            self.db.execute(f"UPDATE akkus SET {', '.join(f'{k}=?' for k in felder)} WHERE id=?",
                            (*felder.values(), akku_id))
            self.db.commit()

    def akku_loeschen(self, akku_id: int) -> None:
        self.db.execute("DELETE FROM akkus WHERE id=?", (akku_id,))
        self.db.commit()

    def naechster_name(self, vorlage: str) -> str:
        namen = {a.name for a in self.akkus()}
        n = 1
        while f"{vorlage} #{n}" in namen:
            n += 1
        return f"{vorlage} #{n}"

    # ---- Tests ----
    def test_speichern(self, akku_id: int, einstellung, ergebnis, punkte, wann: float) -> int:
        e, r = einstellung, ergebnis
        c = self.db.execute(
            "INSERT INTO tests (akku_id, wann, strom_a, abschalt_v, nenn_mah, mah, wh, dauer_s, leerlauf_v, "
            "ende_v, innen_mohm, vollstaendig, grund, kurve) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (akku_id, wann, e.strom_a, e.abschalt_v, e.nenn_mah, round(r.mah, 1), round(r.wh, 3),
             round(r.dauer_s), r.leerlauf_v, r.ende_v, r.innen_mohm, int(r.vollstaendig), r.grund,
             json.dumps(_ausduennen(punkte))))
        self.db.commit()
        return c.lastrowid

    def tests(self, akku_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM tests WHERE akku_id=? ORDER BY wann", (akku_id,))]

    def test_loeschen(self, test_id: int) -> None:
        self.db.execute("DELETE FROM tests WHERE id=?", (test_id,))
        self.db.commit()

    def letzter_test(self, akku_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM tests WHERE akku_id=? AND vollstaendig=1 ORDER BY wann DESC LIMIT 1",
                            (akku_id,)).fetchone()
        return dict(r) if r else None

    def csv_schreiben(self, pfad: Path) -> int:
        zeilen = self.db.execute(
            "SELECT a.name, a.modell, a.typ, a.zellen, t.wann, t.nenn_mah, t.mah, t.wh, t.dauer_s, t.strom_a, "
            "t.abschalt_v, t.leerlauf_v, t.ende_v, t.innen_mohm, t.vollstaendig, t.grund "
            "FROM tests t JOIN akkus a ON a.id=t.akku_id ORDER BY a.name, t.wann").fetchall()
        with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Akku", "Modell", "Typ", "Zellen", "Datum", "Nenn mAh", "Gemessen mAh", "Zustand %",
                        "Wh", "Dauer min", "Strom A", "Abschaltung V", "Leerlauf V", "Ende V", "Innenwid. mOhm",
                        "Vollständig", "Ende"])
            for z in zeilen:
                proz = f"{z['mah'] / z['nenn_mah'] * 100:.1f}".replace(".", ",") if z["nenn_mah"] else ""
                zahl = lambda x, n=2: "" if x is None else f"{x:.{n}f}".replace(".", ",")
                w.writerow([z["name"], z["modell"], z["typ"], z["zellen"],
                            time.strftime("%d.%m.%Y %H:%M", time.localtime(z["wann"])), z["nenn_mah"] or "",
                            zahl(z["mah"], 0), proz, zahl(z["wh"]), zahl(z["dauer_s"] / 60, 0), zahl(z["strom_a"]),
                            zahl(z["abschalt_v"]), zahl(z["leerlauf_v"], 3), zahl(z["ende_v"], 3),
                            zahl(z["innen_mohm"], 1), "ja" if z["vollstaendig"] else "nein", z["grund"]])
        return len(zeilen)


def _ausduennen(punkte: list, hoechstens: int = 2000) -> list:
    """Ein Test über 10 Stunden hat 36.000 Punkte. Für die Kurve reichen 2000."""
    if len(punkte) <= hoechstens:
        return list(punkte)
    schritt = len(punkte) / hoechstens
    aus = [punkte[int(i * schritt)] for i in range(hoechstens)]
    aus[-1] = punkte[-1]
    return aus
