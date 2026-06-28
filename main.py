from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.pages.dashboard_page import DashboardPage
from gui.pages.network_page import NetworkPage
from gui.pages.system_page import SystemPage


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("My Big Portfolio")
        self.resize(1200, 800)

        tabs = QTabWidget(self)
        tabs.addTab(DashboardPage(), "Dashboard")
        tabs.addTab(SystemPage(), "System")
        tabs.addTab(NetworkPage(), "Netzwerk")

        self.setCentralWidget(tabs)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
