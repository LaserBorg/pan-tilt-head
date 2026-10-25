import time

import mdns  # type: ignore[reportMissingImports]
import socketpool  # type: ignore[reportMissingImports]
import wifi  # type: ignore[reportMissingImports]
from adafruit_httpserver import Server  # type: ignore[reportMissingImports]

import rest_api
from pan_tilt import Abort, PanTiltHead
from secrets import WIFI_PASSWORD, WIFI_SSID

PORT = 8080


class Runner:
    """Runs one queued job at a time, serving HTTP between motor steps."""

    def __init__(self, head, server):
        self.head = head
        self.server = server
        self.job = None
        self.running = False
        self.abort = False
        self.error = None

    @property
    def busy(self):
        return self.running or self.job is not None

    def submit(self, job):
        self.error = None
        self.job = job

    def stop(self):
        self.job = None
        if self.running:
            self.abort = True
        else:
            self.head.disable()

    def poll(self):
        try:
            self.server.poll()
        except OSError:
            pass  # client dropped mid-request

    def tick(self):
        self.poll()
        if self.abort:
            raise Abort()

    def run_pending(self):
        job, self.job = self.job, None
        if job is None:
            return
        self.running = True
        try:
            job()
        except Abort:
            self.head.disable()
            self.error = "stopped"
        except Exception as error:
            self.error = str(error)
        self.running = False
        self.abort = False


def connect_wifi():
    while not wifi.radio.connected:
        try:
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
        except ConnectionError:
            time.sleep(2)


connect_wifi()
mdns_server = mdns.Server(wifi.radio)
mdns_server.hostname = "pan-tilt-head"
mdns_server.advertise_service(service_type="_http", protocol="_tcp", port=PORT)

server = Server(socketpool.SocketPool(wifi.radio), debug=False)
# A client that connects without sending data would otherwise stall polling for 1 s.
server.socket_timeout = 0.2
head = PanTiltHead()
runner = Runner(head, server)
head.tick = runner.tick
rest_api.register(server, head, runner)
server.start(str(wifi.radio.ipv4_address), port=PORT)

runner.submit(lambda: head.home("both"))
while True:
    runner.poll()
    runner.run_pending()
    head.pan.button.read()  # keeps the LED mirroring the pan switch
