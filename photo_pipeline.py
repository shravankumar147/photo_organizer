import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

app = typer.Typer()
console = Console()


PROJECT_DIR = Path(__file__).resolve().parent
PYTHON_EXECUTABLE = Path(sys.executable)

DEFAULT_MOUNT_POINT = Path("/Volumes/Canon_EOS_M50")
SMB_URL = "smb://192.168.0.1/G/Canon_EOS_M50"

LOG_FILE = Path.home() / "photo_pipeline.log"


def log(message: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def mount_candidates() -> list[Path]:
    parsed = urlparse(SMB_URL)
    host = parsed.netloc
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    share_name = path_parts[-1] if path_parts else None

    candidates: list[Path] = [DEFAULT_MOUNT_POINT]
    if share_name:
        candidates.append(Path("/Volumes") / share_name)
    if host and share_name:
        candidates.append(Path("/Volumes") / host / share_name)

    unique_candidates: list[Path] = []
    for candidate in candidates:
        if candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def find_mounted_dcim() -> Path | None:
    for mount_root in mount_candidates():
        dcim = mount_root / "DCIM"
        if dcim.exists():
            return dcim
    return None


def mount_nas() -> Path:
    mounted_dcim = find_mounted_dcim()
    if mounted_dcim is not None:
        log(f"NAS already mounted at {mounted_dcim}")
        console.print(f"[green]NAS already mounted:[/green] {mounted_dcim}")
        return mounted_dcim

    log(f"Mounting NAS from {SMB_URL} ...")
    console.print(f"[cyan]Mounting NAS[/cyan] from {SMB_URL}")
    result = subprocess.run(
        ["osascript", "-e", f'mount volume "{SMB_URL}"'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        log(f"Mount command exited with code {result.returncode}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}s"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Waiting for NAS mount", total=10)
        for _ in range(10):
            mounted_dcim = find_mounted_dcim()
            if mounted_dcim is not None:
                log(f"Mount ready at {mounted_dcim}")
                console.print(f"[green]Mount ready:[/green] {mounted_dcim}")
                return mounted_dcim
            time.sleep(1)
            progress.advance(task_id)

    log("Mount failed")
    console.print("[red]Mount failed[/red]")
    raise RuntimeError("NAS mount failed")


def run_command(args: list[str]) -> None:
    log(f"Running: {' '.join(args)}")
    subprocess.run(args, cwd=PROJECT_DIR, check=True)


def run_pipeline_step(description: str, args: list[str]) -> None:
    console.print(f"[bold blue]{description}[/bold blue]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description, total=None)
        run_command(args)
    console.print(f"[green]Done:[/green] {description}")


@app.command()
def ingest() -> None:
    """Run photo organization."""
    log("Running ingest ...")
    run_pipeline_step("Running ingest", [str(PYTHON_EXECUTABLE), "-m", "photo_organizer"])


@app.command()
def backup() -> None:
    """Run cloud copy and NAS backup."""
    log("Running backup ...")
    mounted_dcim = mount_nas()

    run_pipeline_step("Copying cloud-ready media", [str(PYTHON_EXECUTABLE), "copy_media_for_cloud.py"])
    run_pipeline_step(
        "Backing up to NAS",
        [
            str(PYTHON_EXECUTABLE),
            "network_backup.py",
            "--prune-source",
            "--dst",
            str(mounted_dcim),
        ]
    )


@app.command()
def clean() -> None:
    """Run network backup with prune enabled."""
    log("Running clean ...")
    mounted_dcim = mount_nas()

    run_pipeline_step(
        "Running network backup prune",
        [
            str(PYTHON_EXECUTABLE),
            "network_backup.py",
            "--prune-source",
            "--dst",
            str(mounted_dcim),
        ]
    )


@app.command()
def all() -> None:
    """Run the full pipeline."""
    log("Running full pipeline ...")
    console.rule("[bold]Photo Pipeline[/bold]")
    ingest()
    backup()


if __name__ == "__main__":
    log(f"===== Run started at {time.ctime()} =====")
    try:
        app()
    finally:
        log(f"===== Completed at {time.ctime()} =====")
