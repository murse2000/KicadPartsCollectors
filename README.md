# KiCad Parts Collector

KiCad Parts Collector는 ZIP 파일로 받은 KiCad 회로도 심볼, 풋프린트, 3D STEP 모델을 사내 KiCad 라이브러리 구조에 맞게 자동 정리해 주는 Windows/macOS 데스크톱 앱입니다.

부품 라이브러리를 여러 사람이 함께 관리할 때 반복되는 파일 복사, 심볼 병합, 풋프린트 연결, 3D 모델 경로 보정 작업을 줄이는 것이 목표입니다.

## 주요 기능

- ZIP 파일 드래그 앤 드롭 또는 파일 선택으로 부품 라이브러리 추가
- LCSC ID, Mouser 파트번호, 제조사 부품번호로 EasyEDA/JLCPCB 부품 데이터 가져오기
- 폴더 안의 ZIP 파일을 한 번에 처리하는 일괄 추가
- 지정한 수신 폴더를 감시하다가 ZIP 파일이 들어오면 자동 추가
- 처리된 ZIP 파일을 백업 폴더로 이동
- 심볼은 단일 `.kicad_sym` 라이브러리 파일에 병합
- 풋프린트는 단일 `.pretty` 폴더에 `.kicad_mod` 파일로 추가
- 3D 모델은 단일 `3dmodels` 폴더에 `.step` 또는 `.stp` 파일로 추가
- 심볼의 `Footprint` 속성을 자동 보정
- 풋프린트 내부 3D 모델 경로 자동 보정
- 라이브러리 연결 상태, 풋프린트 연결 상태, 3D 모델 연결 상태 확인
- 선택한 파츠의 속성 보기, 추가, 수정, 삭제
- 선택한 파츠 삭제 시 심볼, 풋프린트, 3D 모델 정리
- 시스템 트레이 상주, 최소화 시 트레이로 숨김
- Windows 시작 또는 macOS 로그인 시 자동 실행 옵션
- GitHub Releases 기반 온라인 업데이트

## 대상 라이브러리 구조

앱은 선택한 라이브러리 루트 폴더 아래에서 다음 구조를 사용합니다.

```text
library-root/
  symbols/
    hrobotics_symbol.kicad_sym
  footprints/
    hrobotics.pretty/
      PART_NAME.kicad_mod
  3dmodels/
    PART_NAME.step
```

심볼 라이브러리 파일명과 풋프린트 라이브러리 폴더명은 기존 라이브러리 상태에 맞춰 앱이 사용합니다. 풋프린트 참조는 KiCad 형식인 `라이브러리닉네임:풋프린트명`으로 저장됩니다.

## 기본 사용 흐름

1. 앱을 실행합니다.
2. 사내 KiCad 라이브러리 루트 폴더를 선택합니다.
3. ZIP 파일을 선택하거나 앱 위에 드래그 앤 드롭합니다.
4. `미리보기`로 추가될 심볼, 풋프린트, 3D 모델을 확인합니다.
5. `라이브러리에 추가`를 누릅니다.
6. 좌측 라이브러리 목록에서 연결 상태를 확인합니다.
7. 필요한 경우 우측 상세 패널에서 파츠 속성을 수정합니다.

LCSC 번호나 Mouser/제조사 부품번호로 바로 추가하려면 상단의 `LCSC/Mouser` 입력칸에 값을 넣고 `EasyEDA에서 가져오기`를 누릅니다.

## ZIP 처리 규칙

- ZIP 안의 `.kicad_sym`, `.kicad_mod`, `.step`, `.stp` 파일을 찾습니다.
- 심볼의 `Value` 속성을 기준 이름으로 사용합니다.
- `Value`가 없으면 심볼 이름을 기준으로 사용합니다.
- 심볼, 풋프린트, 3D 모델 파일명은 기준 이름에 맞춰 보정합니다.
- 심볼의 `Footprint` 값은 실제 풋프린트 라이브러리와 파일명에 맞게 자동 연결합니다.
- 풋프린트의 3D 모델 경로는 실제 STEP 파일 위치에 맞게 자동 보정합니다.
- 이미 같은 대상 파일이 있으면 덮어쓰지 않고 처리를 중단합니다.

## 감시 폴더 자동 추가

`감시 > 감시 시작`을 사용하면 지정한 수신 폴더를 주기적으로 확인합니다.

ZIP 파일이 수신 폴더에 들어오면 앱이 자동으로 라이브러리에 추가하고, 처리된 ZIP 파일은 백업 폴더로 이동합니다.

수신 폴더에 `easyeda_ids.txt`, `lcsc_ids.txt`, `easyeda_parts.txt`, `mouser_parts.txt`, `.lcsc`, `.parts` 파일을 넣으면 파일 안의 부품번호를 한 줄씩 읽어 EasyEDA/JLCPCB에서 자동으로 가져옵니다. `#` 뒤의 내용은 주석으로 처리합니다.

감시를 시작하려면 먼저 라이브러리 위치가 선택되어 있어야 합니다.

## 온라인 업데이트

앱의 `도움말 > 업데이트 확인` 메뉴는 GitHub Releases의 최신 버전을 확인합니다.

현재 실행 중인 버전보다 높은 Release가 있으면 현재 운영체제에 맞는 asset을 다운로드하고 업데이트를 진행합니다.

Release asset 이름은 다음과 같아야 합니다.

```text
Windows: KiCadPartsCollector.exe
macOS: KiCadPartsCollector.dmg, KiCadPartsCollector-macOS.dmg, KiCadPartsCollector.app.zip
```

## 다운로드

최신 실행파일은 GitHub Releases에서 받을 수 있습니다.

```text
https://github.com/murse2000/KicadPartsCollectors/releases
```

## 개발 환경에서 실행

```powershell
python -m pip install -r requirements.txt
python -m kicad_parts_collectors.main
```

## 빌드

Windows와 macOS는 같은 소스 코드와 같은 `KiCadPartsCollector.spec` 파일을 사용합니다. 빌드는 대상 운영체제에서 실행해야 합니다.

### Windows

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean -y KiCadPartsCollector.spec
```

빌드 결과는 다음 위치에 생성됩니다.

```text
dist\KiCadPartsCollector.exe
```

### macOS

```bash
python3 -m pip install pyinstaller
python3 -m PyInstaller --clean -y KiCadPartsCollector.spec
```

빌드 결과는 다음 위치에 생성됩니다.

```text
dist/KiCadPartsCollector.app
```

GitHub Release에 올릴 ZIP 파일이 필요하면 macOS에서 다음 명령으로 생성합니다.

```bash
ditto -c -k --sequesterRsrc --keepParent dist/KiCadPartsCollector.app dist/KiCadPartsCollector.app.zip
```

## 새 버전 배포

1. `kicad_parts_collectors/version.py`의 `APP_VERSION`을 올립니다.
2. 변경 사항을 `main` 브랜치에 커밋하고 푸시합니다.
3. `v버전` 형식의 Git 태그를 만들고 푸시합니다.
4. GitHub Actions가 Windows/macOS 빌드를 실행하고 Release asset을 자동 업로드합니다.

```powershell
git tag v1.0.8
git push origin v1.0.8
```

자동 Release asset 이름은 다음과 같습니다.

```text
KiCadPartsCollector.exe
KiCadPartsCollector.app.zip
```

## 테스트

```powershell
python -m unittest discover -s tests
```

## 상태 파일

사용자 설정은 운영체제별 사용자 설정 폴더에 저장됩니다.

```text
Windows: %APPDATA%\KiCadPartsCollector\settings.json
macOS: ~/Library/Application Support/KiCadPartsCollector/settings.json
```

저장되는 주요 설정은 마지막 라이브러리 위치, 테마, 수신 폴더, 백업 폴더입니다.

## 참고

이 앱은 사내 KiCad 라이브러리를 일정한 구조로 유지하는 업무용 도구입니다. 라이브러리에 추가하기 전에는 `미리보기`와 연결 상태 표를 통해 대상 파일과 연결 상태를 확인하는 것을 권장합니다.
