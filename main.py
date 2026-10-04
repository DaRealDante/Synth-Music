import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, DATA_DIR

if sys.stdout is None or sys.stderr is None:
    _logFile = open(os.path.join(DATA_DIR, "log.txt"), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _logFile
    sys.stderr = sys.stderr or _logFile

from app.updater import activateDownloadedEngine

activateDownloadedEngine()

from app.ui import theme
from app.ui.main_window import MainWindow


def main():
    sys.setswitchinterval(0.002)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00008000)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KenHD.SynthMusic")
        except Exception:
            pass
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("KenHD")
    application.setStyle("Fusion")
    application.setStyleSheet(theme.STYLESHEET)
    application.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
