"""
Standalone E2E Test Suite Runner for Smart PIN Door Lock System
Executes Tiers 1 through 5, aggregates metrics, and generates a formatted report.

Usage:
  python tests/test_e2e_runner.py               # Runs complete test suite (all 5 tiers)
  python tests/test_e2e_runner.py --tier 1      # Runs specific tier (1..5)
  python tests/test_e2e_runner.py --quick       # Runs with fast lockout for rapid CI feedback
"""

import sys
import os
import time
import argparse
import unittest
from pathlib import Path

# Enforce no bytecode generation
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Resolve directories
TESTS_DIR = Path(__file__).resolve().parent
BTL_DIR = TESTS_DIR.parent
if str(BTL_DIR) not in sys.path:
    sys.path.insert(0, str(BTL_DIR))

# Import test cases and baseline integrity verification
import tests.test_tiers as test_tiers
from tests.test_tiers import (
    verify_data_directory_clean,
    TestTier1_F1_KeypadDigitEntry,
    TestTier1_F2_HashSubmitKey,
    TestTier1_F3_StarClearKey,
    TestTier1_F4_ExtraDigitsIgnored,
    TestTier1_F5_CorrectPinMultipleUsers,
    TestTier1_F6_IncorrectPinRejection,
    TestTier1_F7_SerialBridgeAutoReconnect,
    TestTier2_BoundaryAndCornerCases,
    TestTier3_CrossFeatureCombinations,
    TestTier4_RealWorldApplicationScenarios,
    TestTier5_AdversarialCoverageHardening,
)

TIER_MAPPING = {
    1: {
        "name": "Tier 1: Feature Coverage (F1-F7, >=5 tests/feature)",
        "classes": [
            TestTier1_F1_KeypadDigitEntry,
            TestTier1_F2_HashSubmitKey,
            TestTier1_F3_StarClearKey,
            TestTier1_F4_ExtraDigitsIgnored,
            TestTier1_F5_CorrectPinMultipleUsers,
            TestTier1_F6_IncorrectPinRejection,
            TestTier1_F7_SerialBridgeAutoReconnect,
        ],
    },
    2: {
        "name": "Tier 2: Boundary & Corner Cases",
        "classes": [TestTier2_BoundaryAndCornerCases],
    },
    3: {
        "name": "Tier 3: Cross-Feature Combinations (Pairwise)",
        "classes": [TestTier3_CrossFeatureCombinations],
    },
    4: {
        "name": "Tier 4: Real-World Application Scenarios",
        "classes": [TestTier4_RealWorldApplicationScenarios],
    },
    5: {
        "name": "Tier 5: Adversarial Coverage Hardening",
        "classes": [TestTier5_AdversarialCoverageHardening],
    },
}


def build_suite_for_tier(tier_num: int) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    tier_info = TIER_MAPPING.get(tier_num)
    if not tier_info:
        raise ValueError(f"Unknown tier number: {tier_num}")
    for cls in tier_info["classes"]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


def run_e2e_suite(target_tier: int = 0, quick: bool = False) -> int:
    print("=" * 76)
    print("       SMART PIN DOOR LOCK SYSTEM — E2E TEST SUITE RUNNER")
    print("=" * 76)
    print(f"Target: {'All Tiers (1 to 5)' if target_tier == 0 else f'Tier {target_tier}'}")
    print(f"Mode:   {'Quick CI Lockout' if quick else 'Standard (Includes 30s Real Lockout)'}")
    print("-" * 76)

    # 1. Pre-execution Baseline Data Integrity Check
    print(">>> [Pre-Check] Verifying data/ directory SHA256 integrity and bytecode lock...")
    try:
        verify_data_directory_clean()
        print("    [PASS] All 8 baseline files in data/ match bitwise SHA256 hashes.")
        print("    [PASS] No __pycache__ directory exists in data/.")
    except Exception as e:
        print(f"    [FAIL] Pre-check failed: {e}")
        return 1

    # Adjust Scenario 5 lockout if quick mode requested
    if quick:
        TestTier4_RealWorldApplicationScenarios.test_t4_05_scenario_full_30s_lockout_operational_verification = (
            _patch_quick_scenario_5()
        )

    tiers_to_run = [target_tier] if target_tier in TIER_MAPPING else [1, 2, 3, 4, 5]
    tier_results = {}
    overall_start = time.time()
    total_passed = 0
    total_failed = 0
    total_errors = 0

    for t_num in tiers_to_run:
        info = TIER_MAPPING[t_num]
        print(f"\n" + "-" * 76)
        print(f">>> Running {info['name']}...")
        print("-" * 76)

        suite = build_suite_for_tier(t_num)
        runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout)
        t_start = time.time()
        res = runner.run(suite)
        t_elapsed = time.time() - t_start

        passed = res.testsRun - len(res.failures) - len(res.errors)
        tier_results[t_num] = {
            "name": info["name"],
            "total": res.testsRun,
            "passed": passed,
            "failed": len(res.failures),
            "errors": len(res.errors),
            "time": t_elapsed,
        }
        total_passed += passed
        total_failed += len(res.failures)
        total_errors += len(res.errors)

    overall_elapsed = time.time() - overall_start

    # 2. Post-execution Data Integrity Check
    print("\n" + "-" * 76)
    print(">>> [Post-Check] Re-verifying data/ directory SHA256 integrity...")
    try:
        verify_data_directory_clean()
        print("    [PASS] data/ directory remained 100% untouched across all test executions.")
    except Exception as e:
        print(f"    [FAIL] Post-check failed: {e}")
        return 1

    # 3. Formatted Summary Report
    print("\n" + "=" * 76)
    print("                        TEST EXECUTION SUMMARY")
    print("=" * 76)
    print(f"{'Tier':<45} | {'Tests':<6} | {'Passed':<6} | {'Status':<6} | {'Time':<6}")
    print("-" * 76)

    for t_num, r in tier_results.items():
        status = "PASS" if r["failed"] == 0 and r["errors"] == 0 else "FAIL"
        print(
            f"{r['name'][:45]:<45} | {r['total']:<6} | {r['passed']:<6} | {status:<6} | {r['time']:.2f}s"
        )

    print("-" * 76)
    total_tests = total_passed + total_failed + total_errors
    print(
        f"{'TOTAL (All Tiers)':<45} | {total_tests:<6} | {total_passed:<6} | {'PASS' if total_failed == 0 and total_errors == 0 else 'FAIL':<6} | {overall_elapsed:.2f}s"
    )
    print("=" * 76)

    if total_failed == 0 and total_errors == 0:
        print(f"  [RESULT] 100% TESTS PASSED ({total_passed}/{total_tests}) — EXIT CODE 0")
        print("=" * 76)
        return 0
    else:
        print(
            f"  [RESULT] FAILED: {total_failed} failures, {total_errors} errors out of {total_tests} tests."
        )
        print("=" * 76)
        return 1


def _patch_quick_scenario_5():
    def quick_scenario_5(self):
        """Quick 3-second lockout test replacement for fast test runs."""
        self.bridge.stop()
        self.bridge_serial, self.client_serial = test_tiers.create_mock_serial_pair()
        self.bridge = test_tiers.SerialBridge(
            auth_service=self.auth,
            serial_instance=self.bridge_serial,
            lockout_duration=3.0,
        )
        self.bridge.lockout_duration = 3.0
        self.bridge.start()

        for p in ["0001", "0002", "0003"]:
            self.client_serial.write(f"{p}\n".encode("ascii"))
            r = self.client_serial.read(1).decode("ascii")
        self.assertEqual(r, "L")
        self.assertTrue(self.bridge.is_locked())

        time.sleep(0.5)
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "L")

        rem = self.bridge.remaining_lockout()
        if rem > 0:
            time.sleep(rem + 0.2)

        self.assertFalse(self.bridge.is_locked())
        self.client_serial.write(b"1234\n")
        self.assertEqual(self.client_serial.read(1).decode("ascii"), "1")

    return quick_scenario_5


def main():
    parser = argparse.ArgumentParser(description="E2E Test Runner for Smart PIN Lock System")
    parser.add_argument(
        "--tier",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4, 5],
        help="Specific tier to run (1-5, default 0 runs all)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Fast mode (reduces Scenario 5 30s lockout to 3s for quick iteration)",
    )
    args = parser.parse_args()

    exit_code = run_e2e_suite(target_tier=args.tier, quick=args.quick)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
