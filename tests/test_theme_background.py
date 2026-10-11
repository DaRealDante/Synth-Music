import os

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from app.config import BACKGROUNDS_DIR, TEMP_DIR, settings
from app.ui import theme


def _resetTheme():
    settings.set("themeColors", {})
    settings.set("themeBackground", {})
    settings.set("customThemes", {})


def test_normalizeBackgroundFillsDefaultsAndRejectsJunk():
    assert theme.normalizeBackground(None)["type"] == "none"
    background = theme.normalizeBackground({"type": "gradient", "colors": ["#ff0000", "nope", "#0000ff", "#00ff00", "#111111", "#222222"],
                                            "angle": 400, "dim": 300})
    assert background["colors"] == ["#FF0000", "#0000FF", "#00FF00", "#111111"]
    assert background["angle"] == 40 and background["dim"] == 85
    assert theme.normalizeBackground({"type": "gradient", "colors": ["#FF0000"]})["colors"] == theme.DEFAULT_BACKGROUND["colors"]
    assert theme.normalizeBackground({"type": "image", "path": ""})["type"] == "none"
    assert theme.normalizeBackground({"type": "weird"})["type"] == "none"


def test_gradientPaintsFromFirstToLastColor():
    image = QImage(100, 20, QImage.Format_RGB32)
    painter = QPainter(image)
    painter.fillRect(QRectF(0, 0, 100, 20), theme.gradientFor(QRectF(0, 0, 100, 20), ["#FF0000", "#0000FF"], 0))
    painter.end()
    left, right = QColor(image.pixel(1, 10)), QColor(image.pixel(98, 10))
    assert left.red() > 200 and left.blue() < 50
    assert right.blue() > 200 and right.red() < 50


def test_themeColorsFromGradientAreDarkAndVivid():
    colors = theme.themeColorsFrom(["#FF5F6D", "#FFC371"])
    assert set(colors) == {"accent", "background", "panel", "sidebar"}
    palette = theme.resolveColors(colors)
    assert QColor(palette["BACKGROUND"]).valueF() < 0.2
    assert QColor(palette["ACCENT"]).valueF() >= 0.85
    assert theme.themeColorsFrom([]) == {}


def test_ambientStylesheetUsesThemeColors():
    background = QColor(theme.BACKGROUND)
    assert f"rgba({background.red()}, {background.green()}, {background.blue()}, 165)" in theme.AMBIENT_STYLESHEET


def _writeImage(name, color="#3366FF"):
    image = QImage(40, 30, QImage.Format_RGB32)
    image.fill(QColor(color))
    path = os.path.join(TEMP_DIR, name)
    image.save(path)
    return path


def test_storeBackgroundCopiesIntoDataFolder():
    from app.ui.dialogs import storeBackground
    source = _writeImage("sfondo_test.png")
    stored = storeBackground(source)
    assert stored and os.path.dirname(stored) == BACKGROUNDS_DIR and os.path.isfile(stored)
    assert storeBackground(source) == stored
    notImage = os.path.join(TEMP_DIR, "non_immagine.png")
    with open(notImage, "w") as handle:
        handle.write("ciao")
    assert storeBackground(notImage) is None


def test_backdropPaintsGradientAndImage():
    from app.ui.video_controller import BackdropWidget

    class FakeController:
        currentImage = None

        class _Signal:
            def connect(self, callback):
                pass

        frameReady = _Signal()

    backdrop = BackdropWidget(FakeController())
    backdrop.resize(80, 40)
    assert not backdrop.hasThemeBackground()
    backdrop.setThemeBackground(theme.normalizeBackground({"type": "gradient", "colors": ["#FF0000", "#FF0000"], "dim": 0}))
    assert backdrop.hasThemeBackground()
    assert QColor(backdrop.grab().toImage().pixel(40, 20)).red() > 200
    imagePath = _writeImage("sfondo_verde.png", "#00FF00")
    backdrop.setThemeBackground(theme.normalizeBackground({"type": "image", "path": imagePath, "dim": 0}))
    assert QColor(backdrop.grab().toImage().pixel(40, 20)).green() > 200
    backdrop.setThemeBackground(theme.normalizeBackground({"type": "image", "path": os.path.join(TEMP_DIR, "manca.png")}))
    assert not backdrop.hasThemeBackground()
    backdrop.setThemeBackground(theme.normalizeBackground({}))
    assert not backdrop.hasThemeBackground()


def test_settingsDialogSavesBackgroundAndCustomThemes(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from app.ui.dialogs import SettingsDialog
    _resetTheme()
    dialog = SettingsDialog()
    dialog._applyGradientPreset(theme.GRADIENT_PRESETS["Oceano"])
    assert dialog.backgroundTypeButtons["gradient"].isChecked() and not dialog.gradientBox.isHidden()
    dialog._addGradientStop()
    assert len(dialog.chosenBackground["colors"]) == 3
    dialog._setGradientAngle(90)
    dialog._setBackgroundDim(20)
    dialog._matchColorsToBackground()
    assert dialog.chosenColors.get("accent")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("Il mio tema", True)))
    dialog._saveCustomTheme()
    assert "Il mio tema" in settings.get("customThemes")
    dialog._save()
    saved = settings.get("themeBackground")
    assert saved["type"] == "gradient" and saved["angle"] == 90 and saved["dim"] == 20 and len(saved["colors"]) == 3
    assert dialog.restartForColors

    other = SettingsDialog()
    other._applyPreset({})
    other._setBackgroundType("none")
    assert other.chosenBackground["type"] == "none"
    other._applyCustomTheme("Il mio tema")
    assert other.chosenBackground["type"] == "gradient" and other.chosenColors == settings.get("customThemes")["Il mio tema"]["colors"]
    _resetTheme()


def test_mainWindowAppliesThemeBackgroundLive():
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    _resetTheme()
    window = MainWindow()
    assert not window.backdrop.hasThemeBackground()
    settings.set("themeBackground", {"type": "gradient", "colors": ["#FF5F6D", "#FFC371"]})
    window.applyThemeBackground()
    assert window.backdrop.hasThemeBackground()
    assert theme.AMBIENT_STYLESHEET in QApplication.instance().styleSheet()
    settings.set("themeBackground", {})
    window.applyThemeBackground()
    assert theme.AMBIENT_STYLESHEET not in QApplication.instance().styleSheet() or window.ambientActive
    _resetTheme()
