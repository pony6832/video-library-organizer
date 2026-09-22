from pathlib import Path
import importlib.metadata
import sys

project = Path(SPECPATH).parent
datas = []
for package in ('Pillow', 'openpyxl', 'et_xmlfile', 'PyInstaller'):
    distribution = importlib.metadata.distribution(package)
    licenses = [f for f in distribution.files if any(word in str(f).lower() for word in ('license', 'licence', 'copying'))]
    if not licenses:
        raise RuntimeError('Missing license files: ' + package)
    for entry in licenses:
        datas.append((str(distribution.locate_file(entry)), 'licenses/' + package))
base = Path(sys.base_prefix)
datas += [(str(base / 'LICENSE.txt'), 'licenses/Python'),
          (str(project / 'packaging/licenses/Tcl-license.terms'), 'licenses/Tcl'),
          (str(base / 'tcl/tk8.6/license.terms'), 'licenses/Tk'),
          (str(project / '.tools/build/inno/license.txt'), 'licenses/InnoSetup')]
a = Analysis([str(project / 'packaging/desktop_entry.py')],
    pathex=[str(project / 'src')], datas=datas,
    hiddenimports=['PIL._tkinter_finder'],
    excludes=['pytest', '_pytest', 'yaml', 'pip', 'setuptools', 'numpy', 'IPython', 'matplotlib'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name='MediaCatalogVideoDesktop', debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MediaCatalogVideoDesktop')
