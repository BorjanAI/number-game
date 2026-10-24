"""
Build Neon Seeker into a Windows app with PyInstaller.

Run it from this folder with the project's Python:
    .venv\\Scripts\\python build.py             -> builds  dist\\Neon Seeker\\Neon Seeker.exe
    .venv\\Scripts\\python build.py --shortcut  -> also puts a "Number Game" shortcut on your Desktop
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "Neon Seeker"
SHORTCUT_NAME = "Number Game"


def make_icon(path):
    """Draw the game's icon and save it as a Windows .ico file."""
    from PySide6.QtGui import QGuiApplication

    sys.path.insert(0, str(HERE))
    import neon_seeker

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - Qt needs this to draw
    path.parent.mkdir(parents=True, exist_ok=True)
    return neon_seeker.make_icon(256).save(str(path), "ICO")


def build():
    icon = HERE / "build" / "icon.ico"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
    ]
    if make_icon(icon):
        command += ["--icon", str(icon)]
    else:
        print("Could not create the icon, building without it.")
    command.append(str(HERE / "neon_seeker.py"))
    subprocess.run(command, check=True)
    exe = HERE / "dist" / APP_NAME / f"{APP_NAME}.exe"
    print(f"\nDone! The app is here: {exe}")
    return exe


def make_shortcut(exe):
    """Create a Desktop shortcut using Windows' own shortcut maker."""
    def quoted(value):
        return "'" + str(value).replace("'", "''") + "'"

    script = (
        "$desktop = [Environment]::GetFolderPath('Desktop');"
        f"$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop {quoted(SHORTCUT_NAME + '.lnk')}));"
        f"$link.TargetPath = {quoted(exe)};"
        f"$link.WorkingDirectory = {quoted(exe.parent)};"
        f"$link.IconLocation = {quoted(str(exe) + ',0')};"
        f"$link.Description = {quoted(APP_NAME + ' - a number guessing game')};"
        "$link.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    print(f'Shortcut "{SHORTCUT_NAME}" added to your Desktop.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} as a Windows app.")
    parser.add_argument("--shortcut", action="store_true", help=f'also add a "{SHORTCUT_NAME}" shortcut to the Desktop')
    args = parser.parse_args()
    exe = build()
    if args.shortcut:
        make_shortcut(exe)
