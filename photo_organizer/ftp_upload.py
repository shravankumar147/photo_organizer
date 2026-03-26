from __future__ import annotations

import argparse
import ftplib
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from photo_organizer.audit import RunAudit
from photo_organizer.config import load_dotenv_into_environ, load_settings, to_path
SUPPORTED_UPLOAD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".cr3",
    ".raw",
    ".mp4",
    ".mov",
}
FTP_ERRORS = ftplib.all_errors + (OSError,)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftp_upload.py",
        description=(
            "Upload organized media to an FTP server and move successfully "
            "uploaded local files into a local trash folder."
        ),
    )
    parser.add_argument("--src", metavar="PATH", help="Source organized directory.")
    parser.add_argument("--trash", metavar="PATH", help="Local trash directory for successfully uploaded files.")
    parser.add_argument("--host", default=None, help="FTP host.")
    parser.add_argument("--user", default=None, help="FTP username.")
    parser.add_argument("--password", default=None, help="FTP password.")
    parser.add_argument(
        "--remote-root",
        default=None,
        metavar="PATH",
        help="Remote FTP root.",
    )
    parser.add_argument("--port", default=None, type=int, help="FTP port.")
    parser.add_argument("--config", metavar="PATH", help="Optional config file.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without writing files or moving local files.")
    return parser


def _parse_value(raw: str) -> Any:
    value = raw.strip().strip("'\"")
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.isdigit():
        return int(value)
    return value


def normalize_ftp_host(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if "://" not in stripped:
        return stripped
    parsed = urlparse(stripped)
    return parsed.hostname or stripped


def resolve_ftp_settings(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv_into_environ()
    settings = load_settings(args.config)
    ftp_config = settings.ftp

    def cfg(key: str, default: Any = None) -> Any:
        return ftp_config.get(key, default)

    if bool(cfg("use_env_credentials", True)):
        env_host = os.environ.get("FTP_HOST", "")
        env_user = os.environ.get("FTP_USER", "")
        env_password = os.environ.get("FTP_PASS") or os.environ.get("FTP_PASSWORD", "")
    else:
        env_host = ""
        env_user = ""
        env_password = ""

    host = normalize_ftp_host(args.host or cfg("host", "") or env_host)
    user = args.user or cfg("user", "") or env_user
    password = args.password or cfg("password", "") or env_password

    return {
        "source_root": Path(args.src) if args.src else to_path(cfg("source_folder")),
        "trash_root": Path(args.trash) if args.trash else to_path(cfg("trash_folder")),
        "host": host,
        "user": user,
        "password": password,
        "remote_root": args.remote_root or str(cfg("remote_folder", os.environ.get("FTP_REMOTE_ROOT", "/"))),
        "port": args.port or int(cfg("port", os.environ.get("FTP_PORT", 21))),
    }


def iter_upload_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_UPLOAD_EXTENSIONS:
            continue
        candidates.append(path)
    return sorted(candidates)


def ensure_remote_dirs(ftp: ftplib.FTP, remote_dir: str) -> None:
    ftp.cwd("/")
    if not remote_dir or remote_dir == "/":
        return
    for part in [segment for segment in remote_dir.strip("/").split("/") if segment]:
        try:
            ftp.cwd(part)
            continue
        except ftplib.error_perm as exc:
            if not str(exc).startswith("550"):
                raise
        ftp.mkd(part)
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
    audit: RunAudit | None = None,
) -> dict[str, int]:
    stats = {"uploaded": 0, "skipped": 0, "errors": 0}

    for src in iter_upload_candidates(source_root):
        rel = src.relative_to(source_root).as_posix()
        remote_path = f"{remote_root.rstrip('/')}/{rel}" if remote_root != "/" else f"/{rel}"

        if dry_run:
            stats["uploaded"] += 1
            print(f"[dry-run] {src} -> {remote_path}")
            if audit is not None:
                audit.record(status="uploaded", source=str(src), remote_path=remote_path, message="dry_run")
            continue

        if ftp is None:
            raise ValueError("FTP client is required when dry_run is False")

        try:
            upload_file(ftp, src, remote_path)
            trash_path = move_to_trash(source_root, trash_root, src)
            stats["uploaded"] += 1
            print(f"[ok] {src} -> {remote_path} (moved to {trash_path})")
            if audit is not None:
                audit.record(status="uploaded", source=str(src), remote_path=remote_path, trash=str(trash_path), message="uploaded")
        except FTP_ERRORS as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {remote_path}: {exc}", file=sys.stderr)
            if audit is not None:
                audit.record(status="errors", source=str(src), remote_path=remote_path, message=f"upload_failed:{exc}")

    return stats


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = resolve_ftp_settings(args)
    source_root = settings["source_root"]
    trash_root = settings["trash_root"]

    if not source_root.exists():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1

    if not args.dry_run and (
        not settings["host"] or not settings["user"] or not settings["password"]
    ):
        print(
            "[error] FTP credentials are required. Set them in .env, config files, "
            "or pass --host/--user/--password.",
            file=sys.stderr,
        )
        return 1

    ftp: ftplib.FTP | None = None
    connected = False
    try:
        if not args.dry_run:
            ftp = ftplib.FTP()
            ftp.connect(settings["host"], settings["port"])
            ftp.login(settings["user"], settings["password"])
            connected = True

        audit = RunAudit(
            command="ftp_upload",
            folder=to_path(settings.audit.folder),
            source_root=source_root,
            destination_root=Path(settings["remote_root"]),
            config_path=args.config or "config.default.yaml",
            metadata={"dry_run": args.dry_run, "trash_root": str(trash_root), "port": settings["port"]},
        )
        started_at = time.perf_counter()
        stats = upload_to_ftp(
            source_root=source_root,
            trash_root=trash_root,
            ftp=ftp,
            remote_root=settings["remote_root"],
            dry_run=args.dry_run,
            audit=audit,
        )
        stats["elapsed_seconds"] = time.perf_counter() - started_at
    finally:
        if ftp is not None:
            try:
                if connected:
                    ftp.quit()
                else:
                    ftp.close()
            except ftplib.all_errors:
                ftp.close()

    manifest_path = audit.write(stats)
    print()
    print("FTP Upload Summary")
    print(f"  Uploaded: {stats['uploaded']}")
    print(f"  Skipped : {stats['skipped']}")
    print(f"  Errors  : {stats['errors']}")
    print(f"  Manifest: {manifest_path}")
    return 0 if stats["errors"] == 0 else 1
