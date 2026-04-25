"""
Rotary Encoder driver for ESP32-S3
Handles quadrature encoding with interrupt-based detection
"""

from machine import Pin
import time


class RotaryEncoder:
    """
    Rotary encoder driver using interrupts for responsive detection

    Supports standard quadrature encoders with A (CLK) and B (DT) signals.
    Uses state machine decoding for reliable direction detection.
    """

    # State transition table for quadrature decoding
    # [previous_state][current_state] -> direction (1=CW, -1=CCW, 0=invalid/same)
    _STATE_TABLE = [
        [0, -1, 1, 0],   # Previous state 0
        [1, 0, 0, -1],   # Previous state 1
        [-1, 0, 0, 1],   # Previous state 2
        [0, 1, -1, 0],   # Previous state 3
    ]

    def __init__(self, pin_a, pin_b, callback=None, reverse=False, scale=1):
        """
        Initialize rotary encoder

        Args:
            pin_a: GPIO pin number for A signal (CLK)
            pin_b: GPIO pin number for B signal (DT)
            callback: Optional function called on rotation with delta value
            reverse: If True, reverse the direction interpretation
            scale: Multiplier for position/delta values
        """
        self._pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
        self._pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)

        self._callback = callback
        self._reverse = reverse
        self._scale = scale

        # Position tracking
        self._position = 0
        self._last_position = 0

        # State tracking for quadrature decoding
        self._state = self._get_state()

        # Accumulated steps (for batching small movements)
        self._accumulated = 0

        # Timing for debouncing
        self._last_change = time.ticks_ms()
        self._debounce_ms = 8  # Minimum ms between state changes (tuned from calibration)

        # Setup interrupts on both pins
        self._pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq_handler)
        self._pin_b.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq_handler)

    def _get_state(self):
        """Read current encoder state (2-bit value from A and B pins)"""
        return (self._pin_a.value() << 1) | self._pin_b.value()

    def _irq_handler(self, pin):
        """Interrupt handler for pin changes"""
        now = time.ticks_ms()

        # Simple debouncing
        if time.ticks_diff(now, self._last_change) < self._debounce_ms:
            return

        # Get new state
        new_state = self._get_state()

        # Look up direction from state transition table
        direction = self._STATE_TABLE[self._state][new_state]

        if direction != 0:
            self._last_change = now
            self._state = new_state

            # Apply direction reversal if configured
            if self._reverse:
                direction = -direction

            # Update position
            self._position += direction * self._scale
            self._accumulated += direction

            # Call callback if set
            if self._callback:
                self._callback(direction)

    @property
    def position(self):
        """Get current position (accumulated steps)"""
        return self._position

    @position.setter
    def position(self, value):
        """Set position to a specific value"""
        self._position = value

    def reset(self):
        """Reset position to zero"""
        self._position = 0
        self._accumulated = 0
        self._up_count = 0
        self._down_count = 0

    def get_delta(self):
        """Get position change since last read"""
        delta = self._position - self._last_position
        self._last_position = self._position
        return delta

    def get_accumulated(self, clear=True):
        """
        Get accumulated steps and optionally clear

        Args:
            clear: If True, reset accumulated count after reading

        Returns:
            Number of steps accumulated since last clear
        """
        value = self._accumulated
        if clear:
            self._accumulated = 0
        return value

    def get_direction_counts(self, clear=True):
        """
        Get separate up/down step counts for noise filtering

        Returns:
            Tuple of (up_count, down_count)
        """
        up = getattr(self, '_up_count', 0)
        down = getattr(self, '_down_count', 0)
        if clear:
            self._up_count = 0
            self._down_count = 0
        return (up, down)

    def set_callback(self, callback):
        """Set or change the rotation callback"""
        self._callback = callback

    def deinit(self):
        """Disable interrupts and clean up"""
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)


class SmoothedEncoder(RotaryEncoder):
    """
    Rotary encoder with smoothing/acceleration support

    Provides velocity-based scaling for smoother scroll behavior
    """

    def __init__(self, pin_a, pin_b, callback=None, reverse=False,
                 base_scale=1, acceleration=True, max_scale=5):
        """
        Initialize smoothed encoder

        Args:
            pin_a: GPIO pin number for A signal
            pin_b: GPIO pin number for B signal
            callback: Optional callback function
            reverse: Reverse direction if True
            base_scale: Base multiplier for slow movements
            acceleration: Enable velocity-based acceleration
            max_scale: Maximum scale factor when moving fast
        """
        super().__init__(pin_a, pin_b, callback, reverse, 1)

        self._base_scale = base_scale
        self._acceleration = acceleration
        self._max_scale = max_scale

        # Velocity tracking
        self._last_times = []
        self._max_samples = 5

        # Direction hysteresis to filter bouncing
        self._direction_history = []  # Recent direction readings
        self._history_size = 3  # Require this many consistent readings
        self._current_direction = 0  # Locked direction (1, -1, or 0)

        # Initialize direction counters
        self._up_count = 0
        self._down_count = 0

    def _irq_handler(self, pin):
        """Override to add velocity tracking and direction filtering"""
        now = time.ticks_ms()

        # Simple debouncing
        if time.ticks_diff(now, self._last_change) < self._debounce_ms:
            return

        # Get new state
        new_state = self._get_state()

        # Look up direction from state transition table
        direction = self._STATE_TABLE[self._state][new_state]

        if direction != 0:
            self._last_change = now
            self._state = new_state

            # Apply direction reversal if configured
            if self._reverse:
                direction = -direction

            # Track direction history for filtering
            self._direction_history.append(direction)
            if len(self._direction_history) > self._history_size:
                self._direction_history.pop(0)

            # Track timing for velocity calculation
            self._last_times.append(now)
            if len(self._last_times) > self._max_samples:
                self._last_times.pop(0)

            # Calculate scale based on velocity
            scale = self._base_scale
            if self._acceleration and len(self._last_times) >= 2:
                total_time = time.ticks_diff(self._last_times[-1], self._last_times[0])
                avg_time = total_time / (len(self._last_times) - 1)

                if avg_time < 50:
                    scale = self._max_scale
                elif avg_time < 100:
                    scale = (self._base_scale + self._max_scale) // 2
                elif avg_time < 200:
                    scale = self._base_scale + 1

            # Always accumulate raw direction - let main loop filter
            self._position += direction * scale
            self._accumulated += direction

            # Track separate up/down counts for noise filtering
            if direction > 0:
                self._up_count = getattr(self, '_up_count', 0) + 1
            else:
                self._down_count = getattr(self, '_down_count', 0) + 1

            # Call callback if set
            if self._callback:
                self._callback(direction)

    def get_velocity(self):
        """
        Get current rotation velocity (steps per second)

        Returns:
            Estimated steps per second, or 0 if not moving
        """
        if len(self._last_times) < 2:
            return 0

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_times[-1]) > 500:
            # Not moved recently
            self._last_times.clear()
            return 0

        total_time = time.ticks_diff(self._last_times[-1], self._last_times[0])
        if total_time == 0:
            return 0

        steps = len(self._last_times) - 1
        return (steps * 1000) / total_time

    def reset(self):
        """Reset position, accumulated, and direction history"""
        super().reset()
        self._direction_history = []
        self._current_direction = 0
        self._last_times = []
