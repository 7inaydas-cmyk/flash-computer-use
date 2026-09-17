import json
import os
import shutil
import subprocess
import unittest

LCU = os.path.join(os.path.dirname(__file__), "..", "bin", "lcu")


def run_lcu(*args):
    return subprocess.run([LCU, *args], capture_output=True, text=True, timeout=60)


def parse_json_line(out):
    lines = [l for l in out.splitlines() if l.strip()]
    return json.loads(lines[-1])


def have_display():
    return bool(os.environ.get("DISPLAY")) and shutil.which("xdpyinfo") is not None


@unittest.skipUnless(have_display(), "needs an X display (real or Xvfb)")
class LcuIntegration(unittest.TestCase):
    """Read-only X11 tests: safe on a real desktop, real under Xvfb."""

    def test_screenshot_json_contract(self):
        p = run_lcu("screenshot")
        self.assertEqual(p.returncode, 0, p.stderr)
        d = parse_json_line(p.stdout)
        self.assertTrue(d["ok"])
        self.assertIn("width", d["screen"])
        self.assertIn("height", d["screen"])
        self.assertGreater(d["bytes"], 0)
        self.assertTrue(os.path.exists(d["path"]))

    def test_region_capture_reports_offset(self):
        p = run_lcu("screenshot", "--region", "10", "20", "200", "100")
        self.assertEqual(p.returncode, 0, p.stderr)
        d = parse_json_line(p.stdout)
        self.assertTrue(d["ok"])
        self.assertEqual(d["region"], {"x": 10, "y": 20, "width": 200, "height": 100})
        self.assertIn("region x/y", d["note"])

    def test_region_bounds_rejected(self):
        p = run_lcu("screenshot", "--region", "4000", "4000", "100", "100")
        self.assertNotEqual(p.returncode, 0)
        d = parse_json_line(p.stdout)
        self.assertFalse(d["ok"])
        self.assertIn("out of bounds", d["error"])

    def test_window_and_region_mutually_exclusive(self):
        p = run_lcu("screenshot", "--window", "active", "--region", "0", "0", "10", "10")
        self.assertNotEqual(p.returncode, 0)
        d = parse_json_line(p.stdout)
        self.assertFalse(d["ok"])
        self.assertIn("mutually exclusive", d["error"])

    def test_windows_listing_shape(self):
        p = run_lcu("windows")
        self.assertEqual(p.returncode, 0, p.stderr)
        d = parse_json_line(p.stdout)
        self.assertTrue(d["ok"])
        self.assertIsInstance(d["windows"], list)
        self.assertEqual(d["count"], len(d["windows"]))
        for w in d["windows"]:
            for field in ("id", "name", "x", "y", "width", "height", "active"):
                self.assertIn(field, w)


class LcuUnit(unittest.TestCase):
    def test_usage_without_subcommand_fails(self):
        p = run_lcu()
        self.assertNotEqual(p.returncode, 0)

    def test_unknown_subcommand_fails(self):
        p = run_lcu("definitely-not-a-subcommand")
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
