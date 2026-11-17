# Changelog

## 1.0.49 – 17.11.2026

- **Bericht bei „unbekannt – ermitteln“:** Statt „Bei 15 Volt: . Auf dem
  Gerät …“ steht jetzt „Ermittelt.“, und oben „Ermittelt: liefert bis … W“
  statt einer leeren Überschrift.

## 1.0.48 – 17.11.2026

- **Diagramm bleibt bei der laufenden Prüfung:** War vom vorigen Test noch
  das Ergebnis offen (Ergebnisfenster, PDF), stellte die App das Diagramm
  während der neuen Prüfung auf die alte zurück – mit deren Stufenmarken und
  Zeitachse. Jetzt kommt es immer auf die laufende Prüfung zurück.
- **Alte Prüfungen während einer Prüfung ansehen:** Ein Klick in die Liste
  öffnet sie im eigenen Fenster, mit Bericht und PDF – die laufende Anzeige
  bleibt unberührt. Vorher ging das während einer Prüfung gar nicht.

## 1.0.47 – 17.11.2026

- **Widerstand während der Prüfung ohne Sprung auf 0:** Die Anzeige rechnet
  jetzt wie das Ergebnis mit einer Ausgleichsgeraden durch die fertigen
  Stufen. Vorher verglich sie mit der Spannung ohne Last – hob das Gerät die
  Spannung bei kleiner Last etwas an, kam „0 mΩ“ heraus.

## 1.0.46 – 17.11.2026

- **Gestrichelte Buchsen-Kurve bleibt im Bild:** Beim Schnellladen wurde die
  Spannungsachse je Spannung nur nach der gemessenen Kurve gesetzt – mit
  „Kabel herausrechnen“ verschwand die berechnete Linie nach oben.
- **Temperatur:** Grenze für den Fühler jetzt 50 °C statt 70 °C. Haken und
  Grenze bleiben über den Programmstart hinaus gespeichert (Netzteile und
  Powerbanks getrennt). Steckt ein Fühler, ist der Haken aber aus, zeigt die
  Anzeige „aus ⚠“. Im Bericht steht dann „nicht gemessen (Fühler abgewählt)“
  statt gar nichts.
- **Hinweis am Haken „Kabel herausrechnen“:** „Buchse“ ist die Ausgangsbuchse
  des Netzteils bzw. der Powerbank – nicht die Buchse am DL24 oder der
  Fühleranschluss.

## 1.0.45 – 17.11.2026

- **Vorlage „TZT/CKCS PD65W Step-Down-Modul (Eingang 8–30 V)“** bei den
  Netzteilen, nach dem Datenblatt: 5 V 3 A, 9 V 3 A, 12 V 3 A, 20 V 3,25 A;
  15 V steht dort nur als „etc.“ und wird ermittelt. Schnellladen ist gleich
  gesetzt; beim Wählen kommt der Hinweis, dass der Eingang über der
  gewünschten Spannung liegen muss.
- Vorlagen bei den Netzteilen können jetzt die Spannungen für den
  Trigger-Adapter mitbringen.

## 1.0.44 – 17.11.2026

- **Bericht: „Grundlage der Grenzwerte“** – je geprüfter Spannung die Norm
  mit Abschnitt und Werten und ein QR-Code zur Quelle: 5 V nach USB 2.0
  §7.2.2 (IEC/EN 62680-2-1), 9–28 V nach USB Power Delivery §7.1.8
  (EN IEC 62680-1-2). Dazu der gesetzliche Bezug: Richtlinie 2014/53/EU in der
  Fassung (EU) 2022/2380, Anhang Ia – mit dem Hinweis, dass sie für die
  geladenen Geräte gilt, nicht für Netzteile, Ladegeräte oder Powerbanks.
  Normale Netzteile: „keine Norm – Toleranz wie auf dem Typenschild“.
- **28 V (USB PD EPR)** beim Trigger-Adapter. Belegt sind ±5 %; die
  0,5-V-Zone ist aus der allgemeinen Regel übernommen und so gekennzeichnet.
- Neue Abhängigkeit: `qrcode` (reines Python).

## 1.0.43 – 17.11.2026

- **Haken „Kabel herausrechnen“** (Netzteile und Powerbanks), standardmäßig
  aus: Gesetzt wird an der Buchse des Geräts bewertet (gemessen + Strom ×
  Kabelwiderstand) – Ampel, Urteil, Tabelle (Spalte „an der Buchse“) und
  Kapazitätstest. Im Diagramm kommt die berechnete Buchsenspannung
  gestrichelt dazu, die Grenzen bleiben fest. Der Bericht sagt ausdrücklich,
  dass herausgerechnet wurde.
- Erklärt das Kabel fast den ganzen Verlust, lautet der Hinweis jetzt
  neutral: Das spricht für ein gutes Gerät; nur wenn das Kabel mit genau
  diesem Gerät gemessen wurde, wäre es im Kreis gerechnet.

## 1.0.42 – 17.11.2026

- **Powerbank: „Was prüfen?“ als Auswahl** statt des Hakens beim
  Kapazitätstest – Lasttest (Spannungen und Leistung, auch über den
  Trigger-Adapter), Kapazitätstest (nur bis leer bei 5 V, Lasttest und
  Trigger gesperrt) oder beides. Zurück auf Lasttest stellt „Schnellladen“
  wieder her.
- Im Ergebnis steht bei Powerbanks „Powerbank“ statt „Netzteil“.

## 1.0.41 – 17.11.2026

- **Keine falsche Sicherheitsabschaltung beim Herunterstellen:** Beim Wechsel
  auf die nächste Spannung (Powerbank, Schnellladen) wird der Strom auf den
  Mindeststrom gesenkt. Messberichte von kurz davor zeigten noch den alten
  Strom, und die Sicherung brach die Prüfung ab („Es flossen 1,345 A statt
  0,300 A“). Nach dem Herunterstellen gilt die Sicherung jetzt 3 Sekunden lang
  noch für den alten Wert – bleibt der Strom danach zu hoch, schaltet sie wie
  bisher ab.

## 1.0.40 – 17.11.2026

- **Vorlage setzt Schnellladen mit:** Kann die Powerbank laut Vorlage mehr
  als 5 V (z. B. INIU MegaPower 20000), ist der Haken „Schnellladen“ gleich
  gesetzt. Vorher nahm die Vorlage ihn weg und es wurde nur 5 V geprüft.
- **Abschalttest und Kapazitätstest zusammen:** Je Spannung wird über den
  Nennstrom gesteigert (höchste Leistung), zum Schluss folgt die Kapazität.
  Schaltet die Powerbank bei Überlast ab, meldet die App „Knopf drücken“
  und macht danach weiter.

## 1.0.39 – 16.11.2026

- **Powerbank mit Schnellladen:** Mit dem Haken „Schnellladen“ prüft der
  Powerbank-Reiter erst alle gewählten Spannungen über den Trigger-Adapter
  (Stufentest, Grenzen nach USB bzw. USB-PD) und zum Schluss bei 5 V die
  Kapazität bis leer. Die Energie aus den Spannungsstufen zählt zur Kapazität
  dazu – gemessen wird ab voll. Beim Umschalten bleibt die Last mit dem
  Mindeststrom an, damit die Powerbank nicht einschläft.
- Die Vorlage INIU MegaPower 20000 setzt 5 V 3 A, 9 V 2,22 A und 12 V 1,5 A.

## 1.0.38 – 16.11.2026

Enthält alles aus 1.0.36 und 1.0.37 – beide sind nie erschienen. Der Bau
prüft beim Fensterstart die Zahl der Reiter und kannte den neuen Reiter
„Powerbanks“ noch nicht.

## 1.0.37 – 16.11.2026

Nie erschienen (Bau gescheitert), enthalten in 1.0.38.

- **Akkuzustand der Powerbank:** gemessene Energie gegen den Neuwert am
  Ausgang – aus der „Rated Capacity“ des Aufdrucks (neues Feld) oder, ohne
  sie, geschätzt mit 82 % der Zellenergie (so rechnet Anker den
  Wandlerverlust). Ampel: ab 80 % gut, ab 60 % gealtert, darunter stark
  abgenutzt (Einschätzung der App, angelehnt an Handy-Akkus).
- **Spannung beim Entladen:** Der Kapazitätstest bewertet die tiefste
  Spannung bis kurz vor leer (ohne die letzte Minute).
- **Vorlagen:** INIU MegaPower 20000 (B5) und Anker 325 PowerCore 20K
  (A1268) mit Kapazität.
- Restzeit-Schätzung des Kapazitätstests auf 80 % der Zellenergie angehoben
  (vorher 65 % – zu pessimistisch).

## 1.0.36 – 16.11.2026

- **Neuer Reiter „Powerbanks“:** Typenschild mit Kapazität (mAh oder Wh,
  Zellspannung) und Mindeststrom. Die Last fällt nie unter den Mindeststrom
  (Standard 0,3 A) – viele Powerbanks schalten sich sonst von selbst ab. Statt
  einer Leerlaufmessung wird gleich belastet und auf Spannung gewartet
  („Knopf drücken“). Geht sie beim Mindeststrom aus, steht der Hinweis auf die
  Abschaltautomatik dabei.
- **Kapazitätstest:** bis leer entladen, abgegebene Energie in Wh und mAh
  (auch umgerechnet auf 3,7 V) und der Anteil am Aufdruck – mit Ampel
  (ab 60 % grün, unter 45 % rot; Einschätzung der App, keine Vorgabe) und
  Restzeit-Schätzung. Bericht, Diagramme, Vorlagen und Liste wie beim Netzteil.
- **Simulator „Powerbank 5 V / 2 A (2 Wh)“** zum Ausprobieren ohne Gerät.
- Linke Spalte wird nach dem Anzeigen richtig breit (schnitt vorher Felder ab).

## 1.0.35 – 16.11.2026

- **Diagramme bleiben im Bild:** Verschieben und Zoomen mit der Maus ist
  abgeschaltet, alle Streifen passen ihre Höhe bei jedem Messwert selbst an.
  Vorher blieb eine verschobene Ansicht hängen und neue Werte liefen aus dem
  Bild.

## 1.0.34 – 16.11.2026

- **Kabelverlust als Diagramm:** Mit eingetragenem Kabelwert gibt es unter
  Strom/Leistung einen eigenen Streifen: wie viel Watt im Kabel verloren gehen
  (lila) und welcher Anteil der Leistung des Netzteils das ist (türkis). In der
  Kennlinie steht der Verlust je Stufe in Watt und Prozent, bei „Leistung“
  zusätzlich, was das Netzteil selbst abgibt.
- **Tabelle wie Urteil:** Die Häkchen in der Kennlinie haben das Kabel noch
  herausgerechnet – überall ✔, obwohl das Urteil „eingeschränkt“ lautete.
  Jetzt zeigen beide, was am Kabelende ankommt.
- **Grenzen für 9–20 V nach USB-PD (§7.1.8):** grün ±5 %, gelb bis 0,5 V
  darüber hinaus, sonst rot. Vorher galt pauschal die doppelte Toleranz.
  Kurze Spitzen beim Lastwechsel innerhalb dieser 0,5 V sind erlaubt. Für QC
  gibt es keine öffentliche Vorgabe – dort gelten dieselben Grenzen.

## 1.0.33 – 16.11.2026

- **Feste Grenzlinien:** Die Grenzen im Spannungsdiagramm bleiben immer
  gerade (4,75 V / 4,40 V bei USB). Mit eingetragenem Kabelwert waren sie
  vorher ans Kabelende umgerechnet und rutschten mit jeder Stromstufe nach
  unten – das sah aus, als wandere der Wert.
- **Kabel wird nicht mehr herausgerechnet:** Bewertet wird, was am Kabelende
  beim Gerät ankommt. Diagramm und Urteil passen damit immer zusammen; ohne
  Kabelwert gibt es kein „nicht entscheidbar“ mehr. Der Kabelwert steht im
  Bericht, das Kabel wird weiter eigens bewertet, und bei zu niedriger
  Spannung steht dabei, wie viel davon aufs Kabel entfällt.

## 1.0.32 – 16.11.2026

- **Bericht mit allen Diagrammen:** Bei Schnellladegeräten steht für jede
  Spannung ein eigenes, vollständiges Diagramm im Bericht – mit eigener Achse,
  Ampel und Stufenmarken. Vorher war es ein einziges Bildschirmfoto, in dem
  alle Spannungen zusammengedrückt waren.
- Im Bericht hieß es „gemessen: 5,12 V“, obwohl der Wert um das Kabel
  hochgerechnet war – jetzt steht „an der Buchse“, wenn es so ist.

## 1.0.31 – 16.11.2026

- Eigenes Anzeigefeld **„Widerstand (Netzteil + Kabel)“** in mΩ: laufend aus
  dem Spannungsverlust gegenüber dem Leerlauf, nach der Prüfung der Wert aus der
  Kennlinie.

## 1.0.30 – 16.11.2026

- **Diagramm mit Kabelwert neu:** keine hochgerechnete „Buchsen“-Kurve mehr.
  Gezeigt wird nur die gemessene Spannung, dazu die Grenzen (4,75 V / 4,40 V
  bei USB) **ans Kabelende umgerechnet** als gestrichelte Treppe. Liegt die
  gemessene Kurve darüber, reicht das Netzteil; fällt sie darunter, nicht.
- **Hinweis, wenn das Kabel alles erklärt:** Wurde das Kabel mit genau dem
  geprüften Netzteil gemessen, ist das Ergebnis im Kreis gerechnet – die App
  sagt das jetzt im Diagramm und im Bericht.
- **Kabel bewerten:** Kabeltyp wählen (USB-C 3 A, USB-C 5 A, USB 2.0). Grenze
  nach USB-Spezifikation (USB-C: 500 mV + 250 mV bei Nennstrom → 250 mΩ bzw.
  150 mΩ; USB 2.0: 500 mΩ). Grün bis zur Grenze, gelb bis zum Doppelten, rot
  darüber („Schrott“), dazu „taugt für bis zu x A“. Steht auch im Bericht.

## 1.0.29 – 16.11.2026

- **Eigene Vorlagen:** „Speichern“ neben der Vorlagenliste legt das ganze
  Typenschild unter dem Gerätenamen ab – auch Schnellladegeräte mit ihren
  Spannungen und Strömen. Eigene Vorlagen stehen mit ★ oben in der Liste,
  „Löschen“ entfernt sie wieder.
- **Kabel im Bericht:** neues Feld „Kabel (Bezeichnung)“. Der Bericht hat einen
  Abschnitt „Messaufbau“: Messgerät, welches Kabel/welcher Adapter, Widerstand
  und wann er gemessen wurde – oder dass er nicht bekannt ist.
- Kabelwert und Bezeichnung bleiben zwischen zwei Programmstarts eingetragen.

## 1.0.28 – 16.11.2026

- **Schnellladen:** Die Anzeige sagt, welche Spannung gerade dran ist und
  welche noch folgen („Spannung 1 von 2, danach 9 V“), und die Restzeit gilt
  für alle zusammen. Vorher sah es so aus, als würde nur 5 V geprüft.

## 1.0.27 – 16.11.2026

- **Schnellladen:** Die Ampel im Diagramm erscheint jetzt auch hier – für die
  Spannung, die gerade am Trigger-Adapter anliegt (5 V, 9 V, …). Die
  Spannungsachse richtet sich nach der aktuellen Spannung statt von 5 bis 20 V
  zu reichen.

## 1.0.26 – 16.11.2026

- Die Anzeige oben zeigt nur noch die **gemessene** Spannung – die berechnete
  „Buchse“-Angabe daneben konnte mit falschem Kabelwert Unsinn zeigen (mehr als
  ohne Last).
- Ergibt die Rechnung an der Buchse mehr als die Leerlaufspannung, ist der
  Kabelwert falsch: Die gestrichelte Kurve wird sofort ausgeblendet, und es
  erscheint der Hinweis, das Kabel neu zu messen.

## 1.0.25 – 16.11.2026

- Diagramm zeigt die **gemessene Spannung** (durchgezogen) und – mit Kabelwert –
  zusätzlich die **berechnete an der Buchse** (gestrichelt), mit Legende. Vorher
  stand nur die berechnete da, die nicht zur Anzeige oben passte. Oben steht
  während der Prüfung „(Buchse x V)“ dahinter.
- **Unplausibler Kabelwert** (größer als der gesamte gemessene Widerstand,
  z. B. am geprüften Gerät statt an einem guten Ladegerät gemessen) wird nicht
  herausgerechnet – mit Hinweis im Bericht. Sonst sähe ein schwaches Gerät
  perfekt aus.
- **Überspannung** über die ganze Prüfung: nicht nur der Leerlauf, sondern der
  höchste gemessene Wert, auch Spitzen beim Lastwechsel. USB: über 5,25 V gelb
  (entspricht nicht der Vorgabe), über 5,5 V rot (kann Geräte beschädigen).

## 1.0.24 – 15.11.2026

- **Temperaturfühler richtig zugeordnet:** Am echten DL24P (Firmware 1.1.0)
  geprüft – der angesteckte Fühler kommt in Byte 36, der Kühler (MOSFET) in
  Byte 32. Vorher war es nach der Atorch-Software verdreht: Als „Fühler“ wurde
  die Kühlertemperatur angezeigt und ausgewertet. Byte 40 heißt vorerst
  „Temperatur 3 (unbekannt)“.

## 1.0.23 – 15.11.2026

- **Ampel für die Spannung:** grün, gelb, rot – im Diagramm als farbige Bänder,
  in der Kennlinie je Stufe. USB: grün 4,75–5,25 V, gelb bis 4,40 V bzw. 5,5 V,
  rot darüber hinaus. Mit Kabelwert zeigt das Diagramm die Spannung an der Buchse.
- **Schwankung** je Stufe (höchster minus tiefster Wert): grün bis 1 %, gelb bis
  3 %, rot darüber – Einschätzung der App, keine Vorgabe der Spezifikation. Rot
  wertet das Urteil auf „eingeschränkt“ ab. Hinweis im Bericht, dass schnelles
  Brummen (Ripple) nur mit einem Oszilloskop messbar ist.
- Im Bericht steht, **ab welcher Last der Mindestwert unterschritten** wurde und
  dass das Gerät ab dort keine stabile Spannung mehr hält (ohne Kabelwert für das
  Kabelende, mit dem Hinweis, dass Gerät oder Kabel schuld sein kann).
- **USB-Hub:** Hinweis im Bericht und im Formular, dass nur ein Port geprüft
  wird und die Angabe meist für alle Ports zusammen gilt.
- **Ergebnis im eigenen Fenster** – öffnet nach der Prüfung von selbst, für alte
  Prüfungen per Doppelklick oder „Ergebnis groß anzeigen“.
- **Kabel messen …**: eigener Knopf neben „Kabel + Adapter“ – misst Kabel und
  Adapter an einem guten Ladegerät und trägt den Wert ein. „Als Kabelwert
  übernehmen“ geht jetzt auch, wenn schon ein Wert eingetragen ist.
- Steuerung: alle drei Temperaturen (Fühler, CPU, Kühler/MOS) und die Rohwerte
  vom Gerät, um zu prüfen, welcher Wert welcher Fühler ist.
- Knöpfe werden bei kleinem Fenster nicht mehr abgeschnitten; die linke Spalte
  rollt stattdessen.

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
