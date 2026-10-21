---
tags:
  - context/personal
date: 2026-10-05
---
# Project Overview

## Goal
Create a upload Kiosk where choaches or helpers can simply insert Micro-SD cards and the station automatically detect the SD-card,
splits the practice into periods and then uploads it as its own playlist to HUDL.

## Gemini - Brainstroming result

### 1. Project Overview & Architecture

The Sports Footage Ingestion Kiosk is a self-service appliance designed to automate practice video management for sports
clubs. It eliminates the single-point-of-failure volunteer model by allowing coaches to offload raw camera SD cards into
dedicated, illuminated slots. The station automatically scans, groups, archives, and uploads footage to Hudl without
requiring manual file management or computer expertise.
  

```
                  +-----------------------------------+
                  |      PHYSICAL KIOSK STATION       |
                  |  (Pi 4/5 + 7" Screen + M.2 SSD)   |
                  +-----------------+-----------------+
                                    |
            +-----------------------+-----------------------+
            |                       |                       |
            v                       v                       v
     +--------------+        +--------------+        +--------------+
     |   SLOT A     |        |   SLOT B     |        |   SLOT C     |
     |  (Red LED)   |        |  (Blue LED)  |        | (Green LED)  |
     +--------------+        +--------------+        +--------------+
            |                       |                       |
            +-----------------------+-----------------------+
                                    |
                                    v
                  +-----------------------------------+
                  |       DECOUPLED LINUX CORE        |
                  |  (udev / systemd / SQLite WAL)    |
                  +-----------------+-----------------+
                                    |
            +-----------------------+-----------------------+
            |                       |                       |
            v                       v                       v
  +------------------+    +-------------------+   +--------------------+
  |    PyQt6 GUI     |    |  Copy Worker      |   | Upload Daemon      |
  |  (Touch Interface)    |  (1D K-Means/NVMe)|   | (Playwright/Hudl)  |
  +------------------+    +-------------------+   +--------------------+
```

#### System Component Breakdown

```
+-----------------------------------------------------------------------+
|                         PHYSICAL HARDWARE                             |
|  • Raspberry Pi 4/5 (4GB+ RAM)                                       |
|  • Official 7-inch Touchscreen Display (1024x600 resolution)          |
|  • M.2 NVMe SSD via PCIe/USB 3.0 Hat (Local Storage Archive)          |
|  • 3x Color-Coded Push-Push MicroSD Card Readers (Red, Blue, Green)   |
|  • 3x Addressable RGB Status Rings / GPIO LEDs                        |
|  • Custom 3D-Printed Slanted Desk/Wall Enclosure                      |
+-----------------------------------------------------------------------+
                                    │
                                    ▼
+-----------------------------------------------------------------------+
|                         OS & LINUX CORE SERVICE                       |
|  • Raspberry Pi OS (64-bit) / Pop!_OS Staging Host                    |
|  • Kernel udev rules (/etc/udev/rules.d/99-kiosk-slots.rules)         |
|  • Systemd service templates (kiosk-ingest@.service)                  |
|  • File system auto-mounter (udisks2)                                 |
+-----------------------------------------------------------------------+
                                    │
                                    ▼
+-----------------------------------------------------------------------+
|                     DECOUPLED SOFTWARE PROCESSES                      |
|  1. GUI Application (PyQt6 / PySide6 Kiosk View)                      |
|  2. Ingest Worker (Triggered per SD card by udev)                     |
|  3. Copy & Clustering Worker (Short-lived subprocess)                |
|  4. Upload Daemon (Persistent systemd service + Playwright)           |
|  5. Verification Worker (+8h automated DOM checker)                   |
|  6. Archive Daemon (30-day compression background worker)             |
+-----------------------------------------------------------------------+
```

### 2. Software Architecture & Process Isolation

To prevent UI freezes and ensure system recovery if an unhandled error occurs, software processes are decoupled using
**SQLite WAL Mode** as the single source of truth.

  

```
                                  +-----------------------+
                                  |   udev / systemd      |
                                  +-----------+-----------+
                                              |
                                              | Hardware Insertion
                                              v
                                  +-----------------------+
                                  |   ingest_worker.py    |
                                  |  • Reads fingerprint  |
                                  |  • Mounts filesystem  |
                                  +-----------+-----------+
                                              |
                                              | Writes 'AWAITING_CONFIRMATION'
                                              v
+-----------------------+         +-----------------------+         +-----------------------+
|     GUI PROCESS       | <====== |  SQLite (station.db)  | ======> |   UPLOAD WORKER DAEMON|
|    (main_gui.py)      |  Syncs  |   WAL Mode Enabled    |  Pulls  |  (hudl_uploader.py)   |
|  • Print Queue Table  |  State  +-----------+-----------+  Jobs   |  • Single Headless    |
|  • Color Slot Tabs    |                     ^                     |    Playwright Session |
|  • User Override      |                     | Writes Progress     |  • Retry Logic        |
+-----------+-----------+                     | & Local Paths       +-----------------------+
            |                                 |                             │
            | Updates status to 'QUEUED_COPY' |                             │ +8 Hours
            +─────────────────────────────────+                             ▼
                                              ^                     +-----------------------+
                                              | Reads 'QUEUED_COPY' |  VERIFICATION WORKER  |
                                              v                     | (verify_hudl_dom.py)  |
                                  +-----------------------+         | • Checks Playlist DOM |
                                  |  COPY WORKER DAEMON   |         +-----------------------+
                                  |   (copy_worker.py)    |
                                  |  • 1D K-Means Split   |
                                  |  • NVMe Fast Copy     |
                                  |  • Auto-Wipe Card     |
                                  +-----------------------+
```

#### Module Responsibilities

1. **`ingest_worker.py` (CLI Triggered by udev):** Executes when a card is inserted. Calculates a $<200\text{ ms}$ fast fingerprint, checks for duplicates, mounts the device, inserts an `AWAITING_CONFIRMATION` record in SQLite, and emits a UDP signal to the GUI.
2. **`main_gui.py` (Persistent Touch Interface):** Displays a global job queue table and opens color-coded tabs for active slots. Allows coaches to adjust period counts and tap "CONFIRM".
3. **`copy_worker.py` (On-Demand Subprocess):** Runs 1D K-Means clustering to separate practice periods, ignores test clips under 5 seconds, copies files to the NVMe SSD, generates a JSON manifest, and formats the SD card.
4. **`hudl_uploader.py` (Persistent Systemd Daemon):** Polls SQLite for `READY_TO_UPLOAD` jobs, executes Playwright headless browser automation, creates playlists, uploads footage, and schedules a verification check for $+8\text{ hours}$.
5. **`verify_hudl_dom.py` (+8h Verification Task):** Logs into Hudl using Playwright, navigates to the team library, verifies clip counts against the manifest, and updates SQLite.
6. **`archive_daemon.py` (Background Service):** Compresses files older than 30 days into ZIP archives, updates database paths, and reclaims SSD storage.

### 3. Two-Phase Development & Staging Strategy

The project is structured into two development phases, allowing core software validation on an existing Pop!_OS laptop with minimal cost before purchasing specialized hardware.

  

```
+---------------------------------------------------------------------------+
| PHASE 1: PRE-HARDWARE LAPTOP STAGING (Pop!_OS Host)                      |
|                                                                           |
|  • Single MicroSD-to-USB Adapter (~€5)                                    |
|  • Laptop Screen simulates 7" Touchscreen Display                         |
|  • Laptop SSD simulates M.2 Local Archive Storage                         |
|  • Terminal Logs simulate physical LED status indicators                  |
|  • Port Mapping via custom /etc/udev/rules.d/ mappings                   |
|                                                                           |
|  [ Validate Core Logic ] ──► [ Test Field Practices ] ──► [ Lock Schema ]  |
+---------------------------------------------------------------------------+
                                     │
                                     ▼
+---------------------------------------------------------------------------+
| PHASE 2: HARDWARE FABRICATION & ASSEMBLY (Raspberry Pi Station)           |
|                                                                           |
|  • Install Pi 4/5, NVMe Hat, and 7" Display in CAD Shell                  |
|  • Wire 3x Push-Push MicroSD slots to dedicated internal USB channels     |
|  • Wire RGB Status Rings to Pi GPIO pins                                  |
|  • Deploy systemd units & configure read-only boot partition              |
+---------------------------------------------------------------------------+
```

#### Development Phase Matrix

|**Aspect**|**Phase 1: Laptop Staging Area**|**Phase 2: Finished Pi Hardware**|
|---|---|---|
|**Host System**|Pop!_OS / Ubuntu Laptop|Raspberry Pi OS (64-bit)|
|**Card Readers**|1x USB MicroSD Adapter (Moved between ports)|3x Panel-Mount Push-Push Readers|
|**Port Alias Mapping**|`/etc/udev/rules.d/` aliasing physical USB paths|Fixed internal USB hub bus routing|
|**UI Display**|$1024 \times 600$ windowed GUI on Laptop|7" Touchscreen Display (Kiosk Mode)|
|**Status Feedback**|Terminal logs & UI badges|Addressable RGB LED Rings via GPIO|
|**Storage Target**|`/home/user/station_archive/`|`/mnt/nvme/station_archive/`|

### 4. Configuration & Database Schema

#### Station Configuration (`/etc/kiosk/station_config.json`)

JSON

```
{
  "station": {
    "id": "GRAZ_STATION_01",
    "storage_archive_path": "/mnt/nvme/station_archive",
    "temp_staging_path": "/tmp/kiosk_staging",
    "db_path": "/mnt/nvme/station_archive/station.db"
  },
  "clustering": {
    "min_clip_duration_seconds": 5.0,
    "default_period_count": 4,
    "max_kmeans_iterations": 300
  },
  "hudl": {
    "auth_state_path": "/etc/kiosk/hudl_auth.json",
    "max_concurrent_uploads": 1,
    "retry_attempts": 5,
    "verification_delay_hours": 8
  },
  "archiving": {
    "retention_days": 30,
    "auto_zip_enabled": true
  }
}
```

#### Database Schema (`schema.sql`)

SQL

```
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. JOBS TABLE: Core ingestion lifecycle
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id TEXT NOT NULL CHECK(slot_id IN ('RED', 'BLUE', 'GREEN')),
    dev_path TEXT NOT NULL,
    mount_path TEXT,
    status TEXT NOT NULL DEFAULT 'AWAITING_CONFIRMATION' CHECK(status IN (
        'AWAITING_CONFIRMATION', 'QUEUED_COPY', 'COPYING',
        'READY_TO_EJECT', 'READY_TO_UPLOAD', 'UPLOADING',
        'UPLOADED_VERIFYING', 'COMPLETED', 'ARCHIVED', 'FAILED'
    )),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. UPLOAD JOBS TABLE: Individual upload task queues
CREATE TABLE IF NOT EXISTS upload_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    period_number INTEGER NOT NULL,
    playlist_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN (
        'QUEUED', 'UPLOADING', 'UPLOADED', 'VERIFYING', 'VERIFIED', 'RETRY_QUEUED', 'FAILED'
    )),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    error_log TEXT,
    verify_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- 3. FILES TABLE: Metadata for every recorded clip
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    upload_job_id INTEGER,
    file_name TEXT NOT NULL,
    local_path TEXT NOT NULL,
    fast_fingerprint TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    duration_seconds REAL DEFAULT 0.0,
    period_number INTEGER DEFAULT 1,
    is_archived BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (upload_job_id) REFERENCES upload_jobs(id) ON DELETE SET NULL
);

-- 4. ARCHIVES TABLE: 30-day compressed storage metadata
CREATE TABLE IF NOT EXISTS archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    archive_zip_path TEXT NOT NULL,
    archive_size_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_fingerprint ON files(fast_fingerprint);
CREATE INDEX IF NOT EXISTS idx_files_job ON files(job_id);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_status ON upload_jobs(status);
```

### 5. End-to-End Operational Workflow

```
[ Coach Inserts SD Card into Slot A ]
                   │
                   ▼
  [ udev Trigger: kiosk-ingest@red.service ]
  • Generates 128KB sparse fingerprint (<200ms)
  • Queries SQLite for matching fingerprint
  • Status set to 'AWAITING_CONFIRMATION'
                   │
                   ▼
  [ Kiosk Screen Opens RED Slot Tab ]
  • LED turns Pulsing Yellow
  • Displays auto-detected Period Count (e.g., 4)
  • Coach adjusts if needed and taps "CONFIRM"
                   │
                   ▼
  [ Copy Worker Subprocess Launched ]
  • Copies MP4s to NVMe (/mnt/nvme/station_archive/)
  • Runs 1D K-Means clustering algorithm
  • Safe-unmounts and formats SD Card
  • Status updated to 'READY_TO_EJECT'
  • LED turns Solid Green (Card can stay inserted)
                   │
                   ▼
  [ Upload Daemon Polls SQLite ]
  • Claims 'READY_TO_UPLOAD' job
  • Launches headless Playwright session
  • Logins to Hudl, selects files, inputs playlist title
  • Completes upload; updates status to 'UPLOADED_VERIFYING'
  • Schedules verify_at timestamp (+8 hours)
                   │
                   ▼
  [ +8 Hours Later: Verification Worker ]
  • Playwright inspects Hudl library DOM
  • Validates playlist presence and clip counts
  • Status updated to 'COMPLETED'
                   │
                   ▼
  [ +30 Days Later: Archive Daemon ]
  • Compresses video files into job_XXX.zip
  • Updates local_path in database; deletes raw MP4s
```

### 6. User Interface Design

The UI runs in full-screen kiosk mode using PyQt6/PySide6. It features a persistent **Printer-Queue Main Table** alongside **Dynamic Color-Coded Slot Tabs** that appear when human input is required.

#### View 1: Main Printer-Style Job Queue (`ALL JOBS`)

The default screen provides visibility into system history, active transfers, and upload statuses across all slots.
```
+-----------------------------------------------------------------------------------+
|  [ 🖨️ ALL JOBS QUEUE ]  │  [ 🔴 RED SLOT (ACTIVE) ]  │                            |
+-----------------------------------------------------------------------------------+
| JOB ID │ SLOT  │ CREATED          │ LAST UPDATED     │ STATUS          │ ACTION   |
+--------┼───────┼──────────────────┼──────────────────┼─────────────────┼──────────+
| #104   | RED   | 2026-10-05 11:15 | 2026-10-05 11:15 | ⚠️ CONFIRMATION | [OPEN]   |
| #103   | BLUE  | 2026-10-05 10:30 | 2026-10-05 10:32 | 📤 UPLOADING    | [DETAILS]|
| #102   | GREEN | 2026-10-05 09:00 | 2026-10-05 17:00 | ✅ VERIFIED     | [DETAILS]|
| #098   | RED   | 2026-09-02 18:00 | 2026-10-02 00:00 | 📦 ARCHIVED     | [DETAILS]|
+-----------------------------------------------------------------------------------+
| SYSTEM STATUS: ONLINE │ STORAGE: 412 GB FREE │ HUDL: CONNECTED                    |
+-----------------------------------------------------------------------------------+
```

#### View 2: Active Slot Tab (`RED SLOT`)

When an SD card is inserted into the Red Slot, a red tab opens automatically. The coach confirms or adjusts the practice period count before tapping the confirmation button.

  

```
+-----------------------------------------------------------------------------------+
|  [ 🖨️ ALL JOBS QUEUE ]  │  [ 🔴 RED SLOT - CARD DETECTED ]                        |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|   SD CARD DETECTED: 28.4 GB (32 Clips Found)                                     |
|   FAST FINGERPRINT: OK (No prior duplicate detected)                              |
|                                                                                   |
|   AUTO-DETECTED PRACTICE PERIODS:                                                 |
|                                                                                   |
|   [ - ]   PERIOD COUNT:  [ 4 ]   [ + ]                                            |
|                                                                                   |
|   Period 1: 8 Clips (Warmup & Drills)                                             |
|   Period 2: 10 Clips (Offense Set)                                                |
|   Period 3: 8 Clips (Defense Set)                                                 |
|   Period 4: 6 Clips (Scrimmage)                                                   |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |                  [  CONFIRM & START INGEST  ]                             |   |
|   +---------------------------------------------------------------------------+   |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

#### Tab Lifecycle Rules

- **Tab Creation:** Opens automatically when `ingest_worker.py` sets status to `AWAITING_CONFIRMATION`.
- **Tab Auto-Closure:** Closes automatically once the copy process completes and the card is formatted (`READY_TO_EJECT`), returning the display to the main job queue table.
- **Manual Access:** Tapping any row in the main table opens a read-only detail view for that job.

### 7. Fast Fingerprinting & Deduplication Implementation

To meet the $<10\text{-second}$ interaction budget, file deduplication uses a sparse header/trailer sampling hash that executes in $<200\text{ ms}$ for a full SD card.

Python

```
import hashlib
import os

def generate_fast_fingerprint(file_path: str) -> str:
    """
    Generates a fingerprint for a large video file in < 10ms.
    Reads file size, timestamp, and samples 64KB from header and trailer.
    """
    stat = os.stat(file_path)
    file_size = stat.st_size
    creation_time = stat.st_mtime
    
    hasher = hashlib.md5()
    hasher.update(f"{file_size}_{creation_time}".encode('utf-8'))
    
    with open(file_path, 'rb') as f:
        # Read first 64KB (MP4 header/metadata atom)
        hasher.update(f.read(65536))
        # Read last 64KB (MP4 index/moov atom)
        if file_size > 131072:
            f.seek(-65536, os.SEEK_END)
            hasher.update(f.read(65536))
            
    return hasher.hexdigest()
```

### 8. Summary of Development Next Steps

1. **Implement `db_manager.py`:** Create the SQLite wrapper with WAL mode enabled and initialize `schema.sql`.
2. **Build `ingest_worker.py`:** Write the CLI script that handles fast fingerprinting and database job creation.
3. **Set Up Laptop `udev` Rules:** Map physical laptop USB ports to static aliases (`/dev/slot_red`, `/dev/slot_blue`).
4. **Develop PyQt6 Kiosk UI:** Build the main table view and dynamic color-coded slot tabs.
5. **Construct `hudl_uploader.py`:** Implement Playwright browser automation for uploading playlists and checking DOM status.
6. **Field Test at Practice:** Validate software workflows on the Pop!_OS staging laptop before assembling the final Raspberry Pi enclosure.

