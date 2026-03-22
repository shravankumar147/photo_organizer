from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DEFAULT_SOURCE = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/organized")
DEFAULT_DESTINATION = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/cloud_ready")
IMAGE_BUCKET = "images"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}


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
        default=str(DEFAULT_SOURCE),
        metavar="PATH",
        help="Source organized directory. Defaults to the Canon organized tree.",
    )
    parser.add_argument(
        "--dst",
        default=str(DEFAULT_DESTINATION),
        metavar="PATH",
        help="Destination cloud-ready directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without writing files.",
    )
    return parser


def iter_cloud_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        if IMAGE_BUCKET not in path.parts:
            continue
        if path.parts[-2] != IMAGE_BUCKET:
            continue
        candidates.append(path)
    return sorted(candidates)


def cloud_relative_path(source_root: Path, path: Path) -> Path:
    rel = path.relative_to(source_root)
    if rel.parts[-2] != IMAGE_BUCKET:
        raise ValueError(f"Unsupported cloud path: {path}")
    return rel


def copy_for_cloud(source_root: Path, destination_root: Path, dry_run: bool = False) -> dict[str, int]:
    stats = {"copied": 0, "skipped": 0, "errors": 0}

    for src in iter_cloud_candidates(source_root):
        rel = cloud_relative_path(source_root, src)
        dst = destination_root / rel

        if dst.exists():
            stats["skipped"] += 1
            print(f"[skip] {dst}")
            continue

        if dry_run:
            stats["copied"] += 1
            print(f"[dry-run] {src} -> {dst}")
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            stats["copied"] += 1
            print(f"[ok] {src} -> {dst}")
        except OSError as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {dst}: {exc}", file=sys.stderr)

    return stats


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = Path(args.src)
    destination_root = Path(args.dst)

    if not source_root.exists():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1

    stats = copy_for_cloud(source_root, destination_root, dry_run=args.dry_run)
    print()
    print("Cloud Copy Summary")
    print(f"  Copied : {stats['copied']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors : {stats['errors']}")
    return 0 if stats["errors"] == 0 else 1
