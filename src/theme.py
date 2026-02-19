from __future__ import annotations


def normalize_theme(theme: str) -> str:
    return "light" if str(theme).strip().lower() == "light" else "dark"


def theme_colors(theme: str) -> dict[str, str]:
    if normalize_theme(theme) == "light":
        return {
            "window_bg": "#f4f7fb",
            "panel": "#ffffff",
            "field": "#ffffff",
            "text": "#1f2d3d",
            "muted": "#5f7085",
            "border": "#c9d4e0",
            "accent": "#0d84ff",
            "menu_bg": "#ffffff",
            "menu_hover": "#eaf3ff",
            "tray_idle": "#3d7ac7",
            "tray_record": "#2cb34a",
        }
    return {
        "window_bg": "#171b22",
        "panel": "#171b22",
        "field": "#202734",
        "text": "#ecf2fa",
        "muted": "#a6b6ca",
        "border": "#3a475c",
        "accent": "#2ba3ff",
        "menu_bg": "#212a38",
        "menu_hover": "#2d3b50",
        "tray_idle": "#3c78c2",
        "tray_record": "#2daa47",
    }


def settings_stylesheet(theme: str) -> str:
    c = theme_colors(theme)
    return (
        f"QDialog {{ background: {c['window_bg']}; color: {c['text']}; }}"
        f"QLabel {{ color: {c['text']}; }}"
        f"QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 10px; padding: 10px 8px 8px 8px; background: {c['panel']}; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; color: {c['muted']}; }}"
        f"QLineEdit, QComboBox, QSpinBox {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 4px; }}"
        f"QComboBox QAbstractItemView {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['menu_hover']}; selection-color: {c['text']}; }}"
        f"QPushButton {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 5px 10px; }}"
        f"QPushButton:disabled {{ color: {c['muted']}; }}"
        f"QCheckBox, QRadioButton {{ color: {c['text']}; spacing: 8px; }}"
        "QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }"
        f"QCheckBox::indicator {{ border: 1px solid {c['border']}; border-radius: 3px; background: {c['panel']}; }}"
        f"QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
        f"QRadioButton::indicator {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['panel']}; }}"
        f"QRadioButton::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
    )


def menu_stylesheet(theme: str) -> str:
    c = theme_colors(theme)
    return (
        f"QMenu {{ background: {c['menu_bg']}; color: {c['text']}; border: 1px solid {c['border']}; }}"
        f"QMenu::item:selected {{ background: {c['menu_hover']}; }}"
    )
