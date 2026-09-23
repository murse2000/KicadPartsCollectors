from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .collector import (
    CollectorError, LibraryEntry, _symbol_library_for, _footprint_library_for,
    _footprint_path_for_reference, _model_values, _replace_model_value,
    _property_entries,
)

KINDS = ("심볼", "풋프린트", "3D")


def find_kicad_cli() -> Path:
    candidates = []
    if sys.platform == "win32":
        root = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "KiCad"
        candidates.extend(sorted(root.glob("*/bin/kicad-cli.exe"),
                                 key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parts[-3])),
                                 reverse=True))
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"))
    found = shutil.which("kicad-cli")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CollectorError("KiCad 실행 도구를 찾을 수 없습니다. KiCad를 설치해 주세요. 3D 미리보기는 KiCad 9 이상이 필요합니다.")


def _run(cli: Path, *args: str) -> str:
    try:
        result = subprocess.run([str(cli), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except subprocess.TimeoutExpired as exc:
        raise CollectorError("미리보기 생성 시간이 120초를 초과했습니다.") from exc
    if result.returncode:
        raise CollectorError((result.stderr or result.stdout or "KiCad 렌더링 실패").strip()[-2000:])
    return result.stdout.strip()


def _preview_board(footprint: Path, root: Path, cli: Path) -> str:
    text = footprint.read_text(encoding="utf-8-sig")
    models = _model_values(text)
    if not models:
        raise CollectorError("이 풋프린트에는 연결된 3D 모델이 없습니다.")
    # 원본은 수정하지 않고 임시 보드에서만 모델 경로를 절대 경로로 바꾼다.
    for value in models:
        expanded = value.replace("${KIPRJMOD}", root.resolve().as_posix())
        expanded = os.path.expandvars(expanded)
        match = re.search(r"\$\{KICAD\d+_3DMODEL_DIR\}", expanded)
        if match:
            model_root = cli.parent.parent / "share/kicad/3dmodels"
            if sys.platform == "darwin":
                model_root = Path("/Library/Application Support/kicad/3dmodels")
            expanded = expanded.replace(match.group(), model_root.as_posix())
        path = Path(expanded.replace("\\", "/"))
        if not path.is_absolute():
            path = footprint.parent / path
        if not path.is_file():
            raise CollectorError(f"3D 모델 파일을 찾을 수 없습니다: {path}")
        if path.suffix.lower() not in (".step", ".stp", ".igs", ".iges"):
            replacement = next((path.with_suffix(ext) for ext in (".step", ".stp")
                                if path.with_suffix(ext).is_file()), None)
            if replacement is None:
                raise CollectorError(f"대화형 3D 미리보기에는 STEP 모델이 필요합니다: {path.name}")
            path = replacement
        text = _replace_model_value(text, value, path.resolve().as_posix())
    return ('(kicad_pcb (version 20240108) (generator "pcbnew") '
            '(general (thickness 1.6)) (paper "A4") '
            '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) '
            '(36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") '
            '(38 "B.Mask" user) (39 "F.Mask" user) (44 "Edge.Cuts" user) '
            '(46 "B.CrtYd" user) (47 "F.CrtYd" user) (48 "B.Fab" user) (49 "F.Fab" user)) '
            + text + ')')


def render_preview(root: Path, entry: LibraryEntry, kind: str) -> list[tuple[str, bytes]]:
    if kind not in KINDS:
        raise CollectorError("알 수 없는 미리보기 종류입니다.")
    cli = find_kicad_cli()
    with tempfile.TemporaryDirectory(prefix="kicad-preview-") as temp:
        directory = Path(temp)
        if kind == "심볼":
            source = _symbol_library_for(root).read_text(encoding="utf-8-sig")
            # 긴 URL 속성이 도형을 축소시키지 않도록 미리보기 사본에서만 제외한다.
            for prop in reversed(_property_entries(source)):
                if prop.name not in ("Reference", "Value"):
                    source = source[:prop.start] + source[prop.end:]
            symbol_library = directory / "preview.kicad_sym"
            symbol_library.write_text(source, encoding="utf-8")
            _run(cli, "sym", "export", "svg", "--symbol", entry.symbol,
                 "--output", str(directory), str(symbol_library))
        else:
            library = _footprint_library_for(root)
            footprint = _footprint_path_for_reference(entry.footprint, library, library.stem)
            if footprint is None or not footprint.is_file():
                raise CollectorError("연결된 풋프린트 파일을 찾을 수 없습니다.")
            if kind == "풋프린트":
                _run(cli, "fp", "export", "svg", "--footprint", footprint.stem,
                     "--layers", "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Fab,Edge.Cuts",
                     "--output", str(directory), str(library))
            else:
                version = _run(cli, "version")
                if int(version.split(".")[0]) < 9:
                    raise CollectorError("3D 미리보기에는 KiCad 9 이상이 필요합니다.")
                board = directory / "preview.kicad_pcb"
                board.write_text(_preview_board(footprint, root, cli), encoding="utf-8")
                output = directory / "3d.glb"
                _run(cli, "pcb", "export", "glb", "--no-board-body",
                     "--output", str(output), str(board))
                return [(entry.symbol, output.read_bytes())]
        files = sorted(directory.rglob("*.svg"))
        if not files:
            raise CollectorError("선택한 파트의 미리보기 이미지를 생성하지 못했습니다.")
        return [(file.stem, file.read_bytes()) for file in files]
