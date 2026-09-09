# PyInstaller specification for the offline WaveLab desktop build.
from pathlib import Path
ROOT = Path(__file__).resolve().parent
datas = [
    (str(ROOT / 'templates'), 'templates'),
    (str(ROOT / 'static'), 'static'),
]
hiddenimports = [
    'backend.loader', 'backend.csv_loader', 'backend.storage',
    'backend.analysis', 'backend.jobs',
    'backend.filters', 'backend.derived', 'backend.bit_extractor',
    'h5py.defs', 'h5py._objects',
]

a = Analysis(
    [str(ROOT / 'app.py')], pathex=[str(ROOT)],
    binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
         name='WaveLab', debug=False, bootloader_ignore_signals=False,
         strip=False, upx=True, console=False)
