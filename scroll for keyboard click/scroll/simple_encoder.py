"""
Simple Interrupt-based Rotary Encoder
Standard quadrature decoding with basic debouncing.
"""

from machine import Pin
import time

class RotaryEncoder:
    def __init__(self, pin_a, pin_b, callback=None, reverse=False):
        self._pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
        self._pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)
        self._callback = callback
        self._reverse = reverse

        self._position = 0
        self._prev_state = (self._pin_a.value() << 1) | self._pin_b.value()
        self._last_change = time.ticks_ms()

        # Simple lookup table
        # 0=00, 1=01, 2=10, 3=11
        # Direction map: [prev][curr]
        self._transitions = [
            0, -1, 1, 0,
            1, 0, 0, -1,
            -1, 0, 0, 1,
            0, 1, -1, 0
        ]

        self._pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._handler)
        self._pin_b.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._handler)

    def _handler(self, pin):
        curr_state = (self._pin_a.value() << 1) | self._pin_b.value()
        if curr_state == self._prev_state:
            return

        # Basic debounce
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_change) < 2: # Very short debounce
            return

        idx = (self._prev_state << 2) | curr_state
        direction = self._transitions[idx]

        if direction != 0:
            self._last_change = now
            self._prev_state = curr_state

            if self._reverse:
                direction = -direction

            self._position += direction
            if self._callback:
                self._callback(direction)
        else:
            self._prev_state = curr_state

    def reset(self):
        self._position = 0

    def deinit(self):
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)
