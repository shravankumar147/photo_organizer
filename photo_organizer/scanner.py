"""
scanner.py — media file discovery layer.

Responsibilities:
  * Walk the source tree (generator — zero memory overhead)
  * Filter by supported extensions
  * Yield Path objects only — no I/O, no metadata

Extension hook:
  Subclass Scanner and override `_is_supported()` to add new formats without
  touching the rest of the pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS: dict[str, frozenset[str]] = {
    "images": frozenset({"jpg", "jpeg", "png", "heic"}),
    "raw": frozenset({"cr3", "raw"}),
    "videos": frozenset({"mp4", "mov"}),
}

# Default supported extensions (lowercase, no leading dot)
DEFAULT_EXTENSIONS: frozenset[str] = frozenset().union(*MEDIA_EXTENSIONS.values())


def media_bucket_for_path(path: Path) -> str | None:
    """Return the destination bucket for a file path, or None if unsupported."""
    suffix = path.suffix.lstrip(".").lower()
    for bucket, extensions in MEDIA_EXTENSIONS.items():
        if suffix in extensions:
            return bucket
    return None


class Scanner:
    """
    Recursively discovers supported media files under a root directory.

    Uses a generator to avoid loading the entire file list into memory —
    important when scanning large SD cards or network volumes.
    """

    def __init__(
        self,
        root: Path,
        extensions: frozenset[str] = DEFAULT_EXTENSIONS,
    ) -> None:
        self.root = root
        self._extensions = frozenset(ext.lower() for ext in extensions)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> Generator[Path, None, None]:
        """
        Yield every supported media path under self.root.

        Skips hidden directories (names starting with '.') and symlinks to
        avoid loops on macOS alias-heavy libraries.
        """
        log.debug("Starting scan of: %s", self.root)
        count = 0
        for path in self._walk(self.root):
            if self._is_supported(path):
                log.debug("Found: %s", path)
                count += 1
                yield path
        log.info("Scan complete — %d media file(s) found.", count)

    # ------------------------------------------------------------------
    # Internal helpers (override in subclasses for custom behaviour)
    # ------------------------------------------------------------------

    def _walk(self, directory: Path) -> Generator[Path, None, None]:
        """Depth-first traversal, skipping hidden dirs and symlinks."""
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            log.warning("Permission denied, skipping: %s", directory)
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                log.debug("Skipping symlink: %s", entry)
                continue
            if entry.is_dir():
                yield from self._walk(entry)
            elif entry.is_file():
                yield entry

    def _is_supported(self, path: Path) -> bool:
        """Return True when the file extension is in the allow-list."""
        return path.suffix.lstrip(".").lower() in self._extensions
