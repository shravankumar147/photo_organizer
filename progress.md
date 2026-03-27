# Progress

## Current Status

- Branch: `main`
- Latest local commit: `e641667` `add rich photo pipeline wrapper`
- Latest remote commit: `e641667` `add rich photo pipeline wrapper`
- Test status: `python3 -m py_compile photo_pipeline.py` passing

## Progress Log

### 2026-03-27

- Added `photo_pipeline.py` as a Typer-based macOS workflow wrapper for ingest, backup, clean, and full pipeline runs.
- Made the wrapper use the current interpreter and repo-relative paths instead of a hardcoded checkout path and venv binary.
- Added NAS mount discovery so the wrapper can detect realistic mounted volume layouts before running the backup step.
- Added Rich-based terminal status/progress output for mount waits and pipeline step execution.
- Updated the NAS share configuration in `photo_pipeline.py` to use `Canon_EOS_M50`.
- Added `rich` to runtime dependencies in `requirements.txt` and `setup.py`.
- Ignored generated `run_logs/` artifacts in `.gitignore`.
- Pushed the wrapper and ignore updates to `origin/main`.

### 2026-03-21

- Initialized the repository and created a clean first commit for the installable CLI package.
- Added repository hygiene, test discovery config, and the test suite in a separate follow-up commit.
- Expanded media support and bucketed files into `images/`, `raw/`, and `videos/`.

### 2026-03-22

- Updated the default workflow to target `/Volumes/EOS_DIGITAL/DCIM/100CANON`.
- Defaulted the destination to `/Volumes/EOS_DIGITAL/DCIM/100CANON/organized`.
- Changed file handling from copy to move so the organizer acts as a cleanup pass.
- Added scanner protection to skip the nested `organized/` subtree during runs.
- Dropped duplicate files by content even when filenames differ within the same target bucket/date.
- Added post-run cleanup to remove empty source directories after files are organized.
- Switched the output layout to `YYYY/MM/DD/images|raw|videos/` for date-first browsing.
- Added total elapsed time to the run summary and returned stats.
- Tightened date extraction to prefer camera capture metadata before filesystem timestamps.
- Added guardrails to reject bogus epoch-style dates like `1970-01-01`.
- Added a `copy_media_for_cloud.py` helper to copy only image assets from the organized tree.
- Filtered hidden trash and AppleDouble files out of the cloud-copy set.
- Ran `copy_media_for_cloud.py` successfully and copied 61 image files into `cloud_ready/`.
- Added `ftp_upload.py` to upload cloud-ready images and move successful uploads into local FTP trash.
- Could not run the real FTP upload yet because `FTP_HOST`, `FTP_USER`, and `FTP_PASSWORD` are not set in the environment.
- Moved cloud copy and FTP upload logic into package modules and added a package workflow runner.
- Added `.env.example`, `config.yaml.example`, and uploader support for loading FTP settings from them.
- Live FTP testing reached the server successfully but `/backup` returned `550 Permission denied`.
- Fixed FTP host normalization for `ftp://...` values and hardened connection/error handling.
- Found the writable FTP location `/G/ftp_uploads` and successfully uploaded 61 files there, moving local uploaded copies into `ftp_trash/`.
- Added direct network-share backup for the full `organized/` tree to `/Volumes/tp-share/Canon EOS M50/DCIM`.
- Switched the main workflow to prefer network backup over FTP for primary backup.
- Network backup dry run against the mounted share reported `87` files to copy, `12` to skip, and `0` errors.
- Long-running transfer commands will be run manually in the terminal; progress tracking stays in this file.
- Added explicit scanner exclusions for managed output directories like `organized`, `cloud_ready`, and `ftp_trash`.
- Moved path management out of `.env` and into OmegaConf-backed YAML config files.
- Added `config.default.yaml` for the real camera-card workflow and `config.test.yaml` for local test media.
- Changed the CLI defaults so card runs use `config.default.yaml` unless `--config` is passed explicitly.
- Reduced `.env` to FTP secrets only; path values are no longer stored there.
- Added `photo_organizer/config.py` as the shared config loader and updated organize, network backup, cloud copy, FTP upload, and workflow commands to use it.
- Added `--config` support to the workflow runner so local test flows can be run with `config.test.yaml`.
- Updated docs and config examples to reflect the new split between card defaults, test config, and sensitive `.env` values.
- Reordered the packaged workflow to `organize -> cloud copy -> network backup`, with FTP documented as a fallback path when the mounted share is unavailable.
- Updated cloud copy so it includes both `images/` and `videos/`, while still excluding RAW files.
- Added an explicit `network_backup.py --prune-source` mode to move organized files into `network_backup_trash/` only after verified backup and then clean up empty directories.
- Updated empty-directory cleanup to ignore macOS junk files like `.DS_Store` and `._*`.
- Added per-run JSON manifests for organize, cloud copy, network backup, and FTP upload.
- Added `audit.folder` to config so each workflow command writes a structured run log with counts, timing, paths, and per-file outcomes.
- Added `run_all.py` as a one-command workflow entrypoint for organize, cloud copy, and network backup, with optional `--prune-source` and `--ftp-fallback`.
- Moved the cloud-copy destination to `/Users/shravan/Pictures` so cloud-ready media is easier to access outside the repo.

## Next Step

- For the real card workflow, either run `python -m photo_organizer`, `python copy_media_for_cloud.py`, and `python network_backup.py`, or use `python photo_pipeline.py all` on macOS once the NAS share is mounted correctly.
- For local testing, run the same commands with `--config config.test.yaml`, and use `python ftp_upload.py --config config.test.yaml` only as fallback when the mounted share is unavailable.
