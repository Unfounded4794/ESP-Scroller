"""
Encoder Calibration Test
Run this to diagnose encoder behavior and find optimal settings.

Upload to ESP32 and run: import calibrate
"""

import sys
import time
from machine import Pin

sys.path.append('/lib')

# Configuration - match your main.py
ENCODER_PIN_A = 2
ENCODER_PIN_B = 3


class RawEncoder:
    """Minimal encoder with raw data logging - no filtering"""

    def __init__(self, pin_a, pin_b):
        self._pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
        self._pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)

        # Raw event log: list of (timestamp_ms, direction, state)
        self.events = []
        self._state = self._get_state()
        self._last_time = time.ticks_ms()

        # State transition table
        self._STATE_TABLE = [
            [0, -1, 1, 0],
            [1, 0, 0, -1],
            [-1, 0, 0, 1],
            [0, 1, -1, 0],
        ]

        # Setup interrupts
        self._pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq)
        self._pin_b.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq)

    def _get_state(self):
        return (self._pin_a.value() << 1) | self._pin_b.value()

    def _irq(self, pin):
        now = time.ticks_ms()
        new_state = self._get_state()
        direction = self._STATE_TABLE[self._state][new_state]

        if direction != 0:
            delta = time.ticks_diff(now, self._last_time)
            self.events.append((delta, direction, new_state))
            self._state = new_state
            self._last_time = now

    def clear(self):
        self.events = []

    def deinit(self):
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)


def analyze_events(events, label):
    """Analyze recorded events"""
    if not events:
        print(f"\n{label}: No events recorded!")
        return

    up_count = sum(1 for e in events if e[1] == 1)
    down_count = sum(1 for e in events if e[1] == -1)
    total = len(events)

    # Calculate timing stats
    deltas = [e[0] for e in events]
    avg_delta = sum(deltas) / len(deltas) if deltas else 0
    min_delta = min(deltas) if deltas else 0
    max_delta = max(deltas) if deltas else 0

    # Check for rapid direction changes (bouncing)
    direction_changes = 0
    for i in range(1, len(events)):
        if events[i][1] != events[i-1][1]:
            direction_changes += 1

    bounce_ratio = direction_changes / total if total > 0 else 0

    print(f"\n{'='*50}")
    print(f"{label} ANALYSIS")
    print(f"{'='*50}")
    print(f"Total events: {total}")
    print(f"UP events (+1): {up_count} ({100*up_count/total:.1f}%)")
    print(f"DOWN events (-1): {down_count} ({100*down_count/total:.1f}%)")
    print(f"Net direction: {up_count - down_count}")
    print(f"Direction changes: {direction_changes} ({100*bounce_ratio:.1f}% bounce rate)")
    print(f"Time between events: min={min_delta}ms avg={avg_delta:.1f}ms max={max_delta}ms")

    # Show first 20 raw events
    print(f"\nFirst 20 events (delta_ms, direction, state):")
    for i, e in enumerate(events[:20]):
        dir_str = "UP  " if e[1] == 1 else "DOWN"
        print(f"  {i+1:2d}. {e[0]:4d}ms {dir_str} state={e[2]}")

    # Recommendations
    print(f"\nRECOMMENDATIONS:")
    if bounce_ratio > 0.3:
        print(f"  - HIGH BOUNCE RATE ({100*bounce_ratio:.0f}%) - increase debounce_ms")
        if min_delta < 5:
            print(f"  - Events as fast as {min_delta}ms apart - try debounce_ms = {max(5, min_delta*2)}")

    dominant = "UP" if up_count > down_count else "DOWN"
    if abs(up_count - down_count) < total * 0.6:
        print(f"  - Weak direction signal - only {100*abs(up_count-down_count)/total:.0f}% dominant")
    else:
        print(f"  - Good: {dominant} direction is dominant ({100*max(up_count,down_count)/total:.0f}%)")


def run_test():
    """Interactive calibration test"""
    print("\n" + "="*50)
    print("ENCODER CALIBRATION TEST")
    print("="*50)
    print(f"Using GPIO {ENCODER_PIN_A} (CLK) and {ENCODER_PIN_B} (DT)")

    encoder = RawEncoder(ENCODER_PIN_A, ENCODER_PIN_B)

    # Test 1: Scroll UP
    print("\n" + "-"*50)
    print("TEST 1: SCROLL UP")
    print("-"*50)
    print("Turn the encoder in the SCROLL UP direction")
    print("(the direction you want to scroll a page up)")
    print("\nStarting in 3 seconds...")
    time.sleep(3)

    encoder.clear()
    print(">>> RECORDING - turn encoder UP for 5 seconds <<<")
    time.sleep(5)
    up_events = encoder.events.copy()
    print(">>> STOPPED <<<")

    analyze_events(up_events, "SCROLL UP")

    # Test 2: Scroll DOWN
    print("\n" + "-"*50)
    print("TEST 2: SCROLL DOWN")
    print("-"*50)
    print("Turn the encoder in the SCROLL DOWN direction")
    print("(the opposite direction)")
    print("\nStarting in 3 seconds...")
    time.sleep(3)

    encoder.clear()
    print(">>> RECORDING - turn encoder DOWN for 5 seconds <<<")
    time.sleep(5)
    down_events = encoder.events.copy()
    print(">>> STOPPED <<<")

    analyze_events(down_events, "SCROLL DOWN")

    # Test 3: Idle/noise
    print("\n" + "-"*50)
    print("TEST 3: IDLE NOISE")
    print("-"*50)
    print("DO NOT TOUCH the encoder")
    print("\nStarting in 2 seconds...")
    time.sleep(2)

    encoder.clear()
    print(">>> RECORDING IDLE - do not touch for 3 seconds <<<")
    time.sleep(3)
    idle_events = encoder.events.copy()
    print(">>> STOPPED <<<")

    if idle_events:
        print(f"\nWARNING: {len(idle_events)} events while idle - electrical noise!")
        analyze_events(idle_events, "IDLE NOISE")
    else:
        print("\nGood: No events while idle")

    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)

    up_net = sum(e[1] for e in up_events)
    down_net = sum(e[1] for e in down_events)

    print(f"SCROLL UP test net: {up_net:+d}")
    print(f"SCROLL DOWN test net: {down_net:+d}")

    if up_net > 0 and down_net < 0:
        print("\nDirection mapping looks CORRECT")
    elif up_net < 0 and down_net > 0:
        print("\nDirection is INVERTED - set INVERT_SCROLL = True in main.py")
    else:
        print("\nDirection detection has issues - check wiring and encoder quality")

    # Calculate suggested debounce
    all_events = up_events + down_events
    if all_events:
        min_delta = min(e[0] for e in all_events)
        bounce_events = sum(1 for i in range(1, len(all_events))
                          if all_events[i][1] != all_events[i-1][1])

        if min_delta < 5 or bounce_events > len(all_events) * 0.2:
            suggested_debounce = max(8, min_delta * 2)
            print(f"\nSuggested: debounce_ms = {suggested_debounce}")

    encoder.deinit()
    print("\nCalibration complete. Use these results to tune encoder.py settings.")


# Auto-run when imported
if __name__ == "__main__":
    run_test()
else:
    print("Run calibrate.run_test() to start calibration")
