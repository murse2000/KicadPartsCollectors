#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${1:-python3}"
tools_dir="$(dirname "$("$python_bin" -c 'import sys; print(sys.executable)')")"
python_bin="$tools_dir/python"
qt_version=6.11.2
mkdir -p build
(cd build && "$python_bin" -m aqt install-qt mac desktop "$qt_version" clang_64 --archives qtbase -O qt-sdk)
curl -L --fail -o "build/qtbase-$qt_version.tar.gz" "https://github.com/qt/qtbase/archive/refs/tags/v$qt_version.tar.gz"
tar -xzf "build/qtbase-$qt_version.tar.gz" -C build
patch -d "build/qtbase-$qt_version" -p1 < scripts/qt-cocoa/ownership.patch
"$tools_dir/cmake" -S scripts/qt-cocoa -B build/qt-cocoa -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$tools_dir/ninja" \
  -DCMAKE_PREFIX_PATH="$PWD/build/qt-sdk/$qt_version/macos" \
  -DQTBASE_SOURCE_DIR="$PWD/build/qtbase-$qt_version" \
  -DCMAKE_OSX_ARCHITECTURES="$(uname -m)" \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 -DCMAKE_BUILD_TYPE=Release
"$tools_dir/cmake" --build build/qt-cocoa --parallel 8
QT_QPA_PLATFORM_PLUGIN_PATH="$PWD/build/qt-cocoa/plugins/platforms" build/qt-cocoa/ownership_test
