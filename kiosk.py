"""
Upload kiosk: insert SD cards, the clips are copied to the Pi, split into
sessions and uploaded to Hudl, one upload per session. Cards are only read,
never changed.

Clips are split into sessions wherever the pause between two clips is longer
than SESSION_GAP_MINUTES. Sessions are numbered per day across all cards
(first card: Session 1-3, second card: Session 4, ...); coaches rename them
in Hudl if needed. There is one card reader per camera (see READERS), each
with its own LED.

Archive layout:
    <archive>/2026-10-21_Team cam/2026-10-21 - Session 1/C0001.MP4 ...
    <archive>/2026-10-21_Team cam/2026-10-21 - Session 1/.uploaded   <- written after upload
    <archive>/2026-10-21_Inside Run cam/2026-10-21 - Session 4/...
    <archive>/2026-10-21_Team cam/2026-10-21 - Session 1/.rejected  <- Hudl refused the files (see log)
    <archive>/seen.txt                                               <- clips already copied
Clips are kept on the archive HDD; set KEEP_DAYS_AFTER_UPLOAD to delete them after upload.

On the Pi (root is needed to mount cards):
    sudo python3 kiosk.py
    sudo python3 kiosk.py --show-readers     # find the ports for READERS
Find the right SESSION_GAP_MINUTES (pauses between the clips of a practice):
    python kiosk.py --show-gaps real_practice
Test without a card reader:
    python kiosk.py --card-dir test_clips --archive ~/kiosk_test --no-upload
Test with virtual SD cards (see virtual_card.py):
    sudo -E env PATH="$PATH" python3 kiosk.py --archive ~/kiosk_test --allow-loop --no-upload
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import hudl_upload
from status import Status

# One entry per card reader / camera.
#   ports:    how the reader is recognised. A card counts as being in this reader if one
#             of these texts is part of its port (run --show-readers with a card inserted
#             to see the port). /dev/loop10 and /dev/loop11 are the virtual readers.
#   led_pin:  GPIO (BCM) pin of this reader's LED
READERS = [
    {"label": "Inside Run cam", "ports": ["/dev/loop10"], "led_pin": 17},
    {"label": "Team cam", "ports": ["/dev/loop11"], "led_pin": 27},
]
UNKNOWN_READER = {"label": "Unknown reader", "ports": [], "led_pin": None}

DEFAULT_ARCHIVE = Path("/mnt/archive")  # USB HDD
ARCHIVE_LABEL = "KIOSKHDD"  # drive name of the archive HDD - never treated as an SD card
MOUNT_ROOT = Path("/mnt/sdcard")
CARD_FILESYSTEMS = {"vfat", "exfat", "ntfs"}  # filesystems camera cards use
SESSION_GAP_MINUTES = 5  # pause between two clips that starts a new session - check with --show-gaps
VIDEO_TYPE = "Practice"
HUDL_EVENT = "Preseason January 10"  # scheduled event every upload is linked to (Hudl requires one)
CARD_POLL_SECONDS = 2
UPLOAD_POLL_SECONDS = 30
RETRY_AFTER_FAILURE_MINUTES = 5
RETRY_AFTER_LOGIN_FAILURE_MINUTES = 60  # not more often, so Hudl doesn't lock the account
KEEP_DAYS_AFTER_UPLOAD = None  # None = keep clips forever; a number = delete that many days after upload
ALLOW_LOOP_DEVICES = False  # --allow-loop: treat virtual SD cards (loop devices) as cards

archive_lock = threading.Lock()  # two cards can be copied at the same time


def log(text: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}", flush=True)


# ---------- clips & sessions ----------

def find_card_clips(card_root: Path) -> list[Path]:
    """All video files anywhere on the card (e.g. DCIM/100MEDIA), in recording order."""
    clips = [
        f for f in card_root.rglob("*")
        if f.is_file()
        and f.suffix.lower() in hudl_upload.VIDEO_EXTENSIONS
        and not f.name.startswith(".")
    ]
    return sorted(clips, key=lambda f: f.stat().st_mtime)


def group_by_time(clips: list[Path], gap_minutes: float) -> list[list[Path]]:
    """Split clips (sorted by time) into sessions wherever the pause is longer than gap_minutes."""
    sessions: list[list[Path]] = []
    last_time = None
    for clip in clips:
        t = clip.stat().st_mtime
        if last_time is None or t - last_time > gap_minutes * 60:
            sessions.append([])
        sessions[-1].append(clip)
        last_time = t
    return sessions


def show_gaps(folder: Path) -> None:
    """Print every clip with the pause before it, to find the right SESSION_GAP_MINUTES."""
    clips = find_card_clips(folder)
    if not clips:
        print(f"No video files found in {folder}")
        return
    last_time = None
    for clip in clips:
        t = clip.stat().st_mtime
        line = f"{datetime.fromtimestamp(t):%H:%M:%S}  {clip.name:20}"
        if last_time is not None:
            pause = (t - last_time) / 60
            line += f"  pause {pause:5.1f} min"
            if pause > SESSION_GAP_MINUTES:
                line += "   <-- new session"
        print(line)
        last_time = t
    sessions = len(group_by_time(clips, SESSION_GAP_MINUTES))
    print(f"{len(clips)} clips -> {sessions} sessions with SESSION_GAP_MINUTES = {SESSION_GAP_MINUTES}")


def session_number(session_dir: Path) -> int:
    """'2026-10-20 - Session 3' -> 3"""
    try:
        return int(session_dir.name.rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        return 0


def clip_key(clip: Path) -> str:
    """Identifies a clip; includes the start of the file, since both cameras use the same file names."""
    st = clip.stat()
    with open(clip, "rb") as f:
        head = hashlib.md5(f.read(65536)).hexdigest()
    return f"{clip.name}|{st.st_size}|{int(st.st_mtime)}|{head}"


def load_seen(archive: Path) -> set[str]:
    seen_file = archive / "seen.txt"
    return set(seen_file.read_text().splitlines()) if seen_file.exists() else set()


def ingest(card_root: Path, archive: Path, reader: dict) -> int:
    """Copy new clips from the card into session folders. Returns the number of new clips."""
    seen = load_seen(archive)
    new_clips = [c for c in find_card_clips(card_root) if clip_key(c) not in seen]
    if not new_clips:
        log(f"{reader['label']}: no new clips on card")
        return 0

    sessions = group_by_time(new_clips, SESSION_GAP_MINUTES)
    date = datetime.fromtimestamp(new_clips[0].stat().st_mtime).strftime("%Y-%m-%d")
    base = f"{date}_{reader['label']}"
    # Copy into a .partial folder first, so the uploader never sees half-copied sessions.
    with archive_lock:
        final_dir = archive / base
        n = 2
        while final_dir.exists() or final_dir.with_name(final_dir.name + ".partial").exists():
            final_dir = archive / f"{base}_{n}"
            n += 1
        partial_dir = final_dir.with_name(final_dir.name + ".partial")
        partial_dir.mkdir()
        # Continue the day's numbering from earlier cards; reserve the numbers inside the lock.
        first = 1 + max((session_number(d) for d in archive.glob(f"{date}_*/*") if d.is_dir()),
                        default=0)
        session_dirs = [partial_dir / f"{date} - Session {first + i}" for i in range(len(sessions))]
        for d in session_dirs:
            d.mkdir()

    for i, (session_dir, clips) in enumerate(zip(session_dirs, sessions), start=1):
        log(f"{reader['label']}: copying {session_dir.name} ({i}/{len(sessions)}): {len(clips)} clips")
        for clip in clips:
            target = session_dir / clip.name
            if target.exists():  # same file name in two card folders
                target = session_dir / f"{clip.parent.name}_{clip.name}"
            shutil.copy2(clip, target)  # copy2 keeps the recording time

    partial_dir.rename(final_dir)
    with archive_lock, open(archive / "seen.txt", "a") as f:
        f.writelines(clip_key(c) + "\n" for c in new_clips)
    log(f"{reader['label']}: copied {len(new_clips)} clips in {len(sessions)} sessions to {final_dir}")
    return len(new_clips)


# ---------- SD card detection ----------

def find_cards() -> list[dict]:
    """All removable devices with a card filesystem, from lsblk."""
    out = subprocess.run(["lsblk", "-J", "-p", "-o", "NAME,HOTPLUG,FSTYPE,LABEL,MOUNTPOINT"],
                         capture_output=True, text=True, check=True).stdout

    def walk(devices, parent_hotplug=False):
        for dev in devices:
            hotplug = parent_hotplug or dev.get("hotplug") in (True, "1")
            if dev["name"].startswith("/dev/loop"):
                # only the virtual readers, not the loop device virtual_card.py uses to create a card
                hotplug = ALLOW_LOOP_DEVICES and any(dev["name"] in r["ports"] for r in READERS)
            yield dev, hotplug
            yield from walk(dev.get("children", []), hotplug)

    return [dev for dev, hotplug in walk(json.loads(out)["blockdevices"])
            if hotplug and dev.get("fstype") in CARD_FILESYSTEMS
            and dev.get("label") != ARCHIVE_LABEL]


def port_of(device: str) -> str:
    """Physical USB port of a device (udev ID_PATH); the device name if udev doesn't know it."""
    result = subprocess.run(["udevadm", "info", "--query=property", f"--name={device}"],
                            capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if line.startswith("ID_PATH="):
            return line.split("=", 1)[1]
    return device


def reader_for(device: str) -> dict:
    port = port_of(device)
    for reader in READERS:
        if any(p in port for p in reader["ports"]):
            return reader
    return UNKNOWN_READER


def handle_card(card: dict, archive: Path, status: Status) -> None:
    reader = reader_for(card["name"])
    status.card_copying(reader)
    mount_point = MOUNT_ROOT / Path(card["name"]).name
    mounted_by_us = False
    try:
        mountpoint = card.get("mountpoint")
        if not mountpoint:
            mount_point.mkdir(parents=True, exist_ok=True)
            subprocess.run(["mount", "-o", "ro", card["name"], str(mount_point)], check=True)
            mounted_by_us = True
            mountpoint = str(mount_point)
        log(f"{reader['label']}: card {card['name']} mounted at {mountpoint}")
        new_clips = ingest(Path(mountpoint), archive, reader)
        status.card_done(reader, new_clips)
    except Exception:
        log(f"{reader['label']}: card failed:\n" + traceback.format_exc())
        status.card_error(reader)
    finally:
        if mounted_by_us:
            subprocess.run(["umount", str(mount_point)])


def card_loop(archive: Path, status: Status) -> None:
    present: dict[str, dict] = {}  # device name -> reader, for cards already handled
    while True:
        cards = {card["name"]: card for card in find_cards()}
        for name, card in cards.items():
            if name not in present:
                present[name] = reader_for(name)
                threading.Thread(target=handle_card, args=(card, archive, status),
                                 daemon=True).start()
        for name in list(present):
            if name not in cards:
                status.card_removed(present.pop(name))
        time.sleep(CARD_POLL_SECONDS)


def show_readers() -> None:
    cards = find_cards()
    if not cards:
        print("No card found. Insert a card in each reader and run again.")
    for card in cards:
        print(f"{card['name']}: port '{port_of(card['name'])}' -> {reader_for(card['name'])['label']}")


# ---------- uploads ----------

def pending_sessions(archive: Path) -> list[Path]:
    """Sessions not uploaded yet, oldest day first, then by session number."""
    sessions = [
        session
        for practice in archive.iterdir()
        if practice.is_dir() and not practice.name.endswith(".partial")
        for session in practice.iterdir()
        if session.is_dir()
        and not (session / ".uploaded").exists() and not (session / ".rejected").exists()
    ]
    return sorted(sessions, key=lambda s: (s.name[:10], session_number(s)))


def upload_loop(archive: Path, status: Status) -> None:
    while True:
        delete_old_uploads(archive)
        pending = pending_sessions(archive)
        if not pending:
            status.uploads_done()
            time.sleep(UPLOAD_POLL_SECONDS)
            continue

        session = pending[0]
        status.uploading()
        log(f"uploading {session} ({len(pending)} sessions waiting)")
        try:
            ok = hudl_upload.upload(session, session.name, VIDEO_TYPE, HUDL_EVENT,
                                    headless=True, pause=False)
        except hudl_upload.LoginFailed as e:
            log(f"{e} - next try in {RETRY_AFTER_LOGIN_FAILURE_MINUTES} min")
            status.upload_error()
            time.sleep(RETRY_AFTER_LOGIN_FAILURE_MINUTES * 60)
            continue
        except hudl_upload.FilesRejected:
            # Retrying won't help; set the session aside so the queue keeps moving.
            (session / ".rejected").touch()
            log(f"Hudl rejected the files of {session} - skipped, upload them by hand")
            status.upload_error()
            continue
        except Exception:
            log("upload crashed:\n" + traceback.format_exc())
            ok = False

        if ok:
            (session / ".uploaded").touch()
            log(f"uploaded {session}")
        else:
            status.upload_error()
            time.sleep(RETRY_AFTER_FAILURE_MINUTES * 60)


def delete_old_uploads(archive: Path) -> None:
    """Delete card folders whose sessions were all uploaded more than KEEP_DAYS_AFTER_UPLOAD ago.
    seen.txt keeps their clips, so inserting the same card again does not upload them twice."""
    if KEEP_DAYS_AFTER_UPLOAD is None:
        return
    cutoff = time.time() - KEEP_DAYS_AFTER_UPLOAD * 24 * 3600
    for practice in archive.iterdir():
        if not practice.is_dir() or practice.name.endswith(".partial"):
            continue
        sessions = [s for s in practice.iterdir() if s.is_dir()]
        markers = [s / ".uploaded" for s in sessions]
        if sessions and all(m.exists() and m.stat().st_mtime < cutoff for m in markers):
            log(f"deleting {practice} (uploaded more than {KEEP_DAYS_AFTER_UPLOAD} days ago)")
            shutil.rmtree(practice)


def cleanup_partial(archive: Path) -> None:
    """Remove half-copied folders left by a power cut; those clips are not in seen.txt yet."""
    for partial in archive.glob("*.partial"):
        log(f"removing unfinished copy {partial}")
        shutil.rmtree(partial)


def main() -> None:
    global ALLOW_LOOP_DEVICES, SESSION_GAP_MINUTES
    parser = argparse.ArgumentParser(description="SD card -> Hudl upload kiosk")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE,
                        help=f"where clips are stored (default: {DEFAULT_ARCHIVE})")
    parser.add_argument("--card-dir", type=Path,
                        help="treat this folder as an inserted card (testing without a reader)")
    parser.add_argument("--reader", type=int, default=1,
                        help="with --card-dir: which reader the folder is 'in' (1, 2, ...)")
    parser.add_argument("--show-gaps", type=Path, metavar="FOLDER",
                        help="list the clips in FOLDER with the pauses between them and exit")
    parser.add_argument("--gap", type=float, default=SESSION_GAP_MINUTES,
                        help=f"minutes of pause that start a new session (default: {SESSION_GAP_MINUTES})")
    parser.add_argument("--no-upload", action="store_true", help="only copy and group")
    parser.add_argument("--allow-loop", action="store_true",
                        help="accept virtual SD cards from virtual_card.py")
    parser.add_argument("--show-readers", action="store_true",
                        help="print the port of each inserted card and exit")
    args = parser.parse_args()

    ALLOW_LOOP_DEVICES = args.allow_loop
    SESSION_GAP_MINUTES = args.gap

    if args.show_gaps:
        show_gaps(args.show_gaps)
        return
    if args.show_readers:
        show_readers()
        return

    args.archive.mkdir(parents=True, exist_ok=True)
    cleanup_partial(args.archive)
    status = Status(READERS)

    if args.card_dir:
        reader = READERS[args.reader - 1]
        status.card_copying(reader)
        status.card_done(reader, ingest(args.card_dir, args.archive, reader))
    else:
        threading.Thread(target=card_loop, args=(args.archive, status), daemon=True).start()
        log("waiting for SD cards")

    if not args.no_upload:
        upload_loop(args.archive, status)
    elif not args.card_dir:
        threading.Event().wait()  # keep watching for cards


if __name__ == "__main__":
    main()
