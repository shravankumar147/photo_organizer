"""
organizer.py — folder creation and file-copy layer.

Responsibilities:
  * Decide the destination path for each image (YYYY/MM/DD/<filename>)
  * Handle duplicates by appending a numeric suffix
  * Copy files (or simulate in dry-run mode)
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

log = logging.getLogger(__name__)

ProcessResult = Literal["processed", "skipped", "errors"]

# Buffer size for file hashing (4 MiB)
_HASH_CHUNK = 4 * 1024 * 1024


@dataclass
class OrganizerConfig:
    dst: Path
    dry_run: bool = False
    hash_duplicates: bool = True  # SHA-256 check before copy


class Organizer:
    """
    Moves each image into its YYYY/MM/DD destination folder.

    Single public method: `process(path) -> ProcessResult`
    """

    def __init__(self, config: OrganizerConfig) -> None:
        self.config = config
        self._extractor = MetadataExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, src_path: Path) -> ProcessResult:
        """Extract metadata, decide destination, copy file."""
        log.info("Processing: %s", src_path)

        meta = self._extractor.extract(src_path)
        if meta is None:
            log.error("Skipping (no date): %s", src_path)
            return "errors"

        log.info("  Date   : %s  [source: %s]", meta.date.date(), meta.date_source)

        dst_dir = self._destination_dir(meta)
        dst_path = self._resolve_destination(src_path, dst_dir)

        log.info("  Target : %s", dst_path)

        if self.config.dry_run:
            log.info("  [dry-run] Would copy → %s", dst_path)
            return "processed"

        return self._copy(src_path, dst_dir, dst_path)

    # ------------------------------------------------------------------
    # Destination resolution
    # ------------------------------------------------------------------

    def _destination_dir(self, meta: ImageMetadata) -> Path:
        """
        Map an image to its target directory.

        Override this in a subclass to implement event-based, AI-driven, or
        any other grouping strategy.
        """
        d = meta.date
        return self.config.dst / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"

    def _resolve_destination(self, src: Path, dst_dir: Path) -> Path:
        """
        Return a collision-free destination path.

        Strategy: <name>.<ext> → <name>_1.<ext> → <name>_2.<ext> → …
        If hash_duplicates is enabled and the hashes match, we skip the file
        entirely (true duplicate, not just same name).
        """
        stem = src.stem
        suffix = src.suffix
        candidate = dst_dir / src.name
        counter = 0

        while candidate.exists():
            if self.config.hash_duplicates and self._same_content(src, candidate):
                log.info("  [skip] Identical file already exists: %s", candidate)
                return candidate  # signal caller to skip
            counter += 1
            candidate = dst_dir / f"{stem}_{counter}{suffix}"

        return candidate

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _copy(self, src: Path, dst_dir: Path, dst: Path) -> ProcessResult:
        # Check whether resolve decided this is a true duplicate
        if dst.exists() and self.config.hash_duplicates and self._same_content(src, dst):
            log.info("  [skip] Duplicate content, not copying.")
            return "skipped"

        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)  # copy2 preserves timestamps
            log.info("  [ok] Copied → %s", dst)
            return "processed"
        except OSError as exc:
            log.error("  [error] Failed to copy %s → %s: %s", src, dst, exc)
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
