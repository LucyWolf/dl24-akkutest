# Changelog

## 1.0.22 – 15.11.2026

- **Bewertung bei USB nach der USB-Spezifikation** (USB 2.0 §7.2.2, auch
  EN 62680-2-1): 4,75–5,25 V an der Buchse. Liegt die Spannung nachweislich
  darunter, steht im Bericht, dass das Gerät **nicht den Vorgaben für die
  Spannung entspricht**. Die bisherige Grenze 4,4 V galt in der Spezifikation
  nur für Schwachstrom-Ports und war für Netzteile zu großzügig.
- **Ohne Kabelwert kein falsches Urteil:** Kommt am Kabelende zu wenig an, heißt
  es „Noch nicht entscheidbar“ – mit Anleitung, wie man es klärt. Vorher hieß es
  „Nicht verwenden“, auch wenn es am Kabel lag.
- Im Bericht steht „USB-Spezifikation“ statt „Norm“ – es ist keine gesetzliche
  Vorgabe.
- **Temperaturfühler wählbar:** Haken „Temperaturfühler“ bei den Tests,
  standardmäßig aus. Ohne Haken wird die Temperatur nicht ausgewertet.

## 1.0.21 – 15.11.2026

- **Bericht für alle verständlich:** oben „Kurz gesagt“ mit dem Urteil in
  einfachen Sätzen (was heißt das für angeschlossene Geräte?), dann was geprüft
  wurde und das Diagramm – hell, damit es sich drucken lässt. Die Messwerte für
  Fachleute stehen am Ende.
- Auch auf dem Bildschirm steht das Urteil jetzt in einfachen Sätzen.
- **Erst das Typenschild, dann die Tests:** Die Felder starten leer, die Tests
  lassen sich erst einstellen, wenn Spannung und Strom/Watt eingetragen sind
  oder „steht nicht drauf – ermitteln“ angekreuzt ist.
- **„bis zur Abschaltung“** beim Abschalttest nur mit Warnung und Rückfrage:
  Das Gerät wird absichtlich überlastet.
- Der Gerätename aus einer Vorlage stand doppelt im Bericht.

## 1.0.20 – 15.11.2026

- **Vollständiges Diagramm** bei der Netzteilprüfung: oben die Spannung, darunter
  Strom und Leistung, darunter die Temperatur (sobald ein Fühler steckt) – alle
  mit derselben Zeitachse und den Stufenlinien.
- Die Zeitachse zeigt von Anfang an die ganze geplante Dauer; die
  Spannungsachse richtet sich nach dem Betrieb, nicht nach dem Einbruch beim
  Abschalten.
- Restzeit in der Anzeige: „noch 7:30 · gesamt noch 0:08:40“ – damit ist klar,
  dass ein langer Dauertest nicht hängt.

## 1.0.19 – 15.11.2026

- **Klares Urteil** bei Netzteilen und Ladegeräten: ✔ Empfehlenswert,
  ⚠ Eingeschränkt verwendbar oder ✘ Nicht verwenden – mit Begründung. Getrennt
  davon: schafft es, was es verspricht? Zu hohe Spannung im Leerlauf (USB über
  5,5 V) gilt als gefährlich.
- **Größte Leistung finden:** Abschalttest „bis zum Ende“ steigert, bis das
  Gerät abschaltet (höchstens 5 A bei USB / 150 W). Im Ergebnis: größte Leistung
  in der Toleranz und bis zum Abschalten.
- **Kabel herausrechnen:** Widerstand aus der Kennlinie; mit „als Kabelwert
  übernehmen“ wird er bei den nächsten Prüfungen abgezogen, das Urteil gilt dann
  für die Spannung an der Buchse.
- **Bericht als PDF** mit Urteil, Werten, Kennlinie und Diagramm.
- Zahlen in den Meldungen mit Komma.

## 1.0.18 – 15.11.2026

- Im Diagramm der Netzteilprüfung steht an jedem Stufenwechsel eine Linie mit
  dem Strom (bei Schnellladegeräten mit der Spannung) – so ist klar, welcher
  Abschnitt zu welcher Stufe gehört. Auch bei gespeicherten Prüfungen.
- Vorlagen zeigen Spannung, Strom **und Watt**, dazu USB-Hubs (10/15/20 W).
- Strom und Leistung gleichen sich an: Watt eintragen stellt die Ampere ein,
  Ampere eintragen die Watt.

## 1.0.17 – 15.11.2026

- **Schnellladegeräte (USB-PD / QC / Fast Charging)** prüfen, mit einem
  Trigger-Adapter zwischen Ladegerät und DL24: Spannungen 5/9/12/15/20 V
  ankreuzen, je Spannung den Strom vom Aufdruck eintragen. Das Programm sagt an,
  welche Spannung am Adapter einzustellen ist, und prüft jede einzeln. Ergebnis:
  welche Spannungen das Ladegerät kann, was es jeweils liefert, ob es die
  Angaben hält – oder ob es gar kein Schnellladen kann.
- **Strom unbekannt?** Dann ermittelt das Programm, wie viel das Gerät liefert
  (in 0,25-A-Schritten bis zur Abschaltung, höchstens 5 A bei USB bzw. 150 W).
- Lange Ergebnisse lassen sich rollen statt abgeschnitten zu werden.

## 1.0.16 – 15.11.2026

- **Neu: Reiter „Steuerung“** – den DL24 von Hand bedienen wie in der
  Atorch-Software: Strom und Abschaltspannung einstellen, Start/Stop, Zähler
  nullen. Dazu alle Messwerte, auch Widerstand und die Temperatur von Gerät und
  Fühler. Stop geht immer und bricht auch einen laufenden Test ab.

## 1.0.15 – 15.11.2026

- **Neu: Ladegeräte, Netzteile und USB-Hubs prüfen** (eigener Reiter). Angaben
  vom Typenschild eintragen oder eine Vorlage wählen, dann wahlweise
  Stufentest, Dauertest und Abschalttest. Ergebnis: hält es die Angabe, wie weit
  sinkt die Spannung, wo schaltet es ab, wie warm wird es (Fühler des DL24).
  Sicher: Abbruch bei Spannungseinbruch und Temperaturgrenze, eigene
  Obergrenze für den Strom, höchstens 150 W. Alle Prüfungen werden gespeichert.
- Der Temperaturfühler des DL24 wird über USB jetzt mitgelesen.
- Simulator: zusätzlich ein USB-Ladegerät 5 V / 2 A zum Ausprobieren.

## 1.0.14 – 15.11.2026

- Die Statuszeile zeigte über USB „Firmware 0.0“. Das Feld im Messpaket ist bei
  Firmware v1.1.0 leer; die Fassung steht nur im Gerätenamen
  („ATORCH DL24 V1.1.0“) und wird jetzt von dort gelesen.
- Am echten DL24P (Firmware v1.1.0) geprüft: Messwerte über USB stimmen mit dem
  Display überein, 3 Nachkommastellen bei der Spannung.
- Korrektur zum Hinweis bei 1.0.13: Ein Gerät im Update-Modus kann durchaus
  Schaden nehmen, wenn danach ein Update angefangen und abgebrochen wird. Dann
  hilft nur das Neuaufspielen über den Notfallmodus des Chips.

## 1.0.13 – 15.11.2026

- **Wichtig für 1.0.11 und 1.0.12:** Beim Verbinden über USB schickten sie ein
  Paket, das für ein „Anmelden“ gehalten wurde. Tatsächlich ist es der Befehl
  „Firmware-Update starten“ aus der Atorch-Software: Der DL24 ging davon in den
  Update-Modus. Ohne Firmware-Datei wird nichts überschrieben – Kabel ziehen
  bzw. Gerät aus- und einschalten, dann startet er normal. Das Paket ist
  entfernt und lässt sich in der App nicht einmal mehr bauen, ebenso der Befehl
  für die Werkseinstellung.
- **Steuerung über USB**: Die App setzt beim Test über USB Strom und
  Abschaltspannung selbst, nullt die Zähler und schaltet die Last ein und aus –
  wie beim PX100. Die Befehle sind dieselben, die die Atorch-Software über ihre
  Knöpfe schickt.
- Sicherung: Fließt über USB deutlich mehr Strom als eingestellt, schaltet die
  App die Last sofort ab.

## 1.0.12 – 15.11.2026

- USB: Der DL24/P hat in 1.0.11 unter Windows nicht geantwortet. Die
  Atorch-Software spricht ihn über libusb an, die App über den Windows-Treiber,
  und der will die Pakete je nach Gerät mit oder ohne vorangestellte 00. Die App
  probiert jetzt beide Schreibweisen und alle HID-Schnittstellen des Geräts
  durch und schreibt ins Log, welcher Weg geantwortet hat.
- Absturz nach mehreren gescheiterten USB-Versuchen behoben: die Verbindung
  wurde geschlossen, während noch gelesen wurde.

## 1.0.11 – 15.11.2026

- **USB am DL24/P** (Farbdisplay): Das Gerät meldet sich am Kabel als
  HID-Gerät, nicht als COM-Anschluss. Die App findet es jetzt selbst und liest
  darüber Spannung und Strom auf 1 mV / 1 mA genau – so wie auf dem Display.
  Über Bluetooth kommt die Spannung nur in 0,1-V-Schritten. Das Protokoll
  stammt aus der Atorch-PC-Software; der DL24 meldet Entladestrom negativ,
  die App zeigt ihn positiv.
- Über USB fragt die App zweimal je Sekunde statt einmal.

## 1.0.10 – 14.11.2026

- Geräte, die nur Messwerte schicken (Atorch-Bericht), übertragen die
  Spannung in 0,1-V-Schritten. Die Anzeige zeigt dann eine Nachkommastelle
  statt „4,300 V“, was eine Genauigkeit vorgetäuscht hat, die es nicht gibt.

## 1.0.9 – 14.11.2026

- Enthält 1.0.7 und 1.0.8, die nie gebaut wurden.
- Die Kapazität kommt jetzt aus dem Zähler im Gerät (Stand am Ende minus
  Stand beim Start). Die eigene Rechnung aus Strom × Zeit lag bei
  unregelmäßig ankommenden Messwerten daneben; sie dient nur noch als
  Ersatz, wenn das Gerät keinen Zähler meldet.

## 1.0.8 – 14.11.2026 (nicht veröffentlicht)

- Enthält 1.0.7, die nie gebaut wurde.
- Die Live-Kurve konnte einen Fehler werfen, wenn gerade ein neuer Messwert
  ankam (x- und y-Werte verschieden lang).
- Lücken zwischen Messwerten (Bluetooth-Aussetzer) werden bei der Kapazität
  mitgezählt statt verschluckt.
- Ferngesteuerter Test: Schaltet das Gerät an der von der App gesetzten
  Grenze selbst ab, gilt der Test als vollständig.

## 1.0.7 – 14.11.2026 (nicht veröffentlicht)

- DL24 mit 2,4"-Farbdisplay wird erkannt. Er schickt die üblichen
  Atorch-Berichte, aber als Prüfsumme immer 23 – die App hat deshalb jeden
  Bericht verworfen. Die Prüfsumme wird nicht mehr verlangt; Bruchstücke
  erkennt die App daran, dass mittendrin das nächste Paket beginnt.

## 1.0.6 – 14.11.2026

- Sendet das Gerät Daten in einem Format, das die App nicht kennt, bleibt sie
  jetzt verbunden statt zu trennen, und sagt das oben an.
- Die empfangenen Rohdaten stehen zusätzlich in der Logdatei.

## 1.0.5 – 14.11.2026

- Bluetooth: „Device … was not found“ beim Verbinden. Die App suchte das Gerät
  beim Verbinden ein zweites Mal über die Adresse; sendete das Modul gerade
  nicht, schlug das fehl. Jetzt nimmt sie das Gerät aus der Suche und sucht
  bei einem Fehlschlag einmal neu. Findet sie es dann auch nicht, sagt sie,
  was zu tun ist.

## 1.0.4 – 14.11.2026

- Bluetooth: Hatte das Modul keinen Kanal FFE1, schrieb die App ihre Befehle
  in den ersten beschreibbaren Kanal – oft der Gerätename – und lauschte
  womöglich auf einem Standardkanal. Jetzt lauscht sie auf allen Datenkanälen
  und schreibt nie in Standarddienste.
- Diagnose zeigt beim Bluetooth-Verbinden alle Dienste und Kanäle des Moduls,
  und Verbindungsfehler stehen dort auch.

## 1.0.3 – 14.11.2026

- Schaltet das Gerät am Ende selbst ab, gilt der Test jetzt bis 6 % über der
  Abschaltspannung als vollständig (vorher 4 %). Am Ende fällt die Spannung
  steil, und bei hohem Strom lag der letzte Messwert vor dem Abschalten
  darüber – ein vollständiger Test wäre als „vorzeitig“ gewertet worden.
- Enthält die Änderungen aus 1.0.2, die nie gebaut wurde.

## 1.0.2 – 14.11.2026 (nicht veröffentlicht)

- Im dunklen Windows-Design waren die Beschriftungen über den Messwerten und
  der Hinweis zum Akkutyp kaum zu sehen
- Leere Spannungskurve zeigte −400 bis 400 und „x0.001“ an der Achse

## 1.0.1 – 14.11.2026

Erste veröffentlichte Fassung. 1.0.0 wurde nie gebaut: ein Test las das
Ergebnis, bevor das Fenster es angezeigt hatte, und brach den Bau ab.

## 1.0.0 – 14.11.2026

Erste Fassung.

- Verbindung zum Atorch DL24 über USB und Bluetooth LE; erkennt, ob das Gerät
  fernsteuerbar ist (PX100) oder nur Messwerte schickt (Atorch-Bericht)
- Akkutypen mit passender Abschaltspannung, Liste bekannter Zellen,
  Typ-Erkennung aus der Leerlaufspannung
- Entladetest mit Live-Kurve, Zustand in % und Verlust, Innenwiderstand
- Akku-Verlauf mit Kapazität über die Zeit und Entladekurven, CSV-Export
- Simulator zum Ausprobieren ohne Gerät, Diagnose-Reiter mit Rohdaten
- Doppelklick-Installer für Linux, setup.exe für Windows
