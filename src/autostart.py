import sys
import os

APP_NAME = "SmolSTT"


def _autostart_command() -> str:
    """Return the command stored in HKCU\\...\\Run for this app."""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'

    exe = os.path.abspath(sys.executable)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script = os.path.join(project_root, "app.py")
    return f'"{exe}" "{script}"'


def set_autostart(enabled: bool):
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def is_autostart_enabled() -> bool:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False
