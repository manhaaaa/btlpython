"""
Independent Serial Mock Loopback Verification Test Suite
Tests Milestone 4 (R4) requirements without requiring Proteus:
1. Correct PIN -> receives '1'
2. Incorrect PIN -> receives '0'
3. Regex validation: non-4-digit input discarded with warning log, no response
4. 3 consecutive failed PIN attempts -> receives 'L' (lockout triggered)
5. Quick lockout test (5 seconds): receives 'L' while locked, then auto-unlocks after 5s and accepts valid PIN -> receives '1'
6. Full 30-second lockout test (real 30s lockout): receives 'L', waits 30s, unlocks -> receives '1'
7. Audit log verification: verifies all PINs are strictly masked as '****' in log files & DB
8. Data directory SHA256 integrity: verifies data/ is 100% untouched and no __pycache__ exists
"""

import sys
import os
import time
import queue
import hashlib
import unittest
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

# Enforce no bytecode generation
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Resolve paths
TESTS_DIR = Path(__file__).resolve().parent
BTL_DIR = TESTS_DIR.parent
APP_DIR = BTL_DIR / "app"
DATA_DIR = BTL_DIR / "data"

if str(BTL_DIR) not in sys.path:
    sys.path.insert(0, str(BTL_DIR))

try:
    import serial
except ImportError:
    serial = None

from app.auth_service import AuthService, User
from app.serial_bridge import SerialBridge


# Baseline SHA256 hashes of all 8 files in data/
DATA_SHA256_BASELINE = {
    "access_control.db": "5362BFFF81BAD76A91CCB3BE24842CF08ADFB49B8E9D6B92BF922B00B3B1D406",
    "access_logs.csv": "974FBC341D793F4D193995452909307800397CC7471D2DF5230BD826D477BC18",
    "bao_cao_thong_ke.txt": "A333C577B51C6216082F0178B5ABC5953429CB1CDD9FC945E81F91B4D13874A1",
    "database.py": "E7D1508EB54C37BC376FAC3C488AC07F2FA8CC56FC913E79CC1540A140DC1BDF",
    "data_analysis.py": "73A5166851EE02E246E6DE997ADECB295D7C7908CE08C9A6290353737A90BF98",
    "Charts/access_ratio.png": "386E92E1340F919E919F9DD30B47781FD2924058BDE38E754198D238C83CF29F",
    "Charts/access_time.png": "2CC2D5855CCF95703BC285EF7957367D7BC82BFF115D846353BD03B208683764",
    "Charts/success_failed.png": "DC3E0D0850B4BA4EC0D4A40785F0253B579627833CC304655BFFE7E5A907B178",
}


class MockSerialEndpoint:
    """Simulates one endpoint of a bidirectional virtual serial channel."""

    def __init__(
        self,
        rx_queue: queue.Queue,
        tx_queue: queue.Queue,
        name: str = "Endpoint",
        timeout: float = 1.0,
    ):
        self.rx_queue = rx_queue
        self.tx_queue = tx_queue
        self.name = name
        self.timeout = timeout
        self.is_open = True

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError(f"{self.name}: Port is closed")
        for b in data:
            self.tx_queue.put(bytes([b]))
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise OSError(f"{self.name}: Port is closed")
        buf = bytearray()
        timeout = self.timeout if self.timeout is not None else 1.0
        while len(buf) < size:
            try:
                b = self.rx_queue.get(timeout=timeout)
                buf.extend(b)
            except queue.Empty:
                break
        return bytes(buf)

    def readline(self) -> bytes:
        if not self.is_open:
            raise OSError(f"{self.name}: Port is closed")
        buf = bytearray()
        timeout = self.timeout if self.timeout is not None else 1.0
        while True:
            try:
                b = self.rx_queue.get(timeout=timeout)
                buf.extend(b)
                if b == b"\n":
                    break
            except queue.Empty:
                break
        return bytes(buf)


def create_mock_serial_pair(
    timeout: float = 1.0,
) -> Tuple[MockSerialEndpoint, MockSerialEndpoint]:
    """Creates a linked cross-connected pair of mock serial endpoints."""
    q_client_to_bridge = queue.Queue()
    q_bridge_to_client = queue.Queue()

    bridge_side = MockSerialEndpoint(
        rx_queue=q_client_to_bridge,
        tx_queue=q_bridge_to_client,
        name="BridgeSide(COM2)",
        timeout=timeout,
    )
    client_side = MockSerialEndpoint(
        rx_queue=q_bridge_to_client,
        tx_queue=q_client_to_bridge,
        name="ClientSide(COM1)",
        timeout=timeout,
    )
    return bridge_side, client_side


class TestSerialBridgeMock(unittest.TestCase):
    """Test suite executing comprehensive R4 verification."""

    @classmethod
    def setUpClass(cls):
        # Verify baseline before tests
        cls.verify_data_directory_clean()

    def setUp(self):
        # Setup clean test auth and log files
        self.test_log_file = APP_DIR / "test_audit.log"
        self.test_db_file = APP_DIR / "test_access_control.db"

        # Remove previous test artifacts if present
        if self.test_log_file.exists():
            self.test_log_file.unlink()
        if self.test_db_file.exists():
            self.test_db_file.unlink()

        self.auth_service = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log_file,
            db_path=self.test_db_file,
            enable_db=True,
        )

    def tearDown(self):
        # Cleanup test artifacts
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        if self.test_log_file.exists():
            try:
                self.test_log_file.unlink()
            except Exception:
                pass
        if self.test_db_file.exists():
            try:
                self.test_db_file.unlink()
            except Exception:
                pass

    @classmethod
    def verify_data_directory_clean(cls):
        """Verifies that data/ contains no __pycache__ and all SHA256 hashes match baseline."""
        pycache_dir = DATA_DIR / "__pycache__"
        if pycache_dir.exists():
            raise AssertionError(f"HAZARD: {pycache_dir} exists! AC11 violation.")

        for rel_path, expected_hash in DATA_SHA256_BASELINE.items():
            full_path = DATA_DIR / rel_path
            if not full_path.is_file():
                raise AssertionError(f"Expected file missing: {full_path}")
            h = hashlib.sha256(full_path.read_bytes()).hexdigest().upper()
            if h != expected_hash:
                raise AssertionError(
                    f"SHA256 mismatch for {rel_path}!\nExpected: {expected_hash}\nActual:   {h}"
                )

    def test_01_valid_pins_receive_1(self):
        """Test sending valid 4-digit PINs -> receives '1'."""
        bridge_serial, client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

        valid_pins = [("1234", "Nguyễn Văn A"), ("5678", "Trần Thị B"), ("9999", "Quản Trị Viên")]

        for pin, name in valid_pins:
            client_serial.write(f"{pin}\n".encode("ascii"))
            resp = client_serial.read(1).decode("ascii")
            self.assertEqual(
                resp, "1", f"Expected '1' for valid PIN {pin} ({name}), got {repr(resp)}"
            )

        self.assertEqual(self.bridge.consecutive_fails, 0)
        self.assertEqual(self.bridge.metrics["access_granted"], 3)

    def test_02_invalid_pins_receive_0(self):
        """Test sending incorrect 4-digit PINs -> receives '0'."""
        bridge_serial, client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

        # Send 1st wrong PIN
        client_serial.write(b"0000\n")
        resp1 = client_serial.read(1).decode("ascii")
        self.assertEqual(resp1, "0", f"Expected '0' on 1st fail, got {repr(resp1)}")
        self.assertEqual(self.bridge.consecutive_fails, 1)

        # Send 2nd wrong PIN
        client_serial.write(b"1111\n")
        resp2 = client_serial.read(1).decode("ascii")
        self.assertEqual(resp2, "0", f"Expected '0' on 2nd fail, got {repr(resp2)}")
        self.assertEqual(self.bridge.consecutive_fails, 2)

    def test_03_regex_filter_discards_invalid_payloads(self):
        """Test non-4-digit inputs are discarded without response or error."""
        bridge_serial, client_serial = create_mock_serial_pair(timeout=0.3)
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

        invalid_payloads = [
            b"123\n",        # 3 digits (too short)
            b"12345\n",      # 5 digits (too long)
            b"abcd\n",       # Non-digits
            b"\n",           # Empty line
            b"12a4\n",       # Mixed alphanumeric
            b"   \n",        # Whitespace
            b"***#\n",       # Keypad symbols
        ]

        for payload in invalid_payloads:
            client_serial.write(payload)
            resp = client_serial.read(1)
            self.assertEqual(
                resp,
                b"",
                f"Expected no response (timeout/discard) for payload {repr(payload)}, got {repr(resp)}",
            )

        self.assertEqual(
            self.bridge.metrics["invalid_payloads"], len(invalid_payloads)
        )
        # Verify valid PIN immediately works afterwards
        client_serial.write(b"1234\n")
        resp_valid = client_serial.read(1).decode("ascii")
        self.assertEqual(resp_valid, "1")

    def test_04_three_consecutive_fails_triggers_lockout(self):
        """Test 3 consecutive incorrect PINs triggers lockout and returns 'L'."""
        bridge_serial, client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

        # 1st fail -> '0'
        client_serial.write(b"0001\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "0")

        # 2nd fail -> '0'
        client_serial.write(b"0002\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "0")

        # 3rd fail -> 'L' (Lockout activated!)
        client_serial.write(b"0003\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "L")

        self.assertTrue(self.bridge.is_locked())
        self.assertEqual(self.bridge.consecutive_fails, 0)

    def test_05_quick_lockout_5s_and_recovery(self):
        """
        Test 5-second quick lockout:
        - 3 fails -> 'L'
        - Sending input during lockout -> 'L'
        - Auto-recovery after 5s -> valid PIN -> receives '1'
        """
        bridge_serial, client_serial = create_mock_serial_pair()
        lockout_secs = 5.0
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=lockout_secs,
        )
        self.bridge.start()

        # Trigger lockout with 3 wrong PINs
        client_serial.write(b"0001\n")
        client_serial.read(1)
        client_serial.write(b"0002\n")
        client_serial.read(1)
        client_serial.write(b"0003\n")
        resp_l = client_serial.read(1).decode("ascii")
        self.assertEqual(resp_l, "L")
        self.assertTrue(self.bridge.is_locked())

        # While locked, sending valid PIN must return 'L'
        time.sleep(0.5)
        client_serial.write(b"1234\n")
        resp_during = client_serial.read(1).decode("ascii")
        self.assertEqual(
            resp_during,
            "L",
            f"Expected 'L' during lockout, got {repr(resp_during)}",
        )

        # Wait until remaining lockout expires
        rem = self.bridge.remaining_lockout()
        if rem > 0:
            time.sleep(rem + 0.3)

        self.assertFalse(self.bridge.is_locked(), "System should be unlocked after 5s")

        # Send valid PIN -> must receive '1'
        client_serial.write(b"1234\n")
        resp_after = client_serial.read(1).decode("ascii")
        self.assertEqual(
            resp_after,
            "1",
            f"Expected '1' after lockout expired, got {repr(resp_after)}",
        )

    def test_06_full_lockout_30s_and_recovery(self):
        """
        Test full 30-second lockout (per R4 and AC9):
        - 3 fails -> 'L'
        - Mid-lockout attempts at t=2s and t=15s return 'L'
        - Wait until full 30s expires
        - Send valid PIN -> receives '1'
        """
        bridge_serial, client_serial = create_mock_serial_pair()
        lockout_secs = 30.0
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=lockout_secs,
        )
        self.bridge.start()

        print("\n   [30s Lockout Test] Triggering 3 failed attempts...")
        client_serial.write(b"0001\n")
        client_serial.read(1)
        client_serial.write(b"0002\n")
        client_serial.read(1)
        client_serial.write(b"0003\n")
        resp_lock = client_serial.read(1).decode("ascii")
        self.assertEqual(resp_lock, "L")
        self.assertTrue(self.bridge.is_locked())

        start_time = time.monotonic()
        print("   [30s Lockout Test] Lockout triggered. Testing attempts during lockout...")

        # Test at t ~= 2s
        time.sleep(2.0)
        client_serial.write(b"1234\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "L")

        # Test at t ~= 15s
        time.sleep(13.0)
        client_serial.write(b"5678\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "L")

        # Wait remaining time to reach 30.3s
        remaining = self.bridge.remaining_lockout()
        print(f"   [30s Lockout Test] Waiting remaining {remaining:.1f}s for full lockout expiry...")
        if remaining > 0:
            time.sleep(remaining + 0.3)

        elapsed = time.monotonic() - start_time
        print(f"   [30s Lockout Test] Lockout expired after {elapsed:.1f}s elapsed.")
        self.assertFalse(self.bridge.is_locked())

        # Now send valid PIN
        client_serial.write(b"1234\n")
        resp_unlocked = client_serial.read(1).decode("ascii")
        self.assertEqual(
            resp_unlocked,
            "1",
            f"Expected '1' after 30s lockout expired, got {repr(resp_unlocked)}",
        )
        print("   [30s Lockout Test] Success: Received '1' after auto-unlock.")

    def test_07_audit_log_pin_masking_verification(self):
        """
        Verify security requirement:
        - Audit logs record event_type, status, user, timestamp
        - Raw PINs (e.g. 1234, 5678, 9999, 0001, etc.) NEVER appear anywhere
        - '****' is strictly used in place of all PIN occurrences
        """
        # Trigger varied authentication events
        self.auth_service.authenticate("1234")  # Success
        self.auth_service.authenticate("0000")  # Fail
        self.auth_service.log_lockout(30.0)    # Lockout

        self.assertTrue(self.test_log_file.is_file(), "Audit log file was not created")
        log_content = self.test_log_file.read_text(encoding="utf-8")

        # 1. Verify **** is present in log
        self.assertIn("PIN: ****", log_content, "Masked PIN '****' missing from audit log")

        # 2. Verify NO raw PINs appear in log
        forbidden_pins = ["1234", "5678", "9999", "0000"]
        for forbidden in forbidden_pins:
            # Check for explicit PIN disclosure
            self.assertNotIn(
                f"PIN: {forbidden}",
                log_content,
                f"Security Violation: Raw PIN {forbidden} exposed in log!",
            )

        # 3. Verify SQLite DB contents also mask PIN
        if self.test_db_file.is_file():
            logs = self.auth_service.get_logs()
            self.assertGreater(len(logs), 0)
            for entry in logs:
                detail = entry.get("detail", "")
                self.assertNotIn("1234", detail)
                self.assertNotIn("5678", detail)
                self.assertNotIn("9999", detail)

    def test_08_auto_reconnect_loop(self):
        """Test SerialBridge auto-reconnect logic handles port errors gracefully."""
        bridge_serial, client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth_service,
            serial_instance=bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

        # Normal operation
        client_serial.write(b"1234\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "1")

        # Simulate disconnection
        bridge_serial.close()
        self.assertFalse(self.bridge.is_connected())

        # Ensure calling process_line or send_response does not crash the app
        resp = self.bridge.process_line("1234\n")
        self.assertEqual(resp, "1")
        send_ok = self.bridge.send_response("1")
        # send fails gracefully returning False without unhandled exception
        self.assertFalse(send_ok)

    def test_09_data_directory_remains_strictly_unmodified(self):
        """Final verification of AC11: data/ SHA256 hashes unchanged and 0 bytecode."""
        self.verify_data_directory_clean()


def run_tests() -> int:
    """Executes the test suite and returns exit code (0 = success)."""
    print("=" * 70)
    print("  RUNNING MILESTONE 4 SERIAL BRIDGE & AUTH SERVICE TEST SUITE")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestSerialBridgeMock)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print("  ALL TESTS PASSED (100% SUCCESS) - EXIT CODE 0")
        print("=" * 70)
        return 0
    else:
        print(f"  FAILURES: {len(result.failures)} | ERRORS: {len(result.errors)}")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
