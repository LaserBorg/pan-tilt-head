"""Hardware drivers: ULN2003-driven stepper motor and limit switch."""

import time

import board  # type: ignore[reportMissingImports]
from digitalio import DigitalInOut, Direction, Pull  # type: ignore[reportMissingImports]

HALFSTEP = (
    (0, 0, 0, 1), (0, 0, 1, 1), (0, 0, 1, 0), (0, 1, 1, 0),
    (0, 1, 0, 0), (1, 1, 0, 0), (1, 0, 0, 0), (1, 0, 0, 1),
)
FULLSTEP = ((0, 0, 1, 1), (0, 1, 1, 0), (1, 1, 0, 0), (1, 0, 0, 1))

TICK_SECONDS = 0.02


def ticks_every(delay):
    """Number of steps between tick callbacks."""
    return max(1, int(TICK_SECONDS / delay)) if delay > 0 else 1


class Button:
    def __init__(self, pin, inverted=False, indicator=False):
        self._pin = DigitalInOut(getattr(board, f"GP{pin}"))
        self._pin.direction = Direction.INPUT
        self._pin.pull = Pull.UP
        self._inverted = inverted
        self._led = None
        if indicator:
            self._led = DigitalInOut(board.LED)
            self._led.direction = Direction.OUTPUT
            self._led.value = False

    def read(self):
        """Return (raw pin level, pressed); the LED mirrors pressed."""
        raw = self._pin.value
        pressed = raw if self._inverted else not raw
        if self._led is not None:
            self._led.value = pressed
        return raw, pressed

    def is_pressed(self):
        return self.read()[1]


class StepperMotor:
    def __init__(self, pins, steps_per_degree, halfstep=True):
        self._pins = [DigitalInOut(getattr(board, f"GP{pin}")) for pin in pins]
        for pin in self._pins:
            pin.direction = Direction.OUTPUT
        self._sequence = HALFSTEP if halfstep else FULLSTEP
        self._index = 0
        self.steps_per_degree = steps_per_degree
        self.step_factor = len(self._sequence) // 4

    def steps_for(self, degrees):
        """Full-step count for an angle; each full step is step_factor pulses."""
        return round(abs(degrees) * self.steps_per_degree)

    def pulse(self, direction):
        for pin, level in zip(self._pins, self._sequence[self._index]):
            pin.value = level
        self._index = (self._index + direction) % len(self._sequence)

    def zero_phase(self):
        self._index = 0

    def release(self):
        for pin in self._pins:
            pin.value = False

    def step(self, direction, steps, delay, button=None, until_released=False,
             stable_reads=1, tick=None):
        """Move `steps` full steps; with a button, stop early once it has been
        pressed (or released) for `stable_reads` consecutive reads.
        Returns True if stopped by the button."""
        interval = ticks_every(delay)
        matches = 0
        for count in range(steps * self.step_factor):
            if button is not None:
                matches = matches + 1 if button.is_pressed() != until_released else 0
                if matches >= stable_reads:
                    return True
            self.pulse(direction)
            time.sleep(delay)
            if tick is not None and (count + 1) % interval == 0:
                tick()
        return False
