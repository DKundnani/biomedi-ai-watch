"""The two kinds of model call the pipeline makes, on either backend.

  api          the Claude API, billed to ANTHROPIC_API_KEY
  claude_code  the Claude Code CLI (`claude -p`), signed in with a Claude subscription
               through CLAUDE_CODE_OAUTH_TOKEN (create one with `claude setup-token`)

llm.backend in config.yaml picks one; "auto" uses the API when ANTHROPIC_API_KEY is set
and Claude Code otherwise.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

log = logging.getLogger(__name__)

WEB_SEARCHES, WEB_FETCHES = 15, 10


def backend(llm_cfg: dict) -> str:
    choice = llm_cfg.get("backend", "auto")
    if choice != "auto":
        return choice
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if shutil.which("claude"):
        return "claude_code"
    raise RuntimeError("No model access: set ANTHROPIC_API_KEY, or install Claude Code and set "
                       "CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)")


def structured(prompt: str, schema: dict, llm_cfg: dict, system: str | None = None,
               effort: str | None = None, max_tokens: int | None = None) -> dict:
    """One answer, returned as a dict that matches `schema`. No tools."""
    effort = effort or llm_cfg["effort"]
    if backend(llm_cfg) == "claude_code":
        out = _claude_code(prompt, llm_cfg, effort, system=system, schema=schema, tools=())
        return out["structured_output"]

    msg = _api_stream(llm_cfg, [{"role": "user", "content": prompt}], max_tokens=max_tokens,
                      system=system,
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Output hit max_tokens; raise llm.max_tokens in config.yaml")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def web_research(prompt: str, llm_cfg: dict) -> str:
    """A free-text answer written after searching and reading the web."""
    if backend(llm_cfg) == "claude_code":
        prompt += (f"\n\nUse at most {WEB_SEARCHES} web searches and {WEB_FETCHES} page fetches. "
                   "Reply with the spotlight text only, with no preamble.")
        return _claude_code(prompt, llm_cfg, llm_cfg["effort"], tools=("WebSearch", "WebFetch"))["result"]

    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": WEB_SEARCHES},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": WEB_FETCHES}]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(6):  # server tools may pause a long turn; re-send to let it continue
        msg = _api_stream(llm_cfg, messages, tools=tools, output_config={"effort": llm_cfg["effort"]})
        if msg.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": msg.content}]
    return "".join(b.text for b in msg.content if b.type == "text")


# ---------- backends ----------

def _api_stream(llm_cfg: dict, messages: list, max_tokens: int | None = None, system: str | None = None, **kw):
    import anthropic

    if system:
        kw["system"] = system
    with anthropic.Anthropic().beta.messages.stream(
        model=llm_cfg["model"], max_tokens=max_tokens or llm_cfg["max_tokens"], messages=messages,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw,
    ) as s:
        msg = s.get_final_message()
    log.info("claude api: model=%s stop=%s in=%s out=%s request=%s", msg.model, msg.stop_reason,
             msg.usage.input_tokens, msg.usage.output_tokens, msg._request_id)
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {msg.stop_details}")
    return msg


def _claude_code(prompt: str, llm_cfg: dict, effort: str, system: str | None = None,
                 schema: dict | None = None, tools: tuple[str, ...] = ()) -> dict:
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--model", llm_cfg["model"], "--effort", effort, "--tools", ",".join(tools)]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if system:
        cmd += ["--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]

    # Run outside the repo so no project CLAUDE.md or settings leak into the prompt.
    with tempfile.TemporaryDirectory(prefix="bmaw-claude-") as cwd:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=1800)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude -p failed (exit {p.returncode}): {(p.stderr or p.stdout)[-2000:]}")
    log.info("claude code: subtype=%s turns=%s api-equivalent cost=$%s", out.get("subtype"), out.get("num_turns"),
             out.get("total_cost_usd"))
    if out.get("is_error") or out.get("subtype") != "success":
        raise RuntimeError(f"claude -p: {out.get('subtype')}: {str(out.get('result'))[:2000]}")
    if schema and not isinstance(out.get("structured_output"), dict):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(out.get("result", "")).strip())
        out["structured_output"] = json.loads(text)
    return out
