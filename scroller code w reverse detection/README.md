# ESP32 Bluetooth Scroll Wheel

A Bluetooth HID scroll wheel for iOS/iPadOS using an ESP32-S3 and a rotary encoder.

## Hardware

- ESP32-S3 board
- Rotary encoder (mechanical with detents)
  - Pin A → GPIO 2
  - Pin B → GPIO 3
  - GND → GND

## Configuration

All settings are at the top of `main.py`:

### Pin Configuration

| Setting         | Default | Description                    |
| --------------- | ------- | ------------------------------ |
| `ENCODER_PIN_A` | `2`     | GPIO pin for encoder channel A |
| `ENCODER_PIN_B` | `3`     | GPIO pin for encoder channel B |

### Bluetooth

| Setting       | Default            | Description                              |
| ------------- | ------------------ | ---------------------------------------- |
| `DEVICE_NAME` | `"ESP32_Scroller"` | Bluetooth device name shown when pairing |

### Scroll Behavior

| Setting         | Default | Description                                                                           |
| --------------- | ------- | ------------------------------------------------------------------------------------- |
| `INVERT_SCROLL` | `True`  | Reverse scroll direction. Set to `False` if scrolling feels backwards.                |
| `SCROLL_AMOUNT` | `1`     | Scroll distance per encoder detent. Increase for faster scrolling (1-10 recommended). |

### Encoder Tuning

| Setting              | Default | Description                                                                                                                                            |
| -------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `DEBOUNCE_MS`        | `3`     | Milliseconds to ignore transitions after a valid one. Increase to 5-10 if you see phantom scrolls or jitter. Decrease if slow rotation misses detents. |
| `REPORT_INTERVAL_MS` | `30`    | How often to send scroll events to the device (ms). Lower = more responsive but more BLE traffic. Higher = smoother but slight lag. Range: 15-50.      |

## Troubleshooting

### Scrolling works but direction is wrong

- Toggle `INVERT_SCROLL` between `True` and `False`
- Or swap `ENCODER_PIN_A` and `ENCODER_PIN_B` values

### Missing scroll events (especially when rotating slowly)

- Decrease `DEBOUNCE_MS` to 1 or 2
- Check encoder wiring and connections

### Phantom scrolls / jitter / double-counting

- Increase `DEBOUNCE_MS` to 5-10
- Consider adding 0.1µF capacitors between each signal pin and GND (hardware debounce)

### Scrolling feels laggy

- Decrease `REPORT_INTERVAL_MS` to 15-20

### Scrolling is too slow

- Increase `SCROLL_AMOUNT` to 2-5

### Not connecting to iOS

- Forget the device in iOS Settings → Bluetooth, then re-pair
- Restart the ESP32
- Check that the LED blinks on startup (indicates code is running)

## iOS Setup

On first connection, the device automatically moves the pointer to trigger iOS AssistiveTouch recognition. This takes ~8 seconds. Wait for "Ready!" in the serial console before using the scroll wheel.
