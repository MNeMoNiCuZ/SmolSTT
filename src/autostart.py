import sys
import os

from logger import log

APP_NAME = "SmolSTT"
_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


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
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                cmd = _autostart_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                log.debug("Autostart enabled: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    log.debug("Autostart disabled.")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    except Exception:
        log.exception("Failed to update autostart registry entry.")


def is_autostart_enabled() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY_PATH)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        log.exception("Failed to read autostart registry entry.")
        return False
