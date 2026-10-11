import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
import zlib

from PySide6.QtCore import QObject, QTimer, Signal

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_PREFIX = "SYNTH"
PLAYLIST_PREFIX = "SYNTHP"
LINK_SCHEME = "synthmusic://join/"
DEFAULT_BROKERS = [("broker.hivemq.com", 8883, True), ("broker.emqx.io", 8883, True), ("test.mosquitto.org", 8886, True)]
MAX_PAYLOAD = 2 * 1024 * 1024
PRIMARY_RETRY_MS = 5 * 60 * 1000
_CODE_PATTERN = re.compile(r"(SYNTHP|SYNTH)-([A-Z0-9]{4})-([A-Z0-9]{4})")


def makeCode(prefix=ROOM_PREFIX):
    groups = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(2)]
    return f"{prefix}-{groups[0]}-{groups[1]}"


def parseCode(text):
    """Accepts a code or a synthmusic:// link (any case, extra spaces). Returns ("room"|"playlist", code) or None."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", "", str(text)).upper()
    match = _CODE_PATTERN.search(cleaned)
    if not match:
        return None
    prefix, first, second = match.groups()
    if any(character not in CODE_ALPHABET for character in first + second):
        return None
    code = f"{prefix}-{first}-{second}"
    return ("playlist" if prefix == PLAYLIST_PREFIX else "room"), code


def linkFor(code):
    return LINK_SCHEME + code


def brokerList():
    configured = os.environ.get("SYNTH_BROKERS", "").strip()
    if not configured:
        return list(DEFAULT_BROKERS)
    brokers = []
    for item in configured.split(","):
        host, port, useTls = (item.split(":") + ["1"])[:3]
        brokers.append((host, int(port), useTls not in ("0", "false", "")))
    return brokers


class CodeBox:
    """Encrypts and signs messages with a key derived from the code: without the code nobody can read or forge them."""

    def __init__(self, code):
        self.code = code
        keyMaterial = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), b"synthmusic-v1", 20000, 64)
        self.encryptionKey = keyMaterial[:32]
        self.macKey = keyMaterial[32:]
        kind = "p" if code.startswith(PLAYLIST_PREFIX + "-") else "r"
        self.topicBase = f"synthmusic/v1/{kind}/" + hashlib.sha256(b"topic:" + code.encode("utf-8")).hexdigest()[:24]

    def _keystream(self, nonce, length):
        blocks = []
        for counter in range((length + 31) // 32):
            blocks.append(hashlib.sha256(self.encryptionKey + nonce + counter.to_bytes(8, "big")).digest())
        return b"".join(blocks)[:length]

    def _xor(self, data, nonce):
        stream = self._keystream(nonce, len(data))
        return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big") if data else b""

    def seal(self, payload):
        plain = zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"), 6)
        nonce = os.urandom(16)
        cipher = self._xor(plain, nonce)
        mac = hmac.new(self.macKey, nonce + cipher, hashlib.sha256).digest()[:16]
        return b"\x01" + nonce + mac + cipher

    def open(self, data):
        try:
            if not data or len(data) < 33 or data[0] != 1:
                return None
            nonce, mac, cipher = data[1:17], data[17:33], data[33:]
            expected = hmac.new(self.macKey, nonce + cipher, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(mac, expected):
                return None
            decompressor = zlib.decompressobj()
            plain = decompressor.decompress(self._xor(cipher, nonce), MAX_PAYLOAD)
            if decompressor.unconsumed_tail:
                return None
            return json.loads(plain.decode("utf-8"))
        except Exception:
            return None


class Link(QObject):
    """One MQTT connection to the first public broker that answers; reconnects and fails over by itself."""

    received = Signal(str, str, object)
    connectedChanged = Signal(bool)
    _connectResult = Signal(int, str)
    _incoming = Signal(str, bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = {}
        self.subtopics = {}
        self.retainedOut = {}
        self.will = None
        self.client = None
        self.brokers = brokerList()
        self.brokerIndex = 0
        self.attempt = 0
        self.connected = False
        self.running = False
        self.failures = 0
        self._connectResult.connect(self._onConnectResult)
        self._incoming.connect(self._onIncoming)
        self.retryTimer = QTimer(self)
        self.retryTimer.setSingleShot(True)
        self.retryTimer.timeout.connect(self._connect)
        self.primaryTimer = QTimer(self)
        self.primaryTimer.setInterval(PRIMARY_RETRY_MS)
        self.primaryTimer.timeout.connect(self._backToPrimary)

    # ---------- public API ----------
    def start(self):
        if self.running:
            return
        self.running = True
        self._connect()

    def stop(self):
        self.running = False
        self.retryTimer.stop()
        self.primaryTimer.stop()
        self._dropClient(graceful=True)
        self._setConnected(False)

    def restart(self):
        self._dropClient(graceful=True)
        self._setConnected(False)
        if self.running:
            self._connect()

    def watch(self, code, subtopics):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes[code] = box
        self.subtopics[code] = list(subtopics)
        if self.connected and self.client is not None:
            for subtopic in subtopics:
                self.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)

    def unwatch(self, code):
        box = self.boxes.pop(code, None)
        subtopics = self.subtopics.pop(code, [])
        for key in [key for key in self.retainedOut if key[0] == code]:
            del self.retainedOut[key]
        if box is not None and self.connected and self.client is not None:
            for subtopic in subtopics:
                self.client.unsubscribe(f"{box.topicBase}/{subtopic}")

    def setWill(self, code, subtopic):
        """Empty retained message the broker publishes if this app disappears (crash, internet down)."""
        self.will = (code, subtopic) if code else None

    def publish(self, code, subtopic, payload, retain=False):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes.setdefault(code, box)
        data = box.seal(payload)
        if retain:
            self.retainedOut[(code, subtopic)] = data
        if self.client is not None:
            self.client.publish(f"{box.topicBase}/{subtopic}", data, qos=1, retain=retain)

    def clearRetained(self, code, subtopic):
        self.retainedOut.pop((code, subtopic), None)
        box = self.boxes.get(code) or CodeBox(code)
        if self.client is not None:
            info = self.client.publish(f"{box.topicBase}/{subtopic}", b"", qos=1, retain=True)
            try:
                info.wait_for_publish(1.5)
            except Exception:
                pass

    def isConnected(self):
        return self.connected

    def brokerName(self):
        return self.brokers[self.brokerIndex][0] if self.brokers else ""

    # ---------- connection ----------
    def _connect(self):
        if not self.running:
            return
        import paho.mqtt.client as mqtt
        self._dropClient(graceful=False)
        self.attempt += 1
        attempt = self.attempt
        host, port, useTls = self.brokers[self.brokerIndex % len(self.brokers)]
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"synth-{uuid.uuid4().hex[:16]}",
                             protocol=mqtt.MQTTv311, clean_session=True)
        client.max_queued_messages_set(200)
        if useTls:
            client.tls_set()
        if self.will:
            box = self.boxes.get(self.will[0]) or CodeBox(self.will[0])
            client.will_set(f"{box.topicBase}/{self.will[1]}", b"", qos=1, retain=True)
        client.reconnect_delay_set(1, 20)

        attemptState = {"confirmed": False}

        def onConnect(clientRef, userdata, flags, reasonCode, properties):
            attemptState["confirmed"] = not reasonCode.is_failure
            self._connectResult.emit(attempt, "failed" if reasonCode.is_failure else "connected")

        def onConnectFail(clientRef, userdata):
            self._connectResult.emit(attempt, "failed")

        def onDisconnect(clientRef, userdata, flags, reasonCode, properties):
            confirmed = attemptState["confirmed"]
            attemptState["confirmed"] = False
            self._connectResult.emit(attempt, "lost" if confirmed else "failed")

        def onMessage(clientRef, userdata, message):
            self._incoming.emit(message.topic, bytes(message.payload))

        client.on_connect = onConnect
        client.on_connect_fail = onConnectFail
        client.on_disconnect = onDisconnect
        client.on_message = onMessage
        self.client = client
        try:
            client.connect_async(host, port, keepalive=30)
            client.loop_start()
        except Exception as error:
            print(f"[Link] {host}:{port} non raggiungibile: {error!r}")
            self._connectResult.emit(attempt, "failed")

    def _onConnectResult(self, attempt, result):
        if attempt != self.attempt or not self.running:
            return
        if result == "connected":
            self.failures = 0
            for code, subtopics in self.subtopics.items():
                box = self.boxes[code]
                for subtopic in subtopics:
                    self.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)
            for (code, subtopic), data in self.retainedOut.items():
                self.client.publish(f"{self.boxes[code].topicBase}/{subtopic}", data, qos=1, retain=True)
            self._setConnected(True)
            if self.brokerIndex != 0:
                self.primaryTimer.start()
            else:
                self.primaryTimer.stop()
            return
        self._setConnected(False)
        if result == "lost":
            return
        self.failures += 1
        if self.failures >= 2:
            self.failures = 0
            self.brokerIndex = (self.brokerIndex + 1) % len(self.brokers)
            print(f"[Link] passo al server {self.brokerName()}")
            self.retryTimer.start(500)

    def _backToPrimary(self):
        """Everybody prefers the first server: after a failover, go back to it so friends end up on the same one."""
        self.primaryTimer.stop()
        if self.running and self.brokerIndex != 0:
            self.brokerIndex = 0
            self.failures = 0
            self.restart()

    def _dropClient(self, graceful):
        client = self.client
        self.client = None
        self.attempt += 1
        if client is None:
            return
        try:
            if graceful:
                client.disconnect()
            client.loop_stop()
        except Exception:
            pass

    def _setConnected(self, connected):
        if connected != self.connected:
            self.connected = connected
            self.connectedChanged.emit(connected)

    def _onIncoming(self, topic, data):
        for code, box in list(self.boxes.items()):
            prefix = box.topicBase + "/"
            if topic.startswith(prefix):
                subtopic = topic[len(prefix):]
                if not data:
                    self.received.emit(code, subtopic, None)
                    return
                payload = box.open(data)
                if payload is not None:
                    self.received.emit(code, subtopic, payload)
                return
