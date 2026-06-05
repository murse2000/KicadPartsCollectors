# KiCad Parts Collector

ZIP 파일로 받은 KiCad 심볼, 풋프린트, 3D STEP 파일을 사내 라이브러리 폴더에 추가하는 파이썬 데스크톱 앱입니다.

## 실행

```powershell
python -m pip install -r requirements.txt
python -m kicad_parts_collectors.main
```

## 단일 실행파일

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean -y KiCadPartsCollector.spec
```

생성된 실행파일은 `dist\KiCadPartsCollector.exe`입니다.

## 배포와 업데이트

앱의 현재 버전은 `kicad_parts_collectors/version.py`의 `APP_VERSION`에서 관리합니다.

GitHub Releases에 새 버전을 배포하려면:

1. `APP_VERSION`을 새 버전으로 변경합니다.
2. 실행파일을 빌드합니다.
3. GitHub에서 `v버전` 태그로 Release를 생성합니다.
4. Release asset으로 `dist\KiCadPartsCollector.exe`를 업로드합니다.

앱의 `도움말 > 업데이트 확인`은 GitHub 최신 Release를 확인하고, 현재 버전보다 높으면 `KiCadPartsCollector.exe` asset을 다운로드해 업데이트합니다.

## 처리 규칙

- `.kicad_sym` 파일은 선택한 라이브러리 위치 안의 단일 `.kicad_sym` 파일에 병합합니다.
- `.kicad_mod` 파일은 선택한 라이브러리 위치 안의 단일 `.pretty` 폴더에 추가합니다.
- 파일명과 내부 참조 이름은 ZIP 안의 심볼 `Value` 값을 기준으로 통일합니다. `Value`가 없으면 심볼 이름을 사용합니다.
- 심볼의 `Footprint` 값은 `.pretty` 폴더명과 `.kicad_mod` 파일명을 사용해 `라이브러리닉네임:풋프린트명` 형식으로 자동 연결합니다.
- `.step`, `.stp` 파일은 `3dmodels` 폴더에 바로 추가합니다.
- 풋프린트의 3D 모델 경로는 실제 STEP 파일의 절대경로로 자동 보정하고, 공백이 포함된 경로도 KiCad가 읽을 수 있도록 따옴표로 감쌉니다.
- 이미 같은 대상 파일이 있으면 덮어쓰지 않고 중단합니다.
- 라이브러리 연결 상태 표에서 선택한 항목을 삭제하면 심볼 블록과 라이브러리 내부에 있는 연결 footprint/3D 모델 파일을 함께 정리합니다.
- `폴더 일괄 추가`로 선택한 폴더 안의 ZIP 파일들을 순서대로 추가하고, 각 ZIP의 성공/실패 결과를 표로 확인할 수 있습니다.
- `감시 시작`을 누르면 실행파일 옆의 `incoming_zips` 폴더를 감시합니다. ZIP 파일이 들어오면 자동으로 추가하고 `processed_zips` 폴더로 이동해 백업합니다.
- 최소화하면 작업표시줄에서 숨겨지고 시스템 트레이에서 계속 실행됩니다.
- 시스템 트레이 메뉴에서 창 열기, 감시 시작/중지, Windows 시작 시 자동 실행, 종료를 사용할 수 있습니다.
- 라이브러리 추가가 완료되면 시스템 알림을 표시합니다.
- 마지막으로 선택한 라이브러리 폴더는 `%APPDATA%\KiCadPartsCollector\settings.json`에 저장되어 다음 실행 때 자동으로 복원됩니다.
- `도움말 > 업데이트 확인`으로 GitHub Releases에 올라온 최신 실행파일을 설치할 수 있습니다.

## 테스트

```powershell
python -m unittest discover -s tests
```
