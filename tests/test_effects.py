import time

import numpy

from app.audio_engine import SAMPLE_RATE, AudioEngine


def test_spectrumPeaksInRightBand():
    engine = AudioEngine()
    engine.stream = None
    times = numpy.arange(4096) / SAMPLE_RATE
    tone = (0.5 * numpy.sin(2 * numpy.pi * 440 * times)).astype(numpy.float32)
    engine._measureSpectrum(numpy.stack([tone, tone], axis=1))
    from PySide6.QtMultimedia import QMediaPlayer
    engine._state = QMediaPlayer.PlayingState
    engine.spectrumQueue[0] = (time.monotonic() - 1, engine.spectrumQueue[0][1])
    levels = engine.spectrum()
    limits = numpy.geomspace(40, 16000, 33)
    band = int(numpy.searchsorted(limits, 440)) - 1
    assert levels[band] > 0.7
    assert max(levels[:band - 1] + levels[band + 2:]) < levels[band] - 0.3
    engine.shutdown()


def test_fadeInAndOut():
    engine = AudioEngine()
    samples = numpy.ones((4096, 2), dtype=numpy.float32)
    faded = engine._applyFade(samples, 0)
    assert faded[0, 0] == 0.0 and faded[-1, 0] < 0.1
    middle = engine._applyFade(samples, SAMPLE_RATE * 10)
    assert numpy.all(middle == 1.0)
    engine.decodeDone = True
    engine.decodedFrames = SAMPLE_RATE * 10 + 4096
    ending = engine._applyFade(samples, SAMPLE_RATE * 10)
    assert ending[-1, 0] < 0.01 and ending[0, 0] < 0.06
    engine.shutdown()


def test_dominantColorOfRedCover(tmp_path):
    from PySide6.QtGui import QColor, QImage
    from app.ui.effects import dominantColor
    image = QImage(64, 64, QImage.Format_RGB32)
    image.fill(QColor("#D01010"))
    path = str(tmp_path / "red.png")
    image.save(path)
    color = dominantColor(path)
    assert color.red() > color.green() * 3 and color.red() > color.blue() * 3
    assert dominantColor(None) is None
