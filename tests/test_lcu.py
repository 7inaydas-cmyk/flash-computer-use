import importlib.machinery
import importlib.util
import json
import sys
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
            for field in ("id", "pid", "name", "x", "y", "width", "height", "active"):
                self.assertIn(field, w)


def load_lcu():
    spec = importlib.util.spec_from_loader(
        "lcu", importlib.machinery.SourceFileLoader("lcu", LCU))
    m = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = ["lcu"]
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
    return m


class LcuRegionBoundsUnit(unittest.TestCase):
    """Pure logic, no display needed."""

    def test_bounds(self):
        m = load_lcu()
        self.assertTrue(m.region_in_bounds((0, 0, 10, 10), 100, 100))
        self.assertTrue(m.region_in_bounds((90, 90, 10, 10), 100, 100))
        self.assertFalse(m.region_in_bounds((91, 0, 10, 10), 100, 100))
        self.assertFalse(m.region_in_bounds((0, 91, 10, 10), 100, 100))
        self.assertFalse(m.region_in_bounds((0, 0, 0, 10), 100, 100))
        self.assertFalse(m.region_in_bounds((0, 0, 10, 0), 100, 100))
        self.assertFalse(m.region_in_bounds((-1, 0, 10, 10), 100, 100))


class LcuResolveWindowUnit(unittest.TestCase):
    """resolve_window with a stubbed xdotool: literal substring semantics,
    ambiguity is an error, never a silent pick."""

    def setUp(self):
        self.m = load_lcu()
        self.seen = {}
        m = self.m

        def fake_run(cmd, check=True):
            if cmd[1] == "getactivewindow":
                return "9999"
            if cmd[1] == "search":
                self.seen["spec"] = cmd[3]
                table = {m.re.escape(k): v for k, v in {
                    "one": "1234",
                    "many": "111\n222\n333",
                    "Draft (2026": "1234"}.items()}
                return table.get(cmd[3], "")
            return ""
        self._real_run = m.run
        m.run = fake_run
        self.addCleanup(setattr, m, "run", self._real_run)

    def test_active_and_numeric_ids_pass_through(self):
        self.assertEqual(self.m.resolve_window("active"), "9999")
        self.assertEqual(self.m.resolve_window("4455"), "4455")

    def test_unique_substring_resolves(self):
        self.assertEqual(self.m.resolve_window("one"), "1234")

    def test_spec_is_regex_escaped_literal_substring(self):
        # parens in a title must not be treated as regex syntax
        self.assertEqual(self.m.resolve_window("Draft (2026"), "1234")
        self.assertEqual(self.seen["spec"], self.m.re.escape("Draft (2026"))

    def test_ambiguous_match_is_an_error_not_a_silent_pick(self):
        import contextlib, io
        buf = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(buf):
            self.m.resolve_window("many")
        payload = json.loads(buf.getvalue().strip())
        self.assertFalse(payload["ok"])
        self.assertIn("ambiguous", payload["error"])
        self.assertIn("111", payload["error"])

    def test_no_match_is_an_error(self):
        import contextlib, io
        buf = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(buf):
            self.m.resolve_window("nothing-matches-this")
        payload = json.loads(buf.getvalue().strip())
        self.assertFalse(payload["ok"])
        self.assertIn("no window matching", payload["error"])


class LcuUnit(unittest.TestCase):
    def test_usage_without_subcommand_fails(self):
        p = run_lcu()
        self.assertNotEqual(p.returncode, 0)

    def test_unknown_subcommand_fails(self):
        p = run_lcu("definitely-not-a-subcommand")
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
