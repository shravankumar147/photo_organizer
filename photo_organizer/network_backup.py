from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

from photo_organizer.audit import RunAudit
from photo_organizer.config import load_settings, to_path

SUPPORTED_BACKUP_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".cr3",
    ".raw",
    ".mp4",
    ".mov",
}
HASH_CHUNK = 4 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="network_backup.py",
        description="Backup the full organized media tree to a mounted network share.",
    )
    parser.add_argument("--src", metavar="PATH", help="Source organized directory.")
    parser.add_argument("--dst", metavar="PATH", help="Mounted network-share destination.")
    parser.add_argument(
        "--trash",
        metavar="PATH",
        help="Local trash directory for verified source files moved out after backup.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without writing files.")
    parser.add_argument(
        "--prune-source",
        action="store_true",
        help="Move source files into trash after they are confirmed to exist identically at the destination.",
    )
    parser.add_argument("--config", metavar="PATH", help="Optional config file.")
    return parser


def iter_backup_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_BACKUP_EXTENSIONS:
            continue
        candidates.append(path)
    return sorted(candidates)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def same_content(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return sha256(a) == sha256(b)
    except OSError:
        return False


def prune_empty_directories(root: Path) -> int:
    removed = 0
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def move_to_trash(src_root: Path, trash_root: Path, src: Path) -> Path:
    rel = src.relative_to(src_root)
    dst = trash_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst


def backup_to_network(
    source_root: Path,
    destination_root: Path,
    dry_run: bool = False,
    prune_source: bool = False,
    trash_root: Path | None = None,
    audit: RunAudit | None = None,
) -> dict[str, int]:
    stats = {
        "copied": 0,
        "skipped": 0,
        "errors": 0,
        "pruned": 0,
        "empty_dirs_removed": 0,
    }

    if prune_source and trash_root is None:
        raise ValueError("trash_root is required when prune_source is True")

    for src in iter_backup_candidates(source_root):
        rel = src.relative_to(source_root)
        dst = destination_root / rel

        if dst.exists() and same_content(src, dst):
            stats["skipped"] += 1
            print(f"[skip] {dst}")
            if prune_source and not dry_run:
                try:
                    trashed = move_to_trash(source_root, trash_root, src)
                    stats["pruned"] += 1
                    print(f"[prune] {src} -> {trashed}")
                    if audit is not None:
                        audit.record(status="skipped", source=str(src), target=str(dst), trash=str(trashed), message="already_exists_pruned")
                except OSError as exc:
                    stats["errors"] += 1
                    print(f"[error] could not move {src} to trash: {exc}", file=sys.stderr)
                    if audit is not None:
                        audit.record(status="errors", source=str(src), target=str(dst), message=f"trash_move_failed:{exc}")
            elif audit is not None:
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
            if prune_source and same_content(src, dst):
                trashed = move_to_trash(source_root, trash_root, src)
                stats["pruned"] += 1
                print(f"[prune] {src} -> {trashed}")
                if audit is not None:
                    audit.record(status="copied", source=str(src), target=str(dst), trash=str(trashed), message="copied_pruned")
            elif audit is not None:
                audit.record(status="copied", source=str(src), target=str(dst), message="copied")
        except OSError as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {dst}: {exc}", file=sys.stderr)
            if audit is not None:
                audit.record(status="errors", source=str(src), target=str(dst), message=f"backup_failed:{exc}")

    if prune_source and not dry_run:
        stats["empty_dirs_removed"] = prune_empty_directories(source_root)

    return stats


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    source_root = Path(args.src) if args.src else to_path(settings.network_backup.source_folder)
    destination_root = Path(args.dst) if args.dst else to_path(settings.network_backup.destination_folder)
    trash_root = (
        Path(args.trash)
        if args.trash
        else to_path(settings.network_backup.trash_folder)
    )

    if not source_root.exists():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1

    if not args.dry_run:
        try:
            destination_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[error] Could not create destination directory {destination_root}: {exc}", file=sys.stderr)
            return 1
        if args.prune_source:
            try:
                trash_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                print(f"[error] Could not create trash directory {trash_root}: {exc}", file=sys.stderr)
                return 1
    elif not destination_root.exists():
        print(f"[error] Destination directory does not exist: {destination_root}", file=sys.stderr)
        return 1

    audit = RunAudit(
        command="network_backup",
        folder=to_path(settings.audit.folder),
        source_root=source_root,
        destination_root=destination_root,
        config_path=args.config or "config.default.yaml",
        metadata={"dry_run": args.dry_run, "prune_source": args.prune_source, "trash_root": str(trash_root)},
    )
    started_at = time.perf_counter()
    stats = backup_to_network(
        source_root,
        destination_root,
        dry_run=args.dry_run,
        prune_source=args.prune_source,
        trash_root=trash_root if args.prune_source else None,
        audit=audit,
    )
    stats["elapsed_seconds"] = time.perf_counter() - started_at
    manifest_path = audit.write(stats)
    print()
    print("Network Backup Summary")
    print(f"  Copied : {stats['copied']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors : {stats['errors']}")
    print(f"  Pruned : {stats['pruned']}")
    if args.prune_source:
        print("  Organized root retained")
        print(f"  Empty descendants removed : {stats['empty_dirs_removed']}")
        print(f"  Verified files moved to   : {trash_root}")
    print(f"  Manifest: {manifest_path}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
