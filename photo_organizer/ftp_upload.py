from __future__ import annotations

import argparse
import ftplib
import os
import shutil
import sys
from pathlib import Path

DEFAULT_SOURCE = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/cloud_ready")
DEFAULT_TRASH = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/ftp_trash")
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftp_upload.py",
        description=(
            "Upload cloud-ready photos to an FTP server and move successfully "
            "uploaded local files into a local trash folder."
        ),
    )
    parser.add_argument("--src", default=str(DEFAULT_SOURCE), metavar="PATH", help="Source cloud-ready directory.")
    parser.add_argument("--trash", default=str(DEFAULT_TRASH), metavar="PATH", help="Local trash directory for successfully uploaded files.")
    parser.add_argument("--host", default=os.environ.get("FTP_HOST"), help="FTP host. Defaults to FTP_HOST.")
    parser.add_argument("--user", default=os.environ.get("FTP_USER"), help="FTP username. Defaults to FTP_USER.")
    parser.add_argument("--password", default=os.environ.get("FTP_PASSWORD"), help="FTP password. Defaults to FTP_PASSWORD.")
    parser.add_argument(
        "--remote-root",
        default=os.environ.get("FTP_REMOTE_ROOT", "/"),
        metavar="PATH",
        help="Remote FTP root. Defaults to FTP_REMOTE_ROOT or '/'.",
    )
    parser.add_argument("--port", default=int(os.environ.get("FTP_PORT", "21")), type=int, help="FTP port. Defaults to FTP_PORT or 21.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without writing files or moving local files.")
    return parser


def iter_upload_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        candidates.append(path)
    return sorted(candidates)


def ensure_remote_dirs(ftp: ftplib.FTP, remote_dir: str) -> None:
    ftp.cwd("/")
    if not remote_dir or remote_dir == "/":
        return
    for part in [segment for segment in remote_dir.strip("/").split("/") if segment]:
        try:
            ftp.mkd(part)
        except ftplib.error_perm as exc:
            if not str(exc).startswith("550"):
                raise
        ftp.cwd(part)


def upload_file(ftp: ftplib.FTP, src: Path, remote_path: str) -> None:
    remote_dir, remote_name = remote_path.rsplit("/", 1)
    ensure_remote_dirs(ftp, remote_dir)
    with src.open("rb") as fh:
        ftp.storbinary(f"STOR {remote_name}", fh)


def move_to_trash(src_root: Path, trash_root: Path, src: Path) -> Path:
    rel = src.relative_to(src_root)
    dst = trash_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst


def upload_to_ftp(
    source_root: Path,
    trash_root: Path,
    ftp: ftplib.FTP | None,
    remote_root: str,
    dry_run: bool = False,
) -> dict[str, int]:
    stats = {"uploaded": 0, "skipped": 0, "errors": 0}

    for src in iter_upload_candidates(source_root):
        rel = src.relative_to(source_root).as_posix()
        remote_path = f"{remote_root.rstrip('/')}/{rel}" if remote_root != "/" else f"/{rel}"

        if dry_run:
            stats["uploaded"] += 1
            print(f"[dry-run] {src} -> {remote_path}")
            continue

        if ftp is None:
            raise ValueError("FTP client is required when dry_run is False")

        try:
            upload_file(ftp, src, remote_path)
            trash_path = move_to_trash(source_root, trash_root, src)
            stats["uploaded"] += 1
            print(f"[ok] {src} -> {remote_path} (moved to {trash_path})")
        except (OSError, ftplib.all_errors) as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {remote_path}: {exc}", file=sys.stderr)

    return stats


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = Path(args.src)
    trash_root = Path(args.trash)

    if not source_root.exists():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1

    if not args.dry_run and (not args.host or not args.user or not args.password):
        print(
            "[error] FTP credentials are required. Set FTP_HOST, FTP_USER, "
            "FTP_PASSWORD, or pass --host/--user/--password.",
            file=sys.stderr,
        )
        return 1

    ftp: ftplib.FTP | None = None
    try:
        if not args.dry_run:
            ftp = ftplib.FTP()
            ftp.connect(args.host, args.port)
            ftp.login(args.user, args.password)

        stats = upload_to_ftp(
            source_root=source_root,
            trash_root=trash_root,
            ftp=ftp,
            remote_root=args.remote_root,
            dry_run=args.dry_run,
        )
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()

    print()
    print("FTP Upload Summary")
    print(f"  Uploaded: {stats['uploaded']}")
    print(f"  Skipped : {stats['skipped']}")
    print(f"  Errors  : {stats['errors']}")
    return 0 if stats["errors"] == 0 else 1
