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
        # Was eine Powerbank nicht hat: Schnellladen über den Adapter (kommt später), "unbekannt", Toleranz
        for w in (self.schnell, self.schnell_box, self.unbekannt, self.toleranz):
            f.setRowVisible(w, False)
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
        hinweis = QLabel("Die Powerbank vorher <b>ganz voll laden</b>. Danach ist sie leer – ein Abschalttest "
                         "entfällt dann. Üblich sind 60–75 % der aufgedruckten Energie, weil beim Umwandeln auf "
                         "5 V Energie verloren geht.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(gedaempft())
        k.addWidget(hinweis, 1, 0, 1, 2)
        self._links.insertWidget(self._links.indexOf(self.tests_gruppe), g)
        self.kap_gruppe = g
        self.mit_dauer.setChecked(False)
        for w in (self.mah, self.zell_v, self.wh, self.mindest_a, self.kap_a):
            w.valueChanged.connect(self._angabe_zeigen)
        self.mit_kap.toggled.connect(self._kap_umschalten)
        self._breite_anpassen()               # neue Felder: sonst schneidet die linke Spalte ab

    def _kap_umschalten(self, an: bool) -> None:
        if an:
            self.mit_abschalt.setChecked(False)
        self.mit_abschalt.setEnabled(not an and not self.laeuft)
        self._angabe_zeigen()

    def _felder_sperren(self) -> None:
        super()._felder_sperren()
        if hasattr(self, "mah"):
            for w in (self.mah, self.zell_v, self.wh, self.mindest_a):
                w.setEnabled(not self.laeuft)
            self.kap_gruppe.setEnabled(not self.laeuft and self.bereit())

    def _ist_hub(self) -> bool:
        return False

    def _typenschild(self) -> dict:
        d = super()._typenschild()
        d.update(powerbank=True, mah=self.mah.value(), zell_v=self.zell_v.value(), wh=self.wh.value(),
                 mindest_a=self.mindest_a.value())
        return d

    def _vorlage(self, _=None) -> None:
        super()._vorlage(_)
        d = self.vorlage.currentData()
        if isinstance(d, dict) and hasattr(self, "mah"):
            self.mah.setValue(d.get("mah", 0))
            self.zell_v.setValue(d.get("zell_v", 3.7))
            self.wh.setValue(d.get("wh", 0))
            self.mindest_a.setValue(d.get("mindest_a", 0.3))

    def einstellung(self) -> nt.NetzteilEinstellung:
        e = super().einstellung()
        if not hasattr(self, "mah"):
            return e
        name = self.name.text().strip() or self.name.placeholderText().split("z. B.")[0].strip() or "Powerbank"
        return dataclasses.replace(e, name=name, powerbank=True, hub=False, toleranz_proz=5.0,
                                   mah=self.mah.value(), zell_v=round(self.zell_v.value(), 2),
                                   wh=round(self.wh.value(), 1), mindest_a=round(self.mindest_a.value(), 2),
                                   kapazitaet=self.mit_kap.isChecked(), kap_a=round(self.kap_a.value(), 2))

    def bereit(self) -> bool:
        return self.nenn_v.value() > 0 and self.nenn_a.value() > 0

    def _angabe_zeigen(self) -> None:
        super()._angabe_zeigen()
        if not hasattr(self, "mah"):
            return
        e = self.einstellung()
        teile = [self.angabe_hinweis.text()] if self.angabe_hinweis.text() else []
        if e.aufdruck_wh > 0:
            teile.append(f"Aufdruck: {zahl(e.aufdruck_wh, 1)} Wh – üblich kommen davon etwa "
                         f"{zahl(e.aufdruck_wh * 0.6, 1)}–{zahl(e.aufdruck_wh * 0.75, 1)} Wh heraus")
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
        return [self.einstellung()] if self.bereit() else []
