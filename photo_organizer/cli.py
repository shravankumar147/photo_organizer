"""
cli.py — argument parsing layer.

Kept deliberately thin: parse args, validate types, hand off to main.run().
No business logic lives here.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-organizer",
        description=(
            "Recursively scan a photo directory and copy images into a "
            "YYYY/MM/DD folder hierarchy, with EXIF-first date extraction."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python -m photo_organizer --src ~/Pictures/Raw --dst ~/Pictures/Organised
  python -m photo_organizer --src /Volumes/SD --dst ~/Sorted --dry-run --verbose
        """,
    )

    parser.add_argument(
        "--src",
        required=True,
        metavar="PATH",
        help="Source directory to scan recursively.",
    )
    parser.add_argument(
        "--dst",
        required=True,
        metavar="PATH",
        help="Destination root directory for organised output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate the run without copying any files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    return parser
