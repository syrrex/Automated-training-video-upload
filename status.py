"""
Status LEDs and buzzer on the Raspberry Pi GPIO pins.

One LED next to each card reader (pin set in kiosk.READERS):
    blinking       card is being copied - do NOT remove it
    on             done, remove the card (1 beep: new clips, 2 beeps: nothing new)
    fast blinking  card could not be read (long beep)
Blue LED:
    blinking       uploading to Hudl
    fast blinking  upload failed, will retry

Without GPIO (laptop/WSL) the status is only printed. The latest message per
reader and for the upload is kept in `lines` for the touchscreen (gui.py).
"""

# BCM pin numbers
UPLOAD_LED_PIN = 23
BUZZER_PIN = 24


class Status:
    def __init__(self, readers: list[dict]):
        self.lines: dict[str, str] = {}  # latest message per reader / "upload", shown on the screen
        self.leds = {}
        try:
            from gpiozero import LED, Buzzer
            for reader in readers:
                self.leds[reader["label"]] = LED(reader["led_pin"])
            self.upload_led = LED(UPLOAD_LED_PIN)
            self.buzzer = Buzzer(BUZZER_PIN)
            self.has_gpio = True
        except Exception:
            self.has_gpio = False

    def _show(self, text: str, key: str) -> None:
        print(f"[STATUS] {text}", flush=True)
        self.lines[key] = text

    def _led(self, reader: dict):
        return self.leds.get(reader["label"]) if self.has_gpio else None

    def card_copying(self, reader: dict) -> None:
        self._show(f"{reader['label']}: copying - do not remove the card", reader["label"])
        if led := self._led(reader):
            led.blink(on_time=0.5, off_time=0.5)

    def card_done(self, reader: dict, new_clips: int) -> None:
        self._show(f"{reader['label']}: done ({new_clips} new clips) - remove the card", reader["label"])
        if led := self._led(reader):
            led.on()
        if self.has_gpio:
            self.buzzer.beep(on_time=0.2, off_time=0.2, n=1 if new_clips else 2)

    def card_error(self, reader: dict) -> None:
        self._show(f"{reader['label']}: card error - check the log", reader["label"])
        if led := self._led(reader):
            led.blink(on_time=0.1, off_time=0.1)
        if self.has_gpio:
            self.buzzer.beep(on_time=1.5, off_time=0.1, n=1)

    def card_removed(self, reader: dict) -> None:
        print(f"[STATUS] {reader['label']}: card removed", flush=True)
        self.lines.pop(reader["label"], None)
        if led := self._led(reader):
            led.off()

    def uploading(self, what: str) -> None:
        self._show(f"uploading to Hudl: {what}", "upload")
        if self.has_gpio:
            self.upload_led.blink(on_time=1, off_time=1)

    def uploads_done(self) -> None:
        self.lines["upload"] = "Hudl: everything uploaded"
        if self.has_gpio:
            self.upload_led.off()

    def upload_error(self) -> None:
        self._show("upload failed - will retry", "upload")
        if self.has_gpio:
            self.upload_led.blink(on_time=0.1, off_time=0.1)
