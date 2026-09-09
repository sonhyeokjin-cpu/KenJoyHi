try:
    import PyInstaller.__main__ as pyi
except ImportError:
    print("PyInstaller가 설치되어 있지 않습니다. 'pip install pyinstaller'로 설치하세요.")
    exit(1)
import os
import shutil
import glob
import sys
import site
import logging
import traceback

# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('build.log', mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def collect_static_files():
    """수집할 정적 파일 목록을 생성합니다."""
    static_files = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # static 폴더의 모든 파일을 재귀적으로 수집
    static_dir = os.path.join(base_dir, 'static')
    if not os.path.exists(static_dir):
        logging.error(f"static 디렉토리를 찾을 수 없습니다: {static_dir}")
        return static_files
        
    for root, dirs, files in os.walk(static_dir):
        for file in files:
            src_path = os.path.join(root, file)
            # static 폴더를 기준으로 상대 경로 계산
            dst_path = os.path.join('static', os.path.relpath(root, static_dir))
            static_files.append((src_path, dst_path))
            logging.debug(f"정적 파일 추가: {src_path} -> {dst_path}")
    
    return static_files

def get_package_paths():
    """필요한 패키지들의 경로를 수집합니다."""
    package_paths = []
    packages = [
        'flask', 'flask_cors', 'numpy', 'scipy', 'h5py', 'pandas',
        'werkzeug', 'jinja2', 'click', 'itsdangerous', 'markupsafe',
        'blinker', 'colorama'
    ]
    
    for package in packages:
        try:
            package_path = os.path.dirname(__import__(package).__file__)
            if os.path.exists(package_path):
                package_paths.append(package_path)
                logging.debug(f"패키지 경로 추가: {package} -> {package_path}")
            else:
                logging.warning(f"패키지 경로가 존재하지 않습니다: {package_path}")
        except ImportError as e:
            logging.error(f"패키지를 찾을 수 없습니다: {package}")
            logging.error(f"오류: {str(e)}")
            print(f"Warning: {package} 패키지를 찾을 수 없습니다.")
    
    return package_paths

def build():
    """실행 파일을 빌드합니다."""
    logging.info("빌드를 시작합니다...")
    print("빌드를 시작합니다...")
    
    try:
        # 현재 스크립트의 디렉토리를 기준으로 설정
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 빌드 전 기존 dist와 build 폴더 삭제
        for folder in ['dist', 'build']:
            if os.path.exists(folder):
                logging.info(f"기존 {folder} 폴더를 삭제합니다...")
                print(f"기존 {folder} 폴더를 삭제합니다...")
                shutil.rmtree(folder)

        # 정적 파일 수집
        logging.info("정적 파일을 수집합니다...")
        print("정적 파일을 수집합니다...")
        static_files = collect_static_files()
        
        # 패키지 경로 수집
        logging.info("패키지 경로를 수집합니다...")
        print("패키지 경로를 수집합니다...")
        package_paths = get_package_paths()
        
        # PyInstaller 옵션 설정
        logging.info("PyInstaller 옵션을 설정합니다...")
        print("PyInstaller 옵션을 설정합니다...")
        
        # 기본 옵션
        options = [
            os.path.join(base_dir, 'app.py'),  # 메인 스크립트
            '--name=WaveLab',  # 실행 파일 이름
            '--onefile',  # 단일 실행 파일로 생성
            '--windowed',  # 콘솔 창 없이 실행
            '--clean',  # 빌드 전 캐시 삭제
            '--noconfirm',  # 기존 파일 덮어쓰기
            '--log-level=DEBUG',  # 빌드 과정의 로그 레벨 설정
        ]
        
        # 아이콘 파일 확인 및 추가
        icon_path = os.path.join(base_dir, "static", "WaveLab_icon.ico")
        if os.path.exists(icon_path):
            options.append(f'--icon={icon_path}')
        else:
            logging.warning(f"아이콘 파일을 찾을 수 없습니다: {icon_path}")
        
        # 리소스 파일 추가
        for resource in ['templates', 'backend', 'static']:
            resource_path = os.path.join(base_dir, resource)
            if os.path.exists(resource_path):
                options.append(f'--add-data={resource_path};{resource}')
            else:
                logging.warning(f"리소스 경로가 존재하지 않습니다: {resource_path}")
        
        # Flask 관련 리소스 추가
        try:
            flask_path = os.path.dirname(__import__('flask').__file__)
            for resource in ['templates', 'static']:
                flask_resource = os.path.join(flask_path, resource)
                if os.path.exists(flask_resource):
                    options.append(f'--add-data={flask_resource};flask/{resource}')
                else:
                    logging.warning(f"Flask {resource} 경로가 존재하지 않습니다: {flask_resource}")
        except Exception as e:
            logging.error(f"Flask 리소스 추가 중 오류 발생: {str(e)}")
        
        # 패키지 수집 옵션 추가
        for package in ['flask', 'flask_cors', 'numpy', 'scipy', 'h5py', 'pandas',
                       'werkzeug', 'jinja2', 'click', 'itsdangerous', 'markupsafe',
                       'blinker', 'colorama']:
            options.append(f'--collect-all={package}')
        
        # 패키지 경로 추가
        for path in package_paths:
            if os.path.exists(path):
                options.append(f'--add-data={path};{os.path.basename(path)}')
            else:
                logging.warning(f"패키지 경로가 존재하지 않습니다: {path}")
        
        # 필수 의존성 추가
        hidden_imports = [
            'flask', 'flask_cors', 'numpy', 'scipy', 'h5py', 'pandas', 'sqlite3',
            'werkzeug', 'jinja2', 'click', 'itsdangerous', 'markupsafe', 'blinker',
            'colorama', 'flask.templating', 'flask.static', 'flask.json',
            'flask.helpers', 'flask.wrappers', 'flask.sessions', 'flask.signals',
            'flask.globals', 'flask.ctx', 'flask.config', 'flask.blueprints',
            'flask.app', 'flask._compat', 'flask.cli', 'flask.debughelpers'
        ]
        
        for imp in hidden_imports:
            options.append(f'--hidden-import={imp}')
        
        # SQLite DLL 추가
        sqlite_dll = 'sqlite3.dll'
        if os.path.exists(sqlite_dll):
            options.append(f'--add-binary={sqlite_dll};.')
        else:
            logging.warning(f"SQLite DLL을 찾을 수 없습니다: {sqlite_dll}")

        logging.info("PyInstaller를 실행합니다...")
        print("PyInstaller를 실행합니다...")
        pyi.run(options)
        
        # 빌드 완료 후 실행 파일 확인
        exe_path = os.path.join('dist', 'WaveLab.exe')
        if os.path.exists(exe_path):
            logging.info(f"빌드가 완료되었습니다. 실행 파일: {exe_path}")
            print(f"\n빌드가 완료되었습니다. 실행 파일은 {exe_path}에 있습니다.")
        else:
            raise FileNotFoundError(f"실행 파일이 생성되지 않았습니다: {exe_path}")
            
    except Exception as e:
        logging.error(f"빌드 중 오류가 발생했습니다: {str(e)}")
        logging.error(traceback.format_exc())
        print(f"\n빌드 중 오류가 발생했습니다: {str(e)}")
        print("자세한 내용은 build.log 파일을 확인하세요.")
        sys.exit(1)

def main():
    """메인 실행 함수"""
    logging.info("WaveLab 빌드 스크립트를 시작합니다...")
    print("WaveLab 빌드 스크립트를 시작합니다...")
    build()

if __name__ == '__main__':
    main() 