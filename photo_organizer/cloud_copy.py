from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from photo_organizer.audit import RunAudit
from photo_organizer.config import load_settings, to_path

SUPPORTED_CLOUD_BUCKETS = {"images", "videos"}
SUPPORTED_CLOUD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".mp4",
    ".mov",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copy_media_for_cloud.py",
        description=(
            "Copy cloud-ready media from an organized photo tree, excluding RAW "
            "and other non-cloud media."
        ),
    )
    parser.add_argument(
        "--src",
        metavar="PATH",
        help="Source organized directory.",
    )
    parser.add_argument(
        "--dst",
        metavar="PATH",
        help="Destination cloud-ready directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing files.",
    )
    parser.add_argument("--config", metavar="PATH", help="Optional config file.")
    return parser


def iter_cloud_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_CLOUD_EXTENSIONS:
            continue
        bucket = rel.parts[-2] if len(rel.parts) >= 2 else None
        if bucket not in SUPPORTED_CLOUD_BUCKETS:
            continue
        candidates.append(path)
    return sorted(candidates)


def cloud_relative_path(source_root: Path, path: Path) -> Path:
    rel = path.relative_to(source_root)
    if len(rel.parts) < 2 or rel.parts[-2] not in SUPPORTED_CLOUD_BUCKETS:
        raise ValueError(f"Unsupported cloud path: {path}")
    return rel


def copy_for_cloud(
    source_root: Path,
    destination_root: Path,
    dry_run: bool = False,
    audit: RunAudit | None = None,
) -> dict[str, int]:
    stats = {"copied": 0, "skipped": 0, "errors": 0}

    for src in iter_cloud_candidates(source_root):
        rel = cloud_relative_path(source_root, src)
        dst = destination_root / rel

        if dst.exists():
            stats["skipped"] += 1
            print(f"[skip] {dst}")
            if audit is not None:
                audit.record(status="skipped", source=str(src), target=str(dst), message="already_exists")
            continue

        if dry_run:
            stats["copied"] += 1
            print(f"[dry-run] {src} -> {dst}")
            if audit is not None:
                audit.record(status="copied", source=str(src), target=str(dst), message="dry_run")
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            stats["copied"] += 1
            print(f"[ok] {src} -> {dst}")
            if audit is not None:
                audit.record(status="copied", source=str(src), target=str(dst), message="copied")
        except OSError as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {dst}: {exc}", file=sys.stderr)
            if audit is not None:
                audit.record(status="errors", source=str(src), target=str(dst), message=f"copy_failed:{exc}")

    return stats


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    source_root = Path(args.src) if args.src else to_path(settings.cloud.source_folder)
    destination_root = Path(args.dst) if args.dst else to_path(settings.cloud.destination_folder)

    if not source_root.exists():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1

    audit = RunAudit(
        command="cloud_copy",
        folder=to_path(settings.audit.folder),
        source_root=source_root,
        destination_root=destination_root,
        config_path=args.config or "config.default.yaml",
        metadata={"dry_run": args.dry_run},
    )
    started_at = time.perf_counter()
    stats = copy_for_cloud(source_root, destination_root, dry_run=args.dry_run, audit=audit)
    stats["elapsed_seconds"] = time.perf_counter() - started_at
    manifest_path = audit.write(stats)
    print()
    print("Cloud Copy Summary")
    print(f"  Copied : {stats['copied']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors : {stats['errors']}")
    print(f"  Manifest: {manifest_path}")
    return 0 if stats["errors"] == 0 else 1
