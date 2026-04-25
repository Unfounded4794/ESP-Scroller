"""
ESP32-C6 Bluetooth Two-Button Scroller
Uses BLE Mouse HID with wheel (vertical) and AC Pan (horizontal) for
native smooth scrolling on iPadOS / macOS / Windows.

Two modes:
  MODE_AUTO  - Press button to start/stop continuous auto-scroll.
  MODE_HOLD  - Scroll only while button is held down.

Both buttons short press  -> toggle vertical / horizontal scroll axis.
Both buttons held 3 sec   -> switch between MODE_AUTO and MODE_HOLD.
"""

import time
from machine import Pin
from lib.hid_keystores import NVSKeyStore
from lib.hid_services import Mouse


# ─── Configuration ───────────────────────────────────────────────────────────
BUTTON_A_PIN = 0              # GPIO0 (D0) - Scroll Down / Right
BUTTON_B_PIN = 1              # GPIO1 (D1) - Scroll Up / Left
DEVICE_NAME = "ESP32_Scroller"
SCROLL_AMOUNT = 1             # Scroll value per tick (1 is minimum, increase for faster)
INVERT_SCROLL = False         # Flip scroll direction
# iPadOS coalesces frequent small ticks into smooth motion. Too slow (>100ms) causes
# each tick to trigger separate momentum animations that fight each other.
AUTO_SCROLL_INTERVAL_MS = 100  # ms between scroll ticks (~20/sec, smooth on iOS)
DEBOUNCE_MS = 50              # Button debounce window
MODE_SWITCH_HOLD_MS = 3000    # Hold both buttons this long to switch modes
LED_PIN = 15                  # Onboard LED (XIAO ESP32-C6)

# ─── Constants ───────────────────────────────────────────────────────────────
MODE_AUTO = 0   # Toggle auto-scroll on button press
MODE_HOLD = 1   # Scroll while button is held

AXIS_VERTICAL = 0
AXIS_HORIZONTAL = 1


# ─── Debounced Button ────────────────────────────────────────────────────────
class Button:
    """Polling-based debounced button with edge detection (active-low)."""

    def __init__(self, pin_num, debounce_ms=30):
        self.pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self.debounce_ms = debounce_ms
        self._raw = not self.pin.value()  # Active-low: invert to match update() convention
        self._last_change_ms = time.ticks_ms()
        self.down = False       # Debounced state: True = pressed
        self.pressed = False    # Edge: became pressed this tick
        self.released = False   # Edge: became released this tick

    def update(self):
        """Call once per main-loop iteration to refresh state."""
        now = time.ticks_ms()
        raw = not self.pin.value()  # Active-low → invert

        self.pressed = False
        self.released = False

        if raw != self._raw:
            self._last_change_ms = now
            self._raw = raw

        if raw != self.down and time.ticks_diff(now, self._last_change_ms) >= self.debounce_ms:
            old = self.down
            self.down = raw
            if raw and not old:
                self.pressed = True
            elif not raw and old:
                self.released = True


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    # LED blink on startup
    try:
        led = Pin(LED_PIN, Pin.OUT)
        led.on()
        time.sleep(0.3)
        led.off()
    except:
        led = None

    def led_blink(n, on_ms=80, off_ms=80):
        """Quick LED feedback blinks."""
        if led is None:
            return
        for i in range(n):
            led.on()
            time.sleep_ms(on_ms)
            led.off()
            if i < n - 1:
                time.sleep_ms(off_ms)

    # ── BLE Mouse setup ──────────────────────────────────────────────────────
    mouse = Mouse(DEVICE_NAME)
    ks = NVSKeyStore()
    mouse.set_keystore(ks)
    mouse.start()
    mouse.start_advertising()
    print(f"Advertising as {DEVICE_NAME}")

    # ── Buttons ───────────────────────────────────────────────────────────────
    btn_a = Button(BUTTON_A_PIN, DEBOUNCE_MS)
    btn_b = Button(BUTTON_B_PIN, DEBOUNCE_MS)

    # ── State ─────────────────────────────────────────────────────────────────
    mode = MODE_AUTO
    scroll_axis = AXIS_VERTICAL
    auto_scroll_dir = 0       # -1 = down/right, +1 = up/left, 0 = stopped
    hold_scroll_dir = 0       # Same convention, only used in MODE_HOLD
    was_connected = False
    last_scroll_ms = time.ticks_ms()

    # Dual-button tracking
    both_pressed = False
    both_start_ms = 0
    both_action_done = False
    suppress_single = False   # Eat the next single-button release after a dual press

    # ── Helpers ───────────────────────────────────────────────────────────────
    def center_cursor():
        """Move the mouse cursor to roughly the center of the screen.
        
        Since HID mouse reports are relative, we first slam the cursor to the
        top-left corner with large negative movements, then move it toward
        the center with positive movements. This ensures the cursor lands
        over scrollable content so wheel events actually work.
        """
        print("Centering cursor...")
        # Phase 1: Slam to top-left corner (20 × -127 = -2540px per axis)
        for _ in range(20):
            mouse.set_axes(-127, -127)
            mouse.set_wheel(0)
            mouse.set_pan(0)
            try:
                mouse.notify_hid_report()
            except:
                pass
            time.sleep_ms(2)

        # Phase 2: Move toward center (6 × 127 = ~762px per axis)
        for _ in range(6):
            mouse.set_axes(127, 127)
            mouse.set_wheel(0)
            mouse.set_pan(0)
            try:
                mouse.notify_hid_report()
            except:
                pass
            time.sleep_ms(2)

        # Reset axes
        mouse.set_axes(0, 0)
        print("Cursor centered")

    def send_scroll(direction):
        """Send one scroll tick followed by a zero report.
        
        The zero report clears the GATT characteristic so any direct reads
        by the host don't pick up a stale scroll value (which causes phantom
        reverse-scroll on iPadOS).
        """
        amt = direction * SCROLL_AMOUNT
        if INVERT_SCROLL:
            amt = -amt

        # 1) Send the scroll delta
        mouse.set_axes(0, 0)
        if scroll_axis == AXIS_VERTICAL:
            mouse.set_wheel(amt)
            mouse.set_pan(0)
        else:
            mouse.set_wheel(0)
            mouse.set_pan(-amt)
        try:
            mouse.notify_hid_report()
        except:
            pass

        # 2) Immediately send a zero report to clear the characteristic
        mouse.set_wheel(0)
        mouse.set_pan(0)
        try:
            mouse.notify_hid_report()
        except:
            pass

    # ── Main loop ─────────────────────────────────────────────────────────────
    print("Mode: AUTO | Axis: VERTICAL")

    while True:
        is_connected = (mouse.get_state() == Mouse.DEVICE_CONNECTED)

        # ── Connection state changes ──────────────────────────────────────────
        if is_connected and not was_connected:
            print("Connected!")
            was_connected = True
            auto_scroll_dir = 0
            hold_scroll_dir = 0
            time.sleep_ms(2500)  # Let iPadOS finish GATT characteristic reads
            center_cursor()
        elif not is_connected and was_connected:
            print("Disconnected")
            was_connected = False
            auto_scroll_dir = 0
            hold_scroll_dir = 0

        if is_connected:
            now = time.ticks_ms()

            # ── Read buttons ──────────────────────────────────────────────────
            btn_a.update()
            btn_b.update()

            # ── Dual-button detection ─────────────────────────────────────────
            if btn_a.down and btn_b.down:
                if not both_pressed:
                    # Both just went down
                    both_pressed = True
                    both_start_ms = now
                    both_action_done = False
                    # Pause any scrolling while handling gesture
                    auto_scroll_dir = 0
                    hold_scroll_dir = 0
                elif not both_action_done and time.ticks_diff(now, both_start_ms) >= MODE_SWITCH_HOLD_MS:
                    # Long hold → toggle mode
                    mode = MODE_HOLD if mode == MODE_AUTO else MODE_AUTO
                    auto_scroll_dir = 0
                    hold_scroll_dir = 0
                    both_action_done = True
                    mode_name = "HOLD" if mode == MODE_HOLD else "AUTO"
                    print(f"Mode: {mode_name}")
                    led_blink(3, 80, 80)

            elif both_pressed:
                # Was dual-pressed, now one or both released
                if not both_action_done:
                    # Short press → toggle axis
                    scroll_axis = AXIS_HORIZONTAL if scroll_axis == AXIS_VERTICAL else AXIS_VERTICAL
                    axis_name = "HORIZONTAL" if scroll_axis == AXIS_HORIZONTAL else "VERTICAL"
                    print(f"Axis: {axis_name}")
                    led_blink(2, 80, 80)
                both_pressed = False
                suppress_single = True  # Don't let the release trigger a scroll action

            else:
                # ── Single-button logic ───────────────────────────────────────
                if suppress_single:
                    # Wait until both buttons are fully released before accepting singles
                    if not btn_a.down and not btn_b.down:
                        suppress_single = False
                else:
                    if mode == MODE_AUTO:
                        # Toggle auto-scroll on button release
                        if btn_a.released:
                            if auto_scroll_dir == -1:
                                auto_scroll_dir = 0
                                print("Auto-scroll stopped")
                            else:
                                auto_scroll_dir = -1
                                last_scroll_ms = now
                                print("Auto-scroll DOWN" if scroll_axis == AXIS_VERTICAL else "Auto-scroll RIGHT")

                        elif btn_b.released:
                            if auto_scroll_dir == 1:
                                auto_scroll_dir = 0
                                print("Auto-scroll stopped")
                            else:
                                auto_scroll_dir = 1
                                last_scroll_ms = now
                                print("Auto-scroll UP" if scroll_axis == AXIS_VERTICAL else "Auto-scroll LEFT")

                    elif mode == MODE_HOLD:
                        # Scroll while held
                        if btn_a.down and not btn_b.down:
                            hold_scroll_dir = -1
                        elif btn_b.down and not btn_a.down:
                            hold_scroll_dir = 1
                        else:
                            hold_scroll_dir = 0

            # ── Send scroll ticks at interval ─────────────────────────────────
            active_dir = auto_scroll_dir if mode == MODE_AUTO else hold_scroll_dir
            if active_dir != 0 and time.ticks_diff(now, last_scroll_ms) >= AUTO_SCROLL_INTERVAL_MS:
                send_scroll(active_dir)
                last_scroll_ms = now

        # ── Advertising / sleep ───────────────────────────────────────────────
        if mouse.get_state() == Mouse.DEVICE_IDLE:
            mouse.start_advertising()
            time.sleep(1)
        else:
            time.sleep_ms(1)


if __name__ == "__main__":
    main()
