import collections
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
import zlib

from PySide6.QtCore import QObject, QTimer, Signal

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_PREFIX = "SYNTH"
PLAYLIST_PREFIX = "SYNTHP"
LINK_SCHEME = "synthmusic://join/"
# Every server has a normal TLS port and a WebSocket-over-TLS one (like a website): if a network blocks one, the other is tried.
DEFAULT_BROKERS = [
    [("broker.hivemq.com", 8883, True, None), ("broker.hivemq.com", 8884, True, "/mqtt")],
    [("broker.emqx.io", 8883, True, None), ("broker.emqx.io", 8084, True, "/mqtt")],
    [("test.mosquitto.org", 8886, True, None), ("test.mosquitto.org", 8081, True, "/")],
]
ENDPOINT_SWITCH_SECONDS = 8
MAX_PAYLOAD = 2 * 1024 * 1024
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
    """List of servers; each server is a list of endpoints (host, port, tls, websocketPath or None).
    SYNTH_BROKERS="host:port:tls[:wspath]|other endpoint of the same server,next server,..."."""
    configured = os.environ.get("SYNTH_BROKERS", "").strip()
    if not configured:
        return [list(endpoints) for endpoints in DEFAULT_BROKERS]
    servers = []
    for server in configured.split(","):
        endpoints = []
        for item in server.split("|"):
            parts = item.split(":")
            host, port, useTls = (parts + ["1"])[:3]
            path = parts[3] if len(parts) > 3 and parts[3] else None
            endpoints.append((host, int(port), useTls not in ("0", "false", ""), path))
        servers.append(endpoints)
    return servers


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


class _BrokerConnection:
    """One always-retrying MQTT connection to one public server (paho reconnects by itself)."""

    def __init__(self, link, index, endpoints):
        self.link = link
        self.index = index
        self.endpoints = list(endpoints)
        self.endpointIndex = 0
        self.client = None
        self.connected = False
        self.attempt = 0
        self.startedAt = 0.0
        self.lastError = ""

    @property
    def host(self):
        return self.endpoints[self.endpointIndex][0]

    def describe(self):
        host, port, useTls, path = self.endpoints[self.endpointIndex]
        return f"{host}:{port}" + (" (web)" if path else "")

    def switchEndpoint(self):
        """No answer from this port: try the next one of the same server (e.g. the WebSocket port)."""
        if len(self.endpoints) > 1:
            self.endpointIndex = (self.endpointIndex + 1) % len(self.endpoints)
        self.connect()

    def connect(self):
        import paho.mqtt.client as mqtt
        self.drop(graceful=False)
        self.attempt += 1
        attempt = self.attempt
        self.startedAt = time.monotonic()
        host, port, useTls, path = self.endpoints[self.endpointIndex]
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"synth-{uuid.uuid4().hex[:16]}",
                             protocol=mqtt.MQTTv311, clean_session=True, transport="websockets" if path else "tcp")
        if path:
            client.ws_set_options(path=path)
        client.max_queued_messages_set(200)
        if useTls:
            client.tls_set()
        will = self.link.will
        if will:
            box = self.link.boxes.get(will[0]) or CodeBox(will[0])
            client.will_set(f"{box.topicBase}/{will[1]}", b"", qos=1, retain=True)
        client.reconnect_delay_set(1, 30)
        index = self.index

        def onConnect(clientRef, userdata, flags, reasonCode, properties):
            if reasonCode.is_failure:
                self.lastError = f"rifiutato ({reasonCode})"
            self.link._connectionEvent.emit(index, attempt, not reasonCode.is_failure)

        def onConnectFail(clientRef, userdata):
            self.lastError = "connessione fallita (porta bloccata o server giù)"
            self.link._connectionEvent.emit(index, attempt, False)

        def onDisconnect(clientRef, userdata, flags, reasonCode, properties):
            if reasonCode.is_failure:
                self.lastError = f"disconnesso ({reasonCode})"
            self.link._connectionEvent.emit(index, attempt, False)

        def onMessage(clientRef, userdata, message):
            self.link._incoming.emit(index, message.topic, bytes(message.payload))

        client.on_connect = onConnect
        client.on_connect_fail = onConnectFail
        client.on_disconnect = onDisconnect
        client.on_message = onMessage
        self.client = client
        try:
            client.connect_async(host, port, keepalive=30)
            client.loop_start()
        except Exception as error:
            self.lastError = repr(error)
            print(f"[Link] {self.describe()} non raggiungibile: {error!r}")

    def drop(self, graceful):
        client = self.client
        self.client = None
        self.connected = False
        self.attempt += 1
        if client is None:
            return
        client.on_connect = None
        client.on_connect_fail = None
        client.on_disconnect = None
        client.on_message = None

        def close():
            # In the background: a server that never answers keeps paho's thread stuck in the handshake,
            # and waiting for it here froze the whole app for up to 30 seconds.
            try:
                if graceful:
                    client.disconnect()
                client.loop_stop()
            except Exception:
                pass

        threading.Thread(target=close, daemon=True).start()

    def publish(self, topic, data, retain):
        if self.client is not None:
            return self.client.publish(topic, data, qos=1, retain=retain)
        return None


class Link(QObject):
    """Connected to ALL the public servers at once: friends meet even if one of them can't reach a server.
    Every message goes to every server; duplicates are dropped on arrival."""

    received = Signal(str, str, object)
    connectedChanged = Signal(bool)
    _connectionEvent = Signal(int, int, bool)
    _incoming = Signal(int, str, bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = {}
        self.subtopics = {}
        self.retainedOut = {}
        self.will = None
        self.brokers = brokerList()
        self.connections = [_BrokerConnection(self, index, endpoints) for index, endpoints in enumerate(self.brokers)]
        self.switchSeconds = ENDPOINT_SWITCH_SECONDS
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self._checkEndpoints)
        self.connected = False
        self.running = False
        self.seenMessages = collections.OrderedDict()
        self.retainedSeen = {}
        self._connectionEvent.connect(self._onConnectionEvent)
        self._incoming.connect(self._onIncoming)

    # ---------- public API ----------
    def start(self):
        if self.running:
            return
        self.running = True
        for connection in self.connections:
            connection.connect()
        self.watchdog.start()

    def stop(self):
        self.running = False
        self.watchdog.stop()
        for connection in self.connections:
            connection.drop(graceful=True)
        self.retainedSeen.clear()
        self.seenMessages.clear()
        self._updateConnected()

    def restart(self):
        for connection in self.connections:
            connection.drop(graceful=True)
        self.retainedSeen.clear()
        self.seenMessages.clear()
        self._updateConnected()
        if self.running:
            for connection in self.connections:
                connection.connect()

    def watch(self, code, subtopics):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes[code] = box
        self.subtopics[code] = list(subtopics)
        for connection in self.connections:
            if connection.connected and connection.client is not None:
                for subtopic in subtopics:
                    connection.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)

    def unwatch(self, code):
        box = self.boxes.pop(code, None)
        subtopics = self.subtopics.pop(code, [])
        for key in [key for key in self.retainedOut if key[0] == code]:
            del self.retainedOut[key]
        for key in [key for key in self.retainedSeen if key[0] == code]:
            del self.retainedSeen[key]
        if box is not None:
            for connection in self.connections:
                if connection.connected and connection.client is not None:
                    for subtopic in subtopics:
                        connection.client.unsubscribe(f"{box.topicBase}/{subtopic}")

    def setWill(self, code, subtopic):
        """Empty retained message the servers publish if this app disappears (crash, internet down)."""
        self.will = (code, subtopic) if code else None

    def publish(self, code, subtopic, payload, retain=False):
        box = self.boxes.get(code) or CodeBox(code)
        self.boxes.setdefault(code, box)
        if isinstance(payload, dict):
            payload = dict(payload, _mid=uuid.uuid4().hex[:16])
        data = box.seal(payload)
        if retain:
            self.retainedOut[(code, subtopic)] = data
        for connection in self.connections:
            connection.publish(f"{box.topicBase}/{subtopic}", data, retain)

    def clearRetained(self, code, subtopic):
        self.retainedOut.pop((code, subtopic), None)
        box = self.boxes.get(code) or CodeBox(code)
        infos = [connection.publish(f"{box.topicBase}/{subtopic}", b"", True) for connection in self.connections
                 if connection.connected]
        deadline = time.monotonic() + 1.0
        for info in infos:
            try:
                if info is not None:
                    info.wait_for_publish(max(0.05, deadline - time.monotonic()))
            except Exception:
                pass

    def isConnected(self):
        return self.connected

    def brokerName(self):
        return ", ".join(connection.describe() for connection in self.connections if connection.connected)

    def connectedCount(self):
        return sum(1 for connection in self.connections if connection.connected)

    # ---------- connection ----------
    def _checkEndpoints(self):
        if not self.running:
            return
        for connection in self.connections:
            if not connection.connected and time.monotonic() - connection.startedAt > self.switchSeconds:
                connection.lastError = connection.lastError or f"nessuna risposta in {self.switchSeconds}s"
                print(f"[Link] {connection.describe()} non risponde ({connection.lastError}), provo un'altra porta")
                connection.switchEndpoint()

    def _onConnectionEvent(self, index, attempt, success):
        connection = self.connections[index]
        if attempt != connection.attempt or not self.running:
            return
        if success:
            connection.connected = True
            connection.lastError = ""
            connection.loggedError = ""
            print(f"[Link] connesso a {connection.describe()}")
            for code, subtopics in self.subtopics.items():
                box = self.boxes[code]
                for subtopic in subtopics:
                    connection.client.subscribe(f"{box.topicBase}/{subtopic}", qos=1)
            for (code, subtopic), data in self.retainedOut.items():
                connection.publish(f"{self.boxes[code].topicBase}/{subtopic}", data, True)
        else:
            if connection.lastError and connection.lastError != getattr(connection, "loggedError", ""):
                connection.loggedError = connection.lastError
                print(f"[Link] {connection.describe()}: {connection.lastError}")
            if connection.connected:
                print(f"[Link] connessione persa con {connection.describe()}, riprovo")
                connection.startedAt = time.monotonic()
            connection.connected = False
            for key in list(self.retainedSeen):
                self.retainedSeen[key].discard(index)
        self._updateConnected()

    def _updateConnected(self):
        connected = any(connection.connected for connection in self.connections)
        if connected != self.connected:
            self.connected = connected
            self.connectedChanged.emit(connected)

    def _onIncoming(self, index, topic, data):
        for code, box in list(self.boxes.items()):
            prefix = box.topicBase + "/"
            if not topic.startswith(prefix):
                continue
            subtopic = topic[len(prefix):]
            key = (code, subtopic)
            if not data:
                holders = self.retainedSeen.get(key)
                if holders is not None:
                    holders.discard(index)
                    if holders:
                        return
                    del self.retainedSeen[key]
                self.received.emit(code, subtopic, None)
                return
            payload = box.open(data)
            if payload is None:
                return
            messageId = payload.pop("_mid", None) if isinstance(payload, dict) else None
            if messageId:
                firstTime = messageId not in self.seenMessages
                self.seenMessages[messageId] = True
                while len(self.seenMessages) > 2000:
                    self.seenMessages.popitem(last=False)
                self.retainedSeen.setdefault(key, set()).add(index)
                if not firstTime:
                    return
            else:
                self.retainedSeen.setdefault(key, set()).add(index)
            self.received.emit(code, subtopic, payload)
            return
