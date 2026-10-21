# Hudl Upload Kiosk

Two card readers,  one per camera. Insert the SD cards → clips are copied to the Pi
→ split into sessions wherever the pause between two clips is longer than 5 minutes
→ each session is uploaded to Hudl as its own upload (video type Practice, linked to
the Preseason event). Cards are only read, never changed.

Sessions are named `2026-10-20 - Session 1`, `- Session 2`, … and numbered across
the whole day: if the first card has Sessions 1–3, the second card continues with
Session 4. Coaches rename them in Hudl if needed (Skelly, Red Zone, …).

| File | What it does |
|---|---|
| `kiosk.py` | Detects cards, copies and groups clips, runs the upload queue |
| `hudl_upload.py` | Uploads one folder to Hudl (also usable by hand) |
| `status.py` | LEDs and buzzer |
| `kiosk.service` | Starts the kiosk when the Pi boots |
| `virtual_card.py` | Virtual SD cards for testing on a PC |

Clips are stored on a USB HDD as `/mnt/archive/2026-10-20_Team cam/2026-10-20 - Session 1/…`
(a second card from the same camera and day goes to `2026-10-20_Team cam_2/`).

## Finding the right pause length

`SESSION_GAP_MINUTES` (top of `kiosk.py`, default 5) decides where a new session starts.
To check it, copy the clips of a real practice into a folder and run:
```bash
python kiosk.py --show-gaps real_practice            # every clip + pause before it
python kiosk.py --show-gaps real_practice --gap 3    # try another value
```
Pick a value that is longer than the pauses inside a drill but shorter than the
breaks between drills.

## Status lights

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

## Hardware

- Raspberry Pi 5 (4 GB), official 27 W USB-C power supply, Active Cooler or case with fan
- microSD card 32 GB for the system
- USB HDD for the clips, e.g. 1 TB 2.5" (powered over USB). One practice is about
  0.4 GB, so it holds years of practices. Clips are kept forever.
- 2 USB card readers for the cameras' cards (label them "Inside Run" and "Team").
  The HDD goes in a blue USB 3 port, so one reader uses a black USB 2 port (fast enough).
- 3 LEDs (2 green, 1 blue) with 220 Ω resistors, 1 active 3.3 V buzzer
- Network: Wi-Fi works; an Ethernet cable is more reliable if there is a socket

Wiring (BCM numbers, LED long leg → resistor → GPIO, short leg → GND):

| Part | GPIO | Pin |
|---|---|---|
| LED reader 1 (Inside Run) | 17 | 11 |
| LED reader 2 (Team) | 27 | 13 |
| Blue LED (upload) | 23 | 16 |
| Buzzer + | 24 | 18 |
| GND | - | 6, 9, 14… |

## Pi setup

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. Set user `pi`,
   Wi-Fi and SSH in the Imager settings. (Other user name → change paths in `kiosk.service`.)
2. Copy this folder to the Pi as `/home/pi/kiosk` (e.g. `git clone` from GitHub).
3. Archive HDD: format it with the name `KIOSKHDD` (the kiosk never treats a drive with
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
   rights, from your team admin). The password is typed hidden and the test login runs
   right away:
   ```bash
   cd ~/kiosk && sudo PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright ~/kiosk-venv/bin/python hudl_upload.py set-login
   ```
   It is stored in `hudl_credentials.json` (readable only by root). Whenever the Hudl
   login expires (every 14 days), the kiosk logs in again by itself.
7. Start it and enable it at boot:
   ```bash
   sudo cp ~/kiosk/kiosk.service /etc/systemd/system/
   sudo systemctl enable --now kiosk
   journalctl -u kiosk -f        # watch the log
   ```

## Testing without a Pi or card reader (WSL / Linux)

`virtual_card.py` makes virtual SD cards (disk images with test clips). Linux sees an
"inserted" one like a real card, so the kiosk runs exactly the same code as on the Pi.
Only the LEDs are printed as `[STATUS]` lines instead.

Terminal 1, the kiosk:
```bash
sudo -E env PATH="$PATH" python3 kiosk.py --archive ~/kiosk_test --allow-loop --no-upload
```
Terminal 2, the "coach":
```bash
sudo python3 virtual_card.py create insiderun --date 2026-10-20 --sessions 1 --clips 2 --clips-from test_clips
sudo python3 virtual_card.py create teamcam --date 2026-10-20 --sessions 3 --clips 1 --clips-from test_clips --skip 2
sudo python3 virtual_card.py insert insiderun --reader 1   # -> Session 1
sudo python3 virtual_card.py insert teamcam --reader 2     # -> Session 2, 3, 4
sudo python3 virtual_card.py remove insiderun
sudo python3 virtual_card.py remove teamcam
```
`--clips-from` puts real football clips on the virtual card (Hudl may reject generated
test clips); without it, short test clips are generated. Drop `--no-upload` to also
upload to Hudl (this creates real uploads, delete them afterwards).

Quick test without sudo (a folder instead of a card):
```bash
python kiosk.py --card-dir test_clips --archive ~/kiosk_test --no-upload
```

## Settings (top of `kiosk.py`)

- `READERS`: which reader is which camera (USB port) and its LED pin
- `SESSION_GAP_MINUTES = 5`: a pause longer than this between two clips starts a new session
  (see "Finding the right pause length").
  The time used is when the camera finished writing the clip, so this works for short clips.
- `KEEP_DAYS_AFTER_UPLOAD = None`: clips are kept forever; set a number of days to delete them after upload
- `VIDEO_TYPE = "Practice"`
- `HUDL_EVENT = "Preseason January 10"`: the scheduled event every upload is linked to
  (Hudl requires one). Change it when the season's event changes.

## Known gaps

- The Hudl login expires every 14 days; the kiosk then logs in again by itself with
  `hudl_credentials.json`. If that fails (password changed, captcha, security code), uploads
  stop (blue fast blinking), the kiosk retries once an hour, and the log says
  "automatic Hudl login failed". Fix: run `set-login` again, or log in by hand with `login`.
- If Hudl refuses a session's files as "invalid or corrupt", the session gets a `.rejected`
  marker and is skipped (see the log); upload those clips by hand.
- Tested: Wi-Fi outage before and during an upload (detected, retried), kiosk killed in the
  middle of an upload (restarts and uploads again).
- Uploads are counted as finished when the page has had no upload traffic for 30 s.
  Check in Hudl after the first real practice that all clips arrived.
- The kiosk doesn't start without the HDD (`RequiresMountsFor` in `kiosk.service`), so
  clips never end up on the microSD card. If the HDD is unplugged while running, copying fails.
