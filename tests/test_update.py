"""Updater: Versionsvergleich, Prüfsumme, Austausch der Programmdatei - ohne Netz."""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from akkutest import aktualisieren as a


def release(version, daten, summe=None):
    digest = "sha256:" + (summe or hashlib.sha256(daten).hexdigest())
    return {"version": version, "notizen": "",
            "anhaenge": {a.LINUX_DATEI: {"browser_download_url": "x/linux", "digest": digest}}}


def test_versionen():
    assert a.version_tupel("v1.0.10") > a.version_tupel("1.0.9")
    assert a.version_tupel("1.0.51") == (1, 0, 51)


def test_pruefen():
    alt = a.neuestes_release
    try:
        a.neuestes_release = lambda: release("99.0.0", b"x")
        s = a.pruefen()
        assert s["neuer"] and s["verfuegbar"] == "99.0.0" and not s["fehler"]
        a.neuestes_release = lambda: release(a.VERSION, b"x")
        assert not a.pruefen()["neuer"]
    finally:
        a.neuestes_release = alt


def test_einspielen_linux():
    if sys.platform == "win32":
        return
    ordner = Path(tempfile.mkdtemp())
    prog = ordner / "dl24-akkutest-linux"
    prog.write_bytes(b"alt")
    neu = b"neue Fassung"
    alt_rel, alt_ab, alt_exe = a.neuestes_release, a._abrufen, sys.executable
    sys.frozen = True
    try:
        sys.executable = str(prog)
        a._abrufen = lambda url, roh=False, grenze=0: neu
        # falsche Prüfsumme: nichts wird ersetzt
        a.neuestes_release = lambda: release("99.0.0", neu, summe="0" * 64)
        try:
            a.einspielen()
            raise AssertionError("falsche Prüfsumme nicht erkannt")
        except RuntimeError as f:
            assert "Prüfsumme" in str(f)
        assert prog.read_bytes() == b"alt"
        # richtig: Datei ersetzt, ausführbar
        a.neuestes_release = lambda: release("99.0.0", neu)
        assert a.einspielen() == "99.0.0"
        assert prog.read_bytes() == neu and os.access(prog, os.X_OK)
        # nichts Neueres: abgelehnt
        a.neuestes_release = lambda: release("0.0.1", neu)
        try:
            a.einspielen()
            raise AssertionError("ältere Fassung eingespielt")
        except RuntimeError as f:
            assert "Nichts Neueres" in str(f)
    finally:
        a.neuestes_release, a._abrufen, sys.executable = alt_rel, alt_ab, alt_exe
        del sys.frozen


def test_quellordner_nicht():
    assert not a.aktualisierbar()
    try:
        a.einspielen()
        raise AssertionError
    except RuntimeError as f:
        assert "Quellordner" in str(f)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
