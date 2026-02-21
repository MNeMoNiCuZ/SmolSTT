from __future__ import annotations


def normalize_theme(theme: str) -> str:
    return "light" if str(theme).strip().lower() == "light" else "dark"


def theme_colors(theme: str) -> dict[str, str]:
    if normalize_theme(theme) == "light":
        return {
            "window_bg": "#e9eef5",
            "panel": "#f2f5fa",
            "field": "#ffffff",
            "text": "#172233",
            "muted": "#5a6778",
            "border": "#b7c2d0",
            "disabled_bg": "#cfd6e0",
            "disabled_text": "#6f7c8c",
            "disabled_border": "#9aa8ba",
            "accent": "#0d84ff",
            "menu_bg": "#f7f9fc",
            "menu_hover": "#dde8f7",
            "tray_idle": "#3d7ac7",
            "tray_record": "#2cb34a",
        }
    return {
        "window_bg": "#1f2022",
        "panel": "#292b2e",
        "field": "#35383c",
        "text": "#f0f1f3",
        "muted": "#b0b3b8",
        "border": "#666a70",
        "disabled_bg": "#24262a",
        "disabled_text": "#8f9399",
        "disabled_border": "#4f535a",
        "accent": "#2490ff",
        "menu_bg": "#2b2d30",
        "menu_hover": "#3a3d42",
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
        f"QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 4px; }}"
        f"QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled {{ background: {c['disabled_bg']}; color: {c['disabled_text']}; border: 1px solid {c['disabled_border']}; }}"
        f"QComboBox QAbstractItemView {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['menu_hover']}; selection-color: {c['text']}; }}"
        f"QPushButton {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 5px 10px; }}"
        f"QPushButton:disabled {{ background: {c['disabled_bg']}; color: {c['disabled_text']}; border: 1px solid {c['disabled_border']}; }}"
        f"QCheckBox, QRadioButton {{ color: {c['text']}; spacing: 8px; }}"
        f"QCheckBox:disabled, QRadioButton:disabled {{ color: {c['disabled_text']}; }}"
        "QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }"
        f"QCheckBox::indicator {{ border: 1px solid {c['border']}; border-radius: 3px; background: {c['panel']}; }}"
        f"QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
        f"QCheckBox::indicator:disabled {{ background: {c['disabled_bg']}; border: 1px solid {c['disabled_border']}; }}"
        f"QCheckBox::indicator:checked:disabled {{ background: {c['disabled_border']}; border: 1px solid {c['disabled_border']}; }}"
        f"QRadioButton::indicator {{ border-radius: 8px; }}"
        f"QRadioButton::indicator:unchecked:enabled {{ background: {c['field']}; border: 2px solid {c['border']}; }}"
        f"QRadioButton::indicator:checked:enabled {{ background: {c['accent']}; border: 2px solid {c['accent']}; }}"
        f"QRadioButton::indicator:unchecked:disabled {{ background: {c['disabled_bg']}; border: 2px solid {c['disabled_border']}; }}"
        f"QRadioButton::indicator:checked:disabled {{ background: {c['disabled_border']}; border: 2px solid {c['disabled_border']}; }}"
    )


def menu_stylesheet(theme: str) -> str:
    c = theme_colors(theme)
    return (
        f"QMenu {{ background: {c['menu_bg']}; color: {c['text']}; border: 1px solid {c['border']}; }}"
        f"QMenu::item:selected {{ background: {c['menu_hover']}; }}"
    )
