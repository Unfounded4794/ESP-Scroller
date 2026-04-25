"""
ESP32-S3 Bluetooth Scroll Wheel
Robust encoder handling with state table decoding and debouncing.
"""

import time
from machine import Pin, disable_irq, enable_irq
from lib.hid_keystores import NVSKeyStore
from lib.hid_services import Keyboard


# Configuration
ENCODER_PIN_A = 2
ENCODER_PIN_B = 3
DEVICE_NAME = "ESP32_Scroller"
INVERT_SCROLL = True
SCROLL_AMOUNT = 1      # Adjust between 2-5 for multi-line jumps without BLE lag
USE_OPTION_MODIFIER = False # Set True to press Alt/Option + Arrow (jumps a paragraph on iPadOS)
DEBOUNCE_MS = 1        # Ignore transitions within this time window
REPORT_INTERVAL_MS = 1  # Send HID reports at this interval (accumulate scrolls)

# Quadrature state table: maps (old_state, new_state) -> direction
# States: 00=0, 01=1, 11=3, 10=2
# Valid CW sequence:  0 -> 1 -> 3 -> 2 -> 0  (returns +1)
# Valid CCW sequence: 0 -> 2 -> 3 -> 1 -> 0  (returns -1)
# Invalid transitions return 0 (bounce/noise)
ENCODER_TABLE = [
  #  new: 0   1   2   3   (old state is row index)
         [ 0, +1, -1,  0],  # old = 0 (A=0, B=0)
         [-1,  0,  0, +1],  # old = 1 (A=0, B=1)
         [+1,  0,  0, -1],  # old = 2 (A=1, B=0)
         [ 0, -1, +1,  0],  # old = 3 (A=1, B=1)
]


class Encoder:
  """Robust rotary encoder with state table decoding and debouncing."""

  def __init__(self, pin_a, pin_b, debounce_ms=3):
    self.pin_a = Pin(pin_a, Pin.IN, Pin.PULL_UP)
    self.pin_b = Pin(pin_b, Pin.IN, Pin.PULL_UP)
    self.debounce_ms = debounce_ms

    # Read initial state
    self.state = (self.pin_a.value() << 1) | self.pin_b.value()
    self.position = 0  # Accumulated position delta
    self.last_change_ms = time.ticks_ms()

    # Set up interrupts on both pins
    self.pin_a.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq_handler)
    self.pin_b.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._irq_handler)

  def _irq_handler(self, pin):
    """IRQ handler - uses state table to determine direction."""
    now = time.ticks_ms()

    # Debounce: ignore transitions too close together
    if time.ticks_diff(now, self.last_change_ms) < self.debounce_ms:
      return

    # Read new state
    new_state = (self.pin_a.value() << 1) | self.pin_b.value()

    # Skip if no actual change (can happen due to timing)
    if new_state == self.state:
      return

    # Look up direction from state table
    direction = ENCODER_TABLE[self.state][new_state]

    # Update position (atomic operation)
    if direction != 0:
      irq_state = disable_irq()
      self.position += direction
      enable_irq(irq_state)
      self.last_change_ms = now

    self.state = new_state

  def get_delta(self):
    """Get accumulated position change and reset counter."""
    irq_state = disable_irq()
    delta = self.position
    self.position = 0
    enable_irq(irq_state)
    return delta


def main():
  # LED blink on startup
  try:
    led = Pin(21, Pin.OUT)
    led.on()
    time.sleep(0.3)
    led.off()
  except:
    led = None

  # Initialize BLE keyboard
  keyboard = Keyboard(DEVICE_NAME)
  ks = NVSKeyStore()
  keyboard.set_keystore(ks)
  keyboard.start()
  keyboard.start_advertising()
  print(f"Advertising as {DEVICE_NAME}")

  # Initialize encoder with debouncing
  encoder = Encoder(ENCODER_PIN_A, ENCODER_PIN_B, DEBOUNCE_MS)

  was_connected = False
  last_report_ms = time.ticks_ms()
  
  # Non-blocking keystroke state
  pending_strokes = 0
  pending_keycode = 0x00
  is_pressing = False
  last_keystroke_ms = time.ticks_ms()
  KEYSTROKE_DELAY_MS = 3  # Tiny delay between press/release state changes

  while True:
    is_connected = (keyboard.get_state() == Keyboard.DEVICE_CONNECTED)

    # Handle connection state changes
    if is_connected and not was_connected:
      print("Connected! Ready to send keystrokes.")
      was_connected = True
      
      # Reset state on connect
      pending_strokes = 0
      is_pressing = False

    elif not is_connected and was_connected:
      print("Disconnected")
      was_connected = False

    # Handle encoder and send keyboard reports
    if is_connected:
      now = time.ticks_ms()

      # Read the encoder very frequently without blocking
      if time.ticks_diff(now, last_report_ms) >= REPORT_INTERVAL_MS:
        delta = encoder.get_delta()
        if delta != 0:
          direction = delta * SCROLL_AMOUNT
          if INVERT_SCROLL:
            direction = -direction

          # 0x51 = Down Arrow, 0x52 = Up Arrow
          keycode = 0x52 if direction > 0 else 0x51
          
          # If direction changed, flush the queue to feel instantly responsive
          if keycode != pending_keycode:
            pending_keycode = keycode
            pending_strokes = 0
            if is_pressing:
              keyboard.set_keys(0x00) # Quick release
              try: keyboard.notify_hid_report()
              except: pass
              is_pressing = False
              
          # Add to the queue. Cap it dynamically so it NEVER exceeds ~0.4s of lag
          # Every stroke takes 2 * KEYSTROKE_DELAY_MS = 6ms. 60 strokes = 360ms maximum catching up.
          pending_strokes = min(pending_strokes + abs(direction), 60)

        last_report_ms = now

      # Process the keystroke queue non-blockingly (15ms spacing protects the TX Buffer)
      if (pending_strokes > 0 or is_pressing) and time.ticks_diff(now, last_keystroke_ms) >= 15:
        if not is_pressing and pending_strokes > 0:
          if USE_OPTION_MODIFIER:
            keyboard.set_modifiers(left_alt=1)
          keyboard.set_keys(pending_keycode)
          try: keyboard.notify_hid_report()
          except: pass
          is_pressing = True
          pending_strokes -= 1
        else:
          if USE_OPTION_MODIFIER:
            keyboard.set_modifiers(left_alt=0)
          keyboard.set_keys(0x00)
          try: keyboard.notify_hid_report()
          except: pass
          is_pressing = False
          
        last_keystroke_ms = now

    # Handle advertising
    if keyboard.get_state() == Keyboard.DEVICE_IDLE:
      keyboard.start_advertising()
      time.sleep(1)
    else:
      time.sleep_ms(1)


if __name__ == "__main__":
  main()
