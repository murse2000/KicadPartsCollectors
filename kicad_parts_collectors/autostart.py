from __future__ import annotations

import plistlib
import sys
from pathlib import Path

APP_NAME = "KiCadPartsCollector"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LAUNCH_AGENT_LABEL = "com.murse2000.KiCadPartsCollector"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


class AutostartError(Exception):
    pass


def current_launch_arguments() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]

    script = Path(__file__).resolve().parents[1] / "run_app.py"
    return [str(Path(sys.executable).resolve()), str(script)]


def current_launch_command() -> str:
    return " ".join(f'"{argument}"' for argument in current_launch_arguments())


def is_autostart_enabled() -> bool:
    if sys.platform == "darwin":
        return LAUNCH_AGENT_PATH.exists()

    try:
        import winreg
    except ImportError as exc:
        raise AutostartError("이 운영체제에서는 자동 실행을 설정할 수 없습니다.") from exc

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart_enabled(enabled: bool) -> None:
    if sys.platform == "darwin":
        try:
            if enabled:
                LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
                plist = {
                    "Label": LAUNCH_AGENT_LABEL,
                    "ProgramArguments": current_launch_arguments(),
                    "RunAtLoad": True,
                    "KeepAlive": False,
                }
                LAUNCH_AGENT_PATH.write_bytes(plistlib.dumps(plist))
            else:
                try:
                    LAUNCH_AGENT_PATH.unlink()
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise AutostartError(f"macOS 자동 실행 설정을 저장하지 못했습니다: {exc}") from exc
        return

    try:
        import winreg
    except ImportError as exc:
        raise AutostartError("이 운영체제에서는 자동 실행을 설정할 수 없습니다.") from exc

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, current_launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
