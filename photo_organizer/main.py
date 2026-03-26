"""
photo_organizer — entry point.

This module wires together all subsystems and runs the pipeline.
Future: replace run() with a FastAPI route handler that accepts the same
OrganizeRequest DTO, making zero changes to the core engine.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from photo_organizer.audit import RunAudit
from photo_organizer.cli import build_parser
from photo_organizer.config import load_settings, to_path
from photo_organizer.organizer import Organizer, OrganizerConfig
from photo_organizer.scanner import DEFAULT_EXTENSIONS, Scanner
from photo_organizer.utils import configure_logging, print_summary

MANAGED_DIRECTORY_NAMES = frozenset(
    {"organized", "cloud_ready", "ftp_trash", "network_backup_trash"}
)
IGNORABLE_EMPTY_DIR_FILES = frozenset({".DS_Store"})


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


def run(request: OrganizeRequest, audit: RunAudit | None = None) -> dict:
    """
    Execute the full organise pipeline.

    Returns a summary dict so callers (CLI *or* FastAPI) can format output
    themselves.
    """
    configure_logging(verbose=request.verbose)
    log = logging.getLogger(__name__)
    started_at = time.perf_counter()

    log.info("Source      : %s", request.src)
    log.info("Destination : %s", request.dst)
    log.info("Dry-run     : %s", request.dry_run)

    excluded_roots = managed_roots(request.src, request.dst)

    scanner = Scanner(
        root=request.src,
        extensions=request.extensions,
        excluded_roots=excluded_roots,
    )
    config = OrganizerConfig(
        dst=request.dst,
        dry_run=request.dry_run,
    )
    organizer = Organizer(config=config)

    stats = {"processed": 0, "skipped": 0, "errors": 0}

    for media_path in scanner.scan():
        detail = organizer.process_with_details(media_path)
        result = str(detail["status"])
        stats[result] += 1
        if audit is not None:
            audit.record(**detail)

    if not request.dry_run:
        removed_dirs = remove_empty_directories(
            root=request.src,
            excluded_roots=excluded_roots,
        )
        log.info("Removed %d empty directorie(s).", removed_dirs)

    stats["elapsed_seconds"] = time.perf_counter() - started_at

    return stats


def managed_roots(src: Path, dst: Path) -> tuple[Path, ...]:
    roots = {dst.resolve(strict=False)}
    for name in MANAGED_DIRECTORY_NAMES:
        candidate = (src / name).resolve(strict=False)
        roots.add(candidate)
    return tuple(sorted(roots))


def remove_empty_directories(root: Path, excluded_roots: tuple[Path, ...] = ()) -> int:
    """Remove empty directories under root, excluding protected subtrees."""
    removed = 0
    protected = tuple(path.resolve(strict=False) for path in excluded_roots)

    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        resolved = directory.resolve(strict=False)
        if any(
            resolved == excluded or resolved.is_relative_to(excluded)
            for excluded in protected
        ):
            continue

        try:
            children = list(directory.iterdir())
        except OSError:
            continue

        removable_files = [
            child
            for child in children
            if child.is_file() and (child.name in IGNORABLE_EMPTY_DIR_FILES or child.name.startswith("._"))
        ]
        remaining_children = [child for child in children if child not in removable_files]

        if remaining_children:
            continue

        for removable in removable_files:
            try:
                removable.unlink()
            except OSError:
                remaining_children.append(removable)

        if remaining_children:
            continue

        try:
            directory.rmdir()
            removed += 1
        except OSError:
            continue

    return removed


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.config)

    request = OrganizeRequest(
        src=Path(args.src) if args.src else to_path(settings.storage.source_folder),
        dst=Path(args.dst)
        if args.dst
        else to_path(settings.storage.destination_folder),
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    if not request.src.exists():
        print(f"[error] Source directory does not exist: {request.src}", file=sys.stderr)
        return 1

    audit = RunAudit(
        command="organize",
        folder=to_path(settings.audit.folder),
        source_root=request.src,
        destination_root=request.dst,
        config_path=args.config or "config.default.yaml",
        metadata={"dry_run": request.dry_run},
    )
    stats = run(request, audit=audit)
    manifest_path = audit.write(stats)
    print_summary(stats)
    print(f"Manifest            : {manifest_path}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
