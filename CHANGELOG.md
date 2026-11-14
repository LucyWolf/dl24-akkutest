# Changelog

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
