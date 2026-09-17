#!/usr/bin/env python3
"""lcu-mcp - Model Context Protocol server exposing Linux computer use.

Wraps the `lcu` CLI as MCP tools so any agent can see and drive the X11
desktop directly. Screenshots come back as inline image content, so the
model sees the screen rather than a file path.

Pure stdlib JSON-RPC over stdio - no third-party dependencies.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys

LCU = os.environ.get("LCU_BIN") or shutil.which("lcu") or os.path.expanduser("~/.local/bin/lcu")
PROTOCOL_VERSION = "2024-11-05"
MAX_IMAGE_BYTES = 4_000_000


def lcu(*args: str) -> dict:
    proc = subprocess.run([LCU, *args], capture_output=True, text=True, timeout=60)
    out = (proc.stdout or "").strip().splitlines()
    for line in reversed(out):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": (proc.stderr or proc.stdout or "no output").strip()[:500]}


TOOLS = [
    {
        "name": "screenshot",
        "description": ("Capture the screen and return it as an image. Use this to SEE the "
                        "desktop before acting, and again afterwards to verify. Coordinates "
                        "in the returned image are absolute screen coords unless a window is "
                        "specified, in which case add the reported region x/y."),
        "inputSchema": {
            "type": "object",
            "properties": {
                    "window": {"type": "string", "description": "'active', a window id, or a name substring. Omit for the full screen."},
                    "region": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4, "description": "[x, y, w, h] absolute-screen rectangle to capture (zoom for small targets). Coordinates in the returned image are relative; add x/y for absolute screen coords."},
                "scale": {"type": "number", "description": "Scale factor, e.g. 0.5 to halve. Divide image coords by this to get screen coords.", "default": 1.0},
                "delay": {"type": "number", "description": "Seconds to wait before capturing (let UI settle).", "default": 0},
            },
        },
    },
    {
        "name": "click",
        "description": "Click at absolute screen coordinates. Take a screenshot first to find the target.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "middle", "right"], "default": "left"},
                "count": {"type": "integer", "description": "2 for a double-click.", "default": 1},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Type literal text into the focused window.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": "Press key combos, e.g. ['ctrl+s'], ['Return'], ['alt+Tab'], ['ctrl+shift+t'].",
        "inputSchema": {
            "type": "object",
            "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the wheel, optionally after moving the pointer to x/y.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "default": 3},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "drag",
        "description": "Press at (x1,y1), move, release at (x2,y2). For sliders, selection, drag-and-drop.",
        "inputSchema": {
            "type": "object",
            "properties": {"x1": {"type": "integer"}, "y1": {"type": "integer"},
                           "x2": {"type": "integer"}, "y2": {"type": "integer"}},
            "required": ["x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "list_windows",
        "description": "List visible windows with ids, titles, geometry, and which is active.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "focus_window",
        "description": "Activate/raise a window by 'active', id, or name substring. Do this before typing.",
        "inputSchema": {
            "type": "object",
            "properties": {"window": {"type": "string"}},
            "required": ["window"],
        },
    },
]


def call_tool(name: str, a: dict) -> dict:
    if name == "screenshot":
        args = ["screenshot"]
        if a.get("window"):
            args += ["--window", str(a["window"])]
        if a.get("region"):
            args += ["--region", *[str(v) for v in a["region"]]]
        if a.get("scale") and a["scale"] != 1.0:
            args += ["--scale", str(a["scale"])]
        if a.get("delay"):
            args += ["--delay", str(a["delay"])]
        res = lcu(*args)
        if not res.get("ok"):
            return {"content": [{"type": "text", "text": f"screenshot failed: {res.get('error')}"}],
                    "isError": True}
        path = res["path"]
        size = os.path.getsize(path)
        if size > MAX_IMAGE_BYTES:
            return {"content": [{"type": "text",
                                 "text": f"Screenshot too large ({size} bytes) to inline. "
                                         f"Retry with a smaller scale. Saved at {path}"}]}
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode()
        meta = {k: v for k, v in res.items() if k not in ("ok", "path")}
        return {"content": [
            {"type": "image", "data": data, "mimeType": "image/png"},
            {"type": "text", "text": json.dumps(meta)},
        ]}

    if name == "click":
        res = lcu("click", str(a["x"]), str(a["y"]),
                  "--button", a.get("button", "left"), "--count", str(a.get("count", 1)))
    elif name == "type_text":
        res = lcu("type", a["text"])
    elif name == "press_key":
        res = lcu("key", *[str(k) for k in a["keys"]])
    elif name == "scroll":
        args = ["scroll", a["direction"], str(a.get("amount", 3))]
        if a.get("x") is not None and a.get("y") is not None:
            args += ["--x", str(a["x"]), "--y", str(a["y"])]
        res = lcu(*args)
    elif name == "drag":
        res = lcu("drag", str(a["x1"]), str(a["y1"]), str(a["x2"]), str(a["y2"]))
    elif name == "list_windows":
        res = lcu("windows")
    elif name == "focus_window":
        res = lcu("focus", str(a["window"]))
    else:
        return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}

    return {"content": [{"type": "text", "text": json.dumps(res)}],
            "isError": not res.get("ok", False)}


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method, rid = req.get("method"), req.get("id")

        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "lcu", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = req.get("params", {})
            try:
                result = call_tool(params.get("name", ""), params.get("arguments") or {})
            except Exception as exc:  # surface faults as tool errors, never crash the server
                result = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue
        elif method == "ping":
            result = {}
        else:
            if rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                             "error": {"code": -32601, "message": f"method not found: {method}"}}) + "\n")
                sys.stdout.flush()
            continue

        if rid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
