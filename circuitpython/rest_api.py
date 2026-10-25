"""REST routes. Handlers only validate and queue work; motion runs in the main loop."""

import math

from adafruit_httpserver import GET, POST, JSONResponse  # type: ignore[reportMissingImports]

OK = (200, "OK")
ACCEPTED = (202, "Accepted")
BAD_REQUEST = (400, "Bad Request")
CONFLICT = (409, "Conflict")

AXES = ("pan", "tilt", "both")


def _body(request):
    if not request.body:
        return {}
    body = request.json()
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    return body


def _angle(body, key):
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(key + " must be a finite number")
    return float(value)


def register(server, head, runner):
    def reply(request, status=OK, error=None):
        state = head.state()
        state["busy"] = runner.busy
        state["error"] = error or runner.error
        return JSONResponse(request, state, status=status)

    @server.route("/api/v1/state", GET)
    def get_state(request):
        return reply(request)

    @server.route("/api/v1/move", POST)
    def post_move(request):
        if runner.busy:
            return reply(request, CONFLICT, "busy")
        try:
            body = _body(request)
            if set(body) - {"pan", "tilt"}:
                raise ValueError("Unexpected fields")
            pan, tilt = _angle(body, "pan"), _angle(body, "tilt")
            if pan is None and tilt is None:
                raise ValueError("pan or tilt required")
            if (pan is not None and not head.pan.homed) or (tilt is not None and not head.tilt.homed):
                raise ValueError("axis must be homed before moving")
        except ValueError as error:
            return reply(request, BAD_REQUEST, str(error))
        runner.submit(lambda: head.move_to(pan, tilt))
        return reply(request, ACCEPTED)

    @server.route("/api/v1/home", POST)
    def post_home(request):
        if runner.busy:
            return reply(request, CONFLICT, "busy")
        try:
            axis = _body(request).get("axis", "both")
            if axis not in AXES:
                raise ValueError("axis must be pan, tilt or both")
        except ValueError as error:
            return reply(request, BAD_REQUEST, str(error))
        runner.submit(lambda: head.home(axis))
        return reply(request, ACCEPTED)

    @server.route("/api/v1/disable", POST)
    def post_disable(request):
        runner.stop()
        return reply(request)
