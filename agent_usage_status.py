#!/usr/bin/env python3
"""Fetch Codex + Claude Code usage/rate-limit status and write one combined
JSON file: agent-usage-status.json.

Codex:  spawns `codex app-server`, speaks its newline-delimited JSON-RPC
        protocol, calls account/rateLimits/read + account/usage/read.
Claude: spawns `claude -p --input-format stream-json --output-format
        stream-json`, sends a control_request of subtype get_usage.

Both are local, no-cost queries (no model turn is run) -- safe to poll often.

Usage: ./agent_usage_status.py [--timeout SECONDS]
Exit code: 0 if both sources succeeded, 1 if either failed (the JSON is
still written either way, with per-source "ok"/"error").
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "agent-usage-status.json")

CLAUDE_WINDOW_MINUTES = {"five_hour": 300, "seven_day": 10080}


class RpcError(Exception):
    pass


@contextmanager
def _spawn(cmd):
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        yield proc
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


def _window(used_percent, window_minutes, resets_at_epoch, now):
    return {
        "used_percent": used_percent,
        "window_minutes": window_minutes,
        "resets_at": datetime.datetime.fromtimestamp(resets_at_epoch, tz=datetime.timezone.utc).isoformat()
        if resets_at_epoch is not None else None,
        "minutes_until_reset": round((resets_at_epoch - now) / 60, 1) if resets_at_epoch is not None else None,
    }


# ---- Codex ------------------------------------------------------------

def fetch_codex(timeout_s):
    deadline = time.monotonic() + timeout_s
    with _spawn(["codex", "app-server"]) as proc:
        def call(req_id, method, params):
            proc.stdin.write(json.dumps({"id": req_id, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            while True:
                if time.monotonic() > deadline:
                    raise RpcError(f"timed out waiting for {method}")
                line = proc.stdout.readline()
                if not line:
                    raise RpcError(f"app-server exited early (stderr: {proc.stderr.read().strip()})")
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == req_id:
                    if "error" in obj:
                        raise RpcError(f"{method} error: {obj['error']}")
                    return obj.get("result", {})

        call(1, "initialize", {"clientInfo": {"name": "agent-usage-widget", "version": "0.1.0"}})
        rl = (call(2, "account/rateLimits/read", None).get("rateLimits") or {})
        summary = (call(3, "account/usage/read", None).get("summary") or {})

    now = time.time()
    primary = rl.get("primary")
    secondary = rl.get("secondary")
    return {
        "ok": True,
        "plan_type": rl.get("planType"),
        "rate_limit_reached_type": rl.get("rateLimitReachedType"),
        "primary": _window(primary.get("usedPercent"), primary.get("windowDurationMins"), primary.get("resetsAt"), now) if primary else None,
        "secondary": _window(secondary.get("usedPercent"), secondary.get("windowDurationMins"), secondary.get("resetsAt"), now) if secondary else None,
        "credits": rl.get("credits"),
        "lifetime_tokens": summary.get("lifetimeTokens"),
        "peak_daily_tokens": summary.get("peakDailyTokens"),
        "current_streak_days": summary.get("currentStreakDays"),
    }


# ---- Claude -------------------------------------------------------------

def fetch_claude(timeout_s):
    deadline = time.monotonic() + timeout_s
    with _spawn(["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                 "--no-session-persistence", "--verbose"]) as proc:
        request_id = f"usage-{uuid.uuid4().hex[:8]}"
        proc.stdin.write(json.dumps({
            "type": "control_request", "request_id": request_id,
            "request": {"subtype": "get_usage"},
        }) + "\n")
        proc.stdin.flush()
        proc.stdin.close()

        while True:
            if time.monotonic() > deadline:
                raise RpcError("timed out waiting for get_usage response")
            line = proc.stdout.readline()
            if not line:
                raise RpcError(f"claude exited early (stderr: {proc.stderr.read().strip()})")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "control_response":
                continue
            resp = obj.get("response", {})
            if resp.get("request_id") != request_id:
                continue
            if resp.get("subtype") != "success":
                raise RpcError(f"get_usage failed: {resp}")
            usage = resp.get("response", {})
            break

    now = time.time()
    rl = usage.get("rate_limits") or {}

    def win(key):
        w = rl.get(key)
        if not w:
            return None
        resets_epoch = datetime.datetime.fromisoformat(w["resets_at"]).timestamp() if w.get("resets_at") else None
        return _window(w.get("utilization"), CLAUDE_WINDOW_MINUTES[key], resets_epoch, now)

    primary, secondary = win("five_hour"), win("seven_day")
    reached = any((w or {}).get("used_percent", 0) >= 100 for w in (primary, secondary))

    extra = rl.get("extra_usage") or {}
    session = usage.get("session") or {}
    behaviors = usage.get("behaviors") or {}
    return {
        "ok": True,
        "plan_type": usage.get("subscription_type"),
        "rate_limit_reached_type": "rate_limit_reached" if reached else None,
        "primary": primary,
        "secondary": secondary,
        "credits": {
            "hasCredits": extra.get("is_enabled"),
            "unlimited": bool(extra.get("is_enabled") and extra.get("monthly_limit") is None),
            "balance": extra.get("used_credits"),
        },
        "lifetime_tokens": None,   # not exposed by get_usage
        "peak_daily_tokens": None,
        "current_streak_days": None,
        "session_cost_usd": session.get("total_cost_usd"),
        "requests_today": (behaviors.get("day") or {}).get("request_count"),
        "requests_this_week": (behaviors.get("week") or {}).get("request_count"),
    }


# ---- glue ---------------------------------------------------------------

def safe_fetch(fn, timeout_s):
    try:
        return fn(timeout_s)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def write_atomic(path, data):
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    with ThreadPoolExecutor(max_workers=2) as pool:
        codex_fut = pool.submit(safe_fetch, fetch_codex, args.timeout)
        claude_fut = pool.submit(safe_fetch, fetch_claude, args.timeout)
        codex, claude = codex_fut.result(), claude_fut.result()

    doc = {
        "fetched_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "codex": codex,
        "claude": claude,
    }
    write_atomic(OUT_PATH, doc)
    print(json.dumps(doc, indent=2))
    return 0 if codex.get("ok") and claude.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
