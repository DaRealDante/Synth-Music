import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def serverName():
    try:
        user = getpass.getuser()
    except Exception:
        user = "utente"
    return f"SynthMusic-{user}"


def sendToRunning(message, name=None):
    """True if another Synth Music is already open: it receives `message` (a link or "show") and this one should exit."""
    socket = QLocalSocket()
    socket.connectToServer(name or serverName())
    if not socket.waitForConnected(400):
        return False
    socket.write((message or "show").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def waitForPreviousInstance(name=None, timeoutSeconds=15):
    """After "Riavvia ora": wait until the old window has closed before taking its place."""
    import time
    deadline = time.time() + timeoutSeconds
    while time.time() < deadline:
        socket = QLocalSocket()
        socket.connectToServer(name or serverName())
        if not socket.waitForConnected(150):
            return True
        socket.disconnectFromServer()
        time.sleep(0.25)
    return False


class InstanceServer(QObject):
    messageReceived = Signal(str)
    capriRequest = Signal(str, object)  # (message, socket): voice-assistant command that expects a reply

    def __init__(self, name=None, parent=None):
        super().__init__(parent)
        self.name = name or serverName()
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._onConnection)

    def listen(self):
        if self.server.listen(self.name):
            return True
        QLocalServer.removeServer(self.name)
        return self.server.listen(self.name)

    def _onConnection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket):
        data = bytes(socket.readAll()).decode("utf-8", "ignore").strip()
        if not data:
            return
        if data.lower().startswith("capri:"):
            self.capriRequest.emit(data, socket)
        else:
            self.messageReceived.emit(data)

    @staticmethod
    def reply(socket, text):
        """Answer a capri: request on its own connection, then hang up."""
        try:
            socket.write((text + "\n").encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
        except RuntimeError:
            pass  # the client already went away
