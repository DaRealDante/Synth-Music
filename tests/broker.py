import os
import socket
import subprocess
import tempfile
import time

import pytest


def freePort():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def localBroker():
    port = freePort()
    folder = tempfile.mkdtemp()
    configPath = os.path.join(folder, "mosquitto.conf")
    with open(configPath, "w") as configFile:
        configFile.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    process = subprocess.Popen(["mosquitto", "-c", configPath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    os.environ["SYNTH_BROKERS"] = f"127.0.0.1:{port}:0"
    yield port
    process.terminate()
    process.wait(5)


def waitFor(condition, timeout=6.0):
    from PySide6.QtWidgets import QApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def pump(seconds):
    from PySide6.QtWidgets import QApplication
    deadline = time.time() + seconds
    while time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
