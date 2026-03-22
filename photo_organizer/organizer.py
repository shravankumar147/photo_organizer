"""
organizer.py — folder creation and file-copy layer.

Responsibilities:
  * Decide the destination path for each media file
  * Sort into date folders before images/raw/videos buckets
  * Handle duplicates by appending a numeric suffix
  * Move files (or simulate in dry-run mode)
  * Hash files for deduplication (bonus feature)

Extension hook (event-based grouping):
  The `_destination_dir()` method is the *only* place that maps an image to a
  folder.  To group by "event" instead of calendar date, subclass Organizer and
  override that single method — the copy/dedup/logging machinery stays intact.

      class EventOrganizer(Organizer):
          def _destination_dir(self, meta: ImageMetadata) -> Path:
              event_id = self._cluster_client.label(meta.embedding)
              return self.config.dst / f"event_{event_id}"
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from photo_organizer.metadata import ImageMetadata, MetadataExtractor
from photo_organizer.scanner import media_bucket_for_path

log = logging.getLogger(__name__)

ProcessResult = Literal["processed", "skipped", "errors"]

# Buffer size for file hashing (4 MiB)
_HASH_CHUNK = 4 * 1024 * 1024


@dataclass
class OrganizerConfig:
    dst: Path
    dry_run: bool = False
    hash_duplicates: bool = True  # SHA-256 check before move


class Organizer:
    """
    Moves each file into its date-first destination folder.

    Single public method: `process(path) -> ProcessResult`
    """

    def __init__(self, config: OrganizerConfig) -> None:
        self.config = config
        self._extractor = MetadataExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, src_path: Path) -> ProcessResult:
        """Extract metadata, decide destination, move file."""
        log.info("Processing: %s", src_path)

        meta = self._extractor.extract(src_path)
        if meta is None:
            log.error("Skipping (no date): %s", src_path)
            return "errors"

        bucket = media_bucket_for_path(src_path)
        if bucket is None:
            log.error("Skipping (unsupported type): %s", src_path)
            return "errors"

        log.info("  Bucket : %s", bucket)
        log.info("  Date   : %s  [source: %s]", meta.date.date(), meta.date_source)

        dst_dir = self._destination_dir(meta, bucket)
        dst_path = self._resolve_destination(src_path, dst_dir)

        log.info("  Target : %s", dst_path)

        if self.config.dry_run:
            log.info("  [dry-run] Would move → %s", dst_path)
            return "processed"

        return self._move(src_path, dst_dir, dst_path)

    # ------------------------------------------------------------------
    # Destination resolution
    # ------------------------------------------------------------------

    def _destination_dir(self, meta: ImageMetadata, bucket: str) -> Path:
        """
        Map a file to its target directory.

        Override this in a subclass to implement event-based, AI-driven, or
        any other grouping strategy.
        """
        d = meta.date
        return (
            self.config.dst
            / f"{d.year:04d}"
            / f"{d.month:02d}"
            / f"{d.day:02d}"
            / bucket
        )

    def _resolve_destination(self, src: Path, dst_dir: Path) -> Path:
        """
        Return a collision-free destination path.

        Strategy: <name>.<ext> → <name>_1.<ext> → <name>_2.<ext> → …
        If hash_duplicates is enabled and matching content already exists
        anywhere in the target directory, we skip the file entirely.
        """
        if self.config.hash_duplicates:
            duplicate = self._find_duplicate_in_dir(src, dst_dir)
            if duplicate is not None:
                log.info("  [skip] Identical file already exists: %s", duplicate)
                return duplicate

        stem = src.stem
        suffix = src.suffix
        candidate = dst_dir / src.name
        counter = 0

        while candidate.exists():
            counter += 1
            candidate = dst_dir / f"{stem}_{counter}{suffix}"

        return candidate

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _move(self, src: Path, dst_dir: Path, dst: Path) -> ProcessResult:
        # Check whether resolve decided this is a true duplicate
        if dst.exists() and self.config.hash_duplicates and self._same_content(src, dst):
            try:
                src.unlink()
            except OSError as exc:
                log.error("  [error] Failed to remove duplicate %s: %s", src, exc)
                return "errors"
            log.info("  [skip] Duplicate content already organised; removed source.")
            return "skipped"

        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            log.info("  [ok] Moved → %s", dst)
            return "processed"
        except OSError as exc:
            log.error("  [error] Failed to move %s → %s: %s", src, dst, exc)
            return "errors"

    # ------------------------------------------------------------------
    # Hashing (bonus deduplication)
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(_HASH_CHUNK):
                h.update(chunk)
        return h.hexdigest()

    def _same_content(self, a: Path, b: Path) -> bool:
        try:
            # Quick size check first — avoids hashing when sizes differ
            if a.stat().st_size != b.stat().st_size:
                return False
            return self._sha256(a) == self._sha256(b)
        except OSError:
            return False

    def _find_duplicate_in_dir(self, src: Path, dst_dir: Path) -> Path | None:
        try:
            if not dst_dir.exists():
                return None
            for candidate in dst_dir.iterdir():
                if candidate.is_file() and self._same_content(src, candidate):
                    return candidate
        except OSError:
            return None
        return None
