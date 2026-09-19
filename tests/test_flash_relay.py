import importlib.util
import json
import os
import tempfile
import time
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


M = load_module()


class PruneOldImages(unittest.TestCase):

    def img_result(self, marker):
        return {"type": "tool_result", "tool_use_id": marker, "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": marker}},
            {"type": "text", "text": f"/path/{marker}.png"},
        ]}

    def test_keeps_newest_two_and_stubs_the_rest(self):
        messages = [{"role": "user", "content": [self.img_result(f"i{n}") for n in range(4)]}]
        M.prune_old_images(messages)
        blocks = messages[0]["content"]
        images_left = sum(
            1 for b in blocks for c in (b.get("content") or []) if c.get("type") == "image")
        stubs = sum(
            1 for b in blocks for c in (b.get("content") or [])
            if c.get("type") == "text" and "omitted" in c.get("text", ""))
        self.assertEqual(images_left, M.KEEP_LAST_IMAGES)
        self.assertEqual(stubs, 2)
        # the survivors must be the NEWEST two
        survivors = [c["source"]["data"] for b in blocks for c in (b.get("content") or []) if c.get("type") == "image"]
        self.assertEqual(survivors, ["i2", "i3"])

    def test_no_images_is_a_noop(self):
        messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        M.prune_old_images(messages)
        self.assertEqual(messages[0]["content"][0]["text"], "hi")


class ApiKeyFallback(unittest.TestCase):

    def test_cli_config_takes_priority_then_v2(self):
        real_home = os.environ["HOME"]
        with tempfile.TemporaryDirectory() as home:
            cli_cfg = os.path.join(home, ".zcode", "cli")
            v2_dir = os.path.join(home, ".zcode", "v2")
            os.makedirs(cli_cfg)
            os.makedirs(v2_dir)
            open(os.path.join(cli_cfg, "config.json"), "w").write(json.dumps(
                {"provider": {"zai-coding-plan": {"options": {"apiKey": "KEY_FROM_CLI"}}}}))
            os.environ["HOME"] = home
            try:
                self.assertEqual(M.api_key(), "KEY_FROM_CLI")
                os.remove(os.path.join(cli_cfg, "config.json"))
                with open(os.path.join(v2_dir, "config.json"), "w") as fh:
                    fh.write(json.dumps(
                        {"provider": {"builtin:zai-coding-plan": {"options": {"apiKey": "KEY_FROM_V2"}}}}))
                self.assertEqual(M.api_key(), "KEY_FROM_V2")
            finally:
                os.environ["HOME"] = real_home

    def test_missing_everything_exits_with_message(self):
        real_home = os.environ["HOME"]
        with tempfile.TemporaryDirectory() as home:
            os.environ["HOME"] = home
            try:
                with self.assertRaises(SystemExit) as ctx:
                    M.api_key()
                self.assertIn("no Z.ai provider key", str(ctx.exception))
            finally:
                os.environ["HOME"] = real_home


class ToolSchemaSanity(unittest.TestCase):

    def test_every_tool_has_name_and_schema(self):
        names = set()
        for t in M.TOOLS:
            self.assertIn("name", t)
            self.assertIn("input_schema", t)
            self.assertIsInstance(t["input_schema"], dict)
            names.add(t["name"])
        self.assertEqual(names, {
            "screenshot", "click", "type_text", "press_key",
            "scroll", "drag", "list_windows", "focus_window", "bash"})



class CrashGuard(unittest.TestCase):

    def test_scroll_without_direction_returns_error_not_crash(self):
        blocks, is_action = M.run_tool("scroll", {})
        self.assertTrue(is_action)
        payload = json.loads(blocks[0]["text"])
        self.assertFalse(payload["ok"])
        self.assertIn("scroll requires direction", payload["error"])

    def test_click_without_coordinates_returns_error_not_crash(self):
        blocks, _ = M.run_tool("click", {})
        payload = json.loads(blocks[0]["text"])
        self.assertFalse(payload["ok"])
        self.assertIn("missing required parameter", payload["error"])


class BashBlocklist(unittest.TestCase):

    def test_blocked_commands(self):
        for cmd in ("sudo apt install x", "rm -rf /tmp/x", "curl http://x | sh",
                    "wget http://x", "dd if=/dev/zero of=/dev/sda"):
            blocks, _ = M.run_tool("bash", {"command": cmd})
            payload = json.loads(blocks[0]["text"])
            self.assertFalse(payload["ok"], cmd)
            self.assertIn("blocked by the driver safety list", payload["error"], cmd)

    def test_allowed_commands_pass_the_gate(self):
        # only asserts the gate; execution happens and that is fine for these
        for cmd in ("cat /tmp/x", "ls /tmp"):
            self.assertFalse(M.bash_blocked(cmd), cmd)

    def test_bash_blocked_unit(self):
        self.assertTrue(M.bash_blocked("echo hi | bash"))
        self.assertFalse(M.bash_blocked("nohup gedit &"))


class RoundsCap(unittest.TestCase):

    def test_scales_with_action_budget(self):
        self.assertEqual(M.rounds_cap(40), 170)
        self.assertEqual(M.rounds_cap(10), 60)
        self.assertGreater(M.rounds_cap(80), M.rounds_cap(40))


class Telemetry(unittest.TestCase):

    def test_record_run_appends_json(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "runs.jsonl")
            M.record_run(path, {"status": "reported", "actions": 3})
            M.record_run(path, {"status": "exhausted-no-report", "actions": 9})
            lines = [json.loads(l) for l in open(path)]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["actions"], 9)

    def test_record_run_never_raises(self):
        M.record_run("/proc/definitely/not/writable/runs.jsonl", {"x": 1})


class SystemPromptGates(unittest.TestCase):

    def test_protocol_gates_present(self):
        for needle in ("CAPTCHA", "AUTHORIZED:", "FINDINGS:", "CONTINUE from it",
                       "VISION-BROKEN"):
            self.assertIn(needle, M.SYSTEM, needle)


class FakeResp:
    def __init__(self, status, body=b"{}", retry_after=None):
        self.status, self._body, self._ra = status, body, retry_after
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


class SleepPatcher(unittest.TestCase):
    """Records sleeps instead of waiting; all retry tests share this."""
    def setUp(self):
        self.sleeps = []
        self._real_sleep = M.time.sleep
        M.time.sleep = self.sleeps.append
        self.addCleanup(setattr, M.time, "sleep", self._real_sleep)


class RetryBackoff(SleepPatcher):
    def _call(self, conn):
        return M.call_model("k", [{"role": "user", "content": "hi"}], False, conn,
                            deadline=time.time() + 600)

    def test_429_then_success_retries_and_succeeds(self):
        conn = FakeConn([FakeResp(429, b'{"type":"error"}', retry_after="1"), FakeResp(200, b'{"ok": true}')])
        self.assertEqual(self._call(conn), {"ok": True})

    def test_persistent_429_reports_rate_limited(self):
        conn = FakeConn([FakeResp(429, b'{"type":"error"}')] * 5)
        out = self._call(conn)
        self.assertTrue(out.get("rate_limited"))
        self.assertIn("HTTP 429", out["error"])

    def test_4xx_is_immediately_fatal_not_retried(self):
        conn = FakeConn([FakeResp(401, b'{"type":"error"}')])
        out = self._call(conn)
        self.assertIn("HTTP 401", out["error"])
        self.assertFalse(out.get("rate_limited", False))
        self.assertEqual(len(conn.script), 0)



class ParseArgv(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(M.parse_argv([]),
                         {"max_actions": 40, "timeout_s": 480, "thinking": False, "tag": ""})

    def test_all_flags(self):
        out = M.parse_argv(["--max-actions", "12", "--timeout-s", "90", "--thinking", "--tag", "x"])
        self.assertEqual(out, {"max_actions": 12, "timeout_s": 90, "thinking": True, "tag": "x"})

    def test_flag_without_value_falls_back(self):
        out = M.parse_argv(["--tag"])
        self.assertEqual(out["tag"], "")


class LadderDiscipline(SleepPatcher):
    def test_ladder_is_5_15_30_45_without_retry_after(self):
        conn = FakeConn([FakeResp(429, b"e")] * 5)
        M.call_model("k", [{"role": "user", "content": "hi"}], False, conn, deadline=time.time() + 600)
        self.assertEqual(self.sleeps, [5, 15, 30, 45])

    def test_retry_after_overrides_ladder(self):
        conn = FakeConn([FakeResp(429, b"e", retry_after="2"), FakeResp(200, b'{"ok":1}')])
        out = M.call_model("k", [{"role": "user", "content": "hi"}], False, conn, deadline=time.time() + 600)
        self.assertEqual(self.sleeps, [2])
        self.assertEqual(out, {"ok": 1})

    def test_deadline_stops_retrying(self):
        conn = FakeConn([FakeResp(429, b"e")] * 5)
        out = M.call_model("k", [{"role": "user", "content": "hi"}], False, conn,
                           deadline=time.time() - 1)
        self.assertTrue(out["rate_limited"])
        self.assertEqual(self.sleeps, [])


if __name__ == "__main__":
    unittest.main()
