"""
cli.py — argument parsing layer.

Kept deliberately thin: parse args, validate types, hand off to main.run().
No business logic lives here.
"""

from __future__ import annotations

import argparse

DEFAULT_SRC = "/Volumes/EOS_DIGITAL/DCIM/100CANON"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-organizer",
        description=(
            "Recursively scan a photo directory and move media into "
            "bucketed date folders, with EXIF-first date extraction."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python -m photo_organizer
  python -m photo_organizer --src /Volumes/EOS_DIGITAL/DCIM/100CANON
  python -m photo_organizer --src ~/Pictures/Raw --dst ~/Pictures/Raw/organized --dry-run
        """,
    )

    parser.add_argument(
        "--src",
        metavar="PATH",
        default=DEFAULT_SRC,
        help="Source directory to scan recursively.",
    )
    parser.add_argument(
        "--dst",
        metavar="PATH",
        help="Destination root directory for organised output. Defaults to <src>/organized.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate the run without moving any files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    return parser
