"""Reiter „Powerbanks“: wie der Netzteil-Reiter, aber die Last fällt nie unter den
Mindeststrom (sonst schaltet sich die Powerbank ab) und auf Wunsch wird bis leer
entladen, um die echte Kapazität mit dem Aufdruck zu vergleichen."""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel

from . import netzteil as nt
from .fenster import gedaempft, zahl
from .netzteil_reiter import NetzteilReiter


class PowerbankReiter(NetzteilReiter):
    kennung = "pb"
    powerbank = True

    def _bauen(self) -> None:
        super()._bauen()
        f = self._typ_form
        self.name.setPlaceholderText("z. B. Anker PowerCore 10000, Xiaomi 20000")
        # "unbekannt" und eine eigene Toleranz gibt es hier nicht - USB/PD geben die Grenzen vor
        for w in (self.unbekannt, self.toleranz):
            f.setRowVisible(w, False)
        self.schnell.setText("Schnellladen (USB-PD / QC): weitere Spannungen über den Trigger-Adapter")
        self.schnell.setToolTip("Erst werden alle gewählten Spannungen geprüft, zum Schluss läuft bei 5 V der "
                                "Kapazitätstest")
        zeile = f.getWidgetPosition(self.nenn_w)[0] + 1
        self.mah = self._zahlfeld(0, 100000, 0, 500, " mAh", "nicht angegeben")
        self.mah.setToolTip("Kapazität laut Aufdruck, z. B. 10000 mAh. Gemeint ist meist der Akku innen "
                            "(3,6–3,7 V), nicht die Ausgangsseite.")
        f.insertRow(zeile, "Kapazität:", self.mah)
        self.zell_v = self._zahlfeld(3.0, 4.0, 2, 0.05, " V")
        self.zell_v.setValue(3.7)
        self.zell_v.setToolTip("Auf diese Spannung bezieht sich die mAh-Angabe (steht klein auf dem Aufdruck, "
                               "sonst 3,7 V lassen)")
        f.insertRow(zeile + 1, "Zellspannung:", self.zell_v)
        self.wh = self._zahlfeld(0, 400, 1, 1, " Wh", "aus mAh rechnen")
        self.wh.setToolTip("Steht die Energie in Wh drauf, ist sie genauer als mAh")
        f.insertRow(zeile + 2, "Energie:", self.wh)
        self.nenn_mah_aus = self._zahlfeld(0, 60000, 0, 500, " mAh bei 5 V", "nicht angegeben")
        self.nenn_mah_aus.setToolTip("Steht auf vielen Powerbanks klein als „Rated Capacity“, z. B. „12000 mAh "
                                     "(5 V ⎓ 2,1 A)“: so viel liefert sie neu am Ausgang. Damit wird der "
                                     "Akkuzustand genau – sonst wird er aus der Zellenergie geschätzt.")
        f.insertRow(zeile + 3, "Nennkapazität Ausgang:", self.nenn_mah_aus)
        zeile += 1
        self.mindest_a = self._zahlfeld(0.05, 2.0, 2, 0.05, " A")
        self.mindest_a.setValue(0.3)
        self.mindest_a.setToolTip("Darunter schalten sich viele Powerbanks nach einiger Zeit von selbst ab. "
                                  "Der Prüfstrom fällt nie darunter.")
        f.insertRow(zeile + 3, "Mindeststrom:", self.mindest_a)

        g = QGroupBox("Kapazität")
        k = QGridLayout(g)
        self.mit_kap = QCheckBox("Kapazitätstest: bis leer entladen mit")
        self.mit_kap.setToolTip("Misst, wie viel Energie wirklich herauskommt. Die Powerbank vorher voll laden! "
                                "Dauert je nach Größe Stunden.")
        self.kap_a = self._zahlfeld(0.1, 5.0, 2, 0.1, " A")
        self.kap_a.setValue(1.0)
        k.addWidget(self.mit_kap, 0, 0)
        k.addWidget(self.kap_a, 0, 1)
        hinweis = QLabel("Die Powerbank vorher <b>ganz voll laden</b>. Der Kapazitätstest kommt zum Schluss, nach allen "
                         "Spannungen und dem Abschalttest. Daraus ergibt sich der Akkuzustand: wie viel sie noch "
                         "von dem kann, was sie neu konnte (ab 80 % gut).")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        k.addWidget(hinweis, 1, 0, 1, 2)
        self._links.insertWidget(self._links.indexOf(self.tests_gruppe), g)
        self.kap_gruppe = g
        self.mit_dauer.setChecked(False)
        for w in (self.mah, self.zell_v, self.wh, self.mindest_a, self.kap_a, self.nenn_mah_aus):
            w.valueChanged.connect(self._angabe_zeigen)
        self.mit_kap.toggled.connect(self._kap_umschalten)
        self._breite_anpassen()               # neue Felder: sonst schneidet die linke Spalte ab

    def _kap_umschalten(self, an: bool) -> None:
        self._angabe_zeigen()

    def _felder_sperren(self) -> None:
        super()._felder_sperren()
        if hasattr(self, "mah"):
            for w in (self.mah, self.zell_v, self.wh, self.nenn_mah_aus, self.mindest_a):
                w.setEnabled(not self.laeuft)
            self.kap_gruppe.setEnabled(not self.laeuft and self.bereit())

    def _ist_hub(self) -> bool:
        return False

    def _typenschild(self) -> dict:
        d = super()._typenschild()
        d.update(powerbank=True, mah=self.mah.value(), zell_v=self.zell_v.value(), wh=self.wh.value(),
                 mindest_a=self.mindest_a.value(), nenn_mah_aus=self.nenn_mah_aus.value())
        return d

    def _vorlage(self, _=None) -> None:
        super()._vorlage(_)
        d = self.vorlage.currentData()
        if isinstance(d, tuple) and len(d) > 3 and hasattr(self, "mah"):
            d = d[3]                          # bekanntes Modell: Kapazität und Spannungen gleich mit
            for (v, haken, a), (_, an, strom) in zip(self.trigger, d.get("trigger", [])):
                haken.setChecked(an)
                a.setValue(strom)
            # kann sie Schnellladen, wird das auch geprüft - sonst bliebe es bei 5 V
            self.schnell.setChecked(any(an and v > 5.5 for v, an, _ in d.get("trigger", [])))
        if isinstance(d, dict) and hasattr(self, "mah"):
            self.mah.setValue(d.get("mah", 0))
            self.zell_v.setValue(d.get("zell_v", 3.7))
            self.wh.setValue(d.get("wh", 0))
            self.mindest_a.setValue(d.get("mindest_a", 0.3))
            self.nenn_mah_aus.setValue(d.get("nenn_mah_aus", 0))

    def einstellung(self) -> nt.NetzteilEinstellung:
        e = super().einstellung()
        if not hasattr(self, "mah"):
            return e
        name = self.name.text().strip() or self.name.placeholderText().split("z. B.")[0].strip() or "Powerbank"
        return dataclasses.replace(e, name=name, powerbank=True, hub=False, toleranz_proz=5.0,
                                   mah=self.mah.value(), zell_v=round(self.zell_v.value(), 2),
                                   wh=round(self.wh.value(), 1), mindest_a=round(self.mindest_a.value(), 2),
                                   kapazitaet=self.mit_kap.isChecked(), kap_a=round(self.kap_a.value(), 2),
                                   nenn_mah_aus=self.nenn_mah_aus.value())

    def bereit(self) -> bool:
        if self.schnell.isChecked():
            return bool(self._trigger_stufen())
        return self.nenn_v.value() > 0 and self.nenn_a.value() > 0

    def _angabe_zeigen(self) -> None:
        super()._angabe_zeigen()
        if not hasattr(self, "mah"):
            return
        e = self.einstellung()
        teile = [self.angabe_hinweis.text()] if self.angabe_hinweis.text() else []
        neu, geschaetzt = e.neu_wh
        if neu > 0:
            teile.append(f"Neu am Ausgang: {'etwa ' if geschaetzt else ''}{zahl(neu, 1)} Wh"
                         + (f" ({zahl(nt.PB_WIRKUNG * 100, 0)} % von {zahl(e.aufdruck_wh, 1)} Wh – Wandlerverlust)"
                            if geschaetzt else ""))
        elif e.kapazitaet:
            teile.append("Ohne Kapazitätsangabe wird nur gemessen, nicht verglichen")
        self.angabe_hinweis.setText(".  ".join(teile))

    def _freigeben(self) -> None:
        super()._freigeben()
        if hasattr(self, "kap_gruppe"):
            self.kap_gruppe.setEnabled(self.bereit() and not self.laeuft)

    def _dauer_zeigen(self) -> None:
        if not self.bereit():
            self.dauer.setText("")
            return
        super()._dauer_zeigen()

    def _plan(self) -> list[nt.NetzteilEinstellung]:
        if not self.bereit():
            return []
        e = self.einstellung()
        if not self.schnell.isChecked():
            return [e]
        teile = [nt.trigger_einstellung(e, v, a) for v, a in self._trigger_stufen()]
        if e.kapazitaet:
            fuenf = next((a for v, a in self._trigger_stufen() if v == 5.0 and a > 0), e.kap_a)
            teile.append(dataclasses.replace(e, nenn_v=5.0, nenn_a=fuenf, nenn_w=0.0, stufentest=False,
                                             dauertest=False, abschalttest=False, kapazitaet=True))
        return teile
