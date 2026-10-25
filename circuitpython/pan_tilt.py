"""Pan-tilt kinematics: per-axis configuration, homing and coordinated moves."""

import time

import supervisor  # type: ignore[reportMissingImports]

from stepper_driver import Button, StepperMotor, ticks_every

STABLE_READS = 3
HOMING_BOUND_MARGIN_DEGREES = 10


class Abort(Exception):
    """Raised from the tick callback to stop motion immediately."""


class Axis:
    def __init__(self, prefix, indicator=False):
        get = supervisor.get_setting
        halfstep = get(f"{prefix}_halfstep", True)
        pins = [get(f"{prefix}_pin_{index}") for index in range(1, 5)]
        steps_per_degree = float(get("stepper_resolution")) * float(get(f"{prefix}_ratio"))
        self.motor = StepperMotor(pins, steps_per_degree, halfstep)
        self.button = Button(
            get(f"{prefix}_button"), get(f"{prefix}_button_invert"), indicator=indicator)
        # Sign mapping logical angle direction to motor direction.
        self.direction = -1 if get(f"{prefix}_reverse") else 1
        self.min = float(get(f"{prefix}_min"))
        self.max = float(get(f"{prefix}_max"))
        delay_ms = get("move_delay_halfstep_ms" if halfstep else "move_delay_fullstep_ms")
        self.delay = float(delay_ms) / 1000.0
        self.angle = 0.0
        self.homed = False


class PanTiltHead:
    def __init__(self):
        self.pan = Axis("pan", indicator=True)
        self.tilt = Axis("tilt")
        # Called periodically during motion; may raise Abort.
        self.tick = None

    def state(self):
        return {
            "pan": self.pan.angle if self.pan.homed else None,
            "tilt": self.tilt.angle if self.tilt.homed else None,
            "pan_homed": self.pan.homed,
            "tilt_homed": self.tilt.homed,
        }

    def disable(self):
        """De-energize both motors; positions are lost until re-homed."""
        for axis in (self.pan, self.tilt):
            axis.motor.release()
            axis.homed = False

    def home(self, axis="both"):
        failed = []
        if axis in ("pan", "both") and not self.home_pan():
            failed.append("pan")
        if axis in ("tilt", "both") and not self.home_tilt():
            failed.append("tilt")
        if failed:
            raise RuntimeError(" and ".join(failed) + " homing failed")

    def home_pan(self):
        # Zero is the stable clockwise press at the switch's left flank. Starts are
        # assumed within 45 degrees of the switch; every search leg is bounded.
        pan = self.pan
        pan.homed = False
        motor, button, delay = pan.motor, pan.button, pan.delay
        left = -pan.direction
        right = pan.direction
        per_degree = motor.steps_per_degree
        steps_45 = round(45 * per_degree)
        steps_90 = round(90 * per_degree)
        steps_20 = int(20 * per_degree) + 1
        steps_40 = int(40 * per_degree) + 1

        def move(direction, steps, until=None, until_released=False):
            return motor.step(direction, steps, delay, until, until_released,
                              STABLE_READS, self.tick)

        def release_and_rehit(clearance_steps):
            if clearance_steps:
                move(left, clearance_steps)
            if not move(left, steps_90, button, until_released=True):
                return False
            move(left, steps_40)
            return move(right, steps_90, button) or button.is_pressed()

        if button.is_pressed():
            # A pressed start does not reveal which flank is being contacted.
            homed = release_and_rehit(steps_20)
        elif move(left, steps_45, button) or button.is_pressed():
            # The first press going left is the right flank.
            homed = release_and_rehit(0)
        else:
            homed = move(right, steps_90, button) or button.is_pressed()

        if not (homed and button.is_pressed()):
            return False
        pan.angle = 0.0
        pan.homed = True
        return True

    def home_tilt(self):
        # Seek the lower endstop, then move up to the logical zero.
        tilt = self.tilt
        tilt.homed = False
        motor = tilt.motor
        bound = motor.steps_for(tilt.max - tilt.min + HOMING_BOUND_MARGIN_DEGREES)
        if not motor.step(-tilt.direction, bound, tilt.delay, tilt.button, tick=self.tick):
            return False
        motor.zero_phase()
        motor.step(tilt.direction, motor.steps_for(tilt.min), tilt.delay, tick=self.tick)
        tilt.angle = 0.0
        tilt.homed = True
        return True

    def move_to(self, pan=None, tilt=None):
        """Move homed axes to absolute angles (clamped to limits), finishing together."""
        moves = []
        total = 0
        delay = 0.0
        for axis, target in ((self.pan, pan), (self.tilt, tilt)):
            if target is None:
                continue
            target = min(max(target, axis.min), axis.max)
            pulses = axis.motor.steps_for(target - axis.angle) * axis.motor.step_factor
            direction = (1 if target >= axis.angle else -1) * axis.direction
            moves.append((axis, target, direction, pulses))
            total = max(total, pulses)
            delay = max(delay, axis.delay)

        # Bresenham: the shorter axis pulses proportionally so both end on the last tick.
        errors = [0] * len(moves)
        interval = ticks_every(delay)
        for count in range(total):
            for index, (axis, _, direction, pulses) in enumerate(moves):
                errors[index] += pulses
                if errors[index] >= total:
                    errors[index] -= total
                    axis.motor.pulse(direction)
            time.sleep(delay)
            if self.tick is not None and (count + 1) % interval == 0:
                self.tick()
        for axis, target, _, _ in moves:
            axis.angle = target
