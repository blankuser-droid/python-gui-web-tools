"""
gui/widgets/stat_card.py
-------------------------
Wiederverwendbares "Kachel"-Widget zur Anzeige einer einzelnen Kennzahl
(z. B. "CPU-Auslastung: 23%") auf dem Dashboard.

WARUM EIN EIGENES WIDGET STATT INLINE-CODE IM DASHBOARD?
DRY-Prinzip (Don't Repeat Yourself): Das Dashboard zeigt 6+ solcher
Kacheln (CPU, RAM, Festplatte, Uptime, Prozesse, Netzwerk). Ohne ein
eigenes Widget müsste der Layout-Code für jede Kachel einzeln kopiert
werden -- bei einer späteren Design-Änderung (z. B. andere Eckenradien)
müsste man dann an 6 Stellen etwas ändern statt an einer.

Das Widget unterstützt außerdem eine "Statusfarbe" (ok/warn/critical),
sodass z. B. eine Festplatte bei 95% Belegung automatisch rot markiert
wird -- visuelles Feedback ist in Monitoring-Tools Standard.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    """Eine einzelne Dashboard-Kachel mit Titel, Wert und optionaler Statusfarbe."""

    def __init__(self, title: str, value: str = "-", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", "true")
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self.title_label = QLabel(title.upper())
        self.title_label.setProperty("role", "cardTitle")

        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "cardValue")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch()

    def set_value(self, value: str, status: str = "normal") -> None:
        """Aktualisiert den angezeigten Wert und ggf. die Statusfarbe.

        Args:
            value: Anzuzeigender Text, z. B. "42 %".
            status: "normal", "ok", "warn" oder "critical" -- steuert die
                Textfarbe über das im Stylesheet definierte 'role'-Property.
        """
        self.value_label.setText(value)
        role_map = {
            "normal": "cardValue",
            "ok": "cardValueOk",
            "warn": "cardValueWarn",
            "critical": "cardValueCrit",
        }
        self.value_label.setProperty("role", role_map.get(status, "cardValue"))
        # Style-Eigenschaften müssen nach Änderung neu angewendet werden,
        # da Qt das Stylesheet nicht automatisch neu berechnet, wenn nur
        # eine dynamische Property (kein echtes CSS-Class-Toggle) geändert wird.
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)