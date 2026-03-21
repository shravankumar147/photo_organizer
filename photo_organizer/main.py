"""
photo_organizer — entry point.

This module wires together all subsystems and runs the pipeline.
Future: replace run() with a FastAPI route handler that accepts the same
OrganizeRequest DTO, making zero changes to the core engine.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from photo_organizer.cli import build_parser
from photo_organizer.organizer import Organizer, OrganizerConfig
from photo_organizer.scanner import DEFAULT_EXTENSIONS, Scanner
from photo_organizer.utils import configure_logging, print_summary


@dataclass
class OrganizeRequest:
    """
    Central DTO that flows through the entire pipeline.

    Keeping all settings in one place means the future FastAPI layer only needs
    to deserialise a JSON body into this dataclass — the engine stays unchanged.
    """

    src: Path
    dst: Path
    dry_run: bool = False
    verbose: bool = False
    workers: int = 4  # for future ThreadPoolExecutor usage
    extensions: frozenset[str] = field(
        default_factory=lambda: DEFAULT_EXTENSIONS
    )


def run(request: OrganizeRequest) -> dict:
    """
    Execute the full organise pipeline.

    Returns a summary dict so callers (CLI *or* FastAPI) can format output
    themselves.
    """
    configure_logging(verbose=request.verbose)
    log = logging.getLogger(__name__)

    log.info("Source      : %s", request.src)
    log.info("Destination : %s", request.dst)
    log.info("Dry-run     : %s", request.dry_run)

    scanner = Scanner(
        root=request.src,
        extensions=request.extensions,
        excluded_roots=(request.dst,),
    )
    config = OrganizerConfig(
        dst=request.dst,
        dry_run=request.dry_run,
    )
    organizer = Organizer(config=config)

    stats = {"processed": 0, "skipped": 0, "errors": 0}

    for media_path in scanner.scan():
        result = organizer.process(media_path)
        stats[result] += 1

    return stats


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    request = OrganizeRequest(
        src=Path(args.src),
        dst=Path(args.dst) if args.dst else Path(args.src) / "organized",
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    if not request.src.exists():
        print(f"[error] Source directory does not exist: {request.src}", file=sys.stderr)
        return 1

    stats = run(request)
    print_summary(stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
