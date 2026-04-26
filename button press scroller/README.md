# ESP32 Bluetooth Arrow Key Controller

A Bluetooth HID controller for iOS/iPadOS, macOS, and Windows using two buttons on an ESP32-C6.

Instead of sending mouse wheel or horizontal pan scroll events, `main.py` sends BLE keyboard arrow-key presses:

- Button A sends Down in vertical mode, Right in horizontal mode.
- Button B sends Up in vertical mode, Left in horizontal mode.
- Press both buttons briefly to toggle vertical/horizontal arrow mode.
- Hold both buttons for 3 seconds to toggle AUTO/HOLD mode.

## Hardware

- XIAO ESP32-C6 or compatible ESP32-C6 board running MicroPython
- Button A wired to GPIO1/D1 and GND
- Button B wired to GPIO0/D0 and GND
- Optional onboard LED on GPIO15 for feedback

The button inputs use internal pull-ups, so each button should connect the GPIO pin to GND when pressed.

## Configuration

Settings are at the top of `main.py`:

| Setting                  | Default           | Description |
| ------------------------ | ----------------- | ----------- |
| `BUTTON_A_PIN`           | `1`               | GPIO for the Down/Right button |
| `BUTTON_B_PIN`           | `0`               | GPIO for the Up/Left button |
| `DEVICE_NAME`            | `"ESP32_Scroller"` | Bluetooth device name shown when pairing |
| `KEYSTROKES_PER_TICK`    | `1`               | Arrow-key taps sent per manual repeat tick |
| `INVERT_ARROWS`          | `False`           | Reverse Up/Down and Left/Right behavior |
| `USE_HOST_KEY_REPEAT`    | `True`            | Hold arrow keys down so the host repeats like a real keyboard |
| `KEY_REPEAT_INTERVAL_MS` | `10`              | Delay between repeated taps when `USE_HOST_KEY_REPEAT` is `False` |
| `KEY_PRESS_MS`           | `6`               | How long each manual tap is held down |
| `KEY_RELEASE_MS`         | `4`               | Delay between manual taps inside one tick |
| `DEBOUNCE_MS`            | `25`              | Button debounce window |
| `MODE_SWITCH_HOLD_MS`    | `3000`            | Hold time for switching AUTO/HOLD mode |

## Modes

The controller starts in HOLD mode.

AUTO mode toggles repeating arrow-key presses when a button is released.

HOLD mode repeats arrow-key presses only while a button is held.

With `USE_HOST_KEY_REPEAT = True`, both AUTO and HOLD mode send key-down/key-up state changes and let the connected device handle repeat timing, just like a physical keyboard.

## Troubleshooting

If directions feel backwards, toggle `INVERT_ARROWS`.

If repeats are too slow or too fast with `USE_HOST_KEY_REPEAT = True`, adjust the keyboard repeat settings on the connected device. Firmware cannot slow AUTO mode separately while it is literally holding the key down.

If a host keeps using an old HID profile, forget/remove `ESP32_Scroller` from Bluetooth settings and pair it again.
