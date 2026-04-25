"""
Polling-based Rotary Encoder driver for ESP32-S3
Handles noisy/bouncy encoders by using polling instead of interrupts
"""

from machine import Pin
import time


class PollingEncoder:
    """
    Polling-based rotary encoder for noisy/bouncy hardware.

    Call poll() regularly from main loop. Uses state confirmation
    to filter bounce - requires state to be stable for multiple reads.
    """

    def __init__(self, pin_a, pin_b, reverse=False):
        """
        Initialize polling encoder

        Args:
            pin_a: GPIO pin number for A signal (CLK)
            pin_b: GPIO pin number for B signal (DT)
            reverse: If True, reverse the direction interpretation
        """
        self._pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
        self._pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)
        self._reverse = reverse

        # Position tracking
        self._position = 0
        self._accumulated = 0

        # State tracking - use "full step" counting
        # Only count when encoder completes a full detent cycle
        self._last_state = self._get_state()
        self._last_settled_state = self._last_state

        # State confirmation for debouncing
        self._pending_state = self._last_state
        self._pending_count = 0
        self._confirm_threshold = 3  # Require N consecutive same readings

        # Track last valid detent position (states 0 or 3 are detent positions)
        self._at_detent = self._last_state in (0, 3)
        self._last_detent_state = self._last_state if self._at_detent else None

    def _get_state(self):
        """Read current encoder state (2-bit value from A and B pins)"""
        return (self._pin_a.value() << 1) | self._pin_b.value()

    def poll(self):
        """
        Poll encoder state and return direction.
        Call this from main loop every few ms.

        Returns:
            Direction: 1 (CW), -1 (CCW), or 0 (no movement/bounce)
        """
        current = self._get_state()

        # State confirmation - require consistent readings
        if current == self._pending_state:
            self._pending_count += 1
        else:
            self._pending_state = current
            self._pending_count = 1

        # Don't act until state is confirmed stable
        if self._pending_count < self._confirm_threshold:
            return 0

        # State is confirmed - check if it's different from last settled state
        if current == self._last_settled_state:
            return 0

        # Valid state change - determine direction using gray code sequence
        # Full sequence CW: 0 -> 1 -> 3 -> 2 -> 0
        # Full sequence CCW: 0 -> 2 -> 3 -> 1 -> 0

        old = self._last_settled_state
        self._last_settled_state = current

        # Simple direction detection based on state pair
        # Using lookup: (old_state, new_state) -> direction
        direction = 0

        # Clockwise transitions
        if (old, current) in [(0, 1), (1, 3), (3, 2), (2, 0)]:
            direction = 1
        # Counter-clockwise transitions
        elif (old, current) in [(0, 2), (2, 3), (3, 1), (1, 0)]:
            direction = -1

        if direction != 0:
            if self._reverse:
                direction = -direction

            self._position += direction
            self._accumulated += direction

        return direction

    def get_accumulated(self, clear=True):
        """Get accumulated steps and optionally clear"""
        value = self._accumulated
        if clear:
            self._accumulated = 0
        return value

    @property
    def position(self):
        """Get current position"""
        return self._position

    def reset(self):
        """Reset position and accumulated counts"""
        self._position = 0
        self._accumulated = 0

    def deinit(self):
        """Clean up (no-op for polling encoder)"""
        pass


class DetentEncoder:
    """
    Detent-counting encoder for standard mechanical encoders with detents.

    Only counts when encoder settles into a detent position,
    ignoring all intermediate states. Very noise resistant.
    """

    def __init__(
        self,
        pin_a,
        pin_b,
        reverse=False,
        stable_threshold=5,
        direction_threshold=2,
        min_interval_ms=12,
        direction_change_guard_ms=30,
    ):
        self._pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
        self._pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)
        self._reverse = reverse

        self._position = 0
        self._accumulated = 0

        # State tracking
        self._last_state = self._get_state()
        self._last_counted_direction = 0

        # For detent detection - track sequence of states
        self._state_sequence = [self._last_state]
        self._max_sequence = 6

        # Confirmation - require very stable readings
        self._stable_state = self._last_state
        self._stable_count = 0
        self._stable_threshold = stable_threshold  # Require N same readings to confirm

        # Direction hysteresis - require multiple same-direction counts
        self._pending_direction = 0
        self._direction_confirm_count = 0
        self._direction_threshold = direction_threshold  # Require N same-direction detections

        # Timing guards to avoid double-counting and bounce-induced flips
        self._min_detent_interval_ms = min_interval_ms
        self._direction_change_guard_ms = direction_change_guard_ms
        self._last_detent_time = time.ticks_ms()

    def _get_state(self):
        return (self._pin_a.value() << 1) | self._pin_b.value()

    def poll(self):
        """Poll and return accumulated direction since last poll"""
        now = time.ticks_ms()
        current = self._get_state()

        # State stability check
        if current == self._stable_state:
            self._stable_count += 1
        else:
            # State changed - track sequence
            if current != self._state_sequence[-1]:
                self._state_sequence.append(current)
                if len(self._state_sequence) > self._max_sequence:
                    self._state_sequence.pop(0)

            self._stable_state = current
            self._stable_count = 1
            return 0

        # Not stable enough yet
        if self._stable_count < self._stable_threshold:
            return 0

        # State is stable - analyze sequence to determine direction
        if len(self._state_sequence) < 2:
            return 0

        # Get the transition that led to current stable state
        raw_direction = self._analyze_sequence()

        if raw_direction != 0:
            # Clear sequence after analyzing
            self._state_sequence = [current]

            # Direction hysteresis - need consistent direction
            if raw_direction == self._pending_direction:
                self._direction_confirm_count += 1
            else:
                self._pending_direction = raw_direction
                self._direction_confirm_count = 1

            # Only count if direction is confirmed
            if self._direction_confirm_count >= self._direction_threshold:
                direction = self._pending_direction

                # Guard against too-fast repeats and noisy direction flips
                if time.ticks_diff(now, self._last_detent_time) < self._min_detent_interval_ms:
                    return 0
                if self._last_counted_direction != 0 and direction != self._last_counted_direction:
                    if time.ticks_diff(now, self._last_detent_time) < self._direction_change_guard_ms:
                        self._direction_confirm_count = 0
                        return 0

                if self._reverse:
                    direction = -direction

                self._position += direction
                self._accumulated += direction
                self._last_counted_direction = direction
                self._last_detent_time = now

                # Reset for next detection
                self._direction_confirm_count = 0
                return direction

        return 0

    def _analyze_sequence(self):
        """Analyze state sequence to determine rotation direction"""
        # Count CW vs CCW transitions in sequence
        cw_transitions = [(0,1), (1,3), (3,2), (2,0)]
        ccw_transitions = [(0,2), (2,3), (3,1), (1,0)]

        cw_count = 0
        ccw_count = 0

        for i in range(len(self._state_sequence) - 1):
            pair = (self._state_sequence[i], self._state_sequence[i+1])
            if pair in cw_transitions:
                cw_count += 1
            elif pair in ccw_transitions:
                ccw_count += 1

        # Count if there's any majority (removed +1 margin for better sensitivity)
        if cw_count > ccw_count:
            return 1
        elif ccw_count > cw_count:
            return -1

        return 0

    def get_accumulated(self, clear=True):
        value = self._accumulated
        if clear:
            self._accumulated = 0
        return value

    @property
    def position(self):
        return self._position

    def reset(self):
        self._position = 0
        self._accumulated = 0
        self._state_sequence = [self._get_state()]
        self._pending_direction = 0
        self._direction_confirm_count = 0
        self._last_counted_direction = 0
        self._last_detent_time = time.ticks_ms()

    def deinit(self):
        pass
