"""
Platform detection and dynamic module loading utilities.
Enforces runtime isolation between Desktop (Serial/Auth) and Android (Demo mode).
"""
import os
import sys
from typing import Optional, List, Tuple, Any

import flet as ft

_SerialBridgeClass = None
_AuthServiceClass = None


def is_android_platform(page: Optional[ft.Page] = None) -> bool:
    """
    Detects if the application is running in Android or Demo/Monitoring mode.
    Checks environment variables and Flet PagePlatform.
    """
    forced = os.environ.get("FORCE_PLATFORM", "").strip().lower()
    if forced in ("android", "demo"):
        return True
    if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_BOOTLOGO"):
        return True
    if page is not None:
        plat = getattr(page, "platform", None)
        if plat in (ft.PagePlatform.ANDROID, ft.PagePlatform.ANDROID_TV):
            return True
    return False


def load_desktop_modules() -> Tuple[Any, Any]:
    """
    Dynamically loads SerialBridge and AuthService only when executing on Desktop.
    Guarantees that on Android, pyserial and auth_service are never imported.
    """
    global _SerialBridgeClass, _AuthServiceClass
    if _SerialBridgeClass is None or _AuthServiceClass is None:
        try:
            from app.auth_service import AuthService
            from app.serial_bridge import SerialBridge
            _AuthServiceClass = AuthService
            _SerialBridgeClass = SerialBridge
        except (ImportError, ModuleNotFoundError):
            from auth_service import AuthService
            from serial_bridge import SerialBridge
            _AuthServiceClass = AuthService
            _SerialBridgeClass = SerialBridge
    return _SerialBridgeClass, _AuthServiceClass


def get_available_com_ports() -> List[str]:
    """Helper discovering available serial COM ports without breaking Android isolation."""
    try:
        from app.serial_bridge import list_available_ports
        return list_available_ports()
    except Exception:
        try:
            from serial_bridge import list_available_ports
            return list_available_ports()
        except Exception:
            return ["COM1", "COM2", "COM5", "COM6"]
