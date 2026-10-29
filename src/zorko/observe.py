"""Self-observation: Zorko notes its own weak spots so it can be improved.

Nothing is recorded until the user agrees (zorko consent). Records stay on this
computer in ~/.zorko/observations/ and hold the site name and technical facts
(what failed, how big the map was), never page text, typed text or full URLs.
With the "share" choice the user can send a monthly report as a GitHub issue;
they see the whole text and press submit themselves. Zorko has no server and
sends nothing on its own.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import urllib.parse
from pathlib import Path

from . import __version__


REPO = "dmminga1983/zorko"
CHOICES = ("off", "local", "share")

CONSENT_TEXT = """\
Zorko can learn from how it works for you, to get better over time.

  off    record nothing
  local  keep a journal of Zorko's own problems on this computer only
  share  same, and once a month offer you a report to send to the developers

The journal holds the site name and technical facts (what failed, how large the
map was). It never holds page text, what you typed, passwords or full addresses.
Nothing leaves your computer unless you choose share AND press submit on the
report, which you will see in full first. Change any time: zorko consent

Zorko может учиться на своей работе у вас, чтобы становиться лучше.

  off    ничего не записывать
  local  вести журнал проблем Zorko только на этом компьютере
  share  то же, и раз в месяц предлагать отправить отчёт разработчикам

В журнале только имя сайта и технические факты (что не сработало, какого
размера была карта). Никогда текст страниц, что вы вводили, пароли или полные
адреса. Ничего не уходит с компьютера, пока вы не выберете share И сами не
нажмёте «отправить» в отчёте, который сначала увидите целиком.
Изменить в любой момент: zorko consent
"""


def _home() -> Path:
    return Path(os.environ.get("ZORKO_HOME") or Path.home() / ".zorko")


def _cfg_path() -> Path:
    return _home() / "config.json"


def _read_cfg() -> dict:
    try:
        return json.loads(_cfg_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cfg(cfg: dict):
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def consent() -> str | None:
    """The user's choice: 'off', 'local', 'share', or None when not asked yet."""
    c = _read_cfg().get("consent")
    return c if c in CHOICES else None


def set_consent(choice: str) -> str:
    choice = (choice or "").strip().lower()
    aliases = {"no": "off", "нет": "off", "0": "off", "1": "local", "yes": "local", "да": "local",
               "local only": "local", "2": "share", "send": "share"}
    choice = aliases.get(choice, choice)
    if choice not in CHOICES:
        raise ValueError(f"choose one of: {', '.join(CHOICES)}")
    cfg = _read_cfg()
    cfg["consent"] = choice
    cfg["consent_date"] = _dt.date.today().isoformat()
    _write_cfg(cfg)
    return choice


def recording_allowed() -> bool:
    cfg = _read_cfg()
    return cfg.get("consent") in ("local", "share") and cfg.get("observe", True) is not False


def host_of(url: str) -> str:
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h.removeprefix("www.")


class Observer:
    def __init__(self, enabled: bool | None = None):
        self.enabled = recording_allowed() if enabled is None else enabled

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


def last_month() -> str:
    first = _dt.date.today().replace(day=1)
    return f"{first - _dt.timedelta(days=1):%Y-%m}"


def share_pending() -> str | None:
    """Month whose report is waiting to be offered for sharing, if any."""
    if consent() != "share":
        return None
    m = last_month()
    if m in _read_cfg().get("shared", []) or not load(m):
        return None
    return m


def share_url(month: str, include_sites: bool = True) -> tuple[str, str]:
    """(report text, prefilled GitHub issue URL). Nothing is sent by this function."""
    text = report(month)
    if not include_sites:
        import re

        known = sorted({r["host"] for r in load(month) if r.get("host")}, key=len, reverse=True)
        for i, h in enumerate(known, 1):
            text = text.replace(h, f"site{i}")
        text = re.sub(r"(?m)^- \d{4}-\d\d-\d\d .*$", "- (feedback note hidden)", text)
    body = (f"Anonymous usage report for {month}, zorko {__version__}.\n"
            "Reviewed by me before sending.\n\n" + text)
    if len(body) > 6000:
        body = body[:6000] + "\n\n(truncated)"
    q = urllib.parse.urlencode({"title": f"Usage report {month}", "labels": "usage-report", "body": body})
    return text, f"https://github.com/{REPO}/issues/new?{q}"


def mark_shared(month: str):
    cfg = _read_cfg()
    done = cfg.setdefault("shared", [])
    if month not in done:
        done.append(month)
    _write_cfg(cfg)
