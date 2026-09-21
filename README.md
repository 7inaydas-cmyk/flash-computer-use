# flash-computer-use

Drive a Linux desktop with a cheap model while an expensive one supervises.

ZCode sessions run on GLM-5.3, which is good at planning and poor value for
pointing at pixels. This repo adds the other tier: GLM-5.3-Flash workers
that look at the screen, click, type, and file a report, while your main
agent decomposes the task, enforces the safety rules, and verifies the
result with oracles it can trust.

Built and battle-tested on one machine over two days of real work: editor
automation, self-addressed Gmail sends through the compose window, and job
application forms. The last one is where it got interesting, in the painful
sense, and the safety rules below exist because of it.

## What is in the box

| Piece | What it is |
|---|---|
| `bin/lcu` | Linux Computer Use: a single-file X11 CLI. xdotool for input, ffmpeg x11grab for capture, one JSON line per subcommand. Includes `screenshot --region X Y W H` for full-resolution crops of small targets. |
| `bin/flash-relay` | The dispatch driver. Calls GLM-5.3-Flash directly over the Anthropic-compatible API with the worker protocol as its system prompt and lcu as its tool surface. Structural enforcement in code: one tool call per model turn, screenshot before anything else runs, a fresh screenshot before every action, a hard action cap (no action executes past it), a bash allowlist, and crash guards that always leave a report and a telemetry line. |
| `agents/flash-worker.md` | A ZCode subagent profile for spawning workers from an interactive session. Same protocol as the driver. |
| `skills/flash-computer-use/SKILL.md` | The orchestration skill your main agent loads: task decomposition, the escalation list, brief format, budgets, verification duty. |
| `mcp/lcu-mcp-server.py` | Optional MCP wrapper around lcu, so agents get first-class screenshot/click/type tools. |

## Read this before your first run: the blind-worker story

The worker protocol starts with a vision gate, and here is why. On the
author's machine, an interactive ZCode session once spawned a worker whose
model pin was silently dropped; it ran on the text-only main model instead
of Flash. Nobody noticed. The worker could not see the screenshots arriving
in its own transcript, so it improvised: downloading its screenshots with
Bash, cropping them, running OCR, trying edge detection. Two clicks in
eighteen minutes. 5,033,708 input tokens, most of it the model re-reading
its own ever-growing transcript. And somewhere in the coping, it reloaded a
browser tab that held a finished, unsubmitted application form, wiping
twenty minutes of work.

The fixes are now structural:

- The worker's first action is one screenshot it must be able to view. If it
  cannot, it reports `VISION-BROKEN` and stops. A blind run costs one
  screenshot, never five million tokens.
- The driver verifies model routing by construction: it pins
  `GLM-5.3-Flash` itself. For session-spawned workers, the skill includes a
  one-line database check that the child session actually ran Flash. A
  mismatch means discard the report; never re-task a blind worker.
- Workers never navigate, reload, or close a tab holding an unsubmitted
  form. New tab per site, always.
- Old screenshots are pruned from the transcript after two frames, so
  payload cannot grow linearly with run length. That token disease has a
  habit of coming back.

## Requirements

- Linux with an X11 session (`echo $XDG_SESSION_TYPE` says x11). No Wayland.
- A worker model key, found in this order: `FLASH_RELAY_API_KEY` (environment
  or config file), then the ZCode stores (`~/.zcode/cli/config.json`, then
  `~/.zcode/v2/config.json`). A logged-in ZCode install with a working Z.ai
  coding plan therefore needs no configuration at all.
- `xdotool`, `ffmpeg`, `xdpyinfo` on PATH, Python 3.10 or newer.
- For the jev decision head only: a TypeSafe account and key (below).

## Install

```bash
git clone https://github.com/7inaydas-cmyk/flash-computer-use.git
cd flash-computer-use
./install.sh
```

The installer copies lcu and flash-relay to `~/.local/bin`, the MCP server
to `~/.openwork/lcu-mcp/`, the profile to `~/.zcode/agents/`, and the skill
to `~/.agents/skills/`. It will not touch your ZCode config; merge
`zcode-cli-config.example.json` into `~/.zcode/cli/config.json` yourself.
The example has the API key redacted: mirror your own from
`~/.zcode/v2/config.json`, provider `builtin:zai-coding-plan`. Then restart
ZCode so the profile, skill, and MCP server register.

Validate the install before trusting it:

```bash
scripts/validate.sh                            # non-GUI checks, one PASS line each
flash-relay examples/brief-editor-smoke.txt    # full loop, ~3 minutes
```

## Usage

Write a brief. A brief is one bounded subtask with acceptance criteria and
the exact text to type; the worker never invents content.

```
SUBTASK: <imperative one-liner>
APP: <application, and how to launch it>
STEPS_HINT: <optional ordered hints>
EXACT_TEXT: <literal strings>
ACCEPTANCE: <checkable end state>
FORBIDDEN: <additions to the standing prohibition list>
AUTHORIZED: <closed whitelist of the ONLY non-read-only actions allowed;
ABSENT means read-only only>
ACTION_BUDGET: 40
CRITICAL: true only for irreversible or spend-bearing tasks
```

The driver reads `ACTION_BUDGET` from the brief (the `--max-actions` flag
overrides it, values clamp to 1..200) and stops executing actions the
moment the cap is hit, so the number in the brief and the number enforced
are always the same.

Run it, hands off the mouse and keyboard until it finishes:

```bash
flash-relay mytask.txt [--max-actions 40] [--timeout-s 480] [--thinking]
```

Thinking mode is off by default; measured on this endpoint it costs 1.5 to
2.5 seconds per call, and a driving loop does better on reflexes than on
deliberation. Turn it on for hard screens. On the reference benchmark (the
editor smoke test, a 1920x1200 screen) the loop finished in 2m52s at nine
actions with thinking off, versus 3m45s at nineteen actions with it on.
The bigger speed lever is structural: the driver attaches a fresh
screenshot to every action result, so no model round is spent on
re-observation. On an identical ten-action provisioning rehearsal it
dropped from 412 seconds and 25 rounds to 108 seconds and 14 rounds, and
a same-day alternating A/B measured medians of 27 to 15 rounds and 159s
to 93s wall. Across three task classes (provisioning form, editor save,
read-only audit; 12 runs total, every run oracle verified) the win tracks
action density: the two action-driving classes cut rounds 27 to 15 and
wall clock by about 41 percent, while the read-only class is unchanged,
exactly because attached frames pay per action. The design is the
jev-ultrafast act-observe lesson applied to X11 pixels; this tool does
not use TypeSafe's Jev model.

The worker's final message is a fixed report: STATUS, STEPS, EVIDENCE,
PRODUCED, ANOMALIES, RESULT. PRODUCED lists machine-checkable artifacts
(file paths, resource ids) for your oracle. Do not trust a
`STATUS: done` without one: a file that contains the exact expected text,
a window title, a process check. Cheapest first, pixels last, and if your
main model is text-only (GLM-5.3 is), pixels are the worker's job, not
yours. For provisioning-class tasks, verify produced ids against the
service's own CLI or state; a window title proves nothing about what was
provisioned.

## Configuration

Zero-config with a logged-in ZCode install. Everything else is optional
and resolved the same way everywhere: process environment, then a config
file, then built-in defaults.

The worker-provider config file is `./.env` in the directory you run
flash-relay from, or any path named by `FLASH_RELAY_ENV` (useful for the
installed binary, which runs from anywhere). `.env.example` at the repo
root documents every knob; the file is gitignored and no key ever ships
in a repo.

| Variable | Meaning | Default |
|---|---|---|
| `FLASH_RELAY_PROVIDER` | `http`, `openai`, or `claude-cli` (experimental) | `http` |
| `FLASH_RELAY_BASE_URL` | endpoint base; the provider appends its path | `https://api.z.ai/api/anthropic` |
| `FLASH_RELAY_MODEL` | worker model id | `GLM-5.3-Flash` |
| `FLASH_RELAY_API_KEY` | worker key; falls back to the ZCode stores | ZCode walk |
| `FLASH_RELAY_CLAUDE_BIN` | claude binary for the claude-cli provider | `claude` |
| `FLASH_RELAY_HEAD` | decision head: `vision` or `jev` | `vision` |

The `--head` flag overrides `FLASH_RELAY_HEAD` per run.

### Configure your own access

After the clone and install steps above, take exactly as much
configuration as you need; the first option needs nothing at all.

- Zero config, Z.ai default: with a logged-in ZCode install, just run
  `flash-relay mytask.txt`. The key comes from the ZCode stores and the
  worker runs GLM-5.3-Flash at the Z.ai endpoint.
- Any other Anthropic-compatible endpoint: `cp .env.example .env` in the
  directory you run flash-relay from, then uncomment and fill
  `FLASH_RELAY_BASE_URL`, `FLASH_RELAY_MODEL`, and `FLASH_RELAY_API_KEY`;
  or export those three variables instead. The environment beats the
  file.
- OpenAI-compatible endpoint: same as above plus
  `FLASH_RELAY_PROVIDER=openai`, with `FLASH_RELAY_BASE_URL` at the
  endpoint root (the driver appends `/chat/completions`).
- claude -p: `FLASH_RELAY_PROVIDER=claude-cli`. It needs no key and
  ignores base url and model; set `FLASH_RELAY_CLAUDE_BIN` if the binary
  is not on PATH. Experimental and stub-tested only.
- Enable Jev: run with `--head jev` or set `FLASH_RELAY_HEAD=jev`, and
  provide a TypeSafe key: `TYPESAFE_API_KEY` exported, or
  `~/.config/flash-relay/jev.env` (mode 600, never inside a repo tree).
  The run fails closed at startup without the key or with an unpinned
  `TYPESAFE_MODEL`.
- Turn Jev off: run without `--head` and without `FLASH_RELAY_HEAD` set.
  A present `TYPESAFE_API_KEY` alone never flips the head.

### Model providers

- `http` (default): the Anthropic Messages wire format against
  `FLASH_RELAY_BASE_URL`. Any Anthropic-compatible endpoint needs only
  `FLASH_RELAY_BASE_URL` + `FLASH_RELAY_MODEL` + `FLASH_RELAY_API_KEY`;
  there is no provider value to set.
- `openai`: a translation sibling for OpenAI-compatible endpoints: tools
  become function tools, tool results become tool messages, screenshots
  become `image_url` data URLs, and the reply is translated back into
  content blocks. Point `FLASH_RELAY_BASE_URL` at the endpoint root.
- `claude-cli` (experimental): each turn is a `claude -p` subprocess with
  the transcript as stream-json on stdin and the reply read from the json
  output. It needs no API key and ignores base url and model. Stub-tested
  only, never exercised live by the author: treat it as unproven until
  you have run it once yourself.

### Decision heads

- `vision` (default): the single-model loop described above. The worker
  model sees the frame, decides, and acts through the full tool list.
- `jev` (opt-in, `--head jev`): the worker model stays the eyes and the
  gate-keeper and proposes an indexed candidate table (the `observe`
  tool, at most 200 executor-legal rows: coordinates from the current
  frame, key combos, window ids from `list_windows`, GUI-launch bash
  only, exact brief-declared text). One TypeSafe Jev request
  (api.typesafe.ai) picks among the offered rows, and the driver
  executes the chosen row through the same admit/run_tool path as a
  vision action. The full transcript records what was offered and what
  was chosen.

Jev invariants: Jev emits only an offered id; coordinates, text, keys,
and commands originate in the vision-proposed rows, are pre-validated
with the same validators the executor applies, and are re-validated at
execution time. The action cap, fresh-frame rule, one-call-per-turn,
vision gate, bash allowlist, and bounds checks bite identically. The
model is pinned to a versioned id (default `jev-1.13.0`; `TYPESAFE_MODEL`
to bump, aliases such as `jev-latest` are refused) and the response's
model field must match the pin.

Setup: a TypeSafe account, then `TYPESAFE_API_KEY` in the environment or
in `~/.config/flash-relay/jev.env` (mode 600, never inside a repo tree).
Optional: `JEV_MIN_CONFIDENCE` (default 0.0; untuned until live data
exists) and `JEV_MAX_DECISION_AGE_S` (default 45).

Honest bounds of the jev head: a decision may execute on pixels up to
`JEV_MAX_DECISION_AGE_S` old, because the extraction round plus a retried
TypeSafe call can stretch the gap (in vision mode the deciding round is
the round that saw the frame), and each action costs one extraction round
plus one TypeSafe call, so expect roughly 1.5 to 2x the wall time per
action. It is a decision-quality and audit head, not a speed head, and
nothing changes by default. Candidate labels and context are
vision-written text sent to TypeSafe as a second third party (the same
exposure class as the frames already sent to the worker endpoint); the
observe schema forbids transcribing passwords, tokens, or 2FA codes into
rows.

## Safety model

Two layers, and the code one does not depend on the model behaving.

Structural, in the driver, always on:

- One tool call per model turn; batched calls are refused, so one confused
  turn cannot chain a submit sequence.
- The first tool call of a run must be a full screenshot, and every action
  needs a fresh frame since the previous one; no acting blind or on
  stale frames. The driver itself attaches a fresh post-action screenshot
  to every action result, so the loop spends no model round on
  re-observation; model-emitted coordinates are validated against the
  observed screen, and key combos and scroll amounts are format-checked,
  before they become input events.
- A hard action cap (brief `ACTION_BUDGET`, default 40): past it, nothing
  executes, no matter what the model emits.
- The bash tool is an allowlist, not a denylist: one command line, one
  allowed binary (read/oracle commands such as cat, ls, grep, pgrep; GUI
  launchers), no pipes, redirection, expansion, or chaining, executed
  without a shell. An `aws`, `terraform`, `python3`, or `xdotool` command
  is refused outright.
- Crash guards: malformed model turns and tool errors become tool errors
  the model can correct, never tracebacks; every exit writes a telemetry
  line.

Behavioural, in the worker prompt, backstopped by the structural layer:
the standing prohibition list, which the orchestrator enforces by never
writing such a brief and the worker enforces by reporting
`needs-escalation` instead of acting. Credentials and 2FA codes; anything
with external effect (messages, email, posts, orders, payments);
provisioning or spending on cloud services or any paid platform; deletions,
sudo, system settings, anything irreversible. Budgets: 40 actions and 8
minutes per subtask by default, one extension after a reviewed failure, a
checkpoint with the human around 200 cumulative actions. If a report's
STEPS show Bash image processing, the run was blind regardless of what
anything else says: stop, and check whether unsaved state was destroyed.

## Known issues

- Interactive ZCode sessions have been observed to drop a profile's `model:`
  pin and silently run the worker on the session model. The account-qualified
  ref is the candidate fix; until you have seen a session-spawned worker pass
  the database model check on your install, treat `flash-relay` as the only
  proven path. This is also why the shipped profile pins the bare
  `GLM-5.3-Flash` while the author's live copy uses the account-qualified
  ref: that one line is the only intended difference between the two.
- Headless `zcode --prompt` broke entirely on the author's machine after
  connecting account-level coding plans in the desktop app ("Select a model
  before continuing"). That is why flash-relay exists: it needs no registry,
  no profile resolution, no session state, just the key and the API.
- The official computer-use plugin for ZCode is accessibility-first and
  explicitly main-agent-only. This stack is the pixel-driven alternative;
  if sighted workers disappoint you, that plugin's semantic actions are the
  escape hatch, at the cost of re-validating everything.
- The jev head is opt-in and unproven on the author's desktop: the TypeSafe
  integration is offline-tested (fake connections, no network) and has not
  been live-run. Its request limits (255 options per question, 64k tokens
  per request), its retry set (429/529/503), and the pinned model id are
  survey-sourced, enforced conservatively in code (a 200-row candidate cap
  and a 48k estimated-token guard), and the first live gate is an
  authenticated model-list check before any spend.
- The claude-cli provider is stub-tested only and marked experimental until
  its live one-turn gate; the stream-json envelope and auth state have
  never been exercised against a real Claude CLI by this project's tests.
- `./.env` is only found when flash-relay runs with that working directory;
  use `FLASH_RELAY_ENV` for an absolute path. The zero-config default is
  unaffected.

## License

MIT. See LICENSE.
