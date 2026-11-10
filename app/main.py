"""
Smart PIN Door Lock System - Application Entry Point.
Launches the Flet multiplatform application.
"""
import os
import sys

# Enforce strict bytecode prevention
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import flet as ft
from app.ui.app_view import DoorLockApp


def main(page: ft.Page) -> DoorLockApp:
    """Main application entry point."""
    app = DoorLockApp(page)
    app.build_ui()
    return app


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    elif hasattr(ft, "app"):
        ft.app(target=main)
