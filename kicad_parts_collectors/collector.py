from __future__ import annotations

import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class InstallItem:
    source: str
    destination: Path
    kind: str


@dataclass(frozen=True)
class LibraryEntry:
    symbol: str
    value: str
    footprint: str
    footprint_ok: bool
    model: str
    model_ok: bool


@dataclass(frozen=True)
class RemovalResult:
    symbols: int
    footprints: int
    models: int


@dataclass(frozen=True)
class BatchInstallResult:
    zip_path: Path
    ok: bool
    message: str
    items: int


@dataclass(frozen=True)
class WatchFolders:
    incoming: Path
    processed: Path


class CollectorError(Exception):
    pass


def build_install_plan(zip_path: Path, library_root: Path) -> list[InstallItem]:
    zip_path = Path(zip_path)
    library_root = Path(library_root)
    items: list[InstallItem] = []
    destinations: set[Path] = set()

    with zipfile.ZipFile(zip_path) as archive:
        package_name = _package_name_for(archive, zip_path)
        part_name = _part_name_for(archive, package_name)
        symbol_library = _symbol_library_for(library_root)
        footprint_library = _footprint_library_for(library_root)
        for info in archive.infolist():
            if info.is_dir():
                continue

            source = _safe_zip_path(info.filename)
            destination, kind = _destination_for(source, library_root, package_name, part_name, symbol_library, footprint_library)
            if destination is None:
                continue

            if kind != "symbol" and destination in destinations:
                raise CollectorError(f"ZIP 내부 대상 경로가 중복됩니다: {destination}")
            if kind != "symbol" and destination.exists():
                raise CollectorError(f"이미 파일이 존재합니다: {destination}")
            if kind == "symbol":
                _ensure_new_symbols(archive.read(info.filename), destination)

            destinations.add(destination)
            items.append(InstallItem(info.filename, destination, kind))

    if not items:
        raise CollectorError("추가할 KiCad 파일을 찾지 못했습니다.")

    return items


def install_zip(zip_path: Path, library_root: Path) -> list[InstallItem]:
    items = build_install_plan(zip_path, library_root)

    with zipfile.ZipFile(zip_path) as archive:
        footprint_library = _footprint_library_for(Path(library_root))
        part_name = _part_name_for(archive, _package_name_for(archive, Path(zip_path)))
        footprint_references = _footprint_references_for(archive, footprint_library, part_name)
        model_references = _model_references_for(archive, footprint_library, Path(library_root) / "3dmodels", part_name)
        for item in items:
            if item.kind == "symbol":
                _merge_symbol_file(archive.read(item.source), item.destination, footprint_references)
                continue

            if item.kind == "footprint":
                _write_footprint_file(archive.read(item.source), item.destination, item.destination.stem, model_references)
                continue

            item.destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item.source) as source_file:
                with item.destination.open("wb") as destination_file:
                    shutil.copyfileobj(source_file, destination_file)

    return items


def install_zip_directory(zip_directory: Path, library_root: Path) -> list[BatchInstallResult]:
    zip_directory = Path(zip_directory)
    if not zip_directory.exists() or not zip_directory.is_dir():
        raise CollectorError("ZIP 파일이 들어있는 폴더를 선택하세요.")

    zip_paths = sorted(zip_directory.glob("*.zip"))
    if not zip_paths:
        raise CollectorError("선택한 폴더에서 ZIP 파일을 찾지 못했습니다.")

    results: list[BatchInstallResult] = []
    for zip_path in zip_paths:
        try:
            items = install_zip(zip_path, library_root)
            results.append(BatchInstallResult(zip_path, True, "추가 완료", len(items)))
        except Exception as exc:
            results.append(BatchInstallResult(zip_path, False, str(exc), 0))

    return results


def app_base_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent

    return Path(__file__).resolve().parents[1]


def ensure_watch_folders(base_directory: Path | None = None) -> WatchFolders:
    base = Path(base_directory) if base_directory is not None else app_base_directory()
    incoming = base / "incoming_zips"
    processed = base / "processed_zips"
    incoming.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    return WatchFolders(incoming, processed)


def process_watch_folder(library_root: Path, folders: WatchFolders) -> list[BatchInstallResult]:
    results: list[BatchInstallResult] = []
    for zip_path in sorted(folders.incoming.glob("*.zip")):
        if not _is_stable_file(zip_path):
            continue

        try:
            items = install_zip(zip_path, library_root)
            results.append(BatchInstallResult(zip_path, True, "자동 추가 완료", len(items)))
            _move_to_processed(zip_path, folders.processed, False)
        except Exception as exc:
            results.append(BatchInstallResult(zip_path, False, str(exc), 0))
            _move_to_processed(zip_path, folders.processed, True)

    return results


def summarize_items(items: list[InstallItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return counts


def scan_library(library_root: Path) -> list[LibraryEntry]:
    library_root = Path(library_root)
    symbol_library = _symbol_library_for(library_root)
    footprint_library = _footprint_library_for(library_root)
    nickname = footprint_library.stem
    entries: list[LibraryEntry] = []
    symbol_text = symbol_library.read_text(encoding="utf-8-sig")

    for block in _symbol_blocks(symbol_text):
        symbol_name = _symbol_name(block)
        if symbol_name is None:
            continue

        value = _property_value(block, "Value") or symbol_name
        footprint = _property_value(block, "Footprint") or ""
        footprint_path = _footprint_path_for_reference(footprint, footprint_library, nickname)
        footprint_ok = footprint_path is not None and footprint_path.exists()
        model = ""
        model_ok = False

        if footprint_ok and footprint_path is not None:
            footprint_text = footprint_path.read_text(encoding="utf-8-sig")
            model_values = _model_values(footprint_text)
            if model_values:
                model = model_values[0]
                model_ok = _model_exists(model, footprint_library)

        entries.append(LibraryEntry(symbol_name, value, footprint, footprint_ok, model, model_ok))

    return entries


def remove_library_entries(library_root: Path, symbols: list[str]) -> RemovalResult:
    library_root = Path(library_root)
    symbol_library = _symbol_library_for(library_root)
    footprint_library = _footprint_library_for(library_root)
    nickname = footprint_library.stem
    targets = set(symbols)
    text = symbol_library.read_text(encoding="utf-8-sig")
    removed_symbols = 0
    removed_footprints = 0
    removed_models = 0

    for block in _symbol_blocks(text):
        symbol_name = _symbol_name(block)
        if symbol_name not in targets:
            continue

        footprint = _property_value(block, "Footprint") or ""
        candidate_names = _asset_candidate_names(block)
        footprint_path = _footprint_path_for_reference(footprint, footprint_library, nickname)
        if footprint_path is not None and _is_inside(footprint_path, library_root) and footprint_path.exists():
            removed_models += _remove_models_from_footprint(footprint_path, footprint_library, library_root)
            removed_footprints += _remove_file_once(footprint_path, library_root)

        for name in candidate_names:
            removed_footprints += _remove_file_once(footprint_library / f"{name}.kicad_mod", library_root)
            removed_models += _remove_matching_models(library_root / "3dmodels", name, library_root)

        text = text.replace(block, "", 1)
        removed_symbols += 1

    if removed_symbols == 0:
        raise CollectorError("삭제할 심볼을 찾지 못했습니다.")

    symbol_library.write_text(_clean_symbol_library_text(text), encoding="utf-8", newline="\n")
    return RemovalResult(removed_symbols, removed_footprints, removed_models)


def _safe_zip_path(raw_name: str) -> PurePosixPath:
    normalized = PurePosixPath(raw_name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise CollectorError(f"안전하지 않은 ZIP 경로입니다: {raw_name}")
    return normalized


def _footprint_path_for_reference(reference: str, footprint_library: Path, nickname: str) -> Path | None:
    if not reference:
        return None

    if ":" in reference:
        reference_nickname, footprint_name = reference.split(":", 1)
        if reference_nickname != nickname:
            return None
    else:
        footprint_name = reference

    return footprint_library / f"{footprint_name}.kicad_mod"


def _model_exists(model_value: str, footprint_library: Path) -> bool:
    model_path = _model_path_for_value(model_value, footprint_library)
    return model_path is not None and model_path.exists()


def _model_path_for_value(model_value: str, footprint_library: Path) -> Path | None:
    if not model_value:
        return None

    model_path = Path(model_value.replace("\\", "/"))
    if model_path.is_absolute():
        return model_path

    return (footprint_library / model_path).resolve()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _clean_symbol_library_text(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines).rstrip() + "\n"


def _asset_candidate_names(symbol_block: str) -> set[str]:
    names: set[str] = set()
    symbol_name = _symbol_name(symbol_block)
    value = _property_value(symbol_block, "Value")
    footprint = _property_value(symbol_block, "Footprint")

    for name in (symbol_name, value, footprint):
        if not name:
            continue
        names.add(name.split(":")[-1])

    return names


def _remove_models_from_footprint(footprint_path: Path, footprint_library: Path, library_root: Path) -> int:
    removed = 0
    footprint_text = footprint_path.read_text(encoding="utf-8-sig")
    for model in _model_values(footprint_text):
        model_path = _model_path_for_value(model, footprint_library)
        if model_path is not None:
            removed += _remove_file_once(model_path, library_root)
    return removed


def _remove_matching_models(model_directory: Path, name: str, library_root: Path) -> int:
    removed = 0
    for suffix in (".step", ".stp"):
        removed += _remove_file_once(model_directory / f"{name}{suffix}", library_root)
    return removed


def _remove_file_once(path: Path, library_root: Path) -> int:
    if not _is_inside(path, library_root) or not path.exists() or not path.is_file():
        return 0

    path.unlink()
    return 1


def _is_stable_file(path: Path) -> bool:
    try:
        first = path.stat().st_size
        second = path.stat().st_size
    except OSError:
        return False

    return first > 0 and first == second and zipfile.is_zipfile(path)


def _move_to_processed(zip_path: Path, processed_directory: Path, failed: bool) -> Path:
    suffix = "_failed" if failed else ""
    destination = processed_directory / f"{zip_path.stem}{suffix}{zip_path.suffix}"
    if destination.exists():
        destination = processed_directory / f"{zip_path.stem}{suffix}_{_timestamp()}{zip_path.suffix}"

    return zip_path.rename(destination)


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _destination_for(
    source: PurePosixPath,
    library_root: Path,
    package_name: str,
    part_name: str,
    symbol_library: Path,
    footprint_library: Path,
) -> tuple[Path | None, str]:
    suffix = source.suffix.lower()

    if suffix == ".kicad_sym":
        return symbol_library, "symbol"

    if suffix == ".kicad_mod":
        return footprint_library / f"{part_name}.kicad_mod", "footprint"

    if suffix in {".step", ".stp"}:
        return library_root / "3dmodels" / f"{part_name}{suffix}", "3d_model"

    return None, "ignored"


def _symbol_library_for(library_root: Path) -> Path:
    if library_root.suffix.lower() == ".kicad_sym":
        return library_root

    candidates = _existing_paths([
        *library_root.glob("*.kicad_sym"),
        *((library_root / "symbols").glob("*.kicad_sym") if (library_root / "symbols").is_dir() else []),
    ])
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise CollectorError("단일 심볼 라이브러리 파일을 찾지 못했습니다. 라이브러리 폴더 안에 .kicad_sym 파일이 하나 있어야 합니다.")

    raise CollectorError("심볼 라이브러리 파일이 여러 개입니다. 하나의 .kicad_sym 파일만 있는 폴더를 선택하세요.")


def _footprint_library_for(library_root: Path) -> Path:
    if library_root.suffix.lower() == ".pretty":
        return library_root

    candidates = _existing_paths([
        *library_root.glob("*.pretty"),
        *((library_root / "footprints").glob("*.pretty") if (library_root / "footprints").is_dir() else []),
    ])
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise CollectorError("단일 풋프린트 라이브러리 폴더를 찾지 못했습니다. 라이브러리 폴더 안에 .pretty 폴더가 하나 있어야 합니다.")

    raise CollectorError("풋프린트 라이브러리 폴더가 여러 개입니다. 하나의 .pretty 폴더만 있는 폴더를 선택하세요.")


def _existing_paths(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.exists()]


def _ensure_new_symbols(source_bytes: bytes, destination: Path) -> None:
    source_text = source_bytes.decode("utf-8-sig")
    destination_text = destination.read_text(encoding="utf-8-sig")
    existing_names = set(_symbol_names(destination_text))

    for name in _symbol_names(source_text):
        if name in existing_names:
            raise CollectorError(f"이미 심볼이 존재합니다: {name}")


def _merge_symbol_file(source_bytes: bytes, destination: Path, footprint_references: dict[str, str]) -> None:
    source_text = _link_symbol_footprints(source_bytes.decode("utf-8-sig"), footprint_references)
    destination_text = destination.read_text(encoding="utf-8-sig")
    symbol_blocks = _symbol_blocks(source_text)
    if not symbol_blocks:
        raise CollectorError("심볼 파일에서 추가할 symbol 블록을 찾지 못했습니다.")

    insert_at = _last_top_level_close(destination_text)
    merged = destination_text[:insert_at].rstrip() + "\n" + "\n".join(symbol_blocks) + "\n" + destination_text[insert_at:]
    destination.write_text(merged, encoding="utf-8", newline="\n")


def _footprint_references_for(archive: zipfile.ZipFile, footprint_library: Path, part_name: str) -> dict[str, str]:
    nickname = footprint_library.stem
    references: dict[str, str] = {}
    reference = f"{nickname}:{part_name}"

    for info in archive.infolist():
        if info.is_dir():
            continue

        source = _safe_zip_path(info.filename)
        if source.suffix.lower() == ".kicad_mod":
            references[source.stem] = reference
            references[part_name] = reference
        if source.suffix.lower() == ".kicad_sym":
            text = archive.read(info.filename).decode("utf-8-sig")
            for name in _symbol_names(text):
                references[name] = reference

    return references


def _model_references_for(archive: zipfile.ZipFile, footprint_library: Path, model_directory: Path, part_name: str) -> dict[str, str]:
    references: dict[str, str] = {}

    for info in archive.infolist():
        if info.is_dir():
            continue

        source = _safe_zip_path(info.filename)
        if source.suffix.lower() in {".step", ".stp"}:
            model_name = f"{part_name}{source.suffix.lower()}"
            references[source.name] = _model_path(model_directory / model_name)
            references[source.stem] = references[source.name]
            references[part_name] = references[source.name]

    return references


def _model_path(model_path: Path) -> str:
    return model_path.resolve().as_posix()


def _write_footprint_file(source_bytes: bytes, destination: Path, footprint_name: str, model_references: dict[str, str]) -> None:
    text = source_bytes.decode("utf-8-sig")
    text = _rename_footprint(text, footprint_name)
    text = _link_footprint_models(text, model_references)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="\n")


def _rename_footprint(text: str, footprint_name: str) -> str:
    text = _replace_named_sexpr_head(text, "footprint", footprint_name)
    text = _replace_named_sexpr_head(text, "module", footprint_name)
    text = _replace_fp_text_value(text, footprint_name)
    return text


def _replace_named_sexpr_head(text: str, head: str, value: str) -> str:
    start = text.find(f"({head} ")
    if start < 0:
        return text

    value_start = start + len(f"({head} ")
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1

    if value_start < len(text) and text[value_start] == '"':
        value_start += 1
        value_end = _quoted_value_end(text, value_start)
        return text[:value_start] + _escape_symbol_value(value) + text[value_end:]

    value_end = value_start
    while value_end < len(text) and not text[value_end].isspace() and text[value_end] != ")":
        value_end += 1

    return text[:value_start] + value + text[value_end:]


def _replace_fp_text_value(text: str, value: str) -> str:
    marker = "(fp_text value "
    start = text.find(marker)
    if start < 0:
        return text

    value_start = start + len(marker)
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1

    if value_start < len(text) and text[value_start] == '"':
        value_start += 1
        value_end = _quoted_value_end(text, value_start)
        return text[:value_start] + _escape_symbol_value(value) + text[value_end:]

    value_end = value_start
    while value_end < len(text) and not text[value_end].isspace() and text[value_end] != ")":
        value_end += 1

    return text[:value_start] + value + text[value_end:]


def _link_footprint_models(text: str, model_references: dict[str, str]) -> str:
    model_values = _model_values(text)
    if not model_values or not model_references:
        return text

    linked_text = text
    for value in model_values:
        model_name = Path(value.replace("\\", "/")).name
        model_stem = Path(model_name).stem
        reference = model_references.get(model_name) or model_references.get(model_stem)

        if reference is None and len({item for key, item in model_references.items() if "." in key}) == 1:
            reference = next(item for key, item in model_references.items() if "." in key)

        if reference is None:
            raise CollectorError(f"footprint 3D 모델 경로를 자동 연결할 수 없습니다: {value}")

        linked_text = _replace_model_value(linked_text, value, reference)

    return linked_text


def _model_values(text: str) -> list[str]:
    values: list[str] = []
    index = 0

    while True:
        start = text.find("(model ", index)
        if start < 0:
            return values

        value_start = start + len("(model ")
        while value_start < len(text) and text[value_start].isspace():
            value_start += 1

        if value_start < len(text) and text[value_start] == '"':
            value_start += 1
            value_end = _quoted_value_end(text, value_start)
        else:
            value_end = value_start
            while value_end < len(text) and not text[value_end].isspace() and text[value_end] != ")":
                value_end += 1

        values.append(text[value_start:value_end])
        index = value_end


def _replace_model_value(text: str, old_value: str, new_value: str) -> str:
    quoted_new = f'"{_escape_symbol_value(new_value)}"'
    quoted_old = f'"{old_value}"'
    if quoted_old in text:
        return text.replace(quoted_old, quoted_new, 1)

    return text.replace(f"(model {old_value}", f"(model {quoted_new}", 1)


def _link_symbol_footprints(text: str, footprint_references: dict[str, str]) -> str:
    if not footprint_references:
        return text

    blocks = _symbol_blocks(text)
    if not blocks:
        return text

    linked_text = text
    for block in blocks:
        linked_block = _link_symbol_block_footprint(block, footprint_references)
        linked_text = linked_text.replace(block, linked_block, 1)

    return linked_text


def _link_symbol_block_footprint(block: str, footprint_references: dict[str, str]) -> str:
    footprint_value = _property_value(block, "Footprint")
    if footprint_value is None:
        return block

    footprint_name = footprint_value.split(":")[-1]
    reference = footprint_references.get(footprint_name)

    unique_references = set(footprint_references.values())
    if reference is None and len(unique_references) == 1:
        reference = next(iter(unique_references))

    if reference is None:
        raise CollectorError(f"심볼 Footprint 값을 자동 연결할 수 없습니다: {footprint_value}")

    return _replace_property_value(block, "Footprint", reference)


def _property_value(text: str, property_name: str) -> str | None:
    marker = f'(property "{property_name}" "'
    start = text.find(marker)
    if start < 0:
        return None

    start += len(marker)
    end = _quoted_value_end(text, start)
    return text[start:end]


def _replace_property_value(text: str, property_name: str, value: str) -> str:
    marker = f'(property "{property_name}" "'
    start = text.find(marker)
    if start < 0:
        return text

    start += len(marker)
    end = _quoted_value_end(text, start)
    return text[:start] + _escape_symbol_value(value) + text[end:]


def _quoted_value_end(text: str, start: int) -> int:
    escaped = False
    index = start
    while index < len(text):
        char = text[index]
        if char == '"' and not escaped:
            return index
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
        index += 1

    raise CollectorError("심볼 속성 값을 해석하지 못했습니다.")


def _escape_symbol_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _symbol_names(text: str) -> list[str]:
    names: list[str] = []
    for block in _symbol_blocks(text):
        name = _symbol_name(block)
        if name is not None:
            names.append(name)
    return names


def _symbol_name(block: str) -> str | None:
    marker = '(symbol "'
    start = block.find(marker)
    if start < 0:
        return None

    start += len(marker)
    end = _quoted_value_end(block, start)
    return block[start:end]


def _symbol_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if char == '"' and not escaped:
                in_string = False
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            continue

        if char == '"':
            in_string = True
            escaped = False
            continue

        if char == "(":
            if depth == 1 and _starts_symbol(text, index):
                start = _line_start(text, index)
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 1 and start is not None:
                blocks.append(text[start : index + 1].strip("\r\n"))
                start = None

    return blocks


def _starts_symbol(text: str, index: int) -> bool:
    return text[index : index + 8] == "(symbol "


def _line_start(text: str, index: int) -> int:
    line_start = text.rfind("\n", 0, index)
    return 0 if line_start < 0 else line_start + 1


def _last_top_level_close(text: str) -> int:
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if char == '"' and not escaped:
                in_string = False
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            continue

        if char == '"':
            in_string = True
            escaped = False
            continue

        if char == "(":
            depth += 1
            continue

        if char == ")":
            if depth == 1:
                return index
            depth -= 1

    raise CollectorError("심볼 라이브러리 파일 구조를 해석하지 못했습니다.")


def _package_name_for(archive: zipfile.ZipFile, zip_path: Path) -> str:
    for info in archive.infolist():
        if info.is_dir():
            continue

        source = _safe_zip_path(info.filename)
        if source.suffix.lower() in {".kicad_sym", ".kicad_mod", ".step", ".stp"} and _has_package_root(source):
            return source.parts[0]

    return zip_path.stem


def _part_name_for(archive: zipfile.ZipFile, fallback: str) -> str:
    value_names: list[str] = []
    symbol_names: list[str] = []

    for info in archive.infolist():
        if info.is_dir():
            continue

        source = _safe_zip_path(info.filename)
        if source.suffix.lower() != ".kicad_sym":
            continue

        text = archive.read(info.filename).decode("utf-8-sig")
        for block in _symbol_blocks(text):
            value = _property_value(block, "Value")
            if value:
                value_names.append(value)
        symbol_names.extend(_symbol_names(text))

    unique_names = sorted(set(value_names or symbol_names))
    if len(unique_names) == 1:
        return unique_names[0]

    if len(unique_names) > 1:
        raise CollectorError("ZIP 안에 심볼이 여러 개라 공통 파일명을 자동 결정할 수 없습니다.")

    return fallback


def _has_package_root(source: PurePosixPath) -> bool:
    if len(source.parts) < 3:
        return False

    return source.parts[1].lower() in {"kicad", "3d"}


def _find_parent_with_suffix(source: PurePosixPath, suffix: str) -> str | None:
    for parent in reversed(source.parts[:-1]):
        if parent.lower().endswith(suffix):
            return parent
    return None
