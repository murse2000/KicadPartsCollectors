from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from .version import GITHUB_OWNER, GITHUB_REPO, RELEASE_ASSET_NAME, release_asset_names


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    title: str
    body: str
    page_url: str
    asset: ReleaseAsset


def latest_release_api_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def is_newer_version(latest: str, current: str) -> bool:
    return _version_key(latest) > _version_key(current)


def fetch_latest_release() -> ReleaseInfo:
    request = urllib.request.Request(
        latest_release_api_url(),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "KiCadPartsCollector",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise UpdateError(f"업데이트 정보를 가져오지 못했습니다: {exc}") from exc

    asset = _release_asset(data.get("assets", []))
    if asset is None:
        expected = ", ".join(release_asset_names())
        raise UpdateError(f"Release에서 현재 운영체제용 파일을 찾지 못했습니다: {expected}")

    tag_name = str(data.get("tag_name", ""))
    return ReleaseInfo(
        version=tag_name.lstrip("vV"),
        title=str(data.get("name") or tag_name),
        body=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or ""),
        asset=asset,
    )


def download_release_asset(asset: ReleaseAsset) -> Path:
    target_dir = Path(tempfile.gettempdir()) / f"KiCadPartsCollector_update_{uuid.uuid4().hex}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset.name
    request = urllib.request.Request(asset.url, headers={"User-Agent": "KiCadPartsCollector"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            target.write_bytes(response.read())
    except Exception as exc:
        raise UpdateError(f"업데이트 파일을 다운로드하지 못했습니다: {exc}") from exc

    _verify_digest(target, asset.digest)
    return target


def install_downloaded_update(downloaded_exe: Path, current_exe: Path) -> None:
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", str(downloaded_exe)])
        except OSError as exc:
            raise UpdateError(f"업데이트 파일을 열지 못했습니다: {exc}") from exc
        return

    if sys.platform != "win32":
        raise UpdateError("자동 교체 업데이트는 Windows와 macOS 패키지에서만 지원합니다.")

    script = Path(tempfile.gettempdir()) / "KiCadPartsCollector_update.cmd"
    app_dir = current_exe.parent
    script.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "SRC={downloaded_exe}"',
                f'set "DST={current_exe}"',
                f'set "APPDIR={app_dir}"',
                'set "PYINSTALLER_RESET_ENVIRONMENT=1"',
                ":wait",
                "timeout /t 1 /nobreak >nul",
                'copy /Y "%SRC%" "%DST%" >nul',
                "if errorlevel 1 goto wait",
                "timeout /t 2 /nobreak >nul",
                'start "" /D "%APPDIR%" "%DST%"',
                "endlocal",
            ]
        ),
        encoding="utf-8",
        newline="\r\n",
    )
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        cwd=app_dir,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=env,
    )


def _release_asset(assets: list[dict], platform: str | None = None) -> ReleaseAsset | None:
    expected_names = tuple(name.lower() for name in release_asset_names(platform))
    exact_matches = [asset for asset in assets if str(asset.get("name", "")).lower() in expected_names]
    extension_matches = [asset for asset in assets if _asset_matches_platform(str(asset.get("name", "")), platform)]
    selected = (exact_matches or extension_matches or [None])[0]
    if selected is None:
        return None

    return ReleaseAsset(
        name=str(selected.get("name", "")),
        url=str(selected.get("browser_download_url", "")),
        digest=str(selected.get("digest", "")),
    )


def _asset_matches_platform(name: str, platform: str | None = None) -> bool:
    lower_name = name.lower()
    target = platform or sys.platform
    if target == "darwin":
        return lower_name.endswith((".dmg", ".app.zip"))
    if target == "win32":
        return lower_name.endswith(".exe")
    return lower_name.endswith((".tar.gz", ".zip"))


def _verify_digest(path: Path, digest: str) -> None:
    if not digest.startswith("sha256:"):
        return

    expected = digest.split(":", 1)[1].lower()
    actual = hashlib.sha256(path.read_bytes()).hexdigest().lower()
    if actual != expected:
        raise UpdateError("다운로드한 업데이트 파일의 해시가 일치하지 않습니다.")


def _version_key(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    parts: list[int] = []
    for raw_part in cleaned.split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits or "0"))

    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)
