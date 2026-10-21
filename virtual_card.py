"""
Virtual SD cards for testing the kiosk without a card reader.

A virtual card is a small FAT disk image with clips in DCIM/100MEDIA: generated
test clips, or copies of real clips with --clips-from (Hudl may reject the
generated ones). Recording times are set so the clips form the sessions.
"Inserting" it attaches it as a loop device, which Linux treats like a real
drive, so kiosk.py runs exactly the same code as with a real card
(start kiosk.py with --allow-loop). Needs root and ffmpeg.

Reader 1 = /dev/loop10, reader 2 = /dev/loop11 (matching kiosk.READERS).

    sudo python3 virtual_card.py create insiderun --sessions 1 --clips 2 --clips-from test_clips
    sudo python3 virtual_card.py create teamcam --sessions 3 --clips 1 --clips-from test_clips --skip 2
    sudo python3 virtual_card.py insert insiderun --reader 1
    sudo python3 virtual_card.py insert teamcam --reader 2
    sudo python3 virtual_card.py remove teamcam
    sudo python3 virtual_card.py delete teamcam
    sudo python3 virtual_card.py list
"""
import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

# Image files must be on the Linux file system (not /mnt/c) for loop devices to work.
CARD_DIR = Path(f"~{os.environ.get('SUDO_USER', '')}").expanduser() / "virtual_cards"
MIN_CARD_SIZE_MB = 64
CLIP_SECONDS = 2
FIRST_READER_LOOP = 10  # reader 1 = /dev/loop10, reader 2 = /dev/loop11, ...


def run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def image_path(name: str) -> Path:
    return CARD_DIR / f"{name}.img"


def attached_device(image: Path) -> str | None:
    out = run("losetup", "-j", str(image))  # "/dev/loop3: [..]:.. (/path/to/img)"
    return out.split(":")[0] if out else None


def make_clip(path: Path, recorded_at: datetime) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=duration={CLIP_SECONDS}:size=640x360:rate=30",
         "-f", "lavfi", "-i", f"sine=frequency={random.randint(200, 2000)}:duration={CLIP_SECONDS}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True)
    ts = recorded_at.timestamp()
    os.utime(path, (ts, ts))


def pick_real_clips(folder: Path, count: int, skip: int) -> list[Path]:
    """`count` clips from the folder, starting after `skip`; repeats them if there are too few."""
    videos = sorted(f for f in folder.iterdir()
                    if f.suffix.lower() in {".mp4", ".mov", ".m4v", ".mts", ".avi"})
    if not videos:
        sys.exit(f"No video files in {folder}")
    return [videos[(skip + i) % len(videos)] for i in range(count)]


@contextmanager
def new_card(name: str, content_bytes: int):
    """Create an empty FAT card image big enough for content_bytes; yields its mounted folder."""
    image = image_path(name)
    if image.exists():
        sys.exit(f"{image} already exists - remove it with: delete {name}")
    CARD_DIR.mkdir(exist_ok=True)
    size_mb = max(MIN_CARD_SIZE_MB, int(content_bytes / 1024 / 1024 * 1.2) + 16)
    with open(image, "wb") as f:
        f.truncate(size_mb * 1024 * 1024)
    run("mkfs.vfat", "-n", name[:11].upper(), str(image))

    device = run("losetup", "-f", "--show", str(image))
    with tempfile.TemporaryDirectory() as mnt:
        run("mount", device, mnt)
        try:
            yield Path(mnt)
        finally:
            run("umount", mnt)
            run("losetup", "-d", device)


def create_from_folder(name: str, folder: Path) -> None:
    """Copy a whole folder (e.g. test_cards/teamcam) onto a new card, keeping the file times."""
    files = [f for f in folder.rglob("*") if f.is_file()]
    with new_card(name, sum(f.stat().st_size for f in files)) as mnt:
        for f in files:
            target = mnt / f.relative_to(folder)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)  # copy2 keeps the recording time
    print(f"Created {image_path(name)}: {len(files)} files from {folder}, times kept")


def create(name: str, date: str, start: str, sessions: int, clips: int, gap: int,
           clips_from: Path | None, skip: int) -> None:
    real_clips = pick_real_clips(clips_from, sessions * clips, skip) if clips_from else []
    with new_card(name, sum(c.stat().st_size for c in real_clips)) as mnt:
        media = mnt / "DCIM" / "100MEDIA"
        media.mkdir(parents=True)
        session_start = datetime.fromisoformat(f"{date} {start}")
        n = 1
        for s in range(sessions):
            for c in range(clips):
                # clips one minute apart, sessions `gap` minutes apart
                target = media / f"C{n:04d}.MP4"
                recorded_at = session_start + timedelta(minutes=c)
                if real_clips:
                    shutil.copyfile(real_clips[n - 1], target)
                    ts = recorded_at.timestamp()
                    os.utime(target, (ts, ts))
                else:
                    make_clip(target, recorded_at)
                n += 1
            session_start += timedelta(minutes=gap)
    source = f" (from {', '.join(c.name for c in real_clips)})" if real_clips else ""
    print(f"Created {image_path(name)}: {sessions} sessions x {clips} clips on {date}{source}")


def insert(name: str, reader: int) -> None:
    image = image_path(name)
    if not image.exists():
        sys.exit(f"No virtual card '{name}'. Create it first.")
    if attached_device(image):
        sys.exit(f"'{name}' is already inserted")
    number = FIRST_READER_LOOP + reader - 1
    device = f"/dev/loop{number}"
    if not Path(device).exists():
        run("mknod", "-m", "660", device, "b", "7", str(number))
    if run("losetup", "-a").count(device + ":"):
        sys.exit(f"Reader {reader} already has a card")
    run("losetup", device, str(image))
    print(f"Inserted '{name}' into reader {reader} ({device})")


def remove(name: str) -> None:
    device = attached_device(image_path(name))
    if not device:
        sys.exit(f"'{name}' is not inserted")
    run("losetup", "-d", device)
    print(f"Removed '{name}' ({device})")


def delete(name: str) -> None:
    image = image_path(name)
    if not image.exists():
        sys.exit(f"No virtual card '{name}'")
    if attached_device(image):
        sys.exit(f"'{name}' is still inserted - remove it first")
    image.unlink()
    print(f"Deleted '{name}'")


def list_cards() -> None:
    for image in sorted(CARD_DIR.glob("*.img")):
        device = attached_device(image)
        print(f"  {image.stem:20} {'inserted as ' + device if device else ''}")


def main() -> None:
    if os.geteuid() != 0:
        sys.exit("Run with sudo")

    parser = argparse.ArgumentParser(description="Virtual SD cards for testing the kiosk")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="make a new virtual card with test clips")
    c.add_argument("name")
    c.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    c.add_argument("--start", default="18:00", help="time of the first clip, HH:MM")
    c.add_argument("--sessions", type=int, default=4)
    c.add_argument("--clips", type=int, default=3, help="clips per session")
    c.add_argument("--gap", type=int, default=20, help="minutes between session starts")
    c.add_argument("--clips-from", type=Path, metavar="FOLDER",
                   help="copy real clips from this folder instead of generating test clips")
    c.add_argument("--copy-card", type=Path, metavar="FOLDER",
                   help="copy this whole folder onto the card and keep its file times "
                        "(e.g. test_cards/teamcam); ignores the other options")
    c.add_argument("--skip", type=int, default=0,
                   help="with --clips-from: start at this clip (to use different clips per card)")
    i = sub.add_parser("insert", help="put a card into a virtual reader")
    i.add_argument("name")
    i.add_argument("--reader", type=int, default=1, help="1, 2, ...")
    sub.add_parser("remove", help="take a card out").add_argument("name")
    sub.add_parser("delete", help="delete a virtual card").add_argument("name")
    sub.add_parser("list")
    args = parser.parse_args()

    if args.command == "create":
        if args.copy_card:
            create_from_folder(args.name, args.copy_card)
        else:
            create(args.name, args.date, args.start, args.sessions, args.clips, args.gap,
                   args.clips_from, args.skip)
    elif args.command == "insert":
        insert(args.name, args.reader)
    elif args.command == "remove":
        remove(args.name)
    elif args.command == "delete":
        delete(args.name)
    else:
        list_cards()


if __name__ == "__main__":
    main()
