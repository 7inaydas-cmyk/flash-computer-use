---
name: flash-computer-use
description: Orchestrate GUI tasks on the real Linux desktop by delegating the see-act-verify driving loop to a GLM 5.3 Flash worker (flash-worker subagent) that controls the X11 screen via LCU, while the main agent plans subtasks, enforces safety escalations, and independently verifies results. Use when the user asks to operate desktop apps, fill forms, click through UIs, or drive anything with a mouse and keyboard.
---

# flash-computer-use

Two-tier computer use: **you** (GLM 5.3 max effort) plan, gate, and verify;
**flash-worker** (GLM 5.3 Flash) drives the real desktop through LCU.

## Architecture

- Actuation surface: the `lcu` CLI (`~/.local/bin/lcu`): screenshot, windows,
  focus, move, click, drag, scroll, cursor, type, key; JSON output. Also
  registered as the `lcu` MCP server (`~/.openwork/lcu-mcp/server.py`) in
  `~/.zcode/cli/config.json`, so both you and the worker may use
  `mcp__lcu__*` tools.
- Worker: the `flash-worker` subagent profile
  (`~/.zcode/agents/flash-worker.md`, `model: GLM-5.3-Flash`). It carries
  its own driving protocol (fresh-frame anchoring, zoom via
  `--region`, focus-before-typing, budget discipline) and the report
  template. Read that file if you need to know exactly what it will do.
- Target: the user's real X11 desktop, `DISPLAY :0`. The worker's pointer
  actions move the real cursor and steal focus, so warn the user to be hands-off
  for the duration of a run.

## Preconditions (check once per session before first dispatch)

1. X11 session: `echo $XDG_SESSION_TYPE` → `x11` (or `lcu windows` succeeds).
2. `lcu windows` returns JSON with a window list.
3. `~/.zcode/agents/flash-worker.md` exists.
4. First dispatch of a brand-new install doubles as the GLM-5.3-Flash smoke
   test; see "Smoke test" below.

## Intake and decomposition

Turn the user's task into one to N subtasks. A good subtask:

- touches ONE application or one coherent flow (open app X, fill form, save);
- has explicit, checkable acceptance criteria ("file /tmp/foo.txt exists and
  contains …", "the dialog titled Y is dismissed", "the browser shows page Z");
- is completable within the action budget (below);
- names the exact text to type and the exact target filenames; never make the
  worker invent content.

If a step is on the escalation list below, it stays with you: do not delegate
it, ask the user instead.

## Safety escalation list (you are the gate)

Never let the worker (and do not yourself, without asking the user):

- type passwords, tokens, or 2FA codes;
- send/submit anything with external effect: messages, emails, posts,
  comments, orders, payments;
- delete files or anything irreversible;
- run `sudo` or change system settings.

If a task needs one of these, pause at the boundary, show the user the
evidence screenshot, and ask. The worker's `needs-escalation` status means
exactly this: it stopped and is waiting on a human decision relayed by you.

## Dispatch protocol

- Spawn ONE worker at a time (serial), foreground/blocking, via the Agent
  tool with `subagent_type: flash-worker`. Two pointers on one desktop is
  chaos.
- **Dispatch path (primary): `flash-relay`**: the standalone driver at
  `~/.local/bin/flash-relay` (source of truth: the repo). It calls
  GLM-5.3-Flash directly over the API with the worker protocol and LCU
  tools, with the action cap, wall-clock cap, and vision gate enforced in
  code. Invoke: `flash-relay <brief-file> [--max-actions N] [--timeout-s S]`.
  The brief file is the inner SUBTASK brief (no relay-wrapper text needed).
  Model routing is guaranteed by construction (the driver pins
  `model: GLM-5.3-Flash`); no post-hoc assertion required.
- **Dispatch path (desktop/profile)**: interactive-desktop spawns may use
  `subagent_type: flash-worker`, but the desktop runtime has been observed
  to drop profile model pins and silently run the worker on the session's
  text-only model; until a desktop spawn passes the model assertion below,
  treat `flash-relay` as the only proven path.
- **Model assertion (mandatory after every profile-based spawn; not needed
  for flash-relay runs)**: verify the child session actually ran
  GLM-5.3-Flash before trusting anything it reports:

  ```bash
  python3 -c "
  import sqlite3, json, glob, os, time
  db = sqlite3.connect(os.path.expanduser('~/.zcode/cli/db/db.sqlite'))
  fresh = [m for m in glob.glob(os.path.expanduser('~/.zcode/cli/agents/sess_*/agent_*/metadata.json'))
           if time.time() - os.path.getmtime(m) < 600]   # spawned in the last 10 min only
  for m in sorted(fresh, key=os.path.getmtime):
      d = json.load(open(m))
      if d.get('profileId','').startswith('flash-worker'):
          cs = d['childSessionId']
          r = db.execute('SELECT data FROM message WHERE session_id=? ORDER BY sequence LIMIT 1', (cs,)).fetchone()
          print(d.get('createdAt','?')[:19], d.get('profileId'), '->', json.loads(r[0]).get('modelId') if r else 'no-messages')"
  ```

  Filter to the line matching YOUR dispatch time. Anything other than
  `GLM-5.3-Flash` (typically `GLM-5.3`) means the run was blind: discard its
  report, fix the routing, re-dispatch. Never re-task a blind worker. (Beware
  concurrent sessions: match by timestamp, not by "newest".)
- The spawn prompt is a **brief**. Template:

  ```
  SUBTASK: <imperative one-liner>
  APP: <application to drive, and how to launch it if not running>
  STEPS_HINT: <optional ordered hints; the worker re-plans from screenshots>
  EXACT_TEXT: <literal strings to type, if any>
  ACCEPTANCE: <checkable end-state>
  FORBIDDEN: <task-specific additions to the standing prohibition list>
  AUTHORIZED: <what the user explicitly permitted beyond read-only, e.g.
  "click Submit on this application"; ABSENT means the escalation list
  stands in full and submitting stays forbidden>
  RESUME: <optional; "the form may be partially filled; screenshot before
  any navigation and continue from what is there">
  ACTION_BUDGET: <N, default 40>
  ```

- Brief discipline for forms: verification at checkpoints is YOUR job, never
  the worker's per-field. Do not order "screenshot after every field and
  confirm". The worker verifies typed values by field echo, tab order, or one
  screenshot per form section; you verify the end state.
- After the worker returns its report, do NOT relaunch on `blocked` without
  first changing something: reread its EVIDENCE screenshots, diagnose, and
  rewrite the brief.

## Verification (mandatory, every subtask)

Never accept `STATUS: done` on faith. Independently confirm with the
strongest oracle available, cheapest first:

1. Shell oracle: file exists / contains the exact text; process running;
   `lcu windows` shows the expected window title.
2. Flash re-observation: dispatch a tiny follow-up to the worker ("screenshot
   X and describe it") when only pixels can settle it.

Note: some main-tier models (including GLM-5.3) have text-only input and
cannot see screenshots. If yours cannot, verification leans on
shell/window-title oracles and, when pixels are required, on the worker's
own eyes (cross-checked against the EVIDENCE paths it reported).

Only then report success to the user, citing the oracle you used.

## Budgets and stall handling (tunables; recalibrate from real runs)

| Knob | Default | Notes |
|---|---|---|
| Actions per subtask | 40 | brief may override; screenshots unlimited |
| Wall clock per subtask | 8 min | covers slow apps and settle waits |
| Extension | +20 (→60), once | only after reviewing the failure report and rewriting the brief |
| Task checkpoint | ~200 cumulative actions | pause and check in with the user |

Second failure on the same subtask = stop and escalate to the user with
before/after screenshots. No third try: twice-failed pixels mean the brief is
wrong, not unlucky.

Budget by task class (the brief overrides; this is the rule of thumb for
choosing):

| Task class | Actions | Wall clock | Why |
|---|---|---|---|
| Read/verify (idempotent, no input) | 60-80 | 15 min | long searches, many screenshots, zero blast radius |
| Form driving | 40 | 8 min | tighter cap limits damage if the form misbehaves |
| Mixed/unknown | 40 | 8 min | the code default |

## Form brief checklist (traps that cost real runs)

- Custom dropdowns can silently select the NEIGHBOURING option. Screenshot
  after every dropdown, before moving on.
- iCIMS-style select controls often need click, Arrow-Down, Return rather
  than a plain click on the option.
- File pickers (GTK) can leave a stale autocomplete tail in the name field:
  shift+End then Delete before typing the path.
- Resume parsers INVENT employers and titles from formatting. Re-verify
  every field on the review page against the resume, not against what was
  typed.
- Long-idle forms expire mid-flight. If a submit returns to a blank or
  login page, report blocked with the evidence instead of refilling.

## Worker report interpretation

The worker's final message is `STATUS / STEPS / EVIDENCE / ANOMALIES /
RESULT`. Treat `ANOMALIES` seriously: anything the worker clicked that the
brief did not ask for deserves your verification attention. If the report
template is missing or mangled, trust only the EVIDENCE screenshots, not the
prose.

**Blindness signature (abort condition)**: if STEPS show Bash image
processing (downloading screenshots, cropping, OCR, edge detection, zoom
scripts) or ANOMALIES mention being unable to view images, the run was blind
regardless of what the model assertion said. Stop the whole task, do not
re-dispatch until routing is re-verified, and check whether any unsaved form
state was destroyed (a blind worker navigates and reloads to cope).

## Smoke test (acceptance for a fresh install)

Benign end-to-end validation on the real desktop:

1. `rm -f /tmp/flash-smoke-test.txt`
2. Warn the user to be hands-off for ~1 minute.
3. Dispatch flash-worker: open GNOME Text Editor, type
   `flash-computer-use smoke test ok`, save to
   `/tmp/flash-smoke-test.txt`, close the editor.
4. Oracle: `cat /tmp/flash-smoke-test.txt` contains the sentence.
5. Pass → the stack works. Fail → diagnose from the worker report + your own
   screenshots before touching any config.

## Fallbacks and tunables

- **Worker reasoning effort**: profile leaves GLM-5.3-Flash at the provider
  default (max). If runs are too slow, add `thoughtLevel: low` to the profile
  frontmatter; one line.
- **MCP vs CLI**: the worker uses `mcp__lcu__*` when present, else the `lcu`
  CLI over Bash. Both paths are first-class; nothing needs changing to switch.
- **If pixel driving disappoints after real runs**: the escape hatch is the
  official zcode computer-use plugin's accessibility-first tools
  (a11y semantic actions), a different substrate, so re-validate the whole
  protocol before switching.
- Region zoom: `lcu screenshot --region X Y W H` for a full-resolution crop;
  add region x/y to image coords for absolute screen coordinates.
