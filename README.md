# Hudl Upload Kiosk

Put the cameras' SD cards into the kiosk after practice. The kiosk copies the clips,
splits them into sessions by the pauses between clips, lets a coach name each session on
a touchscreen (Team, Skelly, Red Zone, …) and uploads every session to Hudl as its own
playlist, e.g. `2026-10-20 - Red Zone`. Cards are only read, never changed.

It runs on a Raspberry Pi with two card readers (one per camera) and a touchscreen, but
everything can be tried on a normal PC first.

| File | What it does |
|---|---|
| `kiosk.py` | Detects cards, copies and groups clips, runs the upload queue. **Settings at the top** |
| `hudl_upload.py` | Uploads one folder to Hudl by remote-controlling a browser (Hudl has no upload API) |
| `gui.py` | Touchscreen: name the sessions before upload |
| `status.py` | LEDs and buzzer on the Pi |
| `kiosk.service` | Starts the kiosk when the Pi boots |
| `make_test_card.py` | Builds a test "SD card" folder from clips, for trying it without a camera |
| `virtual_card.py` | Virtual SD cards that Linux treats like a real card in a reader |

## Quick start on your PC

**You need:** Linux, or Windows 11 with WSL2 (Ubuntu); Python 3.10 or newer; and a Hudl
account that is allowed to upload to the team (coach or admin).

1. Install:
   ```bash
   git clone https://github.com/syrrex/Automated-training-video-upload.git
   cd Automated-training-video-upload
   sudo apt install ffmpeg python3-venv
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   playwright install --with-deps chromium
   ```
2. Store your Hudl login (the password is typed hidden and tested right away):
   ```bash
   python hudl_upload.py set-login
   ```
   This creates `hudl_credentials.json` and `hudl_auth.json`. **Never share or commit
   them** – they give access to the Hudl account (they are in `.gitignore`).
3. Get test clips. Team videos are not in this repo. In Hudl, download the clips of a
   practice, one folder per session (e.g. `test_clips/Team`, `test_clips/Skelly`, …).
   Downloaded clips have lost their recording time, so build a test card that gives them
   one (clips 1 min apart, 10 min break between sessions):
   ```bash
   python make_test_card.py test_cards/teamcam test_clips/Team test_clips/Skelly test_clips/"Red Zone"
   ```
4. Try the touchscreen in a window – click instead of tapping. `--no-upload` means nothing
   goes to Hudl:
   ```bash
   python kiosk.py --card-dir test_cards/teamcam --reader 2 --archive ~/kiosk_test --no-upload --gui
   ```
5. The real thing, with upload. This creates real playlists in Hudl under the event
   `HUDL_EVENT` (see Settings) – delete them afterwards:
   ```bash
   rm -rf ~/kiosk_test
   python kiosk.py --card-dir test_cards/teamcam --reader 2 --archive ~/kiosk_test --gui
   ```
   Keep the window open until the terminal shows `uploaded …` for every session.

`~/kiosk_test` is where the kiosk keeps its copies. Delete it before trying the same card
again, otherwise the kiosk sees the clips as already copied.

To also test the **card reader detection** (virtual SD cards, needs sudo), see
"More testing" below.

## How it works

1. **Card inserted:** the kiosk notices it, mounts it read-only and copies all new clips
   (clips it has seen before are skipped, so inserting a card twice uploads nothing twice).
2. **Sessions:** clips are split wherever the pause between two clips is longer than
   `SESSION_GAP_MINUTES`.
3. **Naming:** the touchscreen shows each session with a preview picture; the coach taps
   its name and confirms with **Upload**. A second "Team" on the same day becomes `Team 2`.
   If nobody names them within `NAMING_TIMEOUT_MINUTES`, they are uploaded as
   `2026-10-20 - Session 1`, `- Session 2`, … (numbered across the whole day) and can be
   renamed in Hudl.
4. **Upload:** one session after the other, each as its own playlist, video type Practice,
   linked to the event `HUDL_EVENT`. Failed uploads are retried every 5 minutes; when the
   Hudl login has expired (every 14 days), the kiosk logs in again by itself.

Clips are kept on the archive drive as
`<archive>/2026-10-20_Team cam/2026-10-20 - Red Zone/C0001.MP4 …`.
Small marker files next to them: `.uploaded` (done), `.rejected` (Hudl refused the files),
`.naming` (waiting for names), `.hudl_name` (Hudl name with "/", e.g. `WR/DB 1v1`, which
can't be a folder name).

## Settings (top of `kiosk.py`)

- `GROUP_NAMES`: the name buttons on the touchscreen
- `HUDL_EVENT = "Preseason January 10"`: the Hudl schedule event every upload is linked to
  (Hudl requires one; it must exist in your team's schedule). Change it when the season's event changes.
- `SESSION_GAP_MINUTES = 5`: a pause longer than this between two clips starts a new session
  (see "Finding the right pause length")
- `NAMING_TIMEOUT_MINUTES = 30`: how long the touchscreen waits for names before uploading
- `READERS`: which card reader is which camera (USB port) and its LED pin
- `VIDEO_TYPE = "Practice"`
- `KEEP_DAYS_AFTER_UPLOAD = None`: clips are kept forever; set a number of days to delete them after upload

### Finding the right pause length

Copy the clips of a real practice **straight from the camera card** (Hudl downloads have
no recording times) into a folder and run:
```bash
python kiosk.py --show-gaps real_practice            # every clip + pause before it
python kiosk.py --show-gaps real_practice --gap 3    # try another value
```
Pick a value that is longer than the pauses inside a drill but shorter than the breaks
between drills. The time used is when the camera finished writing the clip.

## More testing

### Card reader detection with virtual SD cards (sudo)

`virtual_card.py` puts a card folder into a disk image and "inserts" it into virtual
reader 1 or 2. Linux treats it like a real card, so the kiosk runs exactly the same code
as on the Pi.

Terminal 1, the kiosk (`--allow-loop` accepts the virtual readers):
```bash
sudo -E env PATH="$PATH" PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright \
  python3 kiosk.py --archive ~/kiosk_full --allow-loop --gui
```
Terminal 2, the "coach":
```bash
sudo python3 virtual_card.py create teamcam --copy-card test_cards/teamcam
sudo python3 virtual_card.py insert teamcam --reader 2     # card goes in
sudo python3 virtual_card.py remove teamcam                # card comes out
sudo python3 virtual_card.py list
sudo python3 virtual_card.py delete teamcam
```
Add `--no-upload` to the kiosk command to test without Hudl. Without `--copy-card`,
`create` generates short test clips – fine for testing detection, but Hudl rejects them.

### Two cameras at once without sudo

```bash
python kiosk.py --card-dir test_cards/insiderun test_cards/teamcam --reader 1 2 \
  --archive ~/kiosk_test --no-upload --gui
```

### Uploading a single folder by hand

```bash
python hudl_upload.py upload some_folder --event "Preseason January 10" --name "2026-10-20 - Team"
python hudl_upload.py upload some_folder --dry-run      # only list the clips
```

## The Raspberry Pi kiosk

### Hardware

- Raspberry Pi 5 (4 GB), official 27 W USB-C power supply, Active Cooler or case with fan
- Raspberry Pi Touch Display 2 (5" or 7"), connected with the ribbon cable (DSI), set to
  landscape; the screen is drawn at 800x480 and scaled
- microSD card 32 GB for the system
- USB HDD for the clips, e.g. 1 TB 2.5" (powered over USB). One practice is about
  0.4 GB, so it holds years of practices.
- 2 USB card readers for the cameras' cards (label them "Inside Run" and "Team").
  The HDD goes in a blue USB 3 port, so one reader uses a black USB 2 port (fast enough).
- 3 LEDs (2 green, 1 blue) with 220 Ω resistors, 1 active 3.3 V buzzer
- Network: Wi-Fi works (a normal password, no login page in the browser); an Ethernet
  cable is more reliable if there is a socket

Wiring (BCM numbers, LED long leg → resistor → GPIO, short leg → GND):

| Part | GPIO | Pin |
|---|---|---|
| LED reader 1 (Inside Run) | 17 | 11 |
| LED reader 2 (Team) | 27 | 13 |
| Blue LED (upload) | 23 | 16 |
| Buzzer + | 24 | 18 |
| GND | - | 6, 9, 14… |

### Status lights

One green LED next to each reader:

| Light | Meaning |
|---|---|
| Blinking | Copying, **do not remove the card** |
| On | Done, remove the card (1 beep = new clips, 2 beeps = nothing new on it) |
| Fast blinking + long beep | Card could not be read |

Blue LED:

| Light | Meaning |
|---|---|
| Blinking | Uploading to Hudl |
| Fast blinking | Upload failed, retries every 5 minutes |

### Setup

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. Set user `pi`,
   Wi-Fi and SSH in the Imager settings. (Other user name → change paths in `kiosk.service`.)
2. Get the code: `git clone https://github.com/syrrex/Automated-training-video-upload.git ~/kiosk`
3. System packages: `sudo apt install ffmpeg`.
   Archive HDD: format it with the name `KIOSKHDD` (the kiosk never treats a drive with
   that name as an SD card) and mount it at `/mnt/archive`:
   ```bash
   lsblk                                       # find the HDD, e.g. /dev/sda
   sudo mkfs.ext4 -L KIOSKHDD /dev/sda1        # ERASES the HDD - check the name twice!
   sudo mkdir -p /mnt/archive
   echo 'LABEL=KIOSKHDD /mnt/archive ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
   sudo mount -a
   ```
   ext4 survives power cuts best, but Windows can't read it directly. If you want to
   plug the HDD into a Windows PC, use `sudo mkfs.exfat -L KIOSKHDD /dev/sda1` and
   `exfat` instead of `ext4` in the fstab line.
4. Install:
   ```bash
   python3 -m venv --system-site-packages ~/kiosk-venv   # system packages = gpiozero
   ~/kiosk-venv/bin/pip install -r ~/kiosk/requirements.txt
   sudo PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright ~/kiosk-venv/bin/playwright install --with-deps chromium
   ```
5. Tell the kiosk which reader is which: put a card in each reader, run
   ```bash
   sudo ~/kiosk-venv/bin/python ~/kiosk/kiosk.py --show-readers
   ```
   and copy each reader's port (or a unique part of it, e.g. `usb-0:1.1`) into
   `ports` in `READERS` in `kiosk.py`. Keep each reader in the same USB socket from then on.
6. Store the Hudl login of the **kiosk account** (a dedicated Hudl account with coach
   rights, from your team admin – so no personal account lives on the Pi):
   ```bash
   cd ~/kiosk && sudo PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright ~/kiosk-venv/bin/python hudl_upload.py set-login
   ```
7. Start it and enable it at boot:
   ```bash
   sudo cp ~/kiosk/kiosk.service /etc/systemd/system/
   sudo systemctl enable --now kiosk
   journalctl -u kiosk -f        # watch the log
   ```

## Known gaps

- **Not tested on a Raspberry Pi yet:** the touchscreen without a desktop
  (`SDL_VIDEODRIVER=kmsdrm` in `kiosk.service`), LEDs, real USB card readers and real
  camera cards. Everything else is tested on a PC (WSL), including uploads to Hudl.
- If the automatic Hudl login fails (password changed, captcha, security code), uploads
  stop (blue fast blinking), the kiosk retries once an hour and the log says
  "automatic Hudl login failed". Fix: run `set-login` again.
- If Hudl refuses a session's files as "invalid or corrupt", the session gets a `.rejected`
  marker and is skipped (see the log); upload those clips by hand.
- Uploads count as finished when the browser has sent nothing for 30 s. After the first
  real practices, check in Hudl that all clips arrived.
- The kiosk doesn't start without the HDD (`RequiresMountsFor` in `kiosk.service`), so
  clips never end up on the microSD card. If the HDD is unplugged while running, copying fails.
- If Hudl changes its website, the upload steps may break. The script names the step and
  saves a screenshot in `screenshots/`; re-record the steps with
  `playwright codegen --target python -o recorded_upload.py --load-storage=hudl_auth.json https://www.hudl.com/home`.
