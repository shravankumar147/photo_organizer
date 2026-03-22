from __future__ import annotations

import argparse
import ftplib
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

DEFAULT_SOURCE = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/cloud_ready")
DEFAULT_TRASH = Path("/Volumes/EOS_DIGITAL/DCIM/100CANON/ftp_trash")
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_CONFIG_FILE = Path("config.yaml")
FTP_ERRORS = ftplib.all_errors + (OSError,)


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
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), metavar="PATH", help="Optional .env file with FTP credentials.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_FILE), metavar="PATH", help="Optional config.yaml file.")
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


def resolve_env_placeholders(value: Any, env_values: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("${env:") and value.endswith("}"):
        key = value[6:-1]
        return env_values.get(key, os.environ.get(key, value))
    return value


def normalize_ftp_host(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if "://" not in stripped:
        return stripped
    parsed = urlparse(stripped)
    return parsed.hostname or stripped


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = str(_parse_value(raw))
    return values


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    data: dict[str, Any] = {}
    current_section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1]
            data[current_section] = {}
            continue
        if current_section and ":" in stripped:
            key, raw = stripped.split(":", 1)
            section = data.setdefault(current_section, {})
            if isinstance(section, dict):
                section[key.strip()] = _parse_value(raw)
    return data


def resolve_ftp_settings(args: argparse.Namespace) -> dict[str, Any]:
    env_values = load_dotenv(Path(args.env_file))
    config = load_config(Path(args.config))
    ftp_config = config.get("ftp", {}) if isinstance(config.get("ftp", {}), dict) else {}

    use_env_credentials = bool(ftp_config.get("use_env_credentials", True))
    local_folder = resolve_env_placeholders(
        ftp_config.get("local_folder", DEFAULT_SOURCE),
        env_values,
    )
    trash_folder = resolve_env_placeholders(
        ftp_config.get("trash_folder", DEFAULT_TRASH),
        env_values,
    )
    remote_folder = resolve_env_placeholders(
        ftp_config.get("remote_folder"),
        env_values,
    )

    host = normalize_ftp_host(args.host or env_values.get("FTP_HOST") or ftp_config.get("host"))
    user = args.user or env_values.get("FTP_USER") or ftp_config.get("user")
    password = (
        args.password
        or env_values.get("FTP_PASSWORD")
        or env_values.get("FTP_PASS")
        or ftp_config.get("password")
        or ftp_config.get("pass")
    )
    if not use_env_credentials:
        user = args.user or ftp_config.get("user") or env_values.get("FTP_USER")
        password = (
            args.password
            or ftp_config.get("password")
            or ftp_config.get("pass")
            or env_values.get("FTP_PASSWORD")
            or env_values.get("FTP_PASS")
        )

    return {
        "source_root": Path(args.src or local_folder),
        "trash_root": Path(args.trash or trash_folder),
        "host": host,
        "user": user,
        "password": password,
        "remote_root": args.remote_root or remote_folder or env_values.get("FTP_REMOTE_ROOT") or "/",
        "port": args.port or int(env_values.get("FTP_PORT", ftp_config.get("port", 21))),
    }


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
        except FTP_ERRORS as exc:
            stats["errors"] += 1
            print(f"[error] {src} -> {remote_path}: {exc}", file=sys.stderr)

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
            "[error] FTP credentials are required. Set them in .env, config.yaml, "
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

        stats = upload_to_ftp(
            source_root=source_root,
            trash_root=trash_root,
            ftp=ftp,
            remote_root=settings["remote_root"],
            dry_run=args.dry_run,
        )
    finally:
        if ftp is not None:
            try:
                if connected:
                    ftp.quit()
                else:
                    ftp.close()
            except ftplib.all_errors:
                ftp.close()

    print()
    print("FTP Upload Summary")
    print(f"  Uploaded: {stats['uploaded']}")
    print(f"  Skipped : {stats['skipped']}")
    print(f"  Errors  : {stats['errors']}")
    return 0 if stats["errors"] == 0 else 1
