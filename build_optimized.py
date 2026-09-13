#!/usr/bin/env python3
"""
WaveLab 폐쇄망용 PyInstaller 빌드 스크립트.

기본값은 one-file EXE입니다. 개발/검증 시에는
    python build_optimized.py --mode onedir
최종 배포 시에는
    python build_optimized.py --mode onefile
을 사용합니다.

빌드 머신에서만 PyInstaller와 애플리케이션 의존성이 필요하며,
생성된 EXE를 실행하는 대상 PC에는 Python이나 인터넷 연결이 필요하지 않습니다.
"""
from __future__ import annotations

import argparse
import builtins
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parent
APP_NAME = "WaveLab"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SERVER_URL = "http://127.0.0.1:9840/"

# Static 폴더가 Analysis의 datas로 재귀 포함되지만, 핵심 파일을 사전에
# 확인하여 빌드 성공 후 정적 리소스 누락으로 실패하는 상황을 줄입니다.
REQUIRED_FILES = (
    "app.py",
    "templates/index.html",
    "static/css/styles.css",
    "static/js/main.js",
    "static/js/uPlot.iife.min.js",
    "static/js/html2canvas.min.js",
    "static/js/uPlot.min.css",
    "static/fonts/DancingScript-Regular.ttf",
    "static/fonts/DancingScript-Medium.ttf",
    "static/fonts/DancingScript-SemiBold.ttf",
    "static/fonts/DancingScript-Bold.ttf",
    "static/images/wavelab_tiltrotor.svg",
)

# NumPy는 PyInstaller 기본 hook으로 수집되지만, SciPy/h5py는 플랫폼별
# 바이너리와 데이터 파일 누락 가능성이 있어 collect-all을 사용합니다.
COLLECT_ALL_PACKAGES = ("numpy", "scipy", "h5py", "pandas")
HIDDEN_IMPORTS = (
    "numpy.f2py",
    "numpy.linalg.lapack_lite",
    "scipy._lib.array_api_compat",
)


def _safe_print(*args, **kwargs):
    """Windows cp949 콘솔에서도 빌드 로그가 중단되지 않도록 출력합니다."""
    try:
        return builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        message = " ".join(str(arg) for arg in args)
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        message = message.encode(encoding, errors="ignore").decode(
            encoding, errors="ignore"
        )
        kwargs.pop("file", None)
        return builtins.print(message, **kwargs)


print = _safe_print


def rel_path(path: Path) -> str:
    """로그에 표시할 프로젝트 기준 경로를 반환합니다."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def find_built_executable() -> Path | None:
    """one-file/one-dir 양쪽의 WaveLab.exe를 찾습니다."""
    expected = DIST_DIR / f"{APP_NAME}.exe"
    if expected.is_file():
        return expected

    expected_dir = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    if expected_dir.is_file():
        return expected_dir

    if DIST_DIR.exists():
        candidates = sorted(DIST_DIR.rglob("*.exe"))
        wave_candidates = [p for p in candidates if p.name.lower().startswith("wavelab")]
        if wave_candidates:
            return wave_candidates[0]
        if candidates:
            return candidates[0]
    return None


def pick_existing_icon_path() -> Path | None:
    """현재 저장소의 아이콘 이름을 우선순위대로 선택합니다."""
    for name in ("WaveLab_V3.ico", "WaveLab_V3.0.ico", "WaveLab_icon.ico"):
        candidate = PROJECT_ROOT / "static" / name
        if candidate.is_file():
            return candidate
    return None


def check_requirements() -> bool:
    """소스, 템플릿, 정적 리소스가 모두 존재하는지 확인합니다."""
    print("Checking source and static resources...")
    missing = [
        path for path in REQUIRED_FILES
        if not (PROJECT_ROOT / path).is_file()
    ]

    if missing:
        print("❌ Missing required files:")
        for path in missing:
            print(f"   - {path}")
        return False

    icon = pick_existing_icon_path()
    if icon:
        print(f"✅ Icon: {rel_path(icon)}")
    else:
        print("⚠️ Icon file not found; PyInstaller default icon will be used.")

    # Monaco는 전체 트리가 존재하면 static 폴더를 통해 자동 포함됩니다.
    # 없더라도 현재 index.html의 textarea fallback으로 실행할 수 있습니다.
    monaco_loader = (
        PROJECT_ROOT
        / "static/js/monaco-editor/v0.52.2/min/vs/loader.js"
    )
    if monaco_loader.is_file():
        print(f"✅ Monaco assets: {rel_path(monaco_loader.parent)}")
    else:
        print("ℹ️ Monaco full tree not found; editor fallback will be used.")

    print(f"✅ {len(REQUIRED_FILES)} source/resource checks passed")
    return True


def check_python_dependencies() -> bool:
    """requirements.txt에 정의된 실행/빌드 패키지를 확인합니다."""
    print("Checking Python dependencies...")
    packages = (
        ("flask", "flask"),
        ("flask_cors", "flask-cors"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("h5py", "h5py"),
        ("pandas", "pandas"),
        ("PIL", "Pillow"),
        ("werkzeug", "werkzeug"),
        ("jinja2", "Jinja2"),
        ("PyInstaller", "pyinstaller"),
    )

    missing = []
    for import_name, display_name in packages:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(display_name)

    if missing:
        print("❌ Missing Python packages:")
        for package in missing:
            print(f"   - {package}")
        return False

    print("✅ All Python dependencies found")
    return True


def clean_build() -> None:
    """이전 PyInstaller 결과를 프로젝트 내부에서만 정리합니다."""
    print("Cleaning previous build files...")
    for path in (BUILD_DIR, DIST_DIR, PROJECT_ROOT / "__pycache__"):
        if not path.exists():
            continue

        for attempt in range(1, 4):
            try:
                shutil.rmtree(path)
                print(f"Removed {rel_path(path)}/")
                break
            except PermissionError as exc:
                if attempt == 3:
                    raise RuntimeError(
                        f"Cannot remove {rel_path(path)}; close a running WaveLab instance."
                    ) from exc
                print(f"⚠️ {rel_path(path)} is locked; retrying...")
                time.sleep(2)


def data_argument(source: Path, destination: str) -> str:
    """PyInstaller --add-data의 OS별 구분자를 적용합니다."""
    separator = ";" if os.name == "nt" else ":"
    return f"{source}{separator}{destination}"


def build_command(mode: str) -> list[str]:
    """app.spec를 변형하지 않고 명시적인 PyInstaller 명령을 생성합니다."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]
    command.append("--onefile" if mode == "onefile" else "--onedir")

    icon = pick_existing_icon_path()
    if icon:
        command.extend(["--icon", str(icon)])

    command.extend(["--add-data", data_argument(PROJECT_ROOT / "templates", "templates")])
    command.extend(["--add-data", data_argument(PROJECT_ROOT / "static", "static")])

    # app.py가 직접 import하지 않는 backend 분기와 SciPy/h5py의
    # 플랫폼별 모듈까지 명시적으로 포함합니다.
    command.extend(["--collect-submodules", "backend"])
    for package in COLLECT_ALL_PACKAGES:
        command.extend(["--collect-all", package])
    for module in HIDDEN_IMPORTS:
        command.extend(["--hidden-import", module])

    command.append(str(PROJECT_ROOT / "app.py"))
    return command


def build_executable(mode: str) -> bool:
    """선택된 모드로 PyInstaller를 실행합니다."""
    command = build_command(mode)
    print(f"Building {mode} executable...")
    print(" ".join(command))

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print("❌ PyInstaller build failed")
        if result.stderr:
            print(result.stderr)
        return False

    print("✅ PyInstaller build completed")
    return True


def verify_build_output(mode: str) -> tuple[bool, Path | None]:
    """one-file과 one-dir의 출력 구조를 구분하여 검증합니다."""
    executable = find_built_executable()
    if executable is None:
        print("❌ WaveLab.exe was not found in dist/")
        return False, None

    size_mb = executable.stat().st_size / (1024 * 1024)
    if size_mb < 1:
        print(f"❌ Executable is unexpectedly small: {size_mb:.1f} MB")
        return False, executable

    if mode == "onedir":
        bundle_root = executable.parent
        required_bundle_files = (
            bundle_root / "templates/index.html",
            bundle_root / "static/css/styles.css",
            bundle_root / "static/js/uPlot.iife.min.js",
            bundle_root / "static/fonts/DancingScript-Regular.ttf",
        )
        missing = [rel_path(path) for path in required_bundle_files if not path.is_file()]
        if missing:
            print("❌ Bundled resource checks failed:")
            for path in missing:
                print(f"   - {path}")
            return False, executable

        file_count = sum(1 for path in bundle_root.rglob("*") if path.is_file())
        print(
            f"✅ onedir bundle: {size_mb:.1f} MB executable, "
            f"{file_count} files including templates/static"
        )
    else:
        # one-file는 데이터가 _MEIPASS에 압축되어 들어가므로 dist 폴더에
        # templates/static 파일이 보이지 않는 것이 정상입니다.
        print(f"✅ onefile executable: {size_mb:.1f} MB ({executable})")

    return True, executable


def test_executable(executable: Path, timeout: float = 20.0) -> bool:
    """프로세스를 시작하고 Flask 루트가 HTTP 200을 반환하는지 확인합니다."""
    print("Testing executable startup and local HTTP endpoint...")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = None

    try:
        process = subprocess.Popen(
            [str(executable)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if process.poll() is not None:
                print(f"❌ Executable exited early with code {process.returncode}")
                return False

            try:
                with urllib.request.urlopen(SERVER_URL, timeout=1.0) as response:
                    if response.status == 200:
                        print("✅ Local Flask endpoint returned HTTP 200")
                        return True
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.25)

        print(f"❌ Timed out waiting for {SERVER_URL}")
        return False
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def create_offline_checklist(
    mode: str,
    executable: Path,
    runtime_test_passed: bool | None,
) -> Path:
    """빌드 결과와 자동 검증 결과를 JSON으로 기록합니다."""
    checklist_path = DIST_DIR / "offline_checklist.json"
    monaco_loader = (
        PROJECT_ROOT
        / "static/js/monaco-editor/v0.52.2/min/vs/loader.js"
    )
    payload = {
        "application": APP_NAME,
        "build_mode": mode,
        "executable": str(executable),
        "static_assets_bundled": True,
        "templates_bundled": True,
        "fonts_bundled": True,
        "monaco_full_tree_detected": monaco_loader.is_file(),
        "database_location": "data/timeseries.db beside the executable",
        "upload_location": "uploads/ beside the executable",
        "runtime_http_200_test": runtime_test_passed,
        "manual_offline_tests_required": True,
    }
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    checklist_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"✅ Offline checklist: {checklist_path}")
    return checklist_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build WaveLab for offline Windows deployment."
    )
    parser.add_argument(
        "--mode",
        choices=("onefile", "onedir"),
        default="onefile",
        help="onefile is the portable single EXE; onedir is easier to diagnose.",
    )
    parser.add_argument(
        "--skip-runtime-test",
        action="store_true",
        help="Skip launching the EXE and probing http://127.0.0.1:9840/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.chdir(PROJECT_ROOT)

    print(f"=== WaveLab offline build ({args.mode}) ===")
    if not check_requirements() or not check_python_dependencies():
        return 1

    clean_build()
    if not build_executable(args.mode):
        return 1

    output_ok, executable = verify_build_output(args.mode)
    if not output_ok or executable is None:
        return 1

    runtime_test_passed: bool | None = None
    if not args.skip_runtime_test:
        runtime_test_passed = test_executable(executable)
        if not runtime_test_passed:
            print("⚠️ Runtime smoke test failed; inspect the generated logs before deployment.")

    create_offline_checklist(args.mode, executable, runtime_test_passed)
    print("=== Build finished ===")
    print(f"Executable: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
