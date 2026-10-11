import os
import signal
import subprocess
import sys
import textwrap

from app.session_link import CodeBox, Link, linkFor, makeCode, parseCode
from tests.broker import localBroker, pump, secondBroker, waitFor, webSocketBroker  # noqa: F401


def test_sealOpenRoundTrip():
    box = CodeBox("SYNTH-ABCD-EFGH")
    payload = {"song": "Ciao", "positionMs": 1234, "photo": "x" * 20000}
    assert box.open(box.seal(payload)) == payload


def test_tamperedOrForeignMessagesRejected():
    box = CodeBox("SYNTH-ABCD-EFGH")
    sealed = bytearray(box.seal({"a": 1}))
    sealed[-1] ^= 0x01
    assert box.open(bytes(sealed)) is None
    assert CodeBox("SYNTH-ABCD-EFGJ").open(box.seal({"a": 1})) is None
    assert box.open(b"") is None
    assert box.open(b"garbage" * 10) is None


def test_topicDependsOnCodeAndKind():
    assert CodeBox("SYNTH-ABCD-EFGH").topicBase != CodeBox("SYNTH-ABCD-EFGJ").topicBase
    assert "/r/" in CodeBox("SYNTH-ABCD-EFGH").topicBase
    assert "/p/" in CodeBox("SYNTHP-ABCD-EFGH").topicBase
    assert "ABCD" not in CodeBox("SYNTH-ABCD-EFGH").topicBase


def test_parseCodeAcceptsCodesAndLinks():
    code = makeCode()
    assert parseCode(code) == ("room", code)
    assert parseCode(linkFor(code)) == ("room", code)
    assert parseCode("  " + code.lower() + " ") == ("room", code)
    assert parseCode("Entra qui: synthmusic://join/SYNTHP-ABCD-EFGH grazie") == ("playlist", "SYNTHP-ABCD-EFGH")
    assert parseCode("SYNTH-AB0D-EFGH") is None
    assert parseCode("ciao") is None
    assert parseCode("") is None
    assert makeCode("SYNTHP").startswith("SYNTHP-")


def test_twoLinksExchangeAndRetainedState(localBroker):
    code = makeCode()
    first, second = Link(), Link()
    received = []
    second.received.connect(lambda c, subtopic, payload: received.append((subtopic, payload)))
    first.watch(code, ["state", "msg"])
    first.start()
    assert waitFor(first.isConnected)
    first.publish(code, "state", {"version": 1}, retain=True)
    pump(0.3)
    second.watch(code, ["state", "msg", "presence/+"])
    second.start()
    assert waitFor(lambda: ("state", {"version": 1}) in received)
    first.publish(code, "msg", {"type": "ping"})
    assert waitFor(lambda: ("msg", {"type": "ping"}) in received)
    first.stop()
    second.stop()


def test_willClearsPresenceWhenAppDies(localBroker):
    code = makeCode()
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {os.getcwd()!r})
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication([])
        from app.session_link import Link
        link = Link()
        link.watch({code!r}, ["presence/+"])
        link.setWill({code!r}, "presence/dying")
        link.start()
        deadline = time.time() + 5
        while not link.isConnected() and time.time() < deadline:
            app.processEvents(); time.sleep(0.01)
        link.publish({code!r}, "presence/dying", {{"name": "Luca"}}, retain=True)
        print("ready", flush=True)
        while True:
            app.processEvents(); time.sleep(0.01)
    """)
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, env=dict(os.environ))
    line = b""
    for _ in range(10):
        line = process.stdout.readline().strip()
        if line == b"ready" or not line:
            break
    assert line == b"ready"
    watcher = Link()
    events = []
    watcher.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    watcher.watch(code, ["presence/+"])
    watcher.start()
    assert waitFor(lambda: ("presence/dying", {"name": "Luca"}) in events)
    process.send_signal(signal.SIGKILL)
    process.wait()
    assert waitFor(lambda: ("presence/dying", None) in events, timeout=60)
    watcher.stop()


def test_failoverToSecondBroker(localBroker):
    from tests.broker import freePort
    deadPort = freePort()
    previous = os.environ["SYNTH_BROKERS"]
    os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{deadPort}:0,{previous}"
    try:
        link = Link()
        link.watch(makeCode(), ["state"])
        link.start()
        assert waitFor(link.isConnected, timeout=20)
        assert [c.connected for c in link.connections] == [False, True]
        link.stop()
    finally:
        os.environ["SYNTH_BROKERS"] = previous


def test_failoverWhenBrokerDropsBeforeConfirming(localBroker):
    import socket
    import threading
    from tests.broker import freePort
    dropPort = freePort()
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", dropPort))
    listener.listen(16)
    running = [True]

    def dropConnections():
        listener.settimeout(0.2)
        while running[0]:
            try:
                connection, _ = listener.accept()
                connection.close()
            except OSError:
                pass

    threading.Thread(target=dropConnections, daemon=True).start()
    previous = os.environ["SYNTH_BROKERS"]
    os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{dropPort}:0,{previous}"
    try:
        link = Link()
        link.watch(makeCode(), ["state"])
        link.start()
        assert waitFor(link.isConnected, timeout=25)
        assert [c.connected for c in link.connections] == [False, True]
        link.stop()
    finally:
        os.environ["SYNTH_BROKERS"] = previous
        running[0] = False
        listener.close()


def test_friendsMeetEvenIfOneCannotReachTheFirstServer(localBroker, secondBroker):
    from tests.broker import freePort
    previous = os.environ["SYNTH_BROKERS"]
    code = makeCode()
    try:
        os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{localBroker}:0,127.0.0.1:{secondBroker}:0"
        alice = Link()
        os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{freePort()}:0,127.0.0.1:{secondBroker}:0"
        bruno = Link()
    finally:
        os.environ["SYNTH_BROKERS"] = previous
    aliceEvents, brunoEvents = [], []
    alice.received.connect(lambda c, subtopic, payload: aliceEvents.append((subtopic, payload)))
    bruno.received.connect(lambda c, subtopic, payload: brunoEvents.append((subtopic, payload)))
    for link, name in ((alice, "alice"), (bruno, "bruno")):
        link.watch(code, ["state", "msg", "presence/+"])
        link.setWill(code, f"presence/{name}")
        link.publish(code, f"presence/{name}", {"name": name}, retain=True)
        link.start()
    assert waitFor(lambda: ("presence/alice", {"name": "alice"}) in brunoEvents
                   and ("presence/bruno", {"name": "bruno"}) in aliceEvents, 20)
    alice.publish(code, "msg", {"type": "ciao"})
    assert waitFor(lambda: ("msg", {"type": "ciao"}) in brunoEvents, 10)
    pump(1)
    assert aliceEvents.count(("presence/bruno", {"name": "bruno"})) == 1
    assert ("presence/bruno", None) not in aliceEvents
    bruno.publish(code, "msg", {"type": "uno"})
    pump(1)
    assert aliceEvents.count(("msg", {"type": "uno"})) == 1
    alice.stop()
    bruno.stop()


def test_presenceSurvivesOneServerDropping(localBroker, secondBroker):
    previous = os.environ["SYNTH_BROKERS"]
    code = makeCode()
    os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{localBroker}:0,127.0.0.1:{secondBroker}:0"
    try:
        alice, bruno = Link(), Link()
    finally:
        os.environ["SYNTH_BROKERS"] = previous
    events = []
    alice.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    alice.watch(code, ["presence/+"])
    bruno.watch(code, ["presence/+"])
    bruno.setWill(code, "presence/bruno")
    bruno.publish(code, "presence/bruno", {"name": "bruno"}, retain=True)
    alice.start()
    bruno.start()
    assert waitFor(lambda: ("presence/bruno", {"name": "bruno"}) in events, 15)
    assert waitFor(lambda: len([c for c in bruno.connections if c.connected]) == 2, 15)
    bruno.connections[0].client._sock.close()
    pump(3)
    assert ("presence/bruno", None) not in events
    alice.stop()
    bruno.stop()


def test_switchesToWebSocketPortWhenNormalPortIsBlocked(webSocketBroker):
    from tests.broker import freePort
    previous = os.environ.get("SYNTH_BROKERS", "")
    code = makeCode()
    try:
        os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{freePort()}:0|127.0.0.1:{webSocketBroker}:0:/mqtt"
        blocked = Link()
        os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{webSocketBroker}:0:/mqtt"
        friend = Link()
    finally:
        os.environ["SYNTH_BROKERS"] = previous
    blocked.switchSeconds = 1
    events = []
    friend.received.connect(lambda c, subtopic, payload: events.append((subtopic, payload)))
    friend.watch(code, ["msg", "presence/+"])
    friend.start()
    blocked.watch(code, ["msg", "presence/+"])
    blocked.publish(code, "presence/me", {"name": "me"}, retain=True)
    blocked.start()
    assert waitFor(blocked.isConnected, 15)
    assert "(web)" in blocked.brokerName()
    assert waitFor(lambda: ("presence/me", {"name": "me"}) in events, 10)
    blocked.stop()
    friend.stop()


def test_defaultServersHaveWebSocketFallback():
    from app.session_link import DEFAULT_BROKERS
    assert all(len(endpoints) >= 2 and any(path for *_, path in endpoints) for endpoints in DEFAULT_BROKERS)
