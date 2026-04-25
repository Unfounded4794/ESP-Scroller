"""
ESP32-S3 Bluetooth Scroll Wheel
Robust encoder handling with state table decoding and debouncing.
"""

import time
from machine import Pin, disable_irq, enable_irq
from lib.hid_keystores import NVSKeyStore
from lib.hid_services import Mouse


# Configuration
ENCODER_PIN_A = 2
ENCODER_PIN_B = 3
DEVICE_NAME = "ESP32_Scroller"
INVERT_SCROLL = True
SCROLL_AMOUNT = 1
DEBOUNCE_MS = 1        # Ignore transitions within this time window
REPORT_INTERVAL_MS = 1  # Send HID reports at this interval (accumulate scrolls)

# Swipe mode settings (alternative to wheel scroll for iOS apps needing gestures)
USE_SWIPE_MODE = False# Set True to use drag-swipe instead of wheel scroll
SWIPE_STEPS = 1          # Number of movement steps per swipe
SWIPE_STEP_SIZE = 10     # Pixels per step
SWIPE_STEP_DELAY_MS = 1 # Delay between steps for smooth motion


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


def perform_drag_swipe(mouse, direction):
  """
  Perform a drag-swipe gesture using mouse move + click.
  Based on cross-platform BLE HID best practices.

  Args:
    mouse: Mouse HID instance
    direction: Positive for swipe down (scroll up), negative for swipe up (scroll down)
  """
  if direction == 0:
    return

  # Calculate step direction (invert for natural scrolling if needed)
  step_y = SWIPE_STEP_SIZE if direction > 0 else -SWIPE_STEP_SIZE
  if INVERT_SCROLL:
    step_y = -step_y

  try:
    # Press mouse button to start drag
    mouse.set_button(1)  # Left click
    mouse.set_axes(0, 0)
    mouse.notify_hid_report()
    time.sleep_ms(50)  # Short delay before movement

    # Perform smooth movement in small steps
    for _ in range(SWIPE_STEPS):
      mouse.set_axes(0, step_y)
      mouse.notify_hid_report()
      time.sleep_ms(SWIPE_STEP_DELAY_MS)

    # Release button to complete drag
    time.sleep_ms(50)
    mouse.set_button(0)
    mouse.set_axes(0, 0)
    mouse.notify_hid_report()
  except:
    # Ensure button is released on error
    try:
      mouse.set_button(0)
      mouse.set_axes(0, 0)
      mouse.notify_hid_report()
    except:
      pass


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
    self.last_dir = 0
    self.drift = 0

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
      
      if self.last_dir == 0:
        self.last_dir = direction
        self.position += direction
        self.drift = 0
      else:
        self.drift += direction
        
        if self.last_dir == 1:
          if self.drift > 0:
            self.position += direction
            self.drift = 0
          elif self.drift <= -2:
            self.last_dir = -1
            self.position += direction
            self.drift = 0
        else: # self.last_dir == -1
          if self.drift < 0:
            self.position += direction
            self.drift = 0
          elif self.drift >= 2:
            self.last_dir = 1
            self.position += direction
            self.drift = 0
            
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

  # Initialize BLE mouse
  mouse = Mouse(DEVICE_NAME)
  ks = NVSKeyStore()
  mouse.set_keystore(ks)
  mouse.start()
  mouse.start_advertising()
  print(f"Advertising as {DEVICE_NAME}")

  # Initialize encoder with debouncing
  encoder = Encoder(ENCODER_PIN_A, ENCODER_PIN_B, DEBOUNCE_MS)

  was_connected = False
  last_report_ms = time.ticks_ms()

  while True:
    is_connected = (mouse.get_state() == Mouse.DEVICE_CONNECTED)

    # Handle connection state changes
    if is_connected and not was_connected:
      print("Connected! Running iOS setup...")
      time.sleep(5)

      # iOS AssistiveTouch setup: move pointer to known position
      for _ in range(20):
        mouse.set_axes(-127, -127)
        try:
          mouse.notify_hid_report()
        except:
          pass
        time.sleep(0.02)

      for _ in range(5):
        mouse.set_axes(40, 80)
        try:
          mouse.notify_hid_report()
        except:
          pass
        time.sleep(0.02)

      mouse.set_axes(0, 0)
      try:
        mouse.notify_hid_report()
      except:
        pass

      time.sleep(3)
      print("Ready!")
      was_connected = True

    elif not is_connected and was_connected:
      print("Disconnected")
      was_connected = False

    # Handle encoder and send scroll reports
    if is_connected:
      now = time.ticks_ms()

      # Send accumulated scroll at regular intervals
      if time.ticks_diff(now, last_report_ms) >= REPORT_INTERVAL_MS:
        delta = encoder.get_delta()

        if delta != 0:
          if USE_SWIPE_MODE:
            # Use drag-swipe for iOS apps that need gesture input
            perform_drag_swipe(mouse, delta)
          else:
            # Use standard wheel scroll (works on most platforms)
            scroll = delta * SCROLL_AMOUNT
            if INVERT_SCROLL:
              scroll = -scroll

            # Clamp to valid range
            scroll = max(-127, min(127, scroll))

            mouse.set_axes(0, 0)
            mouse.set_wheel(scroll)
            try:
              mouse.notify_hid_report()
            except:
              pass

            # Reset wheel for next report
            mouse.set_wheel(0)

        last_report_ms = now

    # Handle advertising
    if mouse.get_state() == Mouse.DEVICE_IDLE:
      mouse.start_advertising()
      time.sleep(1)
    else:
      time.sleep_ms(1)


if __name__ == "__main__":
  main()
