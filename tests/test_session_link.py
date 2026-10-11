import os
import signal
import subprocess
import sys
import textwrap

from app.session_link import CodeBox, Link, linkFor, makeCode, parseCode
from tests.broker import localBroker, pump, waitFor  # noqa: F401


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
    assert process.stdout.readline().strip() == b"ready"
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
        assert link.brokerIndex == 1
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
        assert link.brokerIndex == 1
        link.stop()
    finally:
        os.environ["SYNTH_BROKERS"] = previous
        running[0] = False
        listener.close()
