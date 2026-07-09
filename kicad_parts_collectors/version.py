from __future__ import annotations

import sys


APP_VERSION = "1.0.7"
GITHUB_OWNER = "murse2000"
GITHUB_REPO = "KicadPartsCollectors"


def release_asset_names(platform: str | None = None) -> tuple[str, ...]:
    target = platform or sys.platform
    if target == "darwin":
        return (
            "KiCadPartsCollector.dmg",
            "KiCadPartsCollector-macOS.dmg",
            "KiCadPartsCollector.app.zip",
        )
    if target == "win32":
        return ("KiCadPartsCollector.exe",)
    return ("KiCadPartsCollector.tar.gz", "KiCadPartsCollector.zip")


RELEASE_ASSET_NAME = release_asset_names()[0]
