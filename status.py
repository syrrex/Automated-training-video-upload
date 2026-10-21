"""
Status of the card readers and the uploads, shown on the touchscreen (gui.py)
and printed to the log.

Optional buzzer on the Raspberry Pi (GPIO 24, pin 18 + GND):
    1 beep    card done, remove it
    2 beeps   card done, nothing new on it
    long beep card could not be read
Without a buzzer (or on a PC) nothing beeps.
"""

BUZZER_PIN = 24  # BCM numbering

# states, used by gui.py for the colours
COPYING, DONE, ERROR, UPLOADING, UPLOAD_ERROR, UPLOADED = (
    "copying", "done", "error", "uploading", "upload_error", "uploaded")


class Status:
    def __init__(self, readers: list[dict]):
        # latest message per reader label / "upload": (state, text)
        self.lines: dict[str, tuple[str, str]] = {}
        try:
            from gpiozero import Buzzer
            self.buzzer = Buzzer(BUZZER_PIN)
        except Exception:
            self.buzzer = None

    def _show(self, key: str, state: str, text: str) -> None:
        print(f"[STATUS] {text}", flush=True)
        self.lines[key] = (state, text)

    def _beep(self, **kwargs) -> None:
        if self.buzzer:
            self.buzzer.beep(**kwargs)

    def card_copying(self, reader: dict) -> None:
        self._show(reader["label"], COPYING, f"{reader['label']}: copying - don't remove the card")

    def card_done(self, reader: dict, new_clips: int) -> None:
        self._show(reader["label"], DONE,
                   f"{reader['label']}: done ({new_clips} new clips) - remove the card")
        self._beep(on_time=0.2, off_time=0.2, n=1 if new_clips else 2)

    def card_error(self, reader: dict) -> None:
        self._show(reader["label"], ERROR, f"{reader['label']}: card error - check the log")
        self._beep(on_time=1.5, off_time=0.1, n=1)

    def card_removed(self, reader: dict) -> None:
        print(f"[STATUS] {reader['label']}: card removed", flush=True)
        self.lines.pop(reader["label"], None)

    def uploading(self, what: str) -> None:
        self._show("upload", UPLOADING, f"Uploading to Hudl: {what}")

    def uploads_done(self) -> None:
        self.lines["upload"] = (UPLOADED, "Hudl: everything uploaded")

    def upload_error(self) -> None:
        self._show("upload", UPLOAD_ERROR, "Upload failed - will retry")

    def login_failed(self, contact: str) -> None:
        self._show("upload", UPLOAD_ERROR, f"Hudl login failed - please tell {contact}")
