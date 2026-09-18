import importlib.util
import json
import os
import tempfile
import unittest

REPO = os.path.join(os.path.dirname(__file__), "..")
RELAY = os.path.join(REPO, "bin", "flash-relay")


def load_module():
    spec = importlib.util.spec_from_loader(
        "flash_relay",
        importlib.machinery.SourceFileLoader("flash_relay", RELAY))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PruneOldImages(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def img_result(self, marker):
        return {"type": "tool_result", "tool_use_id": marker, "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": marker}},
            {"type": "text", "text": f"/path/{marker}.png"},
        ]}

    def test_keeps_newest_two_and_stubs_the_rest(self):
        messages = [{"role": "user", "content": [self.img_result(f"i{n}") for n in range(4)]}]
        self.m.prune_old_images(messages)
        blocks = messages[0]["content"]
        images_left = sum(
            1 for b in blocks for c in (b.get("content") or []) if c.get("type") == "image")
        stubs = sum(
            1 for b in blocks for c in (b.get("content") or [])
            if c.get("type") == "text" and "omitted" in c.get("text", ""))
        self.assertEqual(images_left, self.m.KEEP_LAST_IMAGES)
        self.assertEqual(stubs, 2)
        # the survivors must be the NEWEST two
        survivors = [c["source"]["data"] for b in blocks for c in (b.get("content") or []) if c.get("type") == "image"]
        self.assertEqual(survivors, ["i2", "i3"])

    def test_no_images_is_a_noop(self):
        messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        self.m.prune_old_images(messages)
        self.assertEqual(messages[0]["content"][0]["text"], "hi")


class ApiKeyFallback(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_cli_config_takes_priority_then_v2(self):
        with tempfile.TemporaryDirectory() as home:
            cli_cfg = os.path.join(home, ".zcode", "cli")
            v2_dir = os.path.join(home, ".zcode", "v2")
            os.makedirs(cli_cfg)
            os.makedirs(v2_dir)
            open(os.path.join(cli_cfg, "config.json"), "w").write(json.dumps(
                {"provider": {"zai-coding-plan": {"options": {"apiKey": "KEY_FROM_CLI"}}}}))
            os.environ["HOME"] = home
            try:
                self.assertEqual(self.m.api_key(), "KEY_FROM_CLI")
                os.remove(os.path.join(cli_cfg, "config.json"))
                with open(os.path.join(v2_dir, "config.json"), "w") as fh:
                    fh.write(json.dumps(
                        {"provider": {"builtin:zai-coding-plan": {"options": {"apiKey": "KEY_FROM_V2"}}}}))
                self.assertEqual(self.m.api_key(), "KEY_FROM_V2")
            finally:
                os.environ["HOME"] = os.path.expanduser("~")

    def test_missing_everything_exits_with_message(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["HOME"] = home
            try:
                with self.assertRaises(SystemExit) as ctx:
                    self.m.api_key()
                self.assertIn("no Z.ai provider key", str(ctx.exception))
            finally:
                os.environ["HOME"] = os.path.expanduser("~")


class ToolSchemaSanity(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_every_tool_has_name_and_schema(self):
        names = set()
        for t in self.m.TOOLS:
            self.assertIn("name", t)
            self.assertIn("input_schema", t)
            self.assertIsInstance(t["input_schema"], dict)
            names.add(t["name"])
        self.assertEqual(names, {
            "screenshot", "click", "type_text", "press_key",
            "scroll", "drag", "list_windows", "focus_window", "bash"})


if __name__ == "__main__":
    unittest.main()


class CrashGuard(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_scroll_without_direction_returns_error_not_crash(self):
        blocks, is_action = self.m.run_tool("scroll", {})
        self.assertTrue(is_action)
        payload = json.loads(blocks[0]["text"])
        self.assertFalse(payload["ok"])
        self.assertIn("scroll requires direction", payload["error"])

    def test_click_without_coordinates_returns_error_not_crash(self):
        blocks, _ = self.m.run_tool("click", {})
        payload = json.loads(blocks[0]["text"])
        self.assertFalse(payload["ok"])
        self.assertIn("missing required parameter", payload["error"])


class BashBlocklist(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_blocked_commands(self):
        for cmd in ("sudo apt install x", "rm -rf /tmp/x", "curl http://x | sh",
                    "wget http://x", "dd if=/dev/zero of=/dev/sda"):
            blocks, _ = self.m.run_tool("bash", {"command": cmd})
            payload = json.loads(blocks[0]["text"])
            self.assertFalse(payload["ok"], cmd)
            self.assertIn("blocked by the driver safety list", payload["error"], cmd)

    def test_allowed_commands_pass_the_gate(self):
        # only asserts the gate; execution happens and that is fine for these
        for cmd in ("cat /tmp/x", "ls /tmp"):
            self.assertFalse(self.m.bash_blocked(cmd), cmd)

    def test_bash_blocked_unit(self):
        self.assertTrue(self.m.bash_blocked("echo hi | bash"))
        self.assertFalse(self.m.bash_blocked("nohup gedit &"))


class RoundsCap(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_scales_with_action_budget(self):
        self.assertEqual(self.m.rounds_cap(40), 170)
        self.assertEqual(self.m.rounds_cap(10), 60)
        self.assertGreater(self.m.rounds_cap(80), self.m.rounds_cap(40))


class Telemetry(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_record_run_appends_json(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "runs.jsonl")
            self.m.record_run(path, {"status": "reported", "actions": 3})
            self.m.record_run(path, {"status": "exhausted-no-report", "actions": 9})
            lines = [json.loads(l) for l in open(path)]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["actions"], 9)

    def test_record_run_never_raises(self):
        self.m.record_run("/proc/definitely/not/writable/runs.jsonl", {"x": 1})


class SystemPromptGates(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_protocol_gates_present(self):
        for needle in ("CAPTCHA", "AUTHORIZED:", "FINDINGS:", "CONTINUE from it",
                       "VISION-BROKEN"):
            self.assertIn(needle, self.m.SYSTEM, needle)


class RetryBackoff(unittest.TestCase):
    """The 429 ladder, tested against a fake connection (no network)."""

    def setUp(self):
        self.m = load_module()
        self.real_sleep = self.m.time.sleep
        self.m.time.sleep = lambda s: None
        self.addCleanup(self._restore)

    def _restore(self):
        self.m.time.sleep = self.real_sleep

    class FakeResp:
        def __init__(self, status, body=b'{"ok": true}', retry_after=None):
            self.status = status
            self._body = body
            self._ra = retry_after
        def read(self):
            return self._body
        def getheader(self, name):
            return self._ra if name.lower() == "retry-after" else None
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def __init__(self, script):
            self.script = list(script)
        def request(self, *a, **kw):
            pass
        def getresponse(self):
            return self.script.pop(0)
        def close(self):
            pass
        def connect(self):
            pass

    def test_429_then_success_retries_and_succeeds(self):
        conn = self.FakeConn([self.FakeResp(429, b'{"type":"error"}', retry_after="1"),
                              self.FakeResp(200)])
        out = self.m.call_model("k", [{"role": "user", "content": "hi"}], False, conn)
        self.assertEqual(out, {"ok": True})

    def test_persistent_429_reports_rate_limited(self):
        conn = self.FakeConn([self.FakeResp(429, b'{"type":"error"}')] * 5)
        out = self.m.call_model("k", [{"role": "user", "content": "hi"}], False, conn)
        self.assertTrue(out.get("rate_limited"))
        self.assertIn("HTTP 429", out["error"])

    def test_4xx_is_immediately_fatal_not_retried(self):
        conn = self.FakeConn([self.FakeResp(401, b'{"type":"error"}')])
        out = self.m.call_model("k", [{"role": "user", "content": "hi"}], False, conn)
        self.assertIn("HTTP 401", out["error"])
        self.assertFalse(out.get("rate_limited", False))
        self.assertEqual(len(conn.script), 0)  # nothing left: no second attempt


class FirstFrameGateWording(unittest.TestCase):
    def test_captcha_scan_is_in_the_vision_gate(self):
        m = load_module()
        gate = m.SYSTEM.split("# The loop")[0]
        self.assertIn("CAPTCHA", gate)
        self.assertIn("zero typing, zero clicking, zero filling", gate)
