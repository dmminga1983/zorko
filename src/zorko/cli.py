"""Command line: zorko look | read | bench | login | mcp | setup | config."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import __version__
from .browser import Browser, ZorkoError, home, login
from .render import estimate_tokens


def _utf8():
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def cmd_look(a):
    with Browser(profile=a.profile, headless=not a.headed, persist=not a.no_profile) as b:
        print(b.open(a.url) if a.part == 1 else (b.open(a.url), b.look(a.part))[1])


def cmd_read(a):
    with Browser(profile=a.profile, persist=not a.no_profile) as b:
        b.open(a.url)
        print(b.read(a.part))


def cmd_bench(a):
    rows = []
    with Browser(profile=a.profile, persist=not a.no_profile) as b:
        b.max_chars = 10**9  # measure the whole page, not one part
        for url in a.urls:
            try:
                zorko = b.open(url)
            except ZorkoError as e:
                print(f"{url}: {e}", file=sys.stderr)
                continue
            html = b.page.content()
            text = b.page.inner_text("body")
            try:
                aria = b.page.aria_snapshot(mode="ai")
            except Exception:
                aria = ""
            rows.append((url, estimate_tokens(html), estimate_tokens(aria), estimate_tokens(text), estimate_tokens(zorko)))
    if not rows:
        return 1
    print(f"{'page':<42} {'HTML':>8} {'ARIA':>8} {'text':>8} {'Zorko':>8}  saving vs ARIA")
    for url, h, ar, t, z in rows:
        save = f"{ar / z:.1f}x" if z and ar else "-"
        print(f"{url[:42]:<42} {h:>8} {ar:>8} {t:>8} {z:>8}  {save}")
    print("(approximate tokens; ARIA is the AI-mode accessibility snapshot that Playwright MCP sends)")


def cmd_login(a):
    login(a.url, a.profile)


def cmd_mcp(a):
    from .mcp import serve

    serve(Browser(profile=a.profile, headless=not a.headed))


def cmd_setup(a):
    print("Installing Chromium for Playwright...")
    r = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
    if r != 0:
        print("Chromium install failed; run: python -m playwright install chromium", file=sys.stderr)
        return r
    from .observe import consent

    if consent() is None and not sys.stdin.isatty():
        print("\nLater, choose whether Zorko may keep a journal of its problems: zorko consent")
    print("\nDone. Connect Zorko to Claude Code with:\n  claude mcp add zorko -- zorko mcp")
    print("Sign in to a site once (the session is kept):\n  zorko login https://example.com")
    return 0


def cmd_report(a):
    from .observe import report

    text = report(a.month)
    if a.out:
        from pathlib import Path

        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(f"report written to {a.out}")
    else:
        print(text)


def cmd_feedback(a):
    from .observe import Observer

    obs = Observer()
    if not obs.enabled:
        print("The journal is off, so nothing was saved. To allow it: zorko consent local")
        return 1
    obs.record("feedback", a.url or "", text=" ".join(a.text))
    print("noted, thanks")


def ask_consent() -> str:
    from .observe import CONSENT_TEXT, set_consent

    print(CONSENT_TEXT)
    while True:
        ans = input("Your choice / ваш выбор [off/local/share]: ").strip().lower()
        try:
            c = set_consent(ans)
        except ValueError as e:
            print(e)
            continue
        print(f"saved: {c}")
        return c


def cmd_consent(a):
    from .observe import CONSENT_TEXT, consent, set_consent

    if a.choice:
        print(f"saved: {set_consent(a.choice)}")
    elif sys.stdin.isatty():
        print(f"current: {consent() or 'not chosen yet'}\n")
        ask_consent()
    else:
        print(CONSENT_TEXT)
        print(f"current: {consent() or 'not chosen yet'}; set with: zorko consent off|local|share")


def cmd_share(a):
    import webbrowser

    from .observe import consent, last_month, load, mark_shared, share_url

    if consent() != "share":
        print("Sharing is off. To allow it: zorko consent share")
        return 1
    month = a.month or last_month()
    if not load(month):
        print(f"No observations for {month}.")
        return 0
    text, url = share_url(month, include_sites=not a.no_sites)
    print(text)
    print("\nThis is everything that would be sent. It opens as a draft GitHub issue; nothing is sent until you press Submit there.")
    if a.yes or (sys.stdin.isatty() and input("Open the draft in your browser? [y/N]: ").strip().lower() in ("y", "yes", "д", "да")):
        webbrowser.open(url)
        mark_shared(month)
        print("Opened. Thank you!")
    else:
        print("Not opened. Run again any time: zorko share")


def cmd_config(a):
    p = home() / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    changed = False
    for d in a.allow or []:
        cfg.setdefault("allow", []).append(d)
        changed = True
    for d in a.deny or []:
        cfg.setdefault("deny", []).append(d)
        changed = True
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        cfg[k] = {"true": True, "false": False}.get(v.lower(), v)
        changed = True
    if changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{p}\n{json.dumps(cfg, ensure_ascii=False, indent=2) if cfg else '(defaults)'}")


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(prog="zorko", description="A browser for AI agents: compact page maps, safe actions.")
    ap.add_argument("--version", action="version", version=f"zorko {__version__}")
    ap.add_argument("--profile", default="default", help="browser profile with saved sign-ins")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("look", help="print the compact map of a page")
    s.add_argument("url")
    s.add_argument("--part", type=int, default=1)
    s.add_argument("--headed", action="store_true")
    s.add_argument("--no-profile", action="store_true", help="fresh browser without saved sign-ins")
    s.set_defaults(fn=cmd_look)

    s = sub.add_parser("read", help="print the main text of a page")
    s.add_argument("url")
    s.add_argument("--part", type=int, default=1)
    s.add_argument("--no-profile", action="store_true")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("bench", help="compare token cost: HTML vs ARIA snapshot vs Zorko")
    s.add_argument("urls", nargs="+")
    s.add_argument("--no-profile", action="store_true")
    s.set_defaults(fn=cmd_bench)

    s = sub.add_parser("login", help="open a visible window to sign in to a site")
    s.add_argument("url")
    s.set_defaults(fn=cmd_login)

    s = sub.add_parser("mcp", help="run the MCP server on stdio (for Claude Code)")
    s.add_argument("--headed", action="store_true", help="show the browser window")
    s.set_defaults(fn=cmd_mcp)

    s = sub.add_parser("setup", help="install Chromium and print the Claude Code command")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("report", help="summary of what Zorko noticed about its own weak spots")
    s.add_argument("--month", help="YYYY-MM, default all time")
    s.add_argument("--out", help="write Markdown to this file")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("feedback", help="tell Zorko what went wrong, for the next improvement")
    s.add_argument("text", nargs="+")
    s.add_argument("--url", help="site it was about")
    s.set_defaults(fn=cmd_feedback)

    s = sub.add_parser("consent", help="choose whether Zorko keeps a journal of its problems (off/local/share)")
    s.add_argument("choice", nargs="?", choices=["off", "local", "share"])
    s.set_defaults(fn=cmd_consent)

    s = sub.add_parser("share", help="review last month's anonymous report and open it as a GitHub issue draft")
    s.add_argument("--month", help="YYYY-MM, default last month")
    s.add_argument("--no-sites", action="store_true", help="replace site names with site1, site2...")
    s.add_argument("--yes", action="store_true", help="open the draft without asking")
    s.set_defaults(fn=cmd_share)

    s = sub.add_parser("config", help="show or change ~/.zorko/config.json")
    s.add_argument("--allow", action="append", metavar="DOMAIN", help="only allow these domains")
    s.add_argument("--deny", action="append", metavar="DOMAIN", help="never open these domains")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="e.g. allow_private=true, respect_robots=false, observe=false")
    s.set_defaults(fn=cmd_config)

    a = ap.parse_args(argv)
    if a.cmd in ("look", "read", "bench", "login", "setup") and sys.stdin.isatty():
        from .observe import consent

        if consent() is None:
            ask_consent()
    try:
        return a.fn(a) or 0
    except ZorkoError as e:
        print(f"zorko: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
