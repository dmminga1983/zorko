"""Self-observation: Zorko notes its own weak spots so it can be improved.

Everything stays on this computer in ~/.zorko/observations/. Nothing is sent
anywhere. Records hold the site host and technical facts (what failed, how big
the map was), never page text, typed text or full URLs.
Turn off with: zorko config --set observe=false
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import urllib.parse
from pathlib import Path

from . import __version__


def _home() -> Path:
    return Path(os.environ.get("ZORKO_HOME") or Path.home() / ".zorko")


def host_of(url: str) -> str:
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h.removeprefix("www.")


class Observer:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def record(self, kind: str, url: str = "", **facts):
        if not self.enabled:
            return
        rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "v": __version__,
               "kind": kind, "host": host_of(url)}
        for k, v in facts.items():
            if isinstance(v, str):
                v = v[:300]
            rec[k] = v
        try:
            d = _home() / "observations"
            d.mkdir(parents=True, exist_ok=True)
            with open(d / f"{_dt.date.today():%Y-%m}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def load(month: str | None = None) -> list[dict]:
    d = _home() / "observations"
    files = sorted(d.glob("*.jsonl")) if d.exists() else []
    if month:
        files = [f for f in files if f.stem == month]
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


# What each kind of record means, and what to look at when improving Zorko.
KINDS = {
    "action_failed": "click/type/select did not work",
    "element_gone": "element number went stale between look and action",
    "open_failed": "page did not open",
    "weak_map": "map looks poorer than the page (missing content?)",
    "unnamed": "controls without a readable name",
    "big_map": "map was large (token cost)",
    "injection": "prompt injection found on a page",
    "refused": "safety refusal (confirm, password, card)",
    "feedback": "note from the agent or user about Zorko",
}


def report(month: str | None = None) -> str:
    """A Markdown summary of observations, ready to guide the next improvement."""
    recs = load(month)
    title = f"Zorko self-observation report ({month or 'all time'})"
    if not recs:
        return f"# {title}\n\nNo observations yet."
    opens = [r for r in recs if r["kind"] == "open"]
    by_kind = collections.Counter(r["kind"] for r in recs if r["kind"] != "open")
    lines = [f"# {title}", "",
             f"Pages opened: {len(opens)}, sites: {len({r['host'] for r in opens})}, "
             f"versions: {', '.join(sorted({r.get('v', '?') for r in recs}))}", ""]
    if opens:
        toks = sorted(r.get("tokens", 0) for r in opens)
        lines += [f"Map size: median {toks[len(toks) // 2]} tokens, max {toks[-1]}.", ""]
    lines += ["## Problems by type", "", "| type | count | meaning |", "|---|---|---|"]
    for k, n in by_kind.most_common():
        lines.append(f"| {k} | {n} | {KINDS.get(k, '')} |")
    for kind in ("action_failed", "element_gone", "open_failed", "weak_map", "unnamed", "big_map"):
        rs = [r for r in recs if r["kind"] == kind]
        if not rs:
            continue
        lines += ["", f"## {kind}: top sites", ""]
        per_host = collections.Counter(r["host"] or "?" for r in rs)
        for host, n in per_host.most_common(10):
            sample = next(r for r in rs if (r["host"] or "?") == host)
            detail = {k: v for k, v in sample.items() if k not in ("ts", "v", "kind", "host")}
            lines.append(f"- {host}: {n}x, e.g. {json.dumps(detail, ensure_ascii=False)}")
    fb = [r for r in recs if r["kind"] == "feedback"]
    if fb:
        lines += ["", "## Feedback notes", ""]
        lines += [f"- {r['ts'][:10]} {r['host'] or ''}: {r.get('text', '')}" for r in fb[-30:]]
    return "\n".join(lines)
