# Progress

## Current Status

- Branch: `main`
- Latest local commit: working tree with ftp upload script
- Latest remote commit: `31f9bed` `bucket media files by type`
- Test status: `.venv/bin/pytest -q` passing (`40 passed`)

## Progress Log

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

## Next Step

- Push local commits to `origin/main`.
