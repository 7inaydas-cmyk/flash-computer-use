#!/usr/bin/env bash
# Non-GUI install validation. Run after install.sh and the config merge.
set -u
fail=0

check() {
  local name="$1" cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "PASS  $name"
  else
    echo "FAIL  $name"
    fail=1
  fi
}

check "lcu on PATH and answers windows in JSON" \
  'lcu windows | python3 -c "import json,sys; d=json.loads([l for l in sys.stdin if l.strip()][-1]); assert d[\"ok\"] and isinstance(d[\"windows\"], list)"'

check "flash-worker profile installed" \
  'test -f ~/.zcode/agents/flash-worker.md'

check "flash-computer-use skill installed" \
  'test -f ~/.agents/skills/flash-computer-use/SKILL.md || test -f ~/.zcode/skills/flash-computer-use/SKILL.md'

check "lcu MCP server installed" \
  'test -f ~/.openwork/lcu-mcp/server.py'

check "flash-relay on PATH and rejects bad args with usage" \
  'flash-relay /nonexistent-brief 2>&1 | grep -q usage'

check "provider key discoverable (cli or v2 config)" \
  'python3 - <<PY
import json, os, sys
for path, pick in (
    ("~/.zcode/cli/config.json", lambda c: c["provider"]["zai-coding-plan"]["options"]["apiKey"]),
    ("~/.zcode/v2/config.json", lambda c: c["provider"]["builtin:zai-coding-plan"]["options"]["apiKey"]),
):
    try:
        k = pick(json.load(open(os.path.expanduser(path))))
        sys.exit(0 if k and "mirror" not in k else 1)
    except Exception:
        continue
sys.exit(1)
PY'

ZCODE_CLI=""
if [ -x /opt/ZCode/resources/glm/zcode.cjs ] && command -v node >/dev/null 2>&1; then
  ZCODE_CLI="node /opt/ZCode/resources/glm/zcode.cjs"
elif command -v zcode >/dev/null 2>&1 && zcode --version >/dev/null 2>&1; then
  ZCODE_CLI="zcode"
fi
if [ -n "$ZCODE_CLI" ] && $ZCODE_CLI skills list 2>/dev/null | grep -q flash-computer-use; then
  echo "PASS  skill registered with zcode"
elif [ -n "$ZCODE_CLI" ]; then
  echo "FAIL  skill registered with zcode"
  fail=1
else
  echo "SKIP  skill registered with zcode (no headless-usable zcode CLI found)"
fi

if [ "$fail" -eq 0 ]; then
  echo "OK: install validated."
else
  echo "NOT OK: see FAIL lines above."
fi
exit "$fail"
