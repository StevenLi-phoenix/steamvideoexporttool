from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from steam_exporter.media import resource_path
from steam_exporter.ui import App


def main():
    application = QApplication([])
    application.setApplicationName("Steam Video Exporter")
    application.setStyle("Fusion")
    icon_path = resource_path("assets", "app-icon.ico")
    if icon_path.exists():
        application.setWindowIcon(QIcon(str(icon_path)))
    window = App()
    window.show()
    application.exec()


if __name__ == "__main__":
    main()
