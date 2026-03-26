# photo-organizer

> EXIF-aware photo organiser CLI — core engine for a future macOS SwiftUI app.

Recursively scans a source directory, extracts the best available date for each
image, and copies it into a clean `YYYY/MM/DD/` hierarchy at the destination.

---

## Quick start

```bash
# 1. Clone / unzip the project
cd photo-organizer

# 2. Create a virtualenv (Python 3.10+)
python3 -m venv .venv && source .venv/bin/activate

# 3. Install
pip install -r requirements.txt          # runtime
pip install pytest pytest-cov            # testing (optional)

# 4. Run against the card defaults from config.default.yaml
python -m photo_organizer

# Run locally against test media from config.test.yaml
python -m photo_organizer --config config.test.yaml

# Dry run (no files moved)
python -m photo_organizer --config config.test.yaml --dry-run

# Verbose (DEBUG logs)
python -m photo_organizer --config config.test.yaml --verbose
```

Or install as a CLI tool:

```bash
pip install -e .
photo-organizer
```

---

## CLI reference

| Flag | Required | Default | Description |
|---|---|---|---|
| `--src PATH` |  | from config | Source directory (scanned recursively) |
| `--dst PATH` |  | from config | Destination root (`YYYY/MM/DD/` created here) |
| `--dry-run` | | false | Simulate; no files are written |
| `--verbose` | | false | DEBUG-level logging |
| `--config PATH` | | `config.default.yaml` | Alternate config file such as `config.test.yaml` |

## Configuration

Paths live in YAML config files, not in `.env`.

- `config.default.yaml`: card / production defaults
- `config.test.yaml`: local test media defaults
- `.env`: sensitive FTP credentials only
- `audit.folder`: where JSON run manifests are written

Typical usage:

```bash
# Card
python -m photo_organizer
python copy_media_for_cloud.py
python network_backup.py
python network_backup.py --prune-source
# Fallback only when the mounted share is unavailable
python ftp_upload.py

# Local test media
python -m photo_organizer --config config.test.yaml
python copy_media_for_cloud.py --config config.test.yaml
python network_backup.py --config config.test.yaml
python network_backup.py --config config.test.yaml --prune-source
# Fallback only when the mounted share is unavailable
python ftp_upload.py --config config.test.yaml
```

One-command workflow:

```bash
python run_all.py --config config.test.yaml
python run_all.py --config config.test.yaml --prune-source
python run_all.py --config config.test.yaml --prune-source --ftp-fallback
```

`run_all.py` runs:

1. organize
2. cloud copy
3. network backup

If `--ftp-fallback` is passed, FTP upload runs only when the network backup step fails.

Recommended order:

1. `python -m photo_organizer --config config.test.yaml`
2. `python copy_media_for_cloud.py --config config.test.yaml`
3. `python network_backup.py --config config.test.yaml`
4. `python ftp_upload.py --config config.test.yaml` only if the network backup path is unavailable

`copy_media_for_cloud.py` copies cloud-friendly `images/` and `videos/`. It excludes RAW files.

`network_backup.py` and `ftp_upload.py` back up from `organized/`. FTP moves successfully uploaded files into `ftp_trash/`.

`network_backup.py` is non-destructive by default. If you want the mounted share to become the source of truth after a verified backup, run `network_backup.py --prune-source`. That moves source files into a local `network_backup_trash/` directory only after matching destination content is confirmed, then removes empty source directories. This gives you a short retention window before permanent deletion.

---

## Output example

```
11:05:47  INFO   Processing: /Volumes/SD/DCIM/100APPLE/IMG_0042.jpg
11:05:47  INFO     Date   : 2024-07-04  [source: exif_original]
11:05:47  INFO     Target : ~/Pictures/Organised/2024/07/04/IMG_0042.jpg
11:05:47  INFO     [ok]   Copied → ~/Pictures/Organised/2024/07/04/IMG_0042.jpg

──────────────────────────────────────────
  Photo Organizer — Run Summary
──────────────────────────────────────────
  Total files scanned : 312
  ✓ Processed         : 309
  ⊘ Skipped           : 2
  ✗ Errors            : 1
──────────────────────────────────────────
```

---

## Architecture

```
photo_organizer/
├── __init__.py        version constant
├── __main__.py        `python -m photo_organizer` entry point
├── cli.py             argparse — thin, no business logic
├── scanner.py         recursive file discovery (generator)
├── metadata.py        EXIF + fallback date extraction
├── organizer.py       destination resolution, copy, dedup
├── utils.py           logging config, summary printer
└── main.py            OrganizeRequest DTO + run() pipeline
```

### Data flow

```
CLI args
  └─► OrganizeRequest (main.py)
        └─► Scanner.scan()            yields Path objects
              └─► Organizer.process()
                    └─► MetadataExtractor.extract()   returns ImageMetadata
                          └─► PIL EXIF → birthtime → mtime
                    └─► _destination_dir()            YYYY/MM/DD
                    └─► _resolve_destination()        collision handling
                    └─► shutil.copy2()                preserves timestamps
```

### Date extraction priority

1. **EXIF DateTimeOriginal** — camera-set timestamp (most accurate)
2. **EXIF DateTime** — file-written timestamp
3. **`st_birthtime`** — macOS file creation time
4. **`st_mtime`** — modification time (last resort)

### Duplicate handling

Files with the same name at the destination:
- **Identical content** (SHA-256 match) → skipped silently
- **Different content** → renamed `photo_1.jpg`, `photo_2.jpg`, …

---

## Running tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=photo_organizer --cov-report=term-missing
```

---

## Extensibility hooks (future AI pipeline)

### 1 — Semantic metadata (`metadata.py`)

`ImageMetadata` is designed to grow:

```python
@dataclass
class ImageMetadata:
    path: Path
    date: datetime
    date_source: str
    # ── Future AI fields ───────────────────────
    embedding: list[float] | None = None   # CLIP
    caption: str | None = None             # LLaVA / GPT-4V
    cluster_id: int | None = None          # k-means / HDBSCAN
    scene_tags: list[str] = field(...)     # zero-shot CLIP labels
```

`MetadataExtractor.extract()` is the single place to call every enrichment
step — the organizer stays unaware of AI.

### 2 — Event-based grouping (`organizer.py`)

Override one method to change the folder logic entirely:

```python
class EventOrganizer(Organizer):
    def _destination_dir(self, meta: ImageMetadata) -> Path:
        event_id = self._cluster_client.label(meta.embedding)
        return self.config.dst / f"event_{event_id:03d}"
```

### 3 — FastAPI wrapper (`main.py`)

`OrganizeRequest` is already a plain dataclass — map it directly from a
Pydantic model:

```python
# api.py (future)
from fastapi import FastAPI
from pydantic import BaseModel
from photo_organizer.main import OrganizeRequest, run

app = FastAPI()

class OrganizeBody(BaseModel):
    src: str
    dst: str
    dry_run: bool = False

@app.post("/organize")
async def organize(body: OrganizeBody):
    req = OrganizeRequest(src=Path(body.src), dst=Path(body.dst),
                          dry_run=body.dry_run)
    return run(req)   # ← zero changes to the core engine
```

---

## Supported formats

| Extension | Notes |
|---|---|
| `.jpg` / `.jpeg` | Full EXIF support via Pillow |
| `.png` | EXIF in PNG chunks (Pillow) |
| `.heic` | Requires `pillow-heif` system lib on macOS |

---

## Dependencies

| Package | Purpose |
|---|---|
| `Pillow` | EXIF parsing (no pixel decode) |
| `pytest` | Testing (dev only) |

Optional (not installed by default):

| Package | Purpose |
|---|---|
| `tqdm` | Progress bars |
| `pyyaml` | YAML config file |
| `fastapi` + `uvicorn` | REST API wrapper |
| `torch` + `openai-clip` | CLIP embeddings |
