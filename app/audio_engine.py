import subprocess
import sys
import threading

import numpy
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from .config import ffmpegExe

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 4096
OUTPUT_LATENCY = 0.3
CREATE_FLAGS = (0x08000000 | 0x00004000) if sys.platform == "win32" else 0

EQ_FREQUENCIES = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_LABELS = ["32", "64", "125", "250", "500", "1K", "2K", "4K", "8K", "16K"]

EQ_PRESETS = {
    "Piatto": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass Boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Bass Extreme": [10, 8, 6, 3, 0, -1, -1, 0, 0, 0],
    "Bassi + Alti": [6, 5, 3, 0, -1, -1, 0, 3, 5, 6],
    "Alti": [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    "Voce": [-2, -2, -1, 1, 3, 4, 4, 3, 1, 0],
    "Rock": [5, 4, 3, 1, -1, -1, 1, 3, 4, 5],
    "Pop": [-1, 0, 2, 3, 4, 3, 1, 0, -1, -1],
    "Hip-Hop": [6, 5, 2, 3, -1, -1, 1, 0, 2, 3],
    "Elettronica": [5, 4, 1, 0, -2, 1, 0, 1, 4, 5],
    "Jazz": [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "Classica": [4, 3, 2, 1, -1, -1, 0, 2, 3, 4],
    "Acustica": [4, 3, 2, 1, 2, 2, 3, 3, 2, 1],
    "Loudness": [5, 4, 1, 0, -1, 0, -1, 1, 4, 5],
    "Notte (bassi soft)": [-4, -3, -2, 0, 1, 2, 2, 1, 0, -1],
}


def _biquadSos(kind, frequency, gainDb, q=1.0):
    gainFactor = 10 ** (gainDb / 40.0)
    omega = 2 * numpy.pi * frequency / SAMPLE_RATE
    sinOmega, cosOmega = numpy.sin(omega), numpy.cos(omega)
    if kind == "peak":
        alpha = sinOmega / (2 * q)
        b0, b1, b2 = 1 + alpha * gainFactor, -2 * cosOmega, 1 - alpha * gainFactor
        a0, a1, a2 = 1 + alpha / gainFactor, -2 * cosOmega, 1 - alpha / gainFactor
    else:
        slope = 1.0
        alpha = sinOmega / 2 * numpy.sqrt((gainFactor + 1 / gainFactor) * (1 / slope - 1) + 2)
        sqrtTerm = 2 * numpy.sqrt(gainFactor) * alpha
        if kind == "lowshelf":
            b0 = gainFactor * ((gainFactor + 1) - (gainFactor - 1) * cosOmega + sqrtTerm)
            b1 = 2 * gainFactor * ((gainFactor - 1) - (gainFactor + 1) * cosOmega)
            b2 = gainFactor * ((gainFactor + 1) - (gainFactor - 1) * cosOmega - sqrtTerm)
            a0 = (gainFactor + 1) + (gainFactor - 1) * cosOmega + sqrtTerm
            a1 = -2 * ((gainFactor - 1) + (gainFactor + 1) * cosOmega)
            a2 = (gainFactor + 1) + (gainFactor - 1) * cosOmega - sqrtTerm
        else:
            b0 = gainFactor * ((gainFactor + 1) + (gainFactor - 1) * cosOmega + sqrtTerm)
            b1 = -2 * gainFactor * ((gainFactor - 1) + (gainFactor + 1) * cosOmega)
            b2 = gainFactor * ((gainFactor + 1) + (gainFactor - 1) * cosOmega - sqrtTerm)
            a0 = (gainFactor + 1) - (gainFactor - 1) * cosOmega + sqrtTerm
            a1 = 2 * ((gainFactor - 1) - (gainFactor + 1) * cosOmega)
            a2 = (gainFactor + 1) - (gainFactor - 1) * cosOmega - sqrtTerm
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


def buildEqSos(gains):
    sections = []
    for index, (frequency, gainDb) in enumerate(zip(EQ_FREQUENCIES, gains)):
        if abs(gainDb) < 0.05:
            continue
        if index == 0:
            sections.append(_biquadSos("lowshelf", frequency * 1.4, gainDb))
        elif index == len(EQ_FREQUENCIES) - 1:
            sections.append(_biquadSos("highshelf", frequency * 0.7, gainDb))
        else:
            sections.append(_biquadSos("peak", frequency, gainDb, 1.1))
    return numpy.array(sections, dtype=numpy.float64) if sections else None


def eqResponse(gains, preampDb, frequencies):
    from scipy.signal import sosfreqz
    sos = buildEqSos(gains)
    if sos is None:
        return numpy.full(len(frequencies), preampDb)
    _, response = sosfreqz(sos, worN=numpy.asarray(frequencies), fs=SAMPLE_RATE)
    return 20 * numpy.log10(numpy.maximum(numpy.abs(response), 1e-6)) + preampDb


def _softLimit(samples):
    threshold = 0.85
    magnitude = numpy.abs(samples)
    over = magnitude > threshold
    if over.any():
        samples[over] = numpy.sign(samples[over]) * (threshold + (1 - threshold) * numpy.tanh((magnitude[over] - threshold) / (1 - threshold)))
    return samples


def speedFilter(rate, keepPitch=True):
    """ffmpeg filter for a speed change: keepPitch=True time-stretches, False changes the pitch too (like a record)."""
    if abs(rate - 1.0) < 0.001:
        return None
    if keepPitch:
        return f"atempo={rate:.4f}"
    return f"aresample={SAMPLE_RATE},asetrate={int(round(SAMPLE_RATE * rate))},aresample={SAMPLE_RATE}"


def makeImpulseResponse(decaySeconds=1.8, seed=7):
    """Synthetic stereo room impulse response (decaying filtered noise + early reflections), unit energy."""
    from scipy.signal import lfilter
    decaySeconds = max(0.2, min(6.0, float(decaySeconds)))
    length = int(SAMPLE_RATE * decaySeconds * 1.1)
    generator = numpy.random.default_rng(seed)
    times = numpy.arange(length) / SAMPLE_RATE
    envelope = numpy.exp(-6.9 * times / decaySeconds)
    response = generator.standard_normal((length, CHANNELS)) * envelope[:, None]
    smoothing = 0.35 + min(0.5, decaySeconds / 10)
    response = lfilter([1 - smoothing], [1, -smoothing], response, axis=0)
    preDelay = int(0.018 * SAMPLE_RATE)
    response = numpy.vstack([numpy.zeros((preDelay, CHANNELS)), response])
    for delay, gain in ((0.011, 0.6), (0.019, 0.45), (0.027, 0.35), (0.041, 0.25)):
        index = int(delay * SAMPLE_RATE)
        response[index, 0] += gain
        response[index + 37, 1] += gain
    response /= numpy.sqrt(numpy.sum(response ** 2) / CHANNELS)
    return response.astype(numpy.float32)


def applyReverbOffline(samples, wet, decaySeconds):
    """Same reverb as the live one, for exporting a file. samples: float32 [n, 2]."""
    from scipy.signal import oaconvolve
    if wet <= 0.001:
        return samples
    response = makeImpulseResponse(decaySeconds)
    wetSignal = numpy.stack([oaconvolve(samples[:, channel], response[:, channel])[:len(samples)] for channel in range(CHANNELS)], axis=1)
    mixed = samples * (1.0 - 0.45 * wet) + wetSignal * (0.6 * wet)
    peak = float(numpy.max(numpy.abs(mixed))) or 1.0
    return (mixed / max(1.0, peak / 0.98)).astype(numpy.float32)


class _Decoder(threading.Thread):
    def __init__(self, engine, path, rate, generation, estimatedSeconds, keepPitch=True):
        super().__init__(daemon=True)
        self.engine = engine
        self.path = path
        self.rate = rate
        self.keepPitch = keepPitch
        self.generation = generation
        self.estimatedFrames = int(max(30.0, estimatedSeconds / rate + 5) * SAMPLE_RATE)
        self.process = None
        self.cancelled = False

    def run(self):
        executable = ffmpegExe()
        command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", self.path, "-vn",
                   "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE)]
        audioFilter = speedFilter(self.rate, self.keepPitch)
        if audioFilter:
            command += ["-af", audioFilter]
        command += ["-f", "s16le", "-acodec", "pcm_s16le", "-"]
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_FLAGS)
        except Exception as error:
            self.engine._decoderFailed(self.generation, str(error))
            return
        buffer = numpy.zeros((self.estimatedFrames, CHANNELS), dtype=numpy.int16)
        self.engine._attachBuffer(self.generation, buffer)
        frameBytes = 2 * CHANNELS
        decodedFrames = 0
        leftover = b""
        while not self.cancelled:
            chunk = self.process.stdout.read(SAMPLE_RATE * frameBytes // 2)
            if not chunk:
                break
            chunk = leftover + chunk
            usable = len(chunk) - len(chunk) % frameBytes
            leftover = chunk[usable:]
            frames = numpy.frombuffer(chunk[:usable], dtype=numpy.int16).reshape(-1, CHANNELS)
            if decodedFrames + len(frames) > len(buffer):
                newBuffer = numpy.zeros((max(len(buffer) * 2, decodedFrames + len(frames)), CHANNELS), dtype=numpy.int16)
                newBuffer[:decodedFrames] = buffer[:decodedFrames]
                buffer = newBuffer
                self.engine._attachBuffer(self.generation, buffer)
            buffer[decodedFrames:decodedFrames + len(frames)] = frames
            decodedFrames += len(frames)
            self.engine._setDecoded(self.generation, decodedFrames)
        if self.cancelled:
            self._kill()
            return
        self.process.wait()
        errorText = self.process.stderr.read().decode("utf-8", "ignore").strip()
        if decodedFrames == 0:
            self.engine._decoderFailed(self.generation, errorText or "Impossibile decodificare il file")
        else:
            self.engine._decodeFinished(self.generation, decodedFrames)

    def _kill(self):
        try:
            if self.process and self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass

    def cancel(self):
        self.cancelled = True
        self._kill()


class AudioEngine(QObject):
    """Drop-in replacement for the parts of QMediaPlayer + QAudioOutput used by Player, with a realtime EQ."""

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lock = threading.RLock()
        self._source = QUrl()
        self._path = None
        self._state = QMediaPlayer.StoppedState
        self._status = QMediaPlayer.NoMedia
        self._rate = 1.0
        self._keepPitch = True
        self.reverbWet = 0.0
        self.reverbSize = 1.8
        self.reverbSpectra = {}
        self.reverbResponse = None
        self.reverbTail = None
        self._volume = 0.5
        self._muted = False
        self._balance = 0.0
        self.buffer = None
        self.decodedFrames = 0
        self.decodeDone = False
        self.frame = 0
        self.generation = 0
        self.decoder = None
        self.reachedEnd = False
        self.loopFrames = None
        self.loopMs = None
        self.pendingSeekMs = None
        self.durationMs = 0
        self.lastEmittedPosition = -1
        self.failMessage = None
        self.pendingStatus = []

        self.eqEnabled = True
        self.eqGains = [0.0] * len(EQ_FREQUENCIES)
        self.preampDb = 0.0
        self.sos = None
        self.zi = None
        self.preampFactor = 1.0

        self.stream = None
        self.streamError = None

        self.pollTimer = QTimer(self)
        self.pollTimer.setInterval(40)
        self.pollTimer.timeout.connect(self._poll)
        self.pollTimer.start()

    # ---------- QMediaPlayer-like API ----------
    def source(self):
        return self._source

    def setSource(self, url):
        self._cancelDecoder()
        with self.lock:
            self.generation += 1
            self.buffer = None
            self.decodedFrames = 0
            self.decodeDone = False
            self.frame = 0
            self.reachedEnd = False
            self.loopFrames = None
            self.loopMs = None
            self.pendingSeekMs = None
            self.failMessage = None
            self.zi = None
        self._source = QUrl(url) if url is not None else QUrl()
        wasPlaying = self._state == QMediaPlayer.PlayingState
        if self._source.isEmpty():
            self._path = None
            self._setDuration(0)
            self._setState(QMediaPlayer.StoppedState)
            self._setStatus(QMediaPlayer.NoMedia)
            return
        self._path = self._source.toLocalFile()
        self._startDecoder(self._path, 0)
        self._setStatus(QMediaPlayer.LoadingMedia)
        if wasPlaying:
            self._setState(QMediaPlayer.StoppedState)

    def _startDecoder(self, path, startMs):
        estimatedSeconds = 0
        try:
            from .metadata import readTags
            estimatedSeconds = readTags(path)["duration"]
        except Exception:
            pass
        if estimatedSeconds:
            self._setDuration(int(estimatedSeconds * 1000))
        self.decoder = _Decoder(self, path, self._rate, self.generation, estimatedSeconds or 300, self._keepPitch)
        if startMs:
            self.pendingSeekMs = startMs
        self.decoder.start()

    def _cancelDecoder(self):
        if self.decoder is not None:
            self.decoder.cancel()
            self.decoder = None

    def play(self):
        if self._source.isEmpty():
            return
        if not self._ensureStream():
            return
        with self.lock:
            if self.reachedEnd:
                self.reachedEnd = False
                self.frame = 0
        self._setState(QMediaPlayer.PlayingState)

    def pause(self):
        if self._state == QMediaPlayer.PlayingState:
            self._setState(QMediaPlayer.PausedState)

    def stop(self):
        with self.lock:
            self.frame = 0
        self._setState(QMediaPlayer.StoppedState)
        self.positionChanged.emit(0)

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def position(self):
        with self.lock:
            if self.pendingSeekMs is not None:
                return int(self.pendingSeekMs)
            return int(self.frame / SAMPLE_RATE * 1000 * self._rate)

    def duration(self):
        return self.durationMs

    def setPosition(self, positionMs):
        positionMs = max(0, int(positionMs))
        with self.lock:
            targetFrame = int(positionMs / 1000 / self._rate * SAMPLE_RATE)
            if self.decodeDone and targetFrame >= self.decodedFrames:
                targetFrame = max(0, self.decodedFrames - 1)
            self.frame = targetFrame
            self.reachedEnd = False
            self.pendingSeekMs = None
        self.lastEmittedPosition = positionMs
        self.positionChanged.emit(positionMs)

    def presetRate(self, rate, keepPitch=True):
        """Sets speed/pitch mode for the NEXT source without re-decoding the current one."""
        self._rate = max(0.5, min(2.0, float(rate)))
        self._keepPitch = bool(keepPitch)

    def keepPitch(self):
        return self._keepPitch

    def setPlaybackRate(self, rate, keepPitch=None):
        rate = max(0.5, min(2.0, float(rate)))
        keepPitch = self._keepPitch if keepPitch is None else bool(keepPitch)
        if abs(rate - self._rate) < 0.001 and keepPitch == self._keepPitch:
            return
        currentMs = self.position()
        self._rate = rate
        self._keepPitch = keepPitch
        if self._path:
            self._cancelDecoder()
            with self.lock:
                self.generation += 1
                self.buffer = None
                self.decodedFrames = 0
                self.decodeDone = False
                self.frame = 0
                self.zi = None
                if self.loopMs:
                    self.loopFrames = self._msRangeToFrames(*self.loopMs)
            self._startDecoder(self._path, currentMs)
            self.setPosition(currentMs)

    def playbackRate(self):
        return self._rate

    def setLoopRange(self, startMs=None, endMs=None):
        with self.lock:
            if startMs is None:
                self.loopMs = None
                self.loopFrames = None
            else:
                self.loopMs = (int(startMs), int(endMs))
                self.loopFrames = self._msRangeToFrames(startMs, endMs)

    def _msRangeToFrames(self, startMs, endMs):
        return (int(startMs / 1000 / self._rate * SAMPLE_RATE), int(endMs / 1000 / self._rate * SAMPLE_RATE))

    # ---------- QAudioOutput-like API ----------
    def setVolume(self, volume):
        self._volume = max(0.0, min(1.0, float(volume)))

    def volume(self):
        return self._volume

    def setMuted(self, muted):
        self._muted = bool(muted)

    def isMuted(self):
        return self._muted

    def setBalance(self, balance):
        self._balance = max(-1.0, min(1.0, float(balance)))

    # ---------- equalizer ----------
    def setEqualizer(self, gains, preampDb, enabled):
        gains = [float(value) for value in gains]
        newSos = buildEqSos(gains) if enabled else None
        with self.lock:
            self.eqGains = gains
            self.preampDb = float(preampDb)
            self.eqEnabled = bool(enabled)
            self.preampFactor = 10 ** (self.preampDb / 20.0) if enabled else 1.0
            if newSos is None or self.sos is None or newSos.shape != self.sos.shape:
                self.zi = None
            self.sos = newSos

    # ---------- reverb ----------
    def setReverb(self, wet, decaySeconds):
        wet = max(0.0, min(1.0, float(wet)))
        decaySeconds = max(0.2, min(6.0, float(decaySeconds)))
        response = None
        if wet > 0.001:
            if self.reverbResponse is not None and abs(decaySeconds - self.reverbSize) < 0.01:
                response = self.reverbResponse
            else:
                response = makeImpulseResponse(decaySeconds)
        with self.lock:
            if response is not self.reverbResponse:
                self.reverbSpectra = {}
                self.reverbTail = None
            self.reverbResponse = response
            self.reverbWet = wet
            self.reverbSize = decaySeconds

    def _prepareReverb(self, blockSize):
        response = self.reverbResponse
        partitions = int(numpy.ceil(len(response) / blockSize))
        padded = numpy.zeros((partitions * blockSize, CHANNELS), dtype=numpy.float32)
        padded[:len(response)] = response
        spectra = numpy.empty((partitions, blockSize + 1, CHANNELS), dtype=numpy.complex64)
        for index in range(partitions):
            segment = numpy.zeros((2 * blockSize, CHANNELS), dtype=numpy.float32)
            segment[:blockSize] = padded[index * blockSize:(index + 1) * blockSize]
            spectra[index] = numpy.fft.rfft(segment, axis=0)
        self.reverbSpectra = {"blockSize": blockSize, "spectra": spectra,
                              "history": numpy.zeros((partitions, blockSize + 1, CHANNELS), dtype=numpy.complex64),
                              "position": 0, "previous": numpy.zeros((blockSize, CHANNELS), dtype=numpy.float32)}

    def _applyReverb(self, samples):
        """Uniformly partitioned overlap-save convolution: cheap enough for the audio callback."""
        if self.reverbResponse is None or self.reverbWet <= 0.001:
            return samples
        blockSize = len(samples)
        state = self.reverbSpectra
        if not state or state.get("blockSize") != blockSize:
            self._prepareReverb(blockSize)
            state = self.reverbSpectra
        current = samples.astype(numpy.float32)
        inputSpectrum = numpy.fft.rfft(numpy.vstack([state["previous"], current]), axis=0)
        state["previous"] = current
        partitions = len(state["spectra"])
        position = (state["position"] + 1) % partitions
        state["position"] = position
        state["history"][position] = inputSpectrum
        order = (position - numpy.arange(partitions)) % partitions
        outputSpectrum = numpy.einsum("kfc,kfc->fc", state["history"][order], state["spectra"])
        wetSignal = numpy.fft.irfft(outputSpectrum, 2 * blockSize, axis=0)[blockSize:]
        wet = self.reverbWet
        return samples * (1.0 - 0.45 * wet) + wetSignal * (0.6 * wet)

    # ---------- output stream ----------
    def _ensureStream(self):
        if self.stream is not None and self.streamError is None:
            return True
        self._closeStream()
        try:
            import sounddevice
            self.stream = sounddevice.OutputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32", blocksize=BLOCK_SIZE,
                latency=OUTPUT_LATENCY, callback=self._callback, finished_callback=self._onStreamFinished,
            )
            self.stream.start()
            self.streamError = None
            return True
        except Exception as error:
            self.stream = None
            self.errorOccurred.emit(QMediaPlayer.ResourceError, f"Dispositivo audio non disponibile: {error}")
            return False

    def _closeStream(self):
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
        self.stream = None

    def _onStreamFinished(self):
        self.streamError = "finished"

    def shutdown(self):
        self._cancelDecoder()
        self._closeStream()

    def _readFrames(self, count):
        """Returns (frames float32 [count, 2], reachedEnd). Called with lock held."""
        output = numpy.zeros((count, CHANNELS), dtype=numpy.float32)
        buffer = self.buffer
        if buffer is None:
            return output, False
        written = 0
        endReached = False
        guard = 0
        while written < count and guard < 8:
            guard += 1
            limit = self.decodedFrames
            if self.loopFrames:
                if self.frame >= self.loopFrames[1]:
                    self.frame = self.loopFrames[0]
                limit = min(limit, self.loopFrames[1])
            available = limit - self.frame
            if available <= 0:
                if self.decodeDone:
                    if self.loopFrames and self.loopFrames[0] < self.decodedFrames:
                        self.frame = self.loopFrames[0]
                        continue
                    endReached = True
                break
            take = min(available, count - written)
            output[written:written + take] = buffer[self.frame:self.frame + take].astype(numpy.float32) * (1.0 / 32768.0)
            written += take
            self.frame += take
            if self.loopFrames and self.frame >= self.loopFrames[1]:
                self.frame = self.loopFrames[0]
        return output, endReached

    def _callback(self, outdata, frames, timeInfo, status):
        with self.lock:
            if self._state != QMediaPlayer.PlayingState or self.pendingSeekMs is not None and self.buffer is None:
                outdata.fill(0)
                return
            if self.pendingSeekMs is not None:
                targetFrame = int(self.pendingSeekMs / 1000 / self._rate * SAMPLE_RATE)
                if targetFrame < self.decodedFrames or self.decodeDone:
                    self.frame = min(targetFrame, max(0, self.decodedFrames - 1))
                    self.pendingSeekMs = None
                else:
                    outdata.fill(0)
                    return
            samples, endReached = self._readFrames(frames)
            if endReached:
                self.reachedEnd = True
            sos = self.sos
            if sos is not None:
                from scipy.signal import sosfilt
                if self.zi is None or self.zi.shape[0] != sos.shape[0]:
                    self.zi = numpy.zeros((sos.shape[0], 2, CHANNELS))
                samples, self.zi = sosfilt(sos, samples, axis=0, zi=self.zi)
            samples = self._applyReverb(samples)
            gain = 0.0 if self._muted else self._volume * self.preampFactor
            samples = samples * gain
            if self._balance:
                samples[:, 0] *= min(1.0, 1.0 - self._balance)
                samples[:, 1] *= min(1.0, 1.0 + self._balance)
            outdata[:] = _softLimit(samples).astype(numpy.float32)

    # ---------- decoder callbacks (worker thread) ----------
    def _attachBuffer(self, generation, buffer):
        with self.lock:
            if generation == self.generation:
                self.buffer = buffer
                if self.decodedFrames == 0:
                    self.pendingStatus.append(QMediaPlayer.LoadedMedia)

    def _setDecoded(self, generation, decodedFrames):
        with self.lock:
            if generation == self.generation:
                self.decodedFrames = decodedFrames

    def _decodeFinished(self, generation, decodedFrames):
        with self.lock:
            if generation == self.generation:
                self.decodedFrames = decodedFrames
                self.decodeDone = True
                self.pendingStatus.append(("duration", int(decodedFrames / SAMPLE_RATE * 1000 * self._rate)))
                self.pendingStatus.append(QMediaPlayer.BufferedMedia)

    def _decoderFailed(self, generation, message):
        with self.lock:
            if generation == self.generation:
                self.failMessage = message or "Errore di decodifica"

    # ---------- main-thread polling ----------
    def _poll(self):
        with self.lock:
            pending = self.pendingStatus
            self.pendingStatus = []
            failMessage = self.failMessage
            self.failMessage = None
            reachedEnd = self.reachedEnd and self._state == QMediaPlayer.PlayingState
        for item in pending:
            if isinstance(item, tuple) and item[0] == "duration":
                self._setDuration(item[1])
            else:
                self._setStatus(item)
        if failMessage:
            self._setStatus(QMediaPlayer.InvalidMedia)
            self._setState(QMediaPlayer.StoppedState)
            self.errorOccurred.emit(QMediaPlayer.FormatError, failMessage)
            return
        if self.streamError and self._state == QMediaPlayer.PlayingState:
            self._ensureStream()
        if self._state == QMediaPlayer.PlayingState:
            position = self.position()
            if position != self.lastEmittedPosition:
                self.lastEmittedPosition = position
                self.positionChanged.emit(position)
        if reachedEnd:
            with self.lock:
                self.reachedEnd = False
            self._setState(QMediaPlayer.StoppedState)
            self._setStatus(QMediaPlayer.EndOfMedia)

    def _setState(self, state):
        if state != self._state:
            self._state = state
            self.playbackStateChanged.emit(state)

    def _setStatus(self, status):
        if status != self._status or status == QMediaPlayer.EndOfMedia:
            self._status = status
            self.mediaStatusChanged.emit(status)

    def _setDuration(self, durationMs):
        if durationMs != self.durationMs:
            self.durationMs = durationMs
            self.durationChanged.emit(durationMs)
