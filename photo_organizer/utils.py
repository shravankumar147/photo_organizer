"""
utils.py — cross-cutting helpers.

Deliberately minimal: logging config + human-readable summary.
Future additions might include: progress bar (tqdm), YAML config loader,
structured JSON log formatter for the FastAPI layer.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(verbose: bool = False) -> None:
    """
    Set up the root logger for the entire package.

    verbose=True  → DEBUG to stderr (noisy, for development)
    verbose=False → INFO  to stderr (clean, for end-users)
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def print_summary(stats: dict[str, int]) -> None:
    """Print a human-readable run summary to stdout."""
    total = sum(stats.values())
    print()
    print("─" * 42)
    print("  Photo Organizer — Run Summary")
    print("─" * 42)
    print(f"  Total files scanned : {total}")
    print(f"  ✓ Processed         : {stats.get('processed', 0)}")
    print(f"  ⊘ Skipped           : {stats.get('skipped', 0)}")
    print(f"  ✗ Errors            : {stats.get('errors', 0)}")
    print("─" * 42)
    print()
