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
- **USB und Bluetooth**: DL24/P mit Farbdisplay über das USB-Kabel (Spannung
  auf 1 mV genau) oder per Bluetooth (BLE, nur 0,1 V); ältere Geräte mit
  CH340-Chip als serieller Anschluss
- **Ladegeräte, Netzteile, USB-Hubs prüfen**: Angaben vom Typenschild
  eintragen (oder Vorlage wählen) und prüfen, ob das Gerät sie hält – mit
  Stufentest, Dauertest mit Temperatur und Abschalttest
- **Steuerung von Hand** wie in der Atorch-Software: Strom und Abschaltspannung
  einstellen, Start/Stop, Zähler nullen (USB)
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

### USB

Der **DL24/P mit 2,4"-Farbdisplay** meldet sich am USB-Kabel nicht als
COM-Anschluss, sondern als HID-Gerät (`0483:5750`). Er steht in der Liste als
„USB: … (genau, 1 mV)“. Über diesen Weg kommt die Spannung so genau wie auf dem
Display – über Bluetooth nur auf 0,1 V. Die Atorch-PC-Software muss dafür
geschlossen sein, sie hält das Gerät sonst fest.

Unter Linux braucht der Benutzer Zugriff auf das HID-Gerät, einmal:

```bash
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5750", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/70-dl24.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Danach das Kabel ab- und wieder anstecken.

Ältere DL24 mit CH340-Chip melden sich als `/dev/ttyUSB0`. Dein Benutzer braucht
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

## So prüfst du ein Ladegerät oder Netzteil

Geht nur, wenn das Programm die Last stellen kann: DL24 **über das USB-Kabel**
verbunden (oder ein PX100).

1. Den Ausgang des Ladegeräts an den Eingang des DL24 anschließen. Bei USB über
   einen USB-Adapter mit Klemmen.
2. Wer die Temperatur messen will: den **Fühler des DL24** mit Klebeband ans
   Gehäuse des Ladegeräts kleben und bei den Tests „Temperaturfühler“
   ankreuzen. Dann wird bei der eingestellten Grenze abgebrochen. Ohne Haken
   bleibt die Temperatur außen vor.
3. Reiter **Ladegeräte & Netzteile**: eine Vorlage wählen oder Spannung und
   Strom **oder** Watt vom Typenschild eintragen – das andere rechnet das
   Programm aus. Steht nichts drauf: „Strom/Leistung steht nicht drauf“
   ankreuzen. Erst dann lassen sich die Tests einstellen. Die Toleranz ist 5 %,
   bei 5 V also 4,75–5,25 V.
4. Tests wählen:

| Test | Was passiert |
|---|---|
| Stufentest | Strom in Stufen von 10 % bis 100 % der Angabe. Zeigt, wie weit die Spannung unter Last sinkt. |
| Dauertest | Ein fester Strom über längere Zeit, mit Temperatur. Zeigt, ob das Gerät warm wird und dann nachgibt. |
| Abschalttest | Über die Angabe hinaus in 5-%-Schritten, bis das Gerät abschaltet oder die Spannung einbricht – höchstens bis zur eingestellten Grenze. |

   Eigene Geräte lassen sich mit **„Speichern“** neben der Vorlagenliste als
   Vorlage ablegen (★) – beim nächsten Mal einfach auswählen.
5. **Prüfen.** Am Ende steht ein klares Urteil, dazu Kennlinie,
   Abschaltgrenze, größte Leistung und höchste Temperatur. Jede Prüfung wird
   gespeichert, mit **Bericht speichern (PDF)** lässt sie sich weitergeben.

| Urteil | Bedeutung |
|---|---|
| ✔ Empfehlenswert | Liefert den angegebenen Strom, die Spannung bleibt im vorgegebenen Bereich. |
| ⚠ Eingeschränkt verwendbar | Liefert den Strom, aber die Spannung an der Buchse liegt unter 4,75 V (über 4,40 V) oder im Leerlauf über 5,25 V – entspricht nicht den Vorgaben der USB-Spezifikation. Zum Laden meist in Ordnung, für empfindliche Geräte nicht. |
| ✘ Nicht verwenden | Schaltet vor dem angegebenen Strom ab, an der Buchse unter 4,40 V, im Leerlauf über 5,5 V (kann Geräte beschädigen) oder wird zu heiß. |
| ? Noch nicht entscheidbar | Am Kabelende kam zu wenig an, aber das Kabel ist nicht herausgerechnet – ob es am Gerät oder am Kabel liegt, ist offen. |

**Ampel:** Im Diagramm und in der Kennlinie zeigen Farben, wo die Spannung
liegt – grün in Ordnung, gelb außerhalb der Vorgabe, aber nutzbar, rot zu
niedrig oder zu hoch. Dazu je Stufe die **Schwankung** (grün bis 1 %, gelb bis
3 % – Einschätzung des Programms). Schnelles Brummen (Ripple) sieht der DL24
nicht, dafür braucht es ein Oszilloskop.

**USB-Hubs:** Geprüft wird immer nur der Port, an dem der DL24 steckt. Die
Angabe auf dem Hub gilt meist für alle Ports zusammen.

**Grundlage bei USB:** die USB-Spezifikation 2.0, Abschnitt 7.2.2 (auch als
Norm EN 62680-2-1 veröffentlicht): An einem Port mit eigener Stromversorgung
4,75–5,25 V, gemessen an der Buchse; 4,40 V nur bei Schwachstrom-Ports. Das ist
eine Vorgabe der Industrie, keine gesetzliche. Bei anderen Netzteilen gilt die
eingestellte Toleranz um die Angabe auf dem Typenschild.

Getrennt davon steht da, ob es **schafft, was es verspricht**, also den
angegebenen Strom ohne Abschalten liefert.

**Größte Leistung finden:** Beim Abschalttest „bis zur Abschaltung“ ankreuzen.
Dann wird gesteigert, bis das Gerät abschaltet oder einbricht – höchstens 5 A
bei USB und 150 W. **Vorsicht:** Dabei wird das Gerät absichtlich überlastet.
Gute Netzteile schalten einfach ab, billige ohne Schutzschaltung können
kaputtgehen oder sehr heiß werden. Nur unter Aufsicht, nichts Brennbares in der
Nähe – das Programm fragt vorher nach.

**Der Bericht (PDF)** ist für Leute ohne Fachwissen geschrieben: oben „Kurz
gesagt“ mit dem Urteil in einfachen Sätzen, dann was geprüft wurde und das
Diagramm, die Messwerte für Fachleute am Ende.

**Das Kabel zählt mit.** Gemessen wird am DL24, also hinter Kabel und Adapter.
Ein dünnes USB-Kabel verliert bei 2 A leicht 0,5 V. Damit das nicht dem
Netzteil angelastet wird: dasselbe Kabel an ein **gutes Ladegerät** stecken und
neben „Kabel + Adapter“ auf **„Kabel messen …“** drücken (oder nach einer
Prüfung „Widerstand als Kabelwert übernehmen“). Ab dann
wird das Kabel herausgerechnet, und das Urteil gilt für die Spannung an der
Buchse.

Abgebrochen wird sofort, wenn die Spannung zusammenbricht oder die
Temperaturgrenze erreicht ist. Der DL24 schafft höchstens 150 W.

**Steht kein Strom drauf?** Strom und Leistung auf „nicht angegeben“ lassen.
Dann ermittelt das Programm, wie viel das Gerät liefert: Es steigert den Strom in
0,25-A-Schritten, bis das Gerät abschaltet oder die Spannung einbricht.

### Schnellladegeräte (USB-PD, QC, Fast Charging)

9 V, 12 V, 15 V oder 20 V gibt ein Schnellladegerät nur heraus, wenn das
angeschlossene Gerät danach fragt. Das kann der DL24 nicht. Dafür steckt ein
**Trigger-Adapter** zwischen Ladegerät und DL24.

1. Haken bei **Schnellladegerät** setzen.
2. Die Spannungen ankreuzen, die geprüft werden sollen, und den Strom vom
   Aufdruck eintragen (z. B. „9 V ⎓ 2 A“). Steht nichts drauf: „unbekannt“
   lassen, dann wird ermittelt, wie viel es liefert.
3. **Prüfen.** Das Programm sagt jeweils an, welche Spannung am Adapter
   einzustellen ist, und beginnt, sobald sie anliegt. Kommt eine Spannung nicht,
   gilt sie nach 2 Minuten als nicht unterstützt. Mit „Kommt nicht –
   überspringen“ geht es sofort weiter.

Im Ergebnis steht, welche Spannungen das Ladegerät kann, was es bei jeder
liefert und ob es die Angaben hält. Kommen über den Adapter nur 5 V, kann es
kein Schnellladen.

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
