from __future__ import annotations

import argparse
import subprocess
import sys


class WorkflowStepError(RuntimeError):
    def __init__(self, module: str, returncode: int) -> None:
        super().__init__(f"{module} failed with exit code {returncode}")
        self.module = module
        self.returncode = returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_all.py",
        description="Run organize, cloud copy, and network backup in sequence.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Optional config file. Defaults to config.default.yaml. Use config.test.yaml for local test runs.",
    )
    parser.add_argument(
        "--prune-source",
        action="store_true",
        help="Pass --prune-source to the network backup step.",
    )
    parser.add_argument(
        "--ftp-fallback",
        action="store_true",
        help="Run FTP upload if the network backup step fails.",
    )
    return parser


def run_step(
    module: str,
    config_path: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    print(f"\nRunning {module} ...")
    command = [sys.executable, "-m", module]
    if config_path:
        command.extend(["--config", config_path])
    if extra_args:
        command.extend(extra_args)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise WorkflowStepError(module, result.returncode)
    print(f"Completed {module}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_step("photo_organizer", config_path=args.config)
        run_step("photo_organizer.cloud_copy", config_path=args.config)
        network_args = ["--prune-source"] if args.prune_source else None
        run_step(
            "photo_organizer.network_backup",
            config_path=args.config,
            extra_args=network_args,
        )
    except WorkflowStepError as exc:
        if exc.module == "photo_organizer.network_backup" and args.ftp_fallback:
            print("\nNetwork backup failed; running FTP fallback ...")
            run_step("photo_organizer.ftp_upload", config_path=args.config)
        else:
            print(f"\nWorkflow stopped: {exc}")
            return exc.returncode
    print("\nAll workflow steps completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
