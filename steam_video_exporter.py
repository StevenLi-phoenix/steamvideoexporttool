from PySide6.QtWidgets import QApplication

from steam_exporter.ui import App


def main():
    application = QApplication([])
    application.setApplicationName("Steam Video Exporter")
    application.setStyle("Fusion")
    window = App()
    window.show()
    application.exec()


if __name__ == "__main__":
    main()
