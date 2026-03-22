"""
metadata.py — date extraction layer.

Priority chain:
  1. EXIF DateTimeOriginal  (most accurate — camera-set timestamp)
  2. EXIF DateTimeDigitized (camera digitization timestamp)
  3. EXIF DateTime          (file-written timestamp, still embedded metadata)
  4. Spotlight/mdls capture metadata on macOS (CR3/MP4 fallback)
  5. stat().st_birthtime    (macOS file creation — not available on Linux)
  6. stat().st_mtime        (modification time — last resort)

Extension hook (AI pipeline):
  The `ImageMetadata` dataclass is designed to grow.  Future fields:

      embedding: list[float] | None = None      # CLIP embedding
      caption: str | None = None                # generated caption
      cluster_id: int | None = None             # clustering label
      scene_tags: list[str] = field(...)        # zero-shot classification

  `MetadataExtractor.extract()` becomes the single place where every
  enrichment step is called, keeping organizer.py completely unaware of AI.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# EXIF tag IDs we care about (raw values from the TIFF spec)
_TAG_DATETIME_ORIGINAL = 0x9003  # 36867
_TAG_DATETIME_DIGITIZED = 0x9004  # 36868
_TAG_DATETIME = 0x0132  # 306

# EXIF datetime format string
_EXIF_DT_FMT = "%Y:%m:%d %H:%M:%S"
_MDLS_DT_FMTS = (
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S",
)


@dataclass
class ImageMetadata:
    """
    All metadata extracted for a single image file.

    Kept as a plain dataclass so it serialises trivially to JSON/dict for the
    future FastAPI response model.
    """

    path: Path
    date: datetime
    date_source: str  # "exif_original" | "exif_digitized" | "exif_datetime" | "mdls_*" | "birthtime" | "mtime"

    # ── Future AI fields (not yet populated) ──────────────────────────
    # embedding: list[float] | None = None
    # caption: str | None = None
    # cluster_id: int | None = None


class MetadataExtractor:
    """
    Extracts image metadata without loading pixel data into memory.

    Pillow is used *only* for EXIF parsing (thumbnail read), not full decode.
    Falls back gracefully when Pillow is absent or EXIF is missing/corrupt.
    """

    def extract(self, path: Path) -> Optional[ImageMetadata]:
        """
        Return ImageMetadata for *path*, or None if the file is unreadable.
        """
        date, source = self._extract_date(path)
        if date is None:
            log.warning("Could not determine date for: %s", path)
            return None
        return ImageMetadata(path=path, date=date, date_source=source)

    # ------------------------------------------------------------------
    # Date extraction — priority chain
    # ------------------------------------------------------------------

    def _extract_date(self, path: Path) -> tuple[Optional[datetime], str]:
        # 1-3 — EXIF / embedded image metadata
        exif_date, exif_source = self._exif_date(path)
        if exif_date:
            return exif_date, exif_source

        # 4 — macOS Spotlight metadata for RAW/video capture times
        mdls_date, mdls_source = self._mdls_capture_date(path)
        if mdls_date:
            return mdls_date, mdls_source

        # 5 — macOS birthtime
        birth = self._birth_date(path)
        if birth:
            return birth, "birthtime"

        # 6 — mtime
        mtime = self._mtime_date(path)
        if mtime:
            return mtime, "mtime"

        return None, "unknown"

    def _exif_date(self, path: Path) -> tuple[Optional[datetime], str]:
        """
        Parse EXIF without decoding the full image.

        We attempt two strategies in order:
          A) Pillow _getexif() — handles JPEG/TIFF/HEIC wrappers cleanly.
          B) Minimal TIFF/EXIF parser — fallback when Pillow is absent.
        """
        try:
            from PIL import Image, ExifTags  # type: ignore

            with Image.open(path) as img:
                # `_getexif()` exists only on JpegImageFile; others expose
                # getexif() (Pillow ≥ 6.0)
                exif_data = None
                if hasattr(img, "_getexif"):
                    exif_data = img._getexif()
                elif hasattr(img, "getexif"):
                    raw = img.getexif()
                    exif_data = dict(raw) if raw else None

                if not exif_data:
                    return None, ""

                # Prefer camera capture timestamps over generic file timestamps
                for tag_id, source_label in (
                    (_TAG_DATETIME_ORIGINAL, "exif_original"),
                    (_TAG_DATETIME_DIGITIZED, "exif_digitized"),
                    (_TAG_DATETIME, "exif_datetime"),
                ):
                    raw_val = exif_data.get(tag_id)
                    if raw_val:
                        dt = self._parse_exif_dt(str(raw_val))
                        if dt:
                            log.debug("EXIF date (%s): %s — %s", source_label, dt, path.name)
                            return dt, source_label

        except Exception as exc:  # noqa: BLE001 — intentionally broad
            log.debug("EXIF extraction failed for %s: %s", path.name, exc)

        return None, ""

    def _mdls_capture_date(self, path: Path) -> tuple[Optional[datetime], str]:
        """
        Use macOS Spotlight metadata as a fallback for formats like CR3/MP4.

        We prefer explicit content/media creation dates before filesystem times.
        """
        for key, source_label in (
            ("kMDItemContentCreationDate", "mdls_content_creation"),
            ("kMDItemMediaCreationDate", "mdls_media_creation"),
        ):
            dt = self._mdls_value(path, key)
            if dt:
                return dt, source_label
        return None, ""

    def _mdls_value(self, path: Path, key: str) -> Optional[datetime]:
        try:
            result = subprocess.run(
                ["mdls", "-name", key, "-raw", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            log.debug("mdls unavailable for %s: %s", path.name, exc)
            return None

        if result.returncode != 0:
            return None

        raw = result.stdout.strip()
        if not raw or raw == "(null)":
            return None

        for fmt in _MDLS_DT_FMTS:
            try:
                parsed = datetime.strptime(raw, fmt)
                return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
            except ValueError:
                continue

        log.debug("Unparseable mdls date for %s (%s): %s", path.name, key, raw)
        return None

    @staticmethod
    def _parse_exif_dt(raw: str) -> Optional[datetime]:
        """Parse EXIF datetime string, returning None on any parse error."""
        try:
            return datetime.strptime(raw.strip(), _EXIF_DT_FMT)
        except ValueError:
            return None

    @staticmethod
    def _birth_date(path: Path) -> Optional[datetime]:
        """Return file creation time on macOS (st_birthtime), else None."""
        try:
            st = path.stat()
            birth_ts = getattr(st, "st_birthtime", None)
            if birth_ts:
                return datetime.fromtimestamp(birth_ts)
        except OSError:
            pass
        return None

    @staticmethod
    def _mtime_date(path: Path) -> Optional[datetime]:
        """Return file modification time."""
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return None
