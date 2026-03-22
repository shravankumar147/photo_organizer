from __future__ import annotations

import subprocess
import sys


def run_step(module: str) -> None:
    print(f"\nRunning {module} ...")
    subprocess.run([sys.executable, "-m", module], check=True)
    print(f"Completed {module}")


def main() -> int:
    for module in (
        "photo_organizer",
        "photo_organizer.cloud_copy",
        "photo_organizer.ftp_upload",
    ):
        run_step(module)
    print("\nAll workflow steps completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
