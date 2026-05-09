"""
ESP32-C6 Bluetooth Two-Button Arrow Keypad
Uses BLE Keyboard HID arrow keys instead of mouse wheel/pan scrolling.

Two modes:
  MODE_AUTO  - Press button to start/stop continuous arrow-key repeats.
  MODE_HOLD  - Send arrow keys only while button is held down.

Both buttons short press  -> toggle vertical / horizontal arrow axis.
Both buttons held 3 sec   -> switch between MODE_AUTO and MODE_HOLD.
"""

import time
from machine import Pin
from lib.hid_keystores import NVSKeyStore
from lib.hid_services import KeyboardMouse

# USB HID Key Codes for Arrow Keys
KEY_RIGHT = 0x4F
KEY_LEFT  = 0x50
KEY_DOWN  = 0x51
KEY_UP    = 0x52


# ─── Configuration ───────────────────────────────────────────────────────────
BUTTON_A_PIN = 1              # GPIO1 (D1) - Arrow Down / Right
BUTTON_B_PIN = 0              # GPIO0 (D0) - Arrow Up / Left
DEVICE_NAME = "ESP32_Scroller"
KEYSTROKES_PER_TICK = 1       # Manual tap presses per repeat tick
INVERT_ARROWS = False         # Flip arrow direction
USE_HOST_KEY_REPEAT = True    # Hold keys down so the host repeats like a real keyboard
KEY_REPEAT_INTERVAL_MS = 10   # ms between manual tap repeat ticks
KEY_PRESS_MS = 6              # ms to hold each manual tap down
KEY_RELEASE_MS = 4            # ms between manual taps when sending multiple per tick
DEBOUNCE_MS = 25              # Button debounce window
MODE_SWITCH_HOLD_MS = 3000    # Hold both buttons this long to switch modes
LED_PIN = 15                  # Onboard LED (XIAO ESP32-C6)

# ─── Constants ───────────────────────────────────────────────────────────────
MODE_AUTO = 0   # Toggle arrow-key repeats on button press
MODE_HOLD = 1   # Send arrow keys while button is held

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

    # ── BLE HID setup ──────────────────────────────────────────────────────
    hid_dev = KeyboardMouse(DEVICE_NAME)
    ks = NVSKeyStore()
    hid_dev.set_keystore(ks)
    hid_dev.start()
    hid_dev.start_advertising()
    print(f"Advertising as {DEVICE_NAME}")

    # ── Buttons ───────────────────────────────────────────────────────────────
    btn_a = Button(BUTTON_A_PIN, DEBOUNCE_MS)
    btn_b = Button(BUTTON_B_PIN, DEBOUNCE_MS)

    # ── State ─────────────────────────────────────────────────────────────────
    mode = MODE_HOLD
    arrow_axis = AXIS_VERTICAL
    auto_key_dir = 0       # -1 = down/right, +1 = up/left, 0 = stopped
    hold_key_dir = 0       # Same convention, only used in MODE_HOLD
    was_connected = False
    last_key_ms = time.ticks_ms()

    # Dual-button tracking
    both_pressed = False
    both_start_ms = 0
    both_action_done = False
    suppress_single = False   # Eat the next single-button release after a dual press
    held_key = 0              # Keyboard key currently held in the HID report

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _notify_kb():
        """Send the current keyboard state to the host."""
        try:
            hid_dev.notify_hid_report()
        except:
            pass

    def _notify_mouse():
        """Send the current mouse state to the host."""
        try:
            hid_dev.notify_mouse_report()
        except:
            pass

    def center_and_click():
        """Center the cursor on screen then click to give focus.

        Phase 1: Slam cursor to top-left with large negative moves.
        Phase 2: Move toward center with positive moves.
        Phase 3: Click to give focus to whatever is under the cursor.
        """
        print("Centering cursor...")
        # Phase 1: Slam to top-left corner
        for _ in range(20):
            hid_dev.set_mouse_axes(-127, -127)
            _notify_mouse()
            time.sleep_ms(3)

        # Phase 2: Move toward center
        for _ in range(6):
            hid_dev.set_mouse_axes(127, 127)
            _notify_mouse()
            time.sleep_ms(3)

        # Reset movement
        hid_dev.set_mouse_axes(0, 0)
        _notify_mouse()
        time.sleep_ms(50)

        # Phase 3: Click to give focus
        print("Clicking to give focus...")
        hid_dev.set_mouse_buttons(b1=1)  # Press left button
        _notify_mouse()
        time.sleep_ms(50)
        hid_dev.set_mouse_buttons(b1=0)  # Release left button
        _notify_mouse()
        time.sleep_ms(100)
        print("Ready")

    def get_arrow_key(direction):
        """Return the arrow key for the current axis/direction."""
        dir_val = direction
        if INVERT_ARROWS:
            dir_val = -dir_val

        if arrow_axis == AXIS_VERTICAL:
            return KEY_UP if dir_val > 0 else KEY_DOWN
        return KEY_RIGHT if dir_val > 0 else KEY_LEFT

    def set_held_arrow_key(direction):
        """Hold one arrow key down, or release all keys when direction is 0."""
        nonlocal held_key

        key = get_arrow_key(direction) if direction else 0
        if key == held_key:
            return

        held_key = key
        hid_dev.set_keys(key)
        _notify_kb()

    def send_arrow_key(direction):
        """Send and release the arrow key for the current axis/direction."""
        key = get_arrow_key(direction)
        for _ in range(KEYSTROKES_PER_TICK):
            hid_dev.set_keys(key)
            _notify_kb()
            time.sleep_ms(KEY_PRESS_MS)

            hid_dev.set_keys()  # Release keys
            _notify_kb()

            if KEYSTROKES_PER_TICK > 1:
                time.sleep_ms(KEY_RELEASE_MS)

    # ── Main loop ─────────────────────────────────────────────────────────────
    print("Mode: HOLD | Axis: VERTICAL")

    while True:
        is_connected = (hid_dev.get_state() == KeyboardMouse.DEVICE_CONNECTED)

        # ── Connection state changes ──────────────────────────────────────────
        if is_connected and not was_connected:
            print("Connected!")
            was_connected = True
            auto_key_dir = 0
            hold_key_dir = 0
            hid_dev.set_keys()
            held_key = 0
            time.sleep_ms(2500)  # Let iPadOS finish GATT discovery
            center_and_click()
        elif not is_connected and was_connected:
            print("Disconnected")
            was_connected = False
            auto_key_dir = 0
            hold_key_dir = 0
            hid_dev.set_keys()
            held_key = 0

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
                    # Pause any arrow-key repeats while handling gesture
                    auto_key_dir = 0
                    hold_key_dir = 0
                elif not both_action_done and time.ticks_diff(now, both_start_ms) >= MODE_SWITCH_HOLD_MS:
                    # Long hold → toggle mode
                    mode = MODE_HOLD if mode == MODE_AUTO else MODE_AUTO
                    auto_key_dir = 0
                    hold_key_dir = 0
                    both_action_done = True
                    mode_name = "HOLD" if mode == MODE_HOLD else "AUTO"
                    print(f"Mode: {mode_name}")
                    led_blink(3, 80, 80)

            elif both_pressed:
                # Was dual-pressed, now one or both released
                if not both_action_done:
                    # Short press → toggle axis
                    arrow_axis = AXIS_HORIZONTAL if arrow_axis == AXIS_VERTICAL else AXIS_VERTICAL
                    axis_name = "HORIZONTAL" if arrow_axis == AXIS_HORIZONTAL else "VERTICAL"
                    print(f"Axis: {axis_name}")
                    led_blink(2, 80, 80)
                both_pressed = False
                suppress_single = True  # Don't let the release trigger an arrow action

            else:
                # ── Single-button logic ───────────────────────────────────────
                if suppress_single:
                    # Wait until both buttons are fully released before accepting singles
                    if not btn_a.down and not btn_b.down:
                        suppress_single = False
                else:
                    if mode == MODE_AUTO:
                        # Toggle arrow-key repeats on button release
                        if btn_a.released:
                            if auto_key_dir == -1:
                                auto_key_dir = 0
                                print("Auto-repeat stopped")
                            else:
                                auto_key_dir = -1
                                last_key_ms = time.ticks_add(now, -KEY_REPEAT_INTERVAL_MS)
                                print("Auto-repeat DOWN" if arrow_axis == AXIS_VERTICAL else "Auto-repeat LEFT")

                        elif btn_b.released:
                            if auto_key_dir == 1:
                                auto_key_dir = 0
                                print("Auto-repeat stopped")
                            else:
                                auto_key_dir = 1
                                last_key_ms = time.ticks_add(now, -KEY_REPEAT_INTERVAL_MS)
                                print("Auto-repeat UP" if arrow_axis == AXIS_VERTICAL else "Auto-repeat LEFT")

                    elif mode == MODE_HOLD:
                        # Send arrow keys while held
                        if btn_a.down and not btn_b.down:
                            hold_key_dir = -1
                            if btn_a.pressed:
                                last_key_ms = time.ticks_add(now, -KEY_REPEAT_INTERVAL_MS)
                        elif btn_b.down and not btn_a.down:
                            hold_key_dir = 1
                            if btn_b.pressed:
                                last_key_ms = time.ticks_add(now, -KEY_REPEAT_INTERVAL_MS)
                        else:
                            hold_key_dir = 0

            # Send arrow-key output.
            active_dir = auto_key_dir if mode == MODE_AUTO else hold_key_dir
            if USE_HOST_KEY_REPEAT:
                set_held_arrow_key(active_dir)
            elif active_dir != 0 and time.ticks_diff(now, last_key_ms) >= KEY_REPEAT_INTERVAL_MS:
                send_arrow_key(active_dir)
                last_key_ms = now

        # ── Advertising / sleep ───────────────────────────────────────────────
        if hid_dev.get_state() == KeyboardMouse.DEVICE_IDLE:
            hid_dev.start_advertising()
            time.sleep(1)
        else:
            time.sleep_ms(1)


if __name__ == "__main__":
    main()
