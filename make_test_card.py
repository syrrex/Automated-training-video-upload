"""
Build a test "SD card" folder from practice clips, for trying the kiosk without a camera.

Clips downloaded from Hudl have no recording time, so this gives them one:
each given folder becomes one session, clips are CLIP_MINUTES apart and there
is a BREAK_MINUTES pause between sessions. The result looks like a camera card:

    <out>/DCIM/100MEDIA/C0001.MP4, C0002.MP4, ...

Example (one folder per drill, e.g. downloaded from Hudl):
    python make_test_card.py test_cards/teamcam "test_clips/Team" "test_clips/Skelly" "test_clips/Red Zone"
    python kiosk.py --card-dir test_cards/teamcam --reader 2 --archive ~/kiosk_test --no-upload --gui
"""
import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import hudl_upload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a test SD card folder from practice clips")
    parser.add_argument("out", type=Path, help="card folder to create, e.g. test_cards/teamcam")
    parser.add_argument("sessions", type=Path, nargs="+",
                        help="one folder of clips per session, in practice order")
    parser.add_argument("--date", default="2026-10-20", help="practice date, YYYY-MM-DD")
    parser.add_argument("--start", default="18:00", help="time of the first clip, HH:MM")
    parser.add_argument("--clip-minutes", type=float, default=1, help="minutes between clips")
    parser.add_argument("--break-minutes", type=float, default=10,
                        help="minutes between sessions (must be longer than SESSION_GAP_MINUTES)")
    args = parser.parse_args()

    if args.out.exists():
        sys.exit(f"{args.out} already exists - delete it first")
    media = args.out / "DCIM" / "100MEDIA"
    media.mkdir(parents=True)

    t = datetime.fromisoformat(f"{args.date} {args.start}")
    n = 1
    for i, folder in enumerate(args.sessions):
        clips = sorted(f for f in folder.iterdir()
                       if f.suffix.lower() in hudl_upload.VIDEO_EXTENSIONS)
        if not clips:
            sys.exit(f"No video files in {folder}")
        if i:
            t += timedelta(minutes=args.break_minutes)
        first = t
        for j, clip in enumerate(clips):
            if j:
                t += timedelta(minutes=args.clip_minutes)
            target = media / f"C{n:04d}.MP4"
            shutil.copyfile(clip, target)
            os.utime(target, (t.timestamp(), t.timestamp()))
            n += 1
        print(f"session {i + 1}: {len(clips):3} clips {first:%H:%M}-{t:%H:%M}  from {folder}")
    print(f"Created {args.out} ({n - 1} clips)")


if __name__ == "__main__":
    main()
