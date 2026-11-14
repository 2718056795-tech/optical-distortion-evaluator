# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

src = Path(SPECPATH)
app = src.parent
data = [(str(app / 'examples' / '畸变样例.txt'), '.'),
        (str(src / 'startup_card.bmp'), '.')]
data.extend((str(font), '.') for font in sorted(src.glob('SourceHanSerifSC-*.otf')))

analysis = Analysis(
    [str(src / 'qt_app.py')],
    pathex=[str(src)],
    binaries=[],
    datas=data,
    hiddenimports=['matplotlib.backends.backend_svg'],
    runtime_hooks=[str(src / 'rth_portable.py')],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6.QtNetwork', 'tkinter', '_hashlib', '_ssl'],
    hooksconfig={'matplotlib': {'backends': ['QtAgg', 'Agg', 'SVG']}},
)
def keep_binary(entry):
    name = Path(entry[0].replace('\\', '/'))
    basename = name.name.lower()
    if basename.startswith(('msvcp', 'vcruntime', 'libssl', 'libcrypto')):
        return False
    if basename in ('qt6network.dll', 'opengl32sw.dll', 'qtuiotouchplugin.dll'):
        return False
    return not {'tls', 'networkinformation'}.intersection(name.parts)


analysis.binaries = [entry for entry in analysis.binaries if keep_binary(entry)]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='光机镜头畸变评估工具V6',
    debug=False,
    console=False,
    upx=False,
)
release = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name='optical-distortion-evaluator-v6',
)
