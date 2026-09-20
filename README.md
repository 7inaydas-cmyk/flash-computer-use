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
- ZCode with a working Z.ai coding plan (the driver reads the provider key
  from `~/.zcode/cli/config.json`).
- `xdotool`, `ffmpeg`, `xdpyinfo` on PATH, Python 3.10 or newer.

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
a same-day alternating A/B (three runs per arm, every run oracle
verified) measured medians of 27 to 15 rounds and 159s to 93s wall.

The worker's final message is a fixed report: STATUS, STEPS, EVIDENCE,
PRODUCED, ANOMALIES, RESULT. PRODUCED lists machine-checkable artifacts
(file paths, resource ids) for your oracle. Do not trust a
`STATUS: done` without one: a file that contains the exact expected text,
a window title, a process check. Cheapest first, pixels last, and if your
main model is text-only (GLM-5.3 is), pixels are the worker's job, not
yours. For provisioning-class tasks, verify produced ids against the
service's own CLI or state; a window title proves nothing about what was
provisioned.

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

## License

MIT. See LICENSE.
