# DL24 Akkutest

Desktop-Programm für die elektronische Last **Atorch DL24**: Akkus entladen, die
echte Kapazität messen und sehen, wie viel sie gegenüber neu verloren haben.

- **Akku auswählen**: Typ (Li-Ion, LiPo, LiFePO4, NiMH, Blei), Zellenzahl,
  Nennkapazität – oder eine bekannte Zelle aus der Liste (Samsung 30Q, LG MJ1,
  Molicel P42A, Eneloop …), dann steht alles schon drin
- **Typ erkennen** aus der Leerlaufspannung eines voll geladenen Akkus
  (z. B. „12,6 V → 3× Li-Ion oder 6× Blei“, du bestätigst)
- **Test**: Abschaltspannung und Strom kommen aus dem Typ (0,2C / 0,5C / 1C
  per Knopf), Live-Kurve, Ende automatisch an der Abschaltspannung
- **Ergebnis**: gemessene mAh und Wh, **Zustand in %** der Nennkapazität,
  **Verlust**, **Innenwiderstand**, Bewertung
- **Verlauf** je Akku: alle Tests mit Kapazität über die Zeit und übereinander
  gelegten Entladekurven, Export als CSV
- **USB und Bluetooth** (BLE; ältere Geräte mit Kopplungs-PIN erscheinen nach
  dem Koppeln als serieller Anschluss)
- **Simulator** zum Ausprobieren ohne Gerät
- **Diagnose**-Reiter: zeigt roh, was über die Leitung geht

## Installieren

Im [neuesten Release](../../releases/latest):

- **Linux**: `dl24-akkutest-arch-installer.desktop` (Arch/CachyOS/Manjaro),
  `dl24-akkutest-deb-installer.desktop` (Debian/Ubuntu/Mint) oder
  `dl24-akkutest-installer.desktop` (alle anderen) herunterladen und doppelklicken.
  Ein zweiter Doppelklick bietet Update oder Deinstallation an.
- **Windows**: `dl24-akkutest-setup.exe`. SmartScreen warnt vor unsignierten
  Programmen: „Weitere Informationen → Trotzdem ausführen“.

### USB unter Linux

Der DL24 meldet sich als `/dev/ttyUSB0` (Chip CH340). Dein Benutzer braucht
Zugriff darauf – unter Arch/CachyOS über die Gruppe `uucp`, unter
Debian/Ubuntu über `dialout`:

```bash
sudo usermod -aG uucp $USER     # Debian/Ubuntu: dialout
```

Danach ab- und wieder anmelden. Das Programm sagt es dir auch, wenn der Zugriff fehlt.

### Bluetooth

„Bluetooth suchen“ findet den DL24 (BLE). Er kann nur mit **einem** Gerät
gleichzeitig verbunden sein – vorher die Handy-App trennen.

## So testest du einen Akku

1. Akku **voll laden** (der DL24 entlädt nur).
2. Anschließen, im Programm verbinden.
3. Akku wählen: neu anlegen (Name, z. B. „Zelle #3“) oder aus der Liste nehmen.
   Modell aus der Liste wählen oder Typ, Zellen und mAh vom Aufdruck eintragen.
   Ohne Nennkapazität gibt es die gemessenen mAh, aber keinen Prozentwert.
4. **Test starten.** Das Programm misst die Leerlaufspannung, stellt Strom und
   Abschaltspannung am Gerät ein und schaltet die Last ein.
5. Am Ende stehen Kapazität, Zustand, Verlust und Innenwiderstand da. Der Test
   wird beim Akku gespeichert, beim nächsten Mal siehst du die Veränderung.

**Vergleichbar** sind Tests nur bei gleichem Strom: Bei höherem Strom kommt
weniger heraus. Herstellerangaben sind meist bei 0,2C gemessen, 0,5C liegt
etwas darunter.

## Zwei Arten DL24

Je nach Fassung und Firmware lässt sich der DL24 **fernsteuern** oder schickt
**nur Messwerte**. Das Programm probiert beim Verbinden beides und zeigt oben,
was geklappt hat:

| Anzeige | Bedeutung |
|---|---|
| ✔ fernsteuerbar (PX100) | Das Programm stellt Strom und Abschaltspannung ein, schaltet die Last an und aus und misst in mV-Auflösung. |
| ✔ nur Messwerte (Atorch-Bericht) | Strom und Abschaltspannung stellst du **am Gerät** ein und startest dort. Das Programm sagt dir die Werte, misst mit und erkennt das Ende. Die Spannung kommt nur in 0,1-V-Schritten, deshalb gibt es hier keinen Innenwiderstand. |

Antwortet das Gerät gar nicht oder kommen seltsame Werte: im Reiter
**Diagnose** ein paar Sekunden mitlaufen lassen und den Inhalt kopieren.

## Daten

Eine SQLite-Datei, dazu ein Protokoll `akkutest.log`:

- Linux: `~/.local/share/dl24-akkutest/`
- Windows: `%APPDATA%\dl24-akkutest\`

## Aus dem Quellcode starten

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python start.py
tests/alle.sh       # Tests, laufen mit dem Simulator ohne Gerät
```

Stand: 14.11.2026
