"""
Touchscreen for the kiosk (800x480, e.g. Raspberry Pi Touch Display 2).

Idle: shows the status (insert card, copying, uploading).
After a card was copied: one screen per session with a preview picture; the
coach taps a name (Team, Redzone, ...), then confirms on a summary screen.
If nobody does within kiosk.NAMING_TIMEOUT_MINUTES, the sessions are uploaded
as "Session N".

Started by kiosk.py --gui. On a PC it is a window you click with the mouse.
"""
import os
import time
import warnings
from datetime import datetime
from pathlib import Path

# Draw without OpenGL: works on every PC/WSL and on the Pi, fast enough for 800x480.
os.environ.setdefault("SDL_RENDER_DRIVER", "software")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
warnings.filterwarnings("ignore", message="no fast renderer")
import pygame  # noqa: E402  (after the settings above)

import kiosk
import status as st

WIDTH, HEIGHT = 800, 480
FPS = 15
BG = (16, 24, 32)
PANEL = (32, 44, 56)
TEXT = (235, 240, 245)
DIM = (140, 155, 170)
BUTTON = (48, 66, 84)
SELECTED = (40, 140, 90)
ACCENT = (230, 120, 40)
STATE_COLORS = {  # card / upload status bars (replace the LEDs)
    st.COPYING: (210, 110, 30), st.DONE: (40, 140, 90), st.ERROR: (190, 50, 50),
    st.UPLOADING: (40, 100, 180), st.UPLOAD_ERROR: (190, 50, 50), st.UPLOADED: PANEL,
}
MESSAGE_SECONDS = 4


class Button:
    def __init__(self, rect: pygame.Rect, label: str, value=None, color=BUTTON):
        self.rect, self.label, self.value, self.color = rect, label, value, color


class Screen:
    def __init__(self, archive: Path, status, fullscreen: bool):
        self.archive = archive
        self.status = status
        flags = pygame.SCALED | (pygame.FULLSCREEN if fullscreen else 0)
        self.surface = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        pygame.display.set_caption("Hudl Upload Kiosk")
        if fullscreen:
            pygame.mouse.set_visible(False)
        self.font_big = pygame.font.Font(None, 52)
        self.font = pygame.font.Font(None, 34)
        self.font_small = pygame.font.Font(None, 26)
        self.previews: dict[Path, pygame.Surface | None] = {}
        self.card: Path | None = None  # card folder being named
        self.sessions: list[Path] = []
        self.names: list[str | None] = []
        self.index = 0  # session on screen; len(sessions) = summary
        self.editing = False  # changing one name from the summary
        self.message = ""
        self.message_until = 0.0
        self.buttons: list[Button] = []

    # ---------- state ----------

    def start_naming(self, card: Path) -> None:
        self.card = card
        self.sessions = kiosk.sessions_of(card)
        self.names = [None] * len(self.sessions)
        self.index = 0
        self.editing = False

    def finish(self, message: str) -> None:
        self.card = None
        self.message = message
        self.message_until = time.monotonic() + MESSAGE_SECONDS

    def update(self) -> None:
        if self.card is None:
            if time.monotonic() > self.message_until:
                waiting = kiosk.cards_waiting_for_names(self.archive)
                if waiting:
                    self.start_naming(waiting[0])
        elif kiosk.naming_deadline(self.card) is None:
            self.finish("Time is up - uploading as Session 1, 2, ...")

    def tap(self, pos) -> None:
        for button in self.buttons:
            if button.rect.collidepoint(pos):
                self.press(button.value)
                return

    def press(self, value) -> None:
        if value == "back":
            self.index = len(self.sessions) if self.editing else max(0, self.index - 1)
            self.editing = False
        elif value == "upload":
            if kiosk.apply_names(self.card, self.names):
                self.finish("Saved - uploading to Hudl")
            else:
                self.finish("Too late - already uploaded as Session 1, 2, ...")
        elif isinstance(value, tuple) and value[0] == "name":
            self.names[self.index] = value[1]
            self.index = len(self.sessions) if self.editing else self.index + 1
            self.editing = False
        elif isinstance(value, tuple) and value[0] == "edit":
            self.index = value[1]
            self.editing = True

    # ---------- drawing ----------

    def text(self, text: str, pos, font=None, color=TEXT, center=False) -> None:
        image = (font or self.font).render(text, True, color)
        rect = image.get_rect(center=pos) if center else image.get_rect(topleft=pos)
        self.surface.blit(image, rect)

    def button(self, rect: pygame.Rect, label: str, value, color=BUTTON) -> None:
        pygame.draw.rect(self.surface, color, rect, border_radius=10)
        self.text(label, rect.center, center=True)
        self.buttons.append(Button(rect, label, value, color))

    def preview(self, session: Path) -> pygame.Surface | None:
        if session not in self.previews:
            picture = session / ".preview.jpg"
            try:
                image = pygame.image.load(str(picture)).convert()
                scale = min(320 / image.get_width(), 180 / image.get_height())
                size = (int(image.get_width() * scale), int(image.get_height() * scale))
                self.previews[session] = pygame.transform.smoothscale(image, size)
            except (pygame.error, FileNotFoundError):
                self.previews[session] = None
        return self.previews[session]

    def countdown(self) -> str:
        deadline = kiosk.naming_deadline(self.card)
        minutes = max(0, int((deadline - time.time()) / 60) + 1) if deadline else 0
        return f"No names? Uploads as Session N in {minutes} min"

    def draw(self) -> None:
        self.surface.fill(BG)
        self.buttons = []
        if self.card is None:
            self.draw_idle()
        elif self.index < len(self.sessions):
            self.draw_session()
        else:
            self.draw_summary()
        if self.card is not None:
            self.draw_card_alert()
        pygame.display.flip()

    def draw_idle(self) -> None:
        self.text("Hudl Upload Kiosk", (20, 18), self.font_small, DIM)
        self.text(datetime.now().strftime("%H:%M"), (WIDTH - 80, 18), self.font_small, DIM)
        if time.monotonic() < self.message_until:
            self.text(self.message, (WIDTH // 2, 90), self.font_big, ACCENT, center=True)
        else:
            self.text("Insert the SD card", (WIDTH // 2, 90), self.font_big, center=True)
        # one coloured bar per card reader, then the upload status
        lines = list(self.status.lines.items())
        cards = [(state, text) for key, (state, text) in lines if key != "upload"]
        upload = [(state, text) for key, (state, text) in lines if key == "upload"]
        y = 150
        for state, text in cards:
            bar = pygame.Rect(20, y, WIDTH - 40, 70)
            pygame.draw.rect(self.surface, STATE_COLORS[state], bar, border_radius=10)
            self.text(text, bar.center, self.font, center=True)
            y += 82
        for state, text in upload:
            bar = pygame.Rect(20, HEIGHT - 70, WIDTH - 40, 50)
            pygame.draw.rect(self.surface, STATE_COLORS[state], bar, border_radius=10)
            self.text(text, bar.center, self.font_small, center=True)

    def draw_card_alert(self) -> None:
        """While naming: show cards that are still copying or failed, so nobody pulls them."""
        alerts = [(state, text) for key, (state, text) in list(self.status.lines.items())
                  if key != "upload" and state in (st.COPYING, st.ERROR)]
        if alerts:
            state, text = alerts[0]
            bar = pygame.Rect(0, 0, WIDTH, 40)
            pygame.draw.rect(self.surface, STATE_COLORS[state], bar)
            self.text(text, bar.center, self.font_small, center=True)

    def draw_session(self) -> None:
        session = self.sessions[self.index]
        clips = kiosk.session_clips(session)
        start = datetime.fromtimestamp(clips[0].stat().st_mtime) if clips else None
        end = datetime.fromtimestamp(clips[-1].stat().st_mtime) if clips else None
        camera = self.card.name[11:]

        self.text(f"{camera} - {self.card.name[:10]}", (20, 14), self.font_small, DIM)
        self.text(f"Group {self.index + 1} of {len(self.sessions)}", (WIDTH - 20 - 190, 14),
                  self.font_small, DIM)
        picture = self.preview(session)
        box = pygame.Rect(20, 50, 320, 180)
        pygame.draw.rect(self.surface, PANEL, box)
        if picture:
            self.surface.blit(picture, picture.get_rect(center=box.center))
        else:
            self.text("no preview", box.center, self.font_small, DIM, center=True)
        if start:
            self.text(f"{start:%H:%M} - {end:%H:%M}", (370, 70), self.font_big)
        self.text(f"{len(clips)} clips", (370, 125))
        self.text("Which drill is this?", (370, 180), self.font, ACCENT)
        self.text(self.countdown(), (20, 245), self.font_small, DIM)

        # name buttons, 4 per row, then "keep Session N" and "Back"; rows share the space below
        labels = [(name, ("name", name)) for name in kiosk.GROUP_NAMES]
        labels.append((session.name[13:], ("name", None)))  # e.g. "Session 2"
        labels.append(("< Back", "back"))
        columns, w, gap, top = 4, 182, 10, 275
        rows = -(-len(labels) // columns)
        h = min(64, (HEIGHT - 10 - top - (rows - 1) * gap) // rows)
        for i, (label, value) in enumerate(labels):
            row, col = divmod(i, columns)
            rect = pygame.Rect(20 + col * (w + gap), top + row * (h + gap), w, h)
            chosen = value != "back" and value[1] == self.names[self.index]
            color = SELECTED if chosen and value[1] is not None else BUTTON
            self.button(rect, label, value, color)

    def draw_summary(self) -> None:
        self.text("Check the names", (20, 14), self.font_big)
        self.text(self.countdown(), (20, 62), self.font_small, DIM)
        y = 100
        for i, (session, name) in enumerate(zip(self.sessions, self.names)):
            clips = kiosk.session_clips(session)
            start = datetime.fromtimestamp(clips[0].stat().st_mtime) if clips else None
            label = name or session.name[13:]
            line = f"{start:%H:%M}  {len(clips):3} clips   ->  {label}" if start else label
            # tap a line to change that name
            self.button(pygame.Rect(20, y, 560, 44), line, ("edit", i), PANEL)
            y += 52
        self.text("Tap a line to change it", (20, y + 4), self.font_small, DIM)
        self.button(pygame.Rect(600, 100, 180, 120), "Upload", "upload", SELECTED)
        self.button(pygame.Rect(600, 240, 180, 64), "< Back", "back")


def run(archive: Path, status, fullscreen: bool = False) -> None:
    pygame.init()
    screen = Screen(archive, status, fullscreen)
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.MOUSEBUTTONUP:  # touch taps arrive as mouse clicks too
                screen.tap(event.pos)
        screen.update()
        screen.draw()
        clock.tick(FPS)
