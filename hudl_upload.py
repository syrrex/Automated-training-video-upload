"""
Upload a folder of practice clips to Hudl using the Hudl web uploader.

Hudl has no public upload API, so this script drives hudl.com in a real
browser with Playwright. The steps were recorded on the new Hudl with
`playwright codegen` (recorded_upload.py):
    Upload -> dismiss popup -> select files -> Upload -> video type (if shown)
    -> scheduled event -> Playlist Name -> Save

Setup (once):
    pip install -r requirements.txt
    playwright install --with-deps chromium
    python hudl_upload.py login

Upload:
    python hudl_upload.py upload test_clips --event "Preseason January 10" --name "2026-10-20 - Session 1"
    python hudl_upload.py upload test_clips --dry-run   # only list clips

If a step fails, the script saves a screenshot to screenshots/ and names the
step. Re-record with codegen if Hudl changed its site.
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTH_FILE = HERE / "hudl_auth.json"  # saved login session - keep this private!
SCREENSHOT_DIR = HERE / "screenshots"
HUDL_HOME = "https://www.hudl.com/home"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mts", ".avi"}
STEP_TIMEOUT_SECONDS = 30
UPLOAD_TIMEOUT_MINUTES = 180
# Upload counts as finished once no upload request was running for this long.
UPLOAD_QUIET_SECONDS = 30


def find_clips(folder: Path) -> list[Path]:
    """Video files in the folder, oldest first (= recording order)."""
    clips = [
        f for f in folder.iterdir()
        if f.is_file()
        and f.suffix.lower() in VIDEO_EXTENSIONS
        and not f.name.startswith(".")  # skip macOS "._" junk files on SD cards
    ]
    return sorted(clips, key=lambda f: f.stat().st_mtime)


def login() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(HUDL_HOME)
        input("Log in to Hudl in the browser window, then press Enter here... ")
        context.storage_state(path=str(AUTH_FILE))
        browser.close()
    print(f"Session saved to {AUTH_FILE}")


class StepFailed(Exception):
    pass


class UploadTracker:
    """Counts the page's open PUT/POST requests, to tell when the file upload is done."""

    def __init__(self, page):
        self.in_flight = 0
        self.seen_any = False
        self.last_activity = time.monotonic()
        page.on("request", self._started)
        page.on("requestfinished", self._finished)
        page.on("requestfailed", self._finished)

    @staticmethod
    def _counts(request) -> bool:
        return request.method in ("PUT", "POST") and request.resource_type in ("xhr", "fetch")

    def _started(self, request):
        if self._counts(request):
            self.in_flight += 1
            self.seen_any = True
            self.last_activity = time.monotonic()

    def _finished(self, request):
        if self._counts(request):
            self.in_flight = max(0, self.in_flight - 1)
            self.last_activity = time.monotonic()

    def wait_until_done(self, page) -> None:
        deadline = time.monotonic() + UPLOAD_TIMEOUT_MINUTES * 60
        while time.monotonic() < deadline:
            quiet_for = time.monotonic() - self.last_activity
            if self.seen_any and self.in_flight == 0 and quiet_for > UPLOAD_QUIET_SECONDS:
                return
            page.wait_for_timeout(1000)  # lets Playwright deliver the request events
        raise StepFailed("wait for upload to finish")


def run_upload_flow(page, clips: list[Path], name: str, video_type: str,
                    event: str | None) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    def step(name: str, action) -> None:
        print(f"  -> {name}")
        try:
            action()
        except PlaywrightTimeout as e:
            raise StepFailed(name) from e

    page.set_default_timeout(STEP_TIMEOUT_SECONDS * 1000)
    tracker = UploadTracker(page)

    step("click Upload", lambda: page.get_by_role("link", name="Upload Upload").click())

    # Hudl sometimes shows a popup here; it is not always there.
    try:
        page.get_by_role("button", name="uidismiss").click(timeout=3000)
        print("  -> dismissed popup")
    except PlaywrightTimeout:
        pass

    step("select files", lambda: page.locator('input[type="file"]').first.set_input_files(
        [str(c) for c in clips]))
    step("start upload", lambda: page.get_by_role("button", name="Upload").click())
    # Hudl does not always ask for the video type.
    try:
        page.get_by_text(video_type, exact=True).click(timeout=5000)
        print(f"  -> video type '{video_type}'")
    except PlaywrightTimeout:
        print("  -> no video type asked, skipped")
    if event:
        def choose_event():
            # arrow icon that opens the event list
            page.locator("span").filter(
                has_text=re.compile(r"^uiexpandregionvertical$")).click()
            page.get_by_role("option", name=event).first.click()
        step(f"scheduled event '{event}'", choose_event)
    step(f"playlist name '{name}'",
         lambda: page.get_by_role("textbox", name="Playlist Name").fill(name))
    step("save", lambda: page.get_by_role("button", name="Save").click())
    # Closing the browser before this point may cancel the upload.
    print(f"  -> waiting for upload to finish (max {UPLOAD_TIMEOUT_MINUTES} min)")
    tracker.wait_until_done(page)


def upload(folder: Path, name: str, video_type: str, event: str | None,
           headless: bool, pause: bool) -> bool:
    from playwright.sync_api import sync_playwright

    clips = find_clips(folder)
    if not clips:
        print(f"No video files found in {folder}")
        return False
    if not AUTH_FILE.exists():
        print("Not logged in yet. Run: python hudl_upload.py login")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        page = context.new_page()
        page.goto(HUDL_HOME)

        if "login" in page.url:
            print("Hudl session expired. Run: python hudl_upload.py login")
            browser.close()
            return False

        if pause:
            # Opens the Playwright Inspector: press "Resume" to continue the upload.
            page.pause()

        print(f"Uploading {len(clips)} clips as '{name}'")
        try:
            run_upload_flow(page, clips, name, video_type, event)
        except StepFailed as e:
            SCREENSHOT_DIR.mkdir(exist_ok=True)
            shot = SCREENSHOT_DIR / f"failed_{datetime.now():%Y%m%d_%H%M%S}.png"
            page.screenshot(path=str(shot), full_page=True)
            print(f"FAILED at step '{e}'. Screenshot: {shot}")
            if not headless:
                input("Browser stays open so you can look. Press Enter to close... ")
            browser.close()
            return False

        # Save the cookies Hudl may have renewed, so the login lasts as long as possible.
        context.storage_state(path=str(AUTH_FILE))
        browser.close()

    print("Done")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a folder of clips to Hudl")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="log in by hand once and save the session")

    up = sub.add_parser("upload", help="upload all clips in a folder")
    up.add_argument("folder", type=Path)
    up.add_argument("--name", help="playlist name in Hudl (default: folder name)")
    up.add_argument("--video-type", default="Practice", help="default: Practice")
    up.add_argument("--event", help="scheduled event to link, e.g. 'Preseason January 10'")
    up.add_argument("--headless", action="store_true", help="hide the browser window")
    up.add_argument("--pause", action="store_true",
                    help="open the Playwright Inspector before uploading")
    up.add_argument("--dry-run", action="store_true", help="only list the clips")

    args = parser.parse_args()

    if args.command == "login":
        login()
        return 0

    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}")
        return 1

    if args.dry_run:
        clips = find_clips(args.folder)
        total_gb = sum(c.stat().st_size for c in clips) / 1e9
        for c in clips:
            print(f"  {c.name}")
        print(f"{len(clips)} clips, {total_gb:.1f} GB")
        return 0

    ok = upload(args.folder, args.name or args.folder.name, args.video_type, args.event,
                args.headless, args.pause)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
