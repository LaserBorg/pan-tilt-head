import os
import time

import mdns  # type: ignore[reportMissingImports]
import socketpool  # type: ignore[reportMissingImports]
import wifi  # type: ignore[reportMissingImports]
from adafruit_httpserver import Server  # type: ignore[reportMissingImports]

import rest_api
from pan_tilt import Abort, PanTiltHead

PORT = 8080
JOG_TIMEOUT = 1.0


class Runner:
    """Runs one queued job at a time, serving HTTP between motor steps."""

    def __init__(self, head, server):
        self.head = head
        self.server = server
        self.job = None
        self.running = False
        self.abort = False
        self.error = None
        self.jogging = False
        self.jog_values = (0.0, 0.0)
        self.jog_deadline = 0.0

    @property
    def busy(self):
        return self.running or self.job is not None

    def submit(self, job):
        self.error = None
        self.job = job

    def set_jog(self, pan, tilt):
        self.jog_values = (pan, tilt)
        self.jog_deadline = time.monotonic() + JOG_TIMEOUT
        if not self.jogging and (pan or tilt):
            self.jogging = True
            self.submit(lambda: self.head.jog(self.read_jog))

    def read_jog(self):
        if time.monotonic() >= self.jog_deadline:
            return (0.0, 0.0)
        return self.jog_values

    def stop(self):
        self.job = None
        self.jogging = False
        self.jog_values = (0.0, 0.0)
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
        self.jogging = False
        self.jog_values = (0.0, 0.0)


def connect_wifi():
    while not wifi.radio.connected:
        try:
            wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
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
