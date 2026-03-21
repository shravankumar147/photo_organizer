# Progress

## Current Status

- Branch: `main`
- Latest local commit: `429041e` `move files into organized destination`
- Latest remote commit: `31f9bed` `bucket media files by type`
- Test status: `.venv/bin/pytest -q` passing (`26 passed`)

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

## Next Step

- Push local commits to `origin/main`.
