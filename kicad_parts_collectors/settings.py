from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    library_root: str = ""
    theme: str = "flatly"


def settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "KiCadPartsCollector" / "settings.json"

    return Path.home() / ".kicad_parts_collector" / "settings.json"


def load_settings(path: Path | None = None) -> AppSettings:
    target = path or settings_path()
    if not target.exists():
        return AppSettings()

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    return AppSettings(library_root=str(data.get("library_root", "")), theme=str(data.get("theme", "flatly")))


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"library_root": settings.library_root, "theme": settings.theme}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
