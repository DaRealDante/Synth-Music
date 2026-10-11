import subprocess
import sys

from app.single_instance import InstanceServer, sendToRunning
from tests.broker import waitFor


_servers = []


def test_secondLaunchForwardsLinkToFirst():
    name = "SynthMusicTest-instance"
    server = InstanceServer(name)
    _servers.append(server)
    assert server.listen()
    messages = []
    server.messageReceived.connect(messages.append)
    script = ("import sys; sys.path.insert(0, '.');"
              "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
              "from app.single_instance import sendToRunning;"
              f"print(sendToRunning('synthmusic://join/SYNTH-ABCD-EFGH', {name!r}))")
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
    assert waitFor(lambda: process.poll() is not None and messages, 10)
    assert process.stdout.read().strip() == b"True"
    assert messages == ["synthmusic://join/SYNTH-ABCD-EFGH"]
    waitFor(lambda: False, 0.3)
    server.server.close()


def test_noRunningInstance():
    assert sendToRunning("show", "SynthMusicTest-nobody") is False
