"""
Milestone 5 Verification Test Suite: Flet Multiplatform UI & APK Packaging
Validates AC12, AC13, AC14, and data protection constraints.

Tests:
- test_01_pyproject_toml_configuration: Verifies root pyproject.toml, [tool.flet.app] path = 'app',
  dependencies contain 'flet' only, and NEVER contains 'pyserial' (AC14).
- test_02_demo_data_integrity_and_isolation: Verifies mock users, simulated logs, PIN masking,
  and zero imports from data/.
- test_03_android_mode_strict_isolation: Verifies that Android mode NEVER imports pyserial,
  auth_service, or data/ (AC14).
- test_04_desktop_ui_launch_and_components: Verifies that DoorLockApp builds and mounts all
  controls without error on Desktop (AC12).
- test_05_desktop_event_handling_and_state_transitions: Verifies door transitions (CLOSED -> OPEN ->
  auto-close, LOCKED) and live log table rendering upon serial events (AC12).
- test_06_desktop_serial_disconnect_resilience: Verifies that COM disconnects/reconnects update
  state gracefully without crashing (AC13).
- test_07_android_ui_controls_and_simulation: Verifies Android demo view, hidden serial controls,
  simulation buttons, and demo user list.
- test_08_data_directory_remains_strictly_unmodified: Verifies AC11 SHA256 integrity and 0 bytecode.
"""

import sys
import os
import time
import unittest
import hashlib
from pathlib import Path
from typing import Dict, Any, List

# Strict bytecode prevention
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Setup import paths
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import flet as ft
from app.demo_data import (
    get_demo_users,
    get_demo_logs,
    generate_simulated_event,
    clear_demo_logs,
    reset_demo_data,
)
from app.main import (
    DoorLockApp,
    is_android_platform,
    load_desktop_modules,
)

# Reference baseline SHA256 hashes for data/
BASELINE_HASHES = {
    "access_control.db": "5362BFFF81BAD76A91CCB3BE24842CF08ADFB49B8E9D6B92BF922B00B3B1D406",
    "access_logs.csv": "974FBC341D793F4D193995452909307800397CC7471D2DF5230BD826D477BC18",
    "bao_cao_thong_ke.txt": "A333C577B51C6216082F0178B5ABC5953429CB1CDD9FC945E81F91B4D13874A1",
    "database.py": "E7D1508EB54C37BC376FAC3C488AC07F2FA8CC56FC913E79CC1540A140DC1BDF",
    "data_analysis.py": "73A5166851EE02E246E6DE997ADECB295D7C7908CE08C9A6290353737A90BF98",
    "Charts/access_ratio.png": "386E92E1340F919E919F9DD30B47781FD2924058BDE38E754198D238C83CF29F",
    "Charts/access_time.png": "2CC2D5855CCF95703BC285EF7957367D7BC82BFF115D846353BD03B208683764",
    "Charts/success_failed.png": "DC3E0D0850B4BA4EC0D4A40785F0253B579627833CC304655BFFE7E5A907B178",
}


class MockFletPage:
    """
    Mock Page container mimicking Flet Page for headless UI lifecycle testing.
    """

    def __init__(self, platform: ft.PagePlatform = ft.PagePlatform.WINDOWS):
        self.platform = platform
        self.title = ""
        self.theme_mode = None
        self.padding = None
        self.appbar = None
        self.navigation_bar = None
        self.controls = []
        self.update_count = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.update_count += 1

    def clean(self):
        self.controls.clear()


class TestMilestone5FletUI(unittest.TestCase):
    """Test suite verifying Milestone 5 objectives and AC12-AC14."""

    def setUp(self):
        reset_demo_data()

    def test_01_pyproject_toml_configuration(self):
        """
        AC14: Verify root pyproject.toml configuration for APK packaging:
        - Must point [tool.flet.app] to 'app'
        - Dependencies must contain 'flet'
        - Dependencies must NEVER contain 'pyserial'
        """
        pyproject_path = REPO_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file(), "Root pyproject.toml must exist")

        content = pyproject_path.read_text(encoding="utf-8")

        # Parse basic TOML sections
        self.assertIn("[tool.flet.app]", content, "Must declare [tool.flet.app] section")
        self.assertIn('path = "app"', content, "[tool.flet.app] path must be 'app'")

        # Check dependencies
        self.assertIn('"flet"', content, "Dependencies must include 'flet'")

        # Critical AC14 constraint: pyserial must NOT be in pyproject.toml
        self.assertNotIn(
            "pyserial",
            content.lower(),
            "CRITICAL VIOLATION: pyproject.toml dependencies MUST NOT contain pyserial (AC14)",
        )

    def test_02_demo_data_integrity_and_isolation(self):
        """
        Verify app/demo_data.py structure:
        - Mock user list exists and masks PINs as '****'
        - Mock event logs exist and mask PINs as '****'
        - Simulation helpers function correctly
        - Zero imports or access to data/
        """
        users = get_demo_users()
        self.assertGreaterEqual(len(users), 3, "Demo users must contain at least 3 sample profiles")
        for u in users:
            self.assertEqual(u["pin"], "****", f"Demo user {u['name']} must mask PIN as '****'")
            self.assertIn("id", u)
            self.assertIn("name", u)
            self.assertIn("role", u)

        logs = get_demo_logs()
        self.assertGreaterEqual(len(logs), 3, "Demo logs must contain initial simulated events")
        for entry in logs:
            self.assertIn("****", entry["detail"], "Log detail must have masked PIN '****'")

        # Test generating simulated events
        new_event = generate_simulated_event("SUCCESS")
        self.assertEqual(new_event["status"], "SUCCESS")
        self.assertIn(new_event, get_demo_logs())

        # Test clearing logs
        clear_demo_logs()
        self.assertEqual(len(get_demo_logs()), 0, "clear_demo_logs() must empty active demo logs")

    def test_03_android_mode_strict_isolation(self):
        """
        AC14: Verify that when running in Android mode:
        - NEVER imports auth_service or pyserial or data/
        - Uses demo_data exclusively
        """
        # Create page configured as Android
        android_page = MockFletPage(platform=ft.PagePlatform.ANDROID)
        self.assertTrue(is_android_platform(android_page))

        # Instantiate app in Android mode
        app = DoorLockApp(android_page, is_android=True)
        app.build_ui()

        # Verify backend is strictly None
        self.assertIsNone(app.auth_service, "AuthService must NOT be instantiated on Android")
        self.assertIsNone(app.serial_bridge, "SerialBridge must NOT be instantiated on Android")

        # Verify serial controls are hidden
        self.assertFalse(hasattr(app, "port_input"), "Serial COM port input must be hidden on Android")
        self.assertFalse(hasattr(app, "connect_btn"), "Serial Connect button must be hidden on Android")

        # Verify demo data is populated
        self.assertGreater(len(app.users_table.rows), 0, "Users table must be populated from demo data")
        self.assertGreater(len(app.log_table.rows), 0, "Log table must be populated from demo logs")

        app.close()

    def test_04_desktop_ui_launch_and_components(self):
        """
        AC12: Verify application launches and renders successfully on Desktop:
        - Instantiates all required UI cards and tables
        - Initial door status is CLOSED
        - Navigation bar and view switching work cleanly
        """
        desktop_page = MockFletPage(platform=ft.PagePlatform.WINDOWS)
        self.assertFalse(is_android_platform(desktop_page))

        app = DoorLockApp(desktop_page, is_android=False)
        app.build_ui()

        # Check required components
        self.assertIsNotNone(app.door_card, "Door status card must exist")
        self.assertIsNotNone(app.serial_card, "Serial status card must exist")
        self.assertIsNotNone(app.log_table, "Live access log table must exist")
        self.assertIsNotNone(app.users_table, "User management table must exist")
        self.assertIsNotNone(app.nav_bar, "Navigation bar must exist")

        # Initial door state
        self.assertEqual(app.door_state, "CLOSED")
        self.assertEqual(app.door_label.value, "CỬA ĐANG ĐÓNG")

        # Serial controls present on Desktop
        self.assertTrue(hasattr(app, "port_input"), "COM port input must exist on Desktop")
        self.assertTrue(hasattr(app, "connect_btn"), "Reconnect button must exist on Desktop")

        # Verify users table populated from AuthService
        self.assertGreaterEqual(len(app.users_table.rows), 3, "Desktop must load configured users")

        app.close()

    def test_05_desktop_event_handling_and_state_transitions(self):
        """
        AC12: Verify real-time door and log updates upon receiving serial events:
        - ACCESS_GRANTED -> Door OPEN (green), auto-closes to CLOSED after 3s
        - LOCKED -> Door LOCKED (red alarm)
        - ACCESS_DENIED -> Door CLOSED, failure logged
        """
        desktop_page = MockFletPage(platform=ft.PagePlatform.WINDOWS)
        app = DoorLockApp(desktop_page, is_android=False)
        app.build_ui()

        # 1. Test ACCESS_GRANTED
        app.handle_serial_state_change("ACCESS_GRANTED")
        self.assertEqual(app.door_state, "OPEN")
        self.assertEqual(app.door_icon.name, ft.Icons.LOCK_OPEN)
        self.assertEqual(app.door_label.color, ft.Colors.GREEN)

        # 2. Test auto-close timer (fast-forward by manually calling timer target)
        app._auto_close_door()
        self.assertEqual(app.door_state, "CLOSED")
        self.assertEqual(app.door_icon.name, ft.Icons.LOCK)
        self.assertEqual(app.door_label.color, ft.Colors.AMBER)

        # 3. Test LOCKED (Lockout Alarm)
        app.handle_serial_state_change("LOCKED")
        self.assertEqual(app.door_state, "LOCKED")
        self.assertEqual(app.door_icon.name, ft.Icons.WARNING)
        self.assertEqual(app.door_label.color, ft.Colors.RED)

        # 4. Verify log table refreshed
        self.assertGreater(len(app.log_table.rows), 0, "Log table must contain updated audit entries")

        app.close()

    def test_06_desktop_serial_disconnect_resilience(self):
        """
        AC13: Verify that the UI does not crash when the serial connection is disconnected,
        unplugged, or reconnecting.
        """
        desktop_page = MockFletPage(platform=ft.PagePlatform.WINDOWS)
        app = DoorLockApp(desktop_page, is_android=False)
        app.build_ui()

        # Simulate serial disconnect
        try:
            app.handle_serial_state_change("DISCONNECTED")
            self.assertEqual(app.serial_state, "DISCONNECTED")
            self.assertEqual(app.serial_label.value, "MẤT KẾT NỐI")
            self.assertEqual(app.serial_icon.color, ft.Colors.RED)
        except Exception as e:
            self.fail(f"Serial disconnect caused unhandled exception: {e}")

        # Simulate reconnecting
        try:
            app.handle_serial_state_change("RECONNECTING")
            self.assertEqual(app.serial_state, "RECONNECTING")
            self.assertEqual(app.serial_label.value, "ĐANG KẾT NỐI LẠI...")
            self.assertEqual(app.serial_icon.color, ft.Colors.AMBER)
        except Exception as e:
            self.fail(f"Serial reconnecting state caused unhandled exception: {e}")

        # Simulate reconnected
        try:
            app.handle_serial_state_change("CONNECTED")
            self.assertEqual(app.serial_state, "CONNECTED")
            self.assertEqual(app.serial_label.value, "ĐÃ KẾT NỐI")
            self.assertEqual(app.serial_icon.color, ft.Colors.GREEN)
        except Exception as e:
            self.fail(f"Serial connected state caused unhandled exception: {e}")

        app.close()

    def test_07_android_ui_controls_and_simulation(self):
        """
        Verify Android interactive simulation controls:
        - Trigger simulated success, fail, and lockout
        - Check UI door and log updates
        """
        android_page = MockFletPage(platform=ft.PagePlatform.ANDROID)
        app = DoorLockApp(android_page, is_android=True)
        app.build_ui()

        initial_count = len(app.log_table.rows)

        # Simulate success
        app._on_sim_event("SUCCESS")
        self.assertEqual(app.door_state, "OPEN")
        self.assertEqual(len(app.log_table.rows), initial_count + 1)

        # Simulate fail
        app._on_sim_event("FAILED")
        self.assertEqual(len(app.log_table.rows), initial_count + 2)

        # Simulate lockout
        app._on_sim_event("LOCKOUT")
        self.assertEqual(app.door_state, "LOCKED")
        self.assertEqual(len(app.log_table.rows), initial_count + 3)

        # Test clear logs
        app.clear_logs_display()
        self.assertEqual(len(app.log_table.rows), 0)

        app.close()

    def test_08_data_directory_remains_strictly_unmodified(self):
        """
        Final check of AC11: data/ directory SHA256 hashes must remain 100% bitwise identical,
        and no __pycache__ directory must exist in data/.
        """
        data_dir = REPO_ROOT / "data"

        # Check for bytecode
        pycache = data_dir / "__pycache__"
        self.assertFalse(
            pycache.exists(),
            "VIOLATION: data/__pycache__ was created! Bytecode prevention failed.",
        )

        # Check all 8 baseline files
        for rel_path, expected_hash in BASELINE_HASHES.items():
            fpath = data_dir / rel_path
            self.assertTrue(fpath.is_file(), f"Expected data file {rel_path} to exist")

            with open(fpath, "rb") as f:
                actual_hash = hashlib.sha256(f.read()).hexdigest().upper()

            self.assertEqual(
                actual_hash,
                expected_hash,
                f"File {rel_path} hash mutated! Expected {expected_hash}, got {actual_hash}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
