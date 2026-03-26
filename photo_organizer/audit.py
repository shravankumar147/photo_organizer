from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class RunAudit:
    command: str
    folder: Path
    source_root: Path | None = None
    destination_root: Path | None = None
    config_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, **entry: Any) -> None:
        self.entries.append(entry)

    def write(self, stats: dict[str, Any]) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        finished_at = datetime.now(UTC)
        stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        payload = {
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "config_path": self.config_path,
            "source_root": str(self.source_root) if self.source_root else None,
            "destination_root": str(self.destination_root) if self.destination_root else None,
            "metadata": self.metadata,
            "stats": stats,
            "entries": self.entries,
        }
        target = self.folder / f"{stamp}-{self.command}.json"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=self.folder,
            prefix=f".{stamp}-{self.command}-",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            temp_path = Path(handle.name)
        temp_path.replace(target)
        return target
