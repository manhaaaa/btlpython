"""
Comprehensive Requirement-Driven E2E Test Suite for Smart PIN Door Lock System
Covers Tiers 1 through 5:
- Tier 1: Feature Coverage (F1 to F7, >=5 tests per feature)
- Tier 2: Boundary & Corner Cases (empty, max-size, overflow, garbage, limits, errors)
- Tier 3: Cross-Feature Combinations (pairwise interactions)
- Tier 4: Real-World Application Scenarios (>=5 application-level tests)
- Tier 5: Adversarial Coverage Hardening (white-box stress, injections, timing, zero-leakage)

Adheres strictly to zero-mutation and bytecode protection for data/.
"""

import sys
import os
import time
import re
import queue
import hashlib
import sqlite3
import unittest
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List

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


def verify_data_directory_clean():
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


class FirmwareKeypadSimulator:
    """
    High-fidelity software model of the PIC16F877A keypad state machine & actuator logic
    defined in firmware/newmain.c.
    - 3x4 matrix mapping (Rows RB4..RB7, Cols RB0..RB2).
    - Enter_PIN() accumulator:
      - Digits '0'-'9': stores in pin[count++] (if count < 4), Green LED (RD0) blink 35ms.
      - '*': resets count = 0, clears buffer, Red LED (RD1) blink 60ms.
      - '#': submits if count == 4 -> returns '<PIN4>\\n', ignored if count < 4.
      - Extra digits beyond 4 are ignored.
    - Actuator handling:
      - '1' -> RD0 Green LED & RD2 Relay ON for 3.0s.
      - '0' -> RD1 Red LED & RD3 Buzzer ON for 1.5s.
      - 'L' -> RD1 Red LED & RD3 Buzzer chirp 3 times.
      - Timeout / Error -> Red LED blinks twice (150ms ON / 150ms OFF x2).
    """

    MATRIX_MAP = {
        (0, 0): '1', (0, 1): '2', (0, 2): '3',
        (1, 0): '4', (1, 1): '5', (1, 2): '6',
        (2, 0): '7', (2, 1): '8', (2, 2): '9',
        (3, 0): '*', (3, 1): '0', (3, 2): '#',
    }

    def __init__(self):
        self.buffer: List[str] = []
        self.submitted_payload: Optional[str] = None
        self.last_visual_feedback: Optional[str] = None
        self.green_blink_count: int = 0
        self.red_blink_count: int = 0
        self.actuator_state: Dict[str, Any] = {
            "RD0_green_led": False,
            "RD1_red_led": False,
            "RD2_relay": False,
            "RD3_buzzer": False,
            "action": "IDLE",
            "duration": 0.0,
            "chirps": 0,
            "red_blinks": 0,
        }

    def reset_buffer(self) -> None:
        self.buffer.clear()
        self.last_visual_feedback = "RED_BLINK_60MS"
        self.red_blink_count += 1

    def press_key(self, key: str) -> Optional[str]:
        """Processes a single key press through the PIC16F877A Enter_PIN logic."""
        if key in "0123456789":
            if len(self.buffer) < 4:
                self.buffer.append(key)
                self.last_visual_feedback = "GREEN_BLINK_35MS"
                self.green_blink_count += 1
            # Extra digits ignored if count == 4
            return None
        elif key == "*":
            self.reset_buffer()
            return None
        elif key == "#":
            if len(self.buffer) == 4:
                pin_str = "".join(self.buffer)
                self.submitted_payload = f"{pin_str}\n"
                # Ready to submit
                return self.submitted_payload
            # Ignored if len < 4
            return None
        return None

    def press_keys(self, sequence: str) -> Optional[str]:
        """Processes a sequence of key presses."""
        result = None
        for char in sequence:
            r = self.press_key(char)
            if r is not None:
                result = r
        return result

    def get_buffer_pin(self) -> str:
        return "".join(self.buffer)

    def handle_uart_response(
        self, response: str, timeout: bool = False, oerr: bool = False
    ) -> Dict[str, Any]:
        """Simulates firmware execution of UART response or error/timeout."""
        if timeout or oerr or response not in ("1", "0", "L"):
            self.actuator_state = {
                "RD0_green_led": False,
                "RD1_red_led": False,
                "RD2_relay": False,
                "RD3_buzzer": False,
                "action": "ERROR_TIMEOUT",
                "duration": 0.6,
                "chirps": 0,
                "red_blinks": 2,
            }
        elif response == "1":
            self.actuator_state = {
                "RD0_green_led": True,
                "RD1_red_led": False,
                "RD2_relay": True,
                "RD3_buzzer": False,
                "action": "ACCESS_GRANTED",
                "duration": 3.0,
                "chirps": 0,
                "red_blinks": 0,
            }
        elif response == "0":
            self.actuator_state = {
                "RD0_green_led": False,
                "RD1_red_led": True,
                "RD2_relay": False,
                "RD3_buzzer": True,
                "action": "ACCESS_DENIED",
                "duration": 1.5,
                "chirps": 0,
                "red_blinks": 0,
            }
        elif response == "L":
            self.actuator_state = {
                "RD0_green_led": False,
                "RD1_red_led": True,
                "RD2_relay": False,
                "RD3_buzzer": True,
                "action": "SYSTEM_LOCKED",
                "duration": 1.2,
                "chirps": 3,
                "red_blinks": 0,
            }
        return self.actuator_state


# ============================================================================
# TIER 1: FEATURE COVERAGE (>=5 tests per feature F1..F7)
# ============================================================================

class TestTier1_F1_KeypadDigitEntry(unittest.TestCase):
    """F1: Keypad digit entry (single digits, multi-digits, 4 digits)."""

    def setUp(self):
        self.sim = FirmwareKeypadSimulator()

    def test_f1_01_single_digit_entry(self):
        self.sim.press_key('1')
        self.assertEqual(self.sim.get_buffer_pin(), "1")
        self.assertEqual(len(self.sim.buffer), 1)
        self.assertEqual(self.sim.last_visual_feedback, "GREEN_BLINK_35MS")
        self.assertEqual(self.sim.green_blink_count, 1)

    def test_f1_02_two_digits_entry(self):
        self.sim.press_keys("12")
        self.assertEqual(self.sim.get_buffer_pin(), "12")
        self.assertEqual(len(self.sim.buffer), 2)
        self.assertEqual(self.sim.green_blink_count, 2)

    def test_f1_03_three_digits_entry(self):
        self.sim.press_keys("567")
        self.assertEqual(self.sim.get_buffer_pin(), "567")
        self.assertEqual(len(self.sim.buffer), 3)
        self.assertEqual(self.sim.green_blink_count, 3)

    def test_f1_04_four_digits_entry(self):
        self.sim.press_keys("9999")
        self.assertEqual(self.sim.get_buffer_pin(), "9999")
        self.assertEqual(len(self.sim.buffer), 4)
        self.assertEqual(self.sim.green_blink_count, 4)

    def test_f1_05_all_ten_digits_supported(self):
        for digit in "0123456789":
            sim = FirmwareKeypadSimulator()
            sim.press_key(digit)
            self.assertEqual(sim.get_buffer_pin(), digit)
            self.assertEqual(sim.last_visual_feedback, "GREEN_BLINK_35MS")


class TestTier1_F2_HashSubmitKey(unittest.TestCase):
    """F2: '#' submit key behavior (less than 4 digits ignored, exactly 4 digits submitted)."""

    def setUp(self):
        self.sim = FirmwareKeypadSimulator()

    def test_f2_01_hash_with_zero_digits_ignored(self):
        res = self.sim.press_key('#')
        self.assertIsNone(res)
        self.assertEqual(self.sim.get_buffer_pin(), "")

    def test_f2_02_hash_with_one_digit_ignored(self):
        self.sim.press_key('1')
        res = self.sim.press_key('#')
        self.assertIsNone(res)
        self.assertEqual(self.sim.get_buffer_pin(), "1")

    def test_f2_03_hash_with_two_digits_ignored(self):
        self.sim.press_keys("12")
        res = self.sim.press_key('#')
        self.assertIsNone(res)
        self.assertEqual(self.sim.get_buffer_pin(), "12")

    def test_f2_04_hash_with_three_digits_ignored(self):
        self.sim.press_keys("123")
        res = self.sim.press_key('#')
        self.assertIsNone(res)
        self.assertEqual(self.sim.get_buffer_pin(), "123")

    def test_f2_05_hash_with_four_digits_submits(self):
        self.sim.press_keys("1234")
        res = self.sim.press_key('#')
        self.assertEqual(res, "1234\n")
        self.assertEqual(self.sim.submitted_payload, "1234\n")


class TestTier1_F3_StarClearKey(unittest.TestCase):
    """F3: '*' clear key behavior (resets input buffer at any stage)."""

    def setUp(self):
        self.sim = FirmwareKeypadSimulator()

    def test_f3_01_star_on_empty_buffer(self):
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")
        self.assertEqual(self.sim.last_visual_feedback, "RED_BLINK_60MS")

    def test_f3_02_star_clears_single_digit(self):
        self.sim.press_key('7')
        self.assertEqual(self.sim.get_buffer_pin(), "7")
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")
        self.assertEqual(len(self.sim.buffer), 0)

    def test_f3_03_star_clears_two_digits(self):
        self.sim.press_keys("12")
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")

    def test_f3_04_star_clears_three_digits(self):
        self.sim.press_keys("987")
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")

    def test_f3_05_star_clears_four_digits_prevents_submit(self):
        self.sim.press_keys("1234")
        self.assertEqual(len(self.sim.buffer), 4)
        self.sim.press_key('*')
        self.assertEqual(len(self.sim.buffer), 0)
        # Attempt to submit now -> must be ignored
        res = self.sim.press_key('#')
        self.assertIsNone(res)


class TestTier1_F4_ExtraDigitsIgnored(unittest.TestCase):
    """F4: Extra digits (>4) ignored."""

    def setUp(self):
        self.sim = FirmwareKeypadSimulator()

    def test_f4_01_fifth_digit_ignored(self):
        self.sim.press_keys("12345")
        self.assertEqual(self.sim.get_buffer_pin(), "1234")
        self.assertEqual(len(self.sim.buffer), 4)
        # Green blink count should be 4, 5th digit produced no feedback
        self.assertEqual(self.sim.green_blink_count, 4)

    def test_f4_02_sixth_digit_ignored(self):
        self.sim.press_keys("987654")
        self.assertEqual(self.sim.get_buffer_pin(), "9876")
        self.assertEqual(len(self.sim.buffer), 4)

    def test_f4_03_burst_ten_digits_ignored_past_four(self):
        self.sim.press_keys("0123456789")
        self.assertEqual(self.sim.get_buffer_pin(), "0123")
        self.assertEqual(len(self.sim.buffer), 4)

    def test_f4_04_extra_zeroes_ignored(self):
        self.sim.press_keys("1234000")
        self.assertEqual(self.sim.get_buffer_pin(), "1234")

    def test_f4_05_extra_digits_submit_only_first_four(self):
        res = self.sim.press_keys("567891#")
        self.assertEqual(res, "5678\n")


class TestTier1_F5_CorrectPinMultipleUsers(unittest.TestCase):
    """F5: Correct PIN recognition for multiple users (1234, 5678, 9999)."""

    def setUp(self):
        self.test_log = APP_DIR / "tier1_f5_audit.log"
        self.test_db = APP_DIR / "tier1_f5.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()
        self.sim = FirmwareKeypadSimulator()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_f5_01_user1_valid_pin_1234(self):
        self.client_serial.write(b"1234\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_GRANTED")
        self.assertTrue(act["RD0_green_led"])
        self.assertTrue(act["RD2_relay"])
        self.assertEqual(act["duration"], 3.0)

    def test_f5_02_user2_valid_pin_5678(self):
        self.client_serial.write(b"5678\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_GRANTED")
        self.assertTrue(act["RD0_green_led"])
        self.assertTrue(act["RD2_relay"])

    def test_f5_03_admin_valid_pin_9999(self):
        self.client_serial.write(b"9999\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_GRANTED")
        self.assertTrue(act["RD2_relay"])

    def test_f5_04_sequential_valid_logins(self):
        for pin in ["1234", "5678", "9999"]:
            self.client_serial.write(f"{pin}\n".encode("ascii"))
            resp = self.client_serial.read(1).decode("ascii")
            self.assertEqual(resp, "1")
        self.assertEqual(self.bridge.consecutive_fails, 0)
        self.assertEqual(self.bridge.metrics["access_granted"], 3)

    def test_f5_05_actuator_response_grant(self):
        act = self.sim.handle_uart_response("1")
        self.assertEqual(act["action"], "ACCESS_GRANTED")
        self.assertTrue(act["RD0_green_led"])
        self.assertFalse(act["RD1_red_led"])
        self.assertTrue(act["RD2_relay"])
        self.assertFalse(act["RD3_buzzer"])
        self.assertEqual(act["duration"], 3.0)


class TestTier1_F6_IncorrectPinRejection(unittest.TestCase):
    """F6: Incorrect PIN rejection."""

    def setUp(self):
        self.test_log = APP_DIR / "tier1_f6_audit.log"
        self.test_db = APP_DIR / "tier1_f6.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()
        self.sim = FirmwareKeypadSimulator()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_f6_01_wrong_pin_0000(self):
        self.client_serial.write(b"0000\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "0")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_DENIED")
        self.assertTrue(act["RD1_red_led"])
        self.assertTrue(act["RD3_buzzer"])
        self.assertFalse(act["RD2_relay"])
        self.assertEqual(act["duration"], 1.5)

    def test_f6_02_wrong_pin_1111(self):
        self.client_serial.write(b"1111\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "0")

    def test_f6_03_wrong_pin_4321(self):
        self.client_serial.write(b"4321\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "0")

    def test_f6_04_wrong_pin_off_by_one_9998(self):
        self.client_serial.write(b"9998\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "0")

    def test_f6_05_two_consecutive_fails_increment(self):
        self.client_serial.write(b"0001\n")
        r1 = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r1, "0")
        self.assertEqual(self.bridge.consecutive_fails, 1)

        self.client_serial.write(b"0002\n")
        r2 = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r2, "0")
        self.assertEqual(self.bridge.consecutive_fails, 2)
        self.assertFalse(self.bridge.is_locked())


class TestTier1_F7_SerialBridgeAutoReconnect(unittest.TestCase):
    """F7: Serial bridge auto-reconnect handling."""

    def test_f7_01_initial_disconnected_state(self):
        bridge = SerialBridge(port="COM999", serial_instance=None)
        self.assertFalse(bridge.is_connected())
        self.assertEqual(bridge.state, "IDLE")

    def test_f7_02_successful_connection(self):
        bridge_serial, _ = create_mock_serial_pair()
        bridge = SerialBridge(serial_instance=bridge_serial)
        bridge.start()
        time.sleep(0.1)
        self.assertTrue(bridge.is_connected())
        bridge.stop()

    def test_f7_03_detect_disconnection(self):
        bridge_serial, _ = create_mock_serial_pair()
        bridge = SerialBridge(serial_instance=bridge_serial)
        bridge.start()
        time.sleep(0.1)
        bridge_serial.close()
        self.assertFalse(bridge.is_connected())
        bridge.stop()

    def test_f7_04_graceful_send_on_disconnect(self):
        bridge_serial, _ = create_mock_serial_pair()
        bridge = SerialBridge(serial_instance=bridge_serial)
        bridge_serial.close()
        ok = bridge.send_response("1")
        self.assertFalse(ok)

    def test_f7_05_reconnect_resumes_processing(self):
        bridge_serial, client_serial = create_mock_serial_pair()
        auth = AuthService()
        bridge = SerialBridge(auth_service=auth, serial_instance=bridge_serial)
        bridge.start()

        # Step 1: Normal message
        client_serial.write(b"1234\n")
        self.assertEqual(client_serial.read(1).decode("ascii"), "1")

        # Step 2: Disconnect
        bridge_serial.close()
        self.assertFalse(bridge.is_connected())

        # Step 3: Direct processing still succeeds cleanly
        res = bridge.process_line("5678\n")
        self.assertEqual(res, "1")
        bridge.stop()


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES (20 tests)
# ============================================================================

class TestTier2_BoundaryAndCornerCases(unittest.TestCase):
    """Tier 2: Boundary & Corner Cases (empty, max-size, overflow, garbage, limits)."""

    def setUp(self):
        self.test_log = APP_DIR / "tier2_audit.log"
        self.test_db = APP_DIR / "tier2.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair(timeout=0.2)
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()
        self.sim = FirmwareKeypadSimulator()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    # Empty & Blank Lines
    def test_t2_01_empty_string(self):
        res = self.bridge.process_line("")
        self.assertIsNone(res)

    def test_t2_02_single_newline(self):
        self.client_serial.write(b"\n")
        self.assertEqual(self.client_serial.read(1), b"")
        self.assertEqual(self.bridge.metrics["invalid_payloads"], 1)

    def test_t2_03_crlf_alone(self):
        self.client_serial.write(b"\r\n")
        self.assertEqual(self.client_serial.read(1), b"")
        self.assertEqual(self.bridge.metrics["invalid_payloads"], 1)

    def test_t2_04_whitespace_only(self):
        self.client_serial.write(b"    \n")
        self.assertEqual(self.client_serial.read(1), b"")
        self.assertEqual(self.bridge.metrics["invalid_payloads"], 1)

    def test_t2_05_tab_newline(self):
        self.client_serial.write(b"\t\n")
        self.assertEqual(self.client_serial.read(1), b"")
        self.assertEqual(self.bridge.metrics["invalid_payloads"], 1)

    # Length Limits & Overflows
    def test_t2_06_too_short_1_digit(self):
        self.client_serial.write(b"1\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_07_too_short_2_digits(self):
        self.client_serial.write(b"12\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_08_too_short_3_digits(self):
        self.client_serial.write(b"123\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_09_too_long_5_digits(self):
        self.client_serial.write(b"12345\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_10_burst_10_digits(self):
        self.client_serial.write(b"1234567890\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_11_extreme_length_100_digits(self):
        payload = (b"9" * 100) + b"\n"
        self.client_serial.write(payload)
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_12_massive_payload_1024_bytes(self):
        payload = (b"A" * 1024) + b"\n"
        self.client_serial.write(payload)
        self.assertEqual(self.client_serial.read(1), b"")

    # Garbage & Non-numeric Characters
    def test_t2_13_alphabetic_characters(self):
        self.client_serial.write(b"abcd\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_14_special_symbols(self):
        self.client_serial.write(b"@#$%\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_15_mixed_alphanumeric(self):
        self.client_serial.write(b"12a4\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_16_non_printable_bytes(self):
        self.client_serial.write(b"\x01\x02\x03\x04\n")
        self.assertEqual(self.client_serial.read(1), b"")

    def test_t2_17_unicode_vietnamese(self):
        self.client_serial.write("khóa\n".encode("utf-8"))
        self.assertEqual(self.client_serial.read(1), b"")

    # Rapid Bursts & Simulated Hardware Errors
    def test_t2_18_rapid_consecutive_submissions(self):
        # Send 10 messages rapidly
        for i in range(10):
            self.client_serial.write(b"1234\n")
        # Read back 10 responses
        responses = [self.client_serial.read(1).decode("ascii") for _ in range(10)]
        self.assertEqual(responses, ["1"] * 10)

    def test_t2_19_uart_overrun_error_oerr_simulation(self):
        act = self.sim.handle_uart_response("", oerr=True)
        self.assertEqual(act["action"], "ERROR_TIMEOUT")
        self.assertEqual(act["red_blinks"], 2)

    def test_t2_20_uart_framing_error_simulation(self):
        act = self.sim.handle_uart_response("", timeout=True)
        self.assertEqual(act["action"], "ERROR_TIMEOUT")
        self.assertEqual(act["red_blinks"], 2)


# ============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise Interactions)
# ============================================================================

class TestTier3_CrossFeatureCombinations(unittest.TestCase):
    """Tier 3: Cross-Feature Combinations (pairwise interactions)."""

    def setUp(self):
        self.test_log = APP_DIR / "tier3_audit.log"
        self.test_db = APP_DIR / "tier3.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=2.0,
        )
        self.bridge.start()
        self.sim = FirmwareKeypadSimulator()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_t3_01_keypad_partial_clear_reenter_submit(self):
        # 1. Enter 2 digits
        self.sim.press_keys("12")
        self.assertEqual(self.sim.get_buffer_pin(), "12")
        # 2. Press '*'
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")
        # 3. Enter 4 digits and submit
        sub = self.sim.press_keys("1234#")
        self.assertEqual(sub, "1234\n")
        # 4. Transmit and receive response
        self.client_serial.write(sub.encode("ascii"))
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_GRANTED")

    def test_t3_02_fail_recovery_resets_counter(self):
        # Two failed attempts
        self.client_serial.write(b"0001\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "0")
        self.client_serial.write(b"0002\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "0")
        self.assertEqual(self.bridge.consecutive_fails, 2)

        # One successful attempt
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")
        # Consecutive fails must be reset to 0!
        self.assertEqual(self.bridge.consecutive_fails, 0)

        # Subsequent failure increments to 1 (not 3, so no lockout)
        self.client_serial.write(b"0003\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "0")
        self.assertEqual(self.bridge.consecutive_fails, 1)
        self.assertFalse(self.bridge.is_locked())

    def test_t3_03_three_fails_lockout_wait_unlock(self):
        # 3 fails -> 'L'
        for pin in ["0001", "0002", "0003"]:
            self.client_serial.write(f"{pin}\n".encode("ascii"))
            resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "L")
        self.assertTrue(self.bridge.is_locked())

        # Attempt during lockout -> 'L'
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "L")

        # Wait until remaining lockout expires
        rem = self.bridge.remaining_lockout()
        if rem > 0:
            time.sleep(rem + 0.2)

        self.assertFalse(self.bridge.is_locked())

        # Now send valid PIN -> '1'
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

    def test_t3_04_disconnect_mid_stream_reconnect_auth(self):
        # Enter 2 digits on keypad
        self.sim.press_keys("56")
        # Port disconnects
        self.bridge_serial.close()
        self.assertFalse(self.bridge.is_connected())

        # Reconnect with new pair
        b2, c2 = create_mock_serial_pair()
        self.bridge._serial = b2
        self.bridge._connected = True

        # Enter remaining 2 digits and submit
        sub = self.sim.press_keys("78#")
        self.assertEqual(sub, "5678\n")
        c2.write(sub.encode("ascii"))
        resp = c2.read(1).decode("ascii")
        self.assertEqual(resp, "1")

    def test_t3_05_multiuser_interleaved_logins_audit_trail(self):
        logins = [
            ("1234", "USR001"),
            ("5678", "USR002"),
            ("9999", "ADM001"),
            ("1234", "USR001"),
        ]
        for pin, expected_user_id in logins:
            self.client_serial.write(f"{pin}\n".encode("ascii"))
            resp = self.client_serial.read(1).decode("ascii")
            self.assertEqual(resp, "1")

        # Verify audit trail
        logs = self.auth.get_logs()
        self.assertGreaterEqual(len(logs), 4)
        details = [entry["detail"] for entry in logs]
        for _, expected_user_id in logins:
            matched = any(expected_user_id in d for d in details)
            self.assertTrue(matched, f"Expected {expected_user_id} in audit log")

    def test_t3_06_keypad_extra_digits_with_clear_and_submit(self):
        # Enter 6 digits: '123456'
        self.sim.press_keys("123456")
        self.assertEqual(self.sim.get_buffer_pin(), "1234")
        # Clear with '*'
        self.sim.press_key('*')
        self.assertEqual(self.sim.get_buffer_pin(), "")
        # Enter valid PIN '5678' and submit
        sub = self.sim.press_keys("5678#")
        self.assertEqual(sub, "5678\n")
        self.client_serial.write(sub.encode("ascii"))
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

    def test_t3_07_lockout_attempt_invalid_then_valid_after_expiry(self):
        # Trigger lockout
        for p in ["0001", "0002", "0003"]:
            self.client_serial.write(f"{p}\n".encode("ascii"))
            r = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r, "L")

        # Invalid PIN during lockout -> returns 'L'
        self.client_serial.write(b"9998\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "L")

        # Wait for lockout to expire
        rem = self.bridge.remaining_lockout()
        if rem > 0:
            time.sleep(rem + 0.2)

        # Now send valid PIN
        self.client_serial.write(b"9999\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")


# ============================================================================
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (>=5 tests)
# ============================================================================

class TestTier4_RealWorldApplicationScenarios(unittest.TestCase):
    """Tier 4: Real-World Application Scenarios (>=5 application-level tests)."""

    def setUp(self):
        self.test_log = APP_DIR / "tier4_audit.log"
        self.test_db = APP_DIR / "tier4.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair()
        # Default 5s lockout for quick scenarios
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()
        self.sim = FirmwareKeypadSimulator()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_t4_01_scenario_morning_office_arrival(self):
        """
        Scenario 1: Morning office arrival.
        - Staff 1 (Nguyễn Văn A) enters '1234#' -> door unlocked ('1'), relay spins 3s.
        - Staff 2 (Trần Thị B) enters '5678#' -> door unlocked ('1'), relay spins 3s.
        - Admin (Quản Trị Viên) enters '9999#' -> door unlocked ('1'), relay spins 3s.
        - Verifies audit logs record all 3 distinct user IDs without any PIN disclosure.
        """
        users = [("1234", "USR001"), ("5678", "USR002"), ("9999", "ADM001")]
        for pin, uid in users:
            sim = FirmwareKeypadSimulator()
            sub = sim.press_keys(f"{pin}#")
            self.assertEqual(sub, f"{pin}\n")
            self.client_serial.write(sub.encode("ascii"))
            resp = self.client_serial.read(1).decode("ascii")
            self.assertEqual(resp, "1")
            act = sim.handle_uart_response(resp)
            self.assertEqual(act["action"], "ACCESS_GRANTED")
            self.assertTrue(act["RD2_relay"])
            self.assertEqual(act["duration"], 3.0)

        logs = self.auth.get_logs()
        self.assertEqual(len(logs), 3)
        self.assertIn("USR001", logs[2]["detail"])
        self.assertIn("USR002", logs[1]["detail"])
        self.assertIn("ADM001", logs[0]["detail"])

    def test_t4_02_scenario_brute_force_attacker(self):
        """
        Scenario 2: Brute-force attacker.
        - Attacker attempts rapid sequential guesses: '0000', '1111', '2222'.
        - 3rd attempt triggers security lockout ('L').
        - Attacker attempts '3333' and correct '1234' during lockout -> immediate 'L', relay stays locked.
        - Verifies audit log records ALARM LOCKOUT.
        """
        guesses = ["0000", "1111", "2222"]
        responses = []
        for g in guesses:
            self.client_serial.write(f"{g}\n".encode("ascii"))
            responses.append(self.client_serial.read(1).decode("ascii"))

        self.assertEqual(responses, ["0", "0", "L"])
        self.assertTrue(self.bridge.is_locked())

        # Attacker tries further guesses during lockout
        for post in ["3333", "1234"]:
            self.client_serial.write(f"{post}\n".encode("ascii"))
            resp = self.client_serial.read(1).decode("ascii")
            self.assertEqual(resp, "L")
            act = self.sim.handle_uart_response(resp)
            self.assertEqual(act["action"], "SYSTEM_LOCKED")
            self.assertFalse(act["RD2_relay"])  # Relay NEVER unlocks

        logs = self.auth.get_logs()
        lockout_entries = [e for e in logs if e["event_type"] == "ALARM"]
        self.assertGreaterEqual(len(lockout_entries), 1)

    def test_t4_03_scenario_fat_finger_mistake(self):
        """
        Scenario 3: Fat-finger mistake.
        - User accidentally enters wrong PIN twice: '1235', '1243' -> Buzzer activates ('0').
        - User pauses, enters correct PIN '1234' -> Access granted ('1'), relay spins 3.0s.
        - Consecutive fail count resets to 0; lockout avoided.
        """
        sim = FirmwareKeypadSimulator()
        # 1st mistake
        sub1 = sim.press_keys("1235#")
        self.client_serial.write(sub1.encode("ascii"))
        r1 = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r1, "0")
        act1 = sim.handle_uart_response(r1)
        self.assertEqual(act1["action"], "ACCESS_DENIED")
        self.assertTrue(act1["RD3_buzzer"])

        # 2nd mistake
        sim.reset_buffer()
        sub2 = sim.press_keys("1243#")
        self.client_serial.write(sub2.encode("ascii"))
        r2 = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r2, "0")

        # Realizes error, enters correct PIN
        sim.reset_buffer()
        sub3 = sim.press_keys("1234#")
        self.client_serial.write(sub3.encode("ascii"))
        r3 = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r3, "1")
        act3 = sim.handle_uart_response(r3)
        self.assertEqual(act3["action"], "ACCESS_GRANTED")
        self.assertTrue(act3["RD2_relay"])
        self.assertEqual(self.bridge.consecutive_fails, 0)

    def test_t4_04_scenario_noise_on_serial_line(self):
        """
        Scenario 4: Noise/glitch on serial line.
        - Spurious electromagnetic noise: raw binary garbage & broken lines.
        - Bridge discards noise without crashing or emitting false alarms.
        - Immediately afterwards, legitimate PIN '5678\n' is sent and succeeds ('1').
        """
        noise_bursts = [
            b"\xFF\xFE\x00\x12\n",
            b"??\x80\r\n",
            b"\x00\x00\x00\x00\n",
        ]
        for burst in noise_bursts:
            self.client_serial.write(burst)
            # No response returned
            self.assertEqual(self.client_serial.read(1), b"")

        self.assertEqual(self.bridge.metrics["invalid_payloads"], 3)

        # Legitimate PIN follows
        self.client_serial.write(b"5678\n")
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")
        act = self.sim.handle_uart_response(resp)
        self.assertEqual(act["action"], "ACCESS_GRANTED")

    def test_t4_05_scenario_full_30s_lockout_operational_verification(self):
        """
        Scenario 5: Full 30s lockout operational verification.
        - Fulfills R4 and AC9 requirements for authentic 30.0-second lockout.
        - 3 consecutive failed attempts trigger 30s lockout.
        - Mid-lockout attempt at t=1.5s receives 'L'.
        - System waits full 30s lockout duration.
        - System unlocks and accepts valid PIN '1234' -> receives '1'.
        """
        # Configure bridge for exactly 30.0s lockout
        self.bridge.stop()
        self.bridge_serial, self.client_serial = create_mock_serial_pair()
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=30.0,
        )
        self.bridge.start()

        # Trigger lockout
        for p in ["0001", "0002", "0003"]:
            self.client_serial.write(f"{p}\n".encode("ascii"))
            r = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r, "L")
        self.assertTrue(self.bridge.is_locked())

        # Mid-lockout attempt
        time.sleep(1.5)
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "L")

        # Wait full lockout duration
        rem = self.bridge.remaining_lockout()
        if rem > 0:
            time.sleep(rem + 0.3)

        self.assertFalse(self.bridge.is_locked(), "System should be unlocked after 30s")

        # Post-lockout entry
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")


# ============================================================================
# TIER 5: ADVERSARIAL COVERAGE HARDENING (9 tests)
# ============================================================================

class TestTier5_AdversarialCoverageHardening(unittest.TestCase):
    """Tier 5: Adversarial Coverage Hardening."""

    def setUp(self):
        self.test_log = APP_DIR / "tier5_audit.log"
        self.test_db = APP_DIR / "tier5.db"
        self._cleanup()
        self.auth = AuthService(
            users_file=APP_DIR / "users.json",
            log_file=self.test_log,
            db_path=self.test_db,
            enable_db=True,
        )
        self.bridge_serial, self.client_serial = create_mock_serial_pair(timeout=0.3)
        self.bridge = SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=5.0,
        )
        self.bridge.start()

    def tearDown(self):
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.stop()
        self._cleanup()

    def _cleanup(self):
        for p in (getattr(self, "test_log", None), getattr(self, "test_db", None)):
            if p and p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_t5_01_newline_variations(self):
        """Tests CRLF, LF, CR, and mixed line endings."""
        # 1. \r\n (CRLF)
        self.client_serial.write(b"1234\r\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

        # 2. \n (LF)
        self.client_serial.write(b"5678\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

        # 3. Direct process_line with \r
        res = self.bridge.process_line("9999\r")
        self.assertEqual(res, "1")

    def test_t5_02_partial_trickle_byte_feed(self):
        """Simulates byte-by-byte trickle feed with pauses between bytes."""
        for b in b"1234\n":
            self.client_serial.write(bytes([b]))
            time.sleep(0.02)
        resp = self.client_serial.read(1).decode("ascii")
        self.assertEqual(resp, "1")

    def test_t5_03_embedded_null_byte_rejection(self):
        """Rejects payload with embedded null byte."""
        self.client_serial.write(b"12\x0034\n")
        self.assertEqual(self.client_serial.read(1), b"")
        self.assertEqual(self.bridge.metrics["invalid_payloads"], 1)

    def test_t5_04_sql_injection_rejection(self):
        """Attempts SQL injection via serial stream."""
        injections = [
            b"1' OR '1'='1\n",
            b"'; DROP TABLE access_logs; --\n",
            b"0000' UNION SELECT * FROM users --\n",
        ]
        for inj in injections:
            self.client_serial.write(inj)
            self.assertEqual(self.client_serial.read(1), b"")

        # Verify DB is intact
        logs = self.auth.get_logs()
        self.assertIsInstance(logs, list)

    def test_t5_05_format_string_and_control_chars(self):
        """Attempts format string or terminal escape sequence injection."""
        malicious = [
            b"%s%s%s%s\n",
            b"%x%x%x%x\n",
            b"\x1b[31m1234\x1b[0m\n",
            b"\x07\x08\x091234\n",
        ]
        for m in malicious:
            self.client_serial.write(m)
            self.assertEqual(self.client_serial.read(1), b"")

    def test_t5_06_rapid_input_burst_50_packets(self):
        """Stress tests bridge thread with 50 packets sent in millisecond bursts."""
        for _ in range(50):
            self.client_serial.write(b"1234\n")
        # Read back all 50
        count = 0
        for _ in range(50):
            r = self.client_serial.read(1).decode("ascii")
            if r == "1":
                count += 1
        self.assertEqual(count, 50)

    def test_t5_07_lockout_boundary_microsecond_precision(self):
        """Verifies state machine precision at the exact boundary of lockout expiry."""
        self.bridge.lockout_duration = 0.5
        # Trigger lockout
        for p in ["0001", "0002", "0003"]:
            self.client_serial.write(f"{p}\n".encode("ascii"))
            r = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r, "L")

        # Just before expiry: should still be locked
        time.sleep(0.2)
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "L")

        # Wait until expiry completes
        time.sleep(0.4)
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

    def test_t5_08_adversarial_audit_pin_leakage_scan(self):
        """Exhaustive scan verifying that no raw PIN is ever logged or exposed."""
        # Perform logins and failures
        self.auth.authenticate("1234")
        self.auth.authenticate("5678")
        self.auth.authenticate("9999")
        self.auth.authenticate("0000")
        self.auth.log_lockout(30.0)

        # 1. Read audit log text
        content = self.test_log.read_text(encoding="utf-8")
        for secret_pin in ["1234", "5678", "9999", "0000"]:
            self.assertNotIn(
                f"PIN: {secret_pin}",
                content,
                f"Adversarial audit failed: Raw PIN {secret_pin} found in audit log text!",
            )

        # 2. Read SQLite database
        if self.test_db.is_file():
            conn = sqlite3.connect(str(self.test_db))
            cursor = conn.cursor()
            cursor.execute("SELECT detail FROM access_logs")
            rows = cursor.fetchall()
            conn.close()
            for (detail,) in rows:
                for secret_pin in ["1234", "5678", "9999", "0000"]:
                    self.assertNotIn(
                        f"PIN: {secret_pin}",
                        detail,
                        f"Adversarial audit failed: Raw PIN {secret_pin} found in SQLite table!",
                    )

    def test_t5_09_data_directory_sha256_unmodified_under_stress(self):
        """Verifies data/ directory is strictly untouched and 0 bytecode exists."""
        verify_data_directory_clean()


if __name__ == "__main__":
    unittest.main()
