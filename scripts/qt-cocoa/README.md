# macOS Qt 접근성 수정

Qt 6.11.2 Cocoa의 합성 행/셀은 부모 표의 접근성 ID를 공유합니다.
원본 구현은 합성 요소 해제 시 부모 인터페이스까지 삭제합니다.
`ownership.patch`는 부모가 관리하는 요소가 공유 ID를 삭제하지 않도록 수정합니다.
접근성이나 셀 선택 기능을 비활성화하지 않습니다.

공식 소스: https://github.com/qt/qtbase/tree/v6.11.2/src/plugins/platforms/cocoa
Qt 원본 소스의 LGPL/GPL/상용 라이선스 조건은 수정한 플러그인에도 적용됩니다.

저장소 루트에서 Python 3.12 가상환경으로 실행합니다.

```sh
python -m pip install -r requirements.txt pyinstaller aqtinstall cmake ninja
bash scripts/build-qt-cocoa.sh "$(which python)"
python -m PyInstaller --clean -y KiCadPartsCollector.spec
```

스크립트는 공식 Qt 6.11.2 SDK와 소스를 build 아래에 받아 패치를 적용합니다.
회귀 테스트는 합성 셀 해제 후 부모 객체가 살아 있는지 확인하고,
선택된 셀 조회와 모델 재설정을 40회 반복합니다.
PyInstaller는 해당 플러그인을 포함하며, 플러그인이 없으면 빌드를 중단합니다.
macOS PySide6 버전은 ABI 일치를 위해 6.11.2로 고정합니다.
