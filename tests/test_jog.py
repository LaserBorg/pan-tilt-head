import importlib.util
import ast
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


FIRMWARE = pathlib.Path(__file__).resolve().parents[1] / "circuitpython"
supervisor = types.ModuleType("supervisor")
stepper_driver = types.ModuleType("stepper_driver")
stepper_driver.Button = object
stepper_driver.StepperMotor = object
stepper_driver.ticks_every = lambda delay: 1
with patch.dict(sys.modules, {"supervisor": supervisor, "stepper_driver": stepper_driver}):
    spec = importlib.util.spec_from_file_location("pan_tilt", FIRMWARE / "pan_tilt.py")
    pan_tilt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pan_tilt)


class Motor:
    steps_per_degree = 2
    step_factor = 1

    def __init__(self):
        self.pulses = []

    def pulse(self, direction):
        self.pulses.append(direction)


def axis(angle=0, minimum=-10, maximum=10, direction=1):
    return types.SimpleNamespace(angle=angle, min=minimum, max=maximum,
                                 delay=0.01, direction=direction, motor=Motor())


class JogTests(unittest.TestCase):
    def head(self, pan=None, tilt=None):
        head = object.__new__(pan_tilt.PanTiltHead)
        head.pan = pan or axis()
        head.tilt = tilt or axis(direction=-1)
        head.tick = None
        return head

    def test_independent_speeds_and_stop(self):
        head = self.head()
        velocities = iter([(1, -0.5)] * 8 + [(0, 0)])
        with patch.object(pan_tilt.time, "sleep"):
            head.jog(lambda: next(velocities))
        self.assertEqual(len(head.pan.motor.pulses), 8)
        self.assertEqual(len(head.tilt.motor.pulses), 4)
        self.assertEqual(head.pan.angle, 4)
        self.assertEqual(head.tilt.angle, -2)
        self.assertEqual(head.tilt.motor.pulses, [1] * 4)

    def test_limits_stop_pulses_without_losing_position(self):
        head = self.head(axis(angle=9.5), axis(angle=-9.5))
        velocities = iter([(1, -1)] * 4 + [(0, 0)])
        with patch.object(pan_tilt.time, "sleep"):
            head.jog(lambda: next(velocities))
        self.assertEqual(head.pan.angle, 10)
        self.assertEqual(head.tilt.angle, -10)
        self.assertEqual(len(head.pan.motor.pulses), 1)
        self.assertEqual(len(head.tilt.motor.pulses), 1)


class RunnerTests(unittest.TestCase):
    def test_jog_lease_expires_and_stop_cancels_pending_motion(self):
        tree = ast.parse((FIRMWARE / "main.py").read_text())
        runner_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Runner")
        module = ast.fix_missing_locations(ast.Module(body=[runner_class], type_ignores=[]))
        clock = types.SimpleNamespace(monotonic=lambda: 10.0)
        namespace = {"time": clock, "JOG_TIMEOUT": 1.0, "Abort": pan_tilt.Abort}
        exec(compile(module, "main.py", "exec"), namespace)
        head = types.SimpleNamespace(disable=lambda: None)
        runner = namespace["Runner"](head, None)
        runner.set_jog(0.5, -0.25)
        self.assertTrue(runner.busy)
        self.assertEqual(runner.read_jog(), (0.5, -0.25))
        clock.monotonic = lambda: 11.0
        self.assertEqual(runner.read_jog(), (0.0, 0.0))
        runner.stop()
        self.assertFalse(runner.busy)
        self.assertFalse(runner.jogging)


class RouteTests(unittest.TestCase):
    def setUp(self):
        httpserver = types.ModuleType("adafruit_httpserver")
        httpserver.GET = "GET"
        httpserver.POST = "POST"
        httpserver.JSONResponse = lambda request, state, status: (status[0], state)
        with patch.dict(sys.modules, {"adafruit_httpserver": httpserver}):
            spec = importlib.util.spec_from_file_location("rest_api", FIRMWARE / "rest_api.py")
            rest_api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rest_api)
        self.routes = {}
        server = types.SimpleNamespace(route=self.route)
        self.head = types.SimpleNamespace(pan=axis(), tilt=axis(), state=lambda: {})
        self.head.pan.homed = True
        self.head.tilt.homed = True
        self.commands = []
        self.runner = types.SimpleNamespace(busy=False, jogging=False, error=None,
                                            set_jog=lambda pan, tilt: self.commands.append((pan, tilt)))
        rest_api.register(server, self.head, self.runner)

    def route(self, path, method):
        def register(handler):
            self.routes[(path, method)] = handler
            return handler
        return register

    def post(self, body):
        request = types.SimpleNamespace(body=b"json", json=lambda: body)
        return self.routes[("/api/v1/jog", "POST")](request)[0]

    def test_jog_validates_values_and_respects_other_jobs(self):
        self.assertEqual(self.post({"pan": 0.5, "tilt": -1}), 202)
        self.assertEqual(self.commands, [(0.5, -1.0)])
        for body in ({"pan": 2, "tilt": 0}, {"pan": True, "tilt": 0},
                     {"pan": 0}, {"pan": 0, "tilt": float("nan")}):
            self.assertEqual(self.post(body), 400)
        self.head.tilt.homed = False
        self.assertEqual(self.post({"pan": 1, "tilt": 0}), 400)
        self.assertEqual(self.post({"pan": 0, "tilt": 0}), 202)
        self.runner.busy = True
        self.assertEqual(self.post({"pan": 0, "tilt": 0}), 409)
        self.runner.jogging = True
        self.assertEqual(self.post({"pan": 0, "tilt": 0}), 202)


if __name__ == "__main__":
    unittest.main()