# PyInstaller recipe: turns the app into "Verse Platform.exe" with Python baked in.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
binaries = [("build_deps/ffmpeg.exe", ".")] if os.path.exists("build_deps/ffmpeg.exe") else []
datas = [("assets/logo.png", "assets"), ("assets/logo.ico", "assets"), ("ui", "ui"), ("release-notes", "release-notes")]
import os
if os.path.exists("squad_secret.txt"):   # written by the GitHub build from a repo secret
    datas += [("squad_secret.txt", ".")]
hidden = ["pystray._win32"]
try:  # the window (pywebview + Edge WebView2 through pythonnet)
    datas += collect_data_files("webview")
    hidden += collect_submodules("webview.platforms") + ["clr", "clr_loader"]
except Exception:
    pass

a = Analysis(
    ["verse_desktop.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "unittest", "pydoc", "test", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Verse Platform",
    icon="assets/logo.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Verse Platform", upx=False)
