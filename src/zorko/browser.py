"""The Zorko browser session: Playwright underneath, a compact map on top."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
import urllib.parse
from importlib import resources
from pathlib import Path

from .guard import Policy, is_risky
from .observe import Observer, consent, share_pending
from .render import UNTRUSTED, build_lines, estimate_tokens, paginate, readable

SNAPSHOT_JS = resources.files("zorko").joinpath("snapshot.js").read_text(encoding="utf-8")
MAX_CHARS = 6000
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def home() -> Path:
    return Path(os.environ.get("ZORKO_HOME") or Path.home() / ".zorko")


def load_config() -> dict:
    p = home() / "config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def policy_from_config(cfg: dict) -> Policy:
    return Policy(
        allow=list(cfg.get("allow", [])),
        deny=list(cfg.get("deny", [])),
        allow_private=bool(cfg.get("allow_private", False)),
        respect_robots=bool(cfg.get("respect_robots", True)),
    )


class ZorkoError(Exception):
    """An error message meant for the agent."""


class Browser:
    def __init__(self, profile: str = "default", headless: bool = True, policy: Policy | None = None,
                 max_chars: int = MAX_CHARS, user_agent: str | None = None, persist: bool = True):
        cfg = load_config()
        self.profile = profile
        self.headless = headless
        self.policy = policy or policy_from_config(cfg)
        self.obs = Observer()
        self._notified = False
        self.max_chars = max_chars
        self.user_agent = user_agent or cfg.get("user_agent")
        self.persist = persist
        self._pw = None
        self._ctx = None
        self._browser = None
        self.page = None
        self.next_id = 1
        self.elements: dict[int, dict] = {}
        self.id_frame: dict[int, object] = {}
        self.last_lines: list[str] = []
        self.events: list[str] = []

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        if self._ctx:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kw = dict(headless=self.headless, viewport={"width": 1280, "height": 900}, accept_downloads=False)
        if self.user_agent:
            kw["user_agent"] = self.user_agent
        if self.persist:
            d = home() / "profiles" / self.profile
            d.mkdir(parents=True, exist_ok=True)
            self._ctx = self._pw.chromium.launch_persistent_context(str(d), **kw)
        else:
            self._browser = self._pw.chromium.launch(headless=self.headless)
            kw.pop("headless")
            self._ctx = self._browser.new_context(**kw)
        self._ctx.route("**/*", self._route)
        self._ctx.on("page", self._on_page)
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._watch(self.page)
        self.events.clear()

    def close(self):
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()
        self._ctx = self._browser = self._pw = self.page = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- guards and events -------------------------------------------------
    def _route(self, route):
        req = route.request
        url = req.url
        if req.is_navigation_request() and req.frame == req.frame.page.main_frame:
            why = self.policy.check(url)
        else:
            # Subresources: only block private-network access (SSRF), not CDNs.
            p = Policy(allow_private=self.policy.allow_private, respect_robots=False,
                       _ip_cache=self.policy._ip_cache)
            why = p.check(url) if url.startswith(("http:", "https:")) else None
        if why:
            if req.is_navigation_request():
                self.events.append(f"blocked navigation: {why}")
            return route.abort("blockedbyclient")
        return route.continue_()

    def _watch(self, page):
        def on_dialog(d):
            self.events.append(f"page dialog ({d.type}) dismissed: \"{d.message[:200]}\"")
            try:
                d.dismiss()
            except Exception:
                pass

        page.on("dialog", on_dialog)

    def _on_page(self, page):
        self._watch(page)
        self.page = page
        self.events.append("a new tab opened and is now active")

    def _log(self, action: str, **data):
        try:
            d = home() / "log"
            d.mkdir(parents=True, exist_ok=True)
            rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "action": action,
                   "url": self.page.url if self.page else "", **data}
            with open(d / f"{_dt.date.today().isoformat()}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _settle(self, ms: int = 2500):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=ms)
        except Exception:
            pass
        self.page.wait_for_timeout(150)

    # -- snapshot ------------------------------------------------------------
    def _snapshot(self) -> list[tuple[str, dict]]:
        page = self.page
        frames = []
        fresh = page.main_frame.evaluate("() => { const f = !window.__zorkoSeen; window.__zorkoSeen = 1; return f; }")
        if fresh:
            self.next_id = 1
            self.elements.clear()
            self.id_frame.clear()
        for fr in page.frames:
            if fr.is_detached():
                continue
            label = ""
            if fr != page.main_frame:
                try:
                    box = fr.frame_element().bounding_box()
                except Exception:
                    box = None
                if not box or box["width"] < 150 or box["height"] < 80:
                    continue
                label = urllib.parse.urlsplit(fr.url).netloc or fr.name or "inline"
            try:
                snap = fr.evaluate(SNAPSHOT_JS, {"startId": self.next_id, "maxText": 400})
            except Exception:
                continue
            for it in snap["items"]:
                if it["k"] == "e":
                    self.id_frame[it["id"]] = fr
            self.next_id = max(self.next_id, snap["nextId"])
            if label and not snap["items"]:
                continue
            frames.append((label, snap))
        return frames

    def _header(self, frames, page_no, total) -> list[str]:
        snap = frames[0][1] if frames else {"title": "", "url": self.page.url, "scroll": {}}
        head = [f"title: {snap['title']}", f"url: {snap['url']}"]
        sc = snap.get("scroll") or {}
        if sc.get("h") and sc.get("vh") and sc["h"] > sc["vh"] * 1.2:
            head.append(f"scroll: {round(100 * sc['y'] / max(1, sc['h'] - sc['vh']))}% of {round(sc['h'] / sc['vh'], 1)} screens")
        if total > 1:
            head.append(f"part {page_no} of {total}")
        notes = self.notes()
        if notes:
            head.append("your saved notes for this site:\n" + notes)
        return head

    def _compose(self, page_no: int = 1) -> str:
        frames = self._snapshot()
        lines, warnings, elements = build_lines(frames)
        self.elements = elements
        self.last_lines = lines
        body, total = paginate(lines, page_no, self.max_chars)
        out = self._header(frames, page_no, total)
        out += self._drain_events()
        out += [f"! {w}" for w in warnings]
        out.append(UNTRUSTED)
        out += body
        if page_no < total:
            out.append(f"(more: look(part={page_no + 1}), or find(text) to search)")
        return "\n".join(out)

    def _drain_events(self) -> list[str]:
        ev, self.events = self.events, []
        return [f"* {e}" for e in ev]

    def _changes(self, before_url: str, before_lines: list[str]) -> str:
        """After an action: the new page if we navigated, otherwise only what changed."""
        self._settle()
        if self.page.url.split("#")[0] != before_url.split("#")[0]:
            return "navigated.\n" + self._compose(1)
        frames = self._snapshot()
        lines, warnings, elements = build_lines(frames)
        self.elements = elements
        self.last_lines = lines
        old = set(before_lines)
        added = [ln for ln in lines if ln not in old]
        removed = len(old - set(lines))
        out = self._drain_events() + [f"! {w}" for w in warnings]
        if not added and not removed:
            out.append("no visible change on the page.")
        else:
            out.append(f"page changed: {len(added)} new lines, {removed} gone.")
            if added:
                out.append(UNTRUSTED)
                shown, total = paginate(added, 1, self.max_chars)
                out += shown
                if total > 1:
                    out.append("(more changes: look())")
        return "\n".join(out)

    # -- public actions ------------------------------------------------------
    def open(self, url: str) -> str:
        self.start()
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
            url = "https://" + url
        why = self.policy.check(url)
        if why:
            raise ZorkoError(f"refused: {why}")
        if not self.policy.robots_allows(url):
            raise ZorkoError("refused: robots.txt of this site disallows automated access to this page "
                             "(set respect_robots=false in ~/.zorko/config.json to override for your own use)")
        self._log("open", target=url)
        if not self._notified:
            self._notified = True
            if consent() is None:
                self.events.append(
                    "Zorko asks the user once: may it keep a local journal of its own problems to improve? "
                    "Ask the user (choices: off, local, share) and pass their own answer to consent(); "
                    "or they can run `zorko consent`. Nothing is recorded until they answer.")
            elif share_pending():
                self.events.append(
                    "Zorko's anonymous usage report for last month is ready. When convenient, tell the user "
                    "they can review and send it with `zorko share` (optional).")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0]
            ev = " ".join(self._drain_events())
            raise self._fail("open_failed", f"could not open {url}: {msg} {ev}".strip(),
                             error=msg.split(":")[0][:80]) from None
        self._settle()
        out = self._compose(1)
        self._observe_open(out)
        return out

    def look(self, part: int = 1) -> str:
        self._need_page()
        return self._compose(part)

    def read(self, part: int = 1) -> str:
        self._need_page()
        frames = self._snapshot()
        lines = readable(frames)
        body, total = paginate(lines, part, self.max_chars)
        out = [f"title: {frames[0][1]['title'] if frames else ''}", f"url: {self.page.url}"]
        if total > 1:
            out.append(f"part {part} of {total}")
        out.append(UNTRUSTED)
        out += body
        if part < total:
            out.append(f"(more: read(part={part + 1}))")
        return "\n".join(out)

    def find(self, text: str) -> str:
        self._need_page()
        self._compose(1)
        q = text.lower().strip()
        hits = [ln for ln in self.last_lines if q in ln.lower()]
        if not hits:
            return f"nothing matching {text!r} on this page."
        body, total = paginate(hits, 1, self.max_chars)
        return "\n".join([f"{len(hits)} matches:", UNTRUSTED, *body] + (["(too many, refine the query)"] if total > 1 else []))

    def _locator(self, eid: int):
        self._need_page()
        fr = self.id_frame.get(eid)
        if eid not in self.elements or fr is None:
            raise ZorkoError(f"no element [{eid}] on the current page; call look() to get fresh numbers")
        loc = fr.locator(f'[data-zorko-id="{eid}"]').first
        if loc.count() == 0:
            raise self._fail("element_gone", f"element [{eid}] is gone (the page changed); call look()",
                             role=self.elements[eid].get("role"))
        return loc

    def click(self, eid: int, confirm: bool = False) -> str:
        loc = self._locator(eid)
        it = self.elements[eid]
        if is_risky(it) and not confirm:
            raise self._fail("refused", f"[{eid}] {it['role']} \"{it.get('name', '')}\" can send, pay, delete or publish something. "
                             "Ask the user first, then call click again with confirm=true.", why="confirm")
        before_url, before = self.page.url, list(self.last_lines)
        self._log("click", target=f"[{eid}] {it.get('name', '')}", confirm=confirm)
        try:
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.click(timeout=10000)
        except Exception as e:  # noqa: BLE001
            raise self._fail("action_failed", f"click on [{eid}] failed: {str(e).splitlines()[0]}",
                             action="click", role=it["role"], error=str(e).splitlines()[0][:120]) from None
        return self._changes(before_url, before)

    def type(self, eid: int, text: str, submit: bool = False, confirm: bool = False) -> str:
        loc = self._locator(eid)
        it = self.elements[eid]
        if it.get("type") == "password" or "парол" in it.get("name", "").lower() or "password" in it.get("name", "").lower():
            raise self._fail("refused", "Zorko never types passwords. Ask the user to sign in themselves with: zorko login <site>",
                             why="password")
        if CARD_RE.search(text):
            raise self._fail("refused", "this looks like a card or account number; Zorko does not enter payment details. Ask the user to do it.",
                             why="card")
        if it["role"] not in ("input", "textarea", "select"):
            raise ZorkoError(f"[{eid}] is a {it['role']}, not a text field")
        if submit and not confirm:
            risky = [e for e in self.elements.values()
                     if it.get("form") and e.get("form") == it.get("form") and e.get("submit") and e.get("risky")]
            if risky:
                raise ZorkoError(f"pressing Enter here submits a form via \"{risky[0].get('name')}\". "
                                 "Ask the user first, then call again with confirm=true.")
        before_url, before = self.page.url, list(self.last_lines)
        self._log("type", target=f"[{eid}] {it.get('name', '')}", chars=len(text), submit=submit)
        try:
            if it.get("type") == "editable":
                loc.click(timeout=5000)
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(text)
            else:
                loc.fill(text, timeout=10000)
            if submit:
                loc.press("Enter")
        except Exception as e:  # noqa: BLE001
            raise self._fail("action_failed", f"typing into [{eid}] failed: {str(e).splitlines()[0]}",
                             action="type", role=it["role"], error=str(e).splitlines()[0][:120]) from None
        return self._changes(before_url, before)

    def select(self, eid: int, option: str) -> str:
        loc = self._locator(eid)
        it = self.elements[eid]
        before_url, before = self.page.url, list(self.last_lines)
        self._log("select", target=f"[{eid}] {it.get('name', '')}", option=option)
        try:
            if it["role"] == "select":
                try:
                    loc.select_option(label=option, timeout=5000)
                except Exception:
                    loc.select_option(value=option, timeout=5000)
            else:
                raise ZorkoError(f"[{eid}] is not a dropdown; click it and pick from the list instead")
        except ZorkoError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._fail("action_failed", f"no option {option!r} in [{eid}]; options: {', '.join(it.get('options', []))}",
                             action="select", error=type(e).__name__) from None
        return self._changes(before_url, before)

    def press(self, key: str) -> str:
        self._need_page()
        before_url, before = self.page.url, list(self.last_lines)
        self._log("press", target=key)
        try:
            self.page.keyboard.press(key)
        except Exception as e:  # noqa: BLE001
            raise ZorkoError(f"unknown key {key!r}: {str(e).splitlines()[0]}") from None
        return self._changes(before_url, before)

    def scroll(self, direction: str = "down", screens: float = 1) -> str:
        self._need_page()
        before_url, before = self.page.url, list(self.last_lines)
        dy = 900 * screens * (-1 if direction == "up" else 1)
        self.page.mouse.wheel(0, dy)
        self.page.wait_for_timeout(400)
        return self._changes(before_url, before)

    def back(self) -> str:
        self._need_page()
        self._log("back")
        self.page.go_back(wait_until="domcontentloaded", timeout=20000)
        self._settle()
        return self._compose(1)

    def screenshot(self, full: bool = False) -> bytes:
        self._need_page()
        return self.page.screenshot(type="jpeg", quality=60, full_page=full)

    def tabs(self, switch: int | None = None) -> str:
        self._need_page()
        pages = self._ctx.pages
        if switch is not None:
            if not 1 <= switch <= len(pages):
                raise ZorkoError(f"no tab {switch}; there are {len(pages)}")
            self.page = pages[switch - 1]
            self.page.bring_to_front()
            return self._compose(1)
        return "\n".join(f"{'*' if p == self.page else ' '} {i}. {p.title()[:60]} {p.url}" for i, p in enumerate(pages, 1))

    def wait(self, text: str = "", seconds: float = 0) -> str:
        self._need_page()
        before_url, before = self.page.url, list(self.last_lines)
        if text:
            try:
                self.page.get_by_text(text).first.wait_for(timeout=min(30, seconds or 15) * 1000)
            except Exception:
                raise ZorkoError(f"text {text!r} did not appear") from None
        else:
            self.page.wait_for_timeout(min(30.0, seconds or 2) * 1000)
        return self._changes(before_url, before)

    # -- site notes ----------------------------------------------------------
    def _notes_path(self) -> Path | None:
        if not self.page:
            return None
        host = urllib.parse.urlsplit(self.page.url).hostname
        if not host:
            return None
        host = re.sub(r"[^a-z0-9.-]", "_", host.lower()).removeprefix("www.")
        return home() / "sites" / f"{host}.md"

    def notes(self) -> str:
        p = self._notes_path()
        if p and p.exists():
            return p.read_text(encoding="utf-8").strip()[-2000:]
        return ""

    def note(self, text: str) -> str:
        p = self._notes_path()
        if not p:
            raise ZorkoError("open a site first")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"- {text.strip()}\n")
        return f"saved note for {p.stem}"

    def _fail(self, kind: str, msg: str, **facts) -> ZorkoError:
        """Record a weak spot for self-improvement and build the error for the agent."""
        self.obs.record(kind, self.page.url if self.page else "", **facts)
        return ZorkoError(msg)

    def feedback(self, text: str) -> str:
        """A note about Zorko itself: what the map missed, what did not work."""
        if not self.obs.enabled:
            return "not saved: the user has not allowed Zorko's journal (they can enable it with `zorko consent`)"
        self.obs.record("feedback", self.page.url if self.page else "", text=text.strip())
        return "thanks, noted for the next Zorko improvement"

    def _observe_open(self, text: str):
        if not self.obs.enabled:
            return
        url = self.page.url
        full = "\n".join(self.last_lines)
        tokens = estimate_tokens(full)
        self.obs.record("open", url, tokens=tokens, elements=len(self.elements), lines=len(self.last_lines))
        if tokens > 8000:
            self.obs.record("big_map", url, tokens=tokens, lines=len(self.last_lines))
        unnamed = [e["role"] for e in self.elements.values() if not e.get("name")]
        if len(unnamed) >= 3:
            self.obs.record("unnamed", url, count=len(unnamed), roles=sorted(set(unnamed)))
        try:
            page_chars = self.page.evaluate("() => (document.body && document.body.innerText || '').length")
        except Exception:
            page_chars = 0
        map_chars = sum(len(ln) for ln in self.last_lines if not ln.startswith("["))
        if page_chars > 3000 and map_chars < page_chars * 0.25:
            self.obs.record("weak_map", url, page_chars=page_chars, map_chars=map_chars)
        inj = [w for w in text.splitlines() if "instructions to an AI" in w]
        if inj:
            self.obs.record("injection", url, hidden=sum("HIDDEN" in w for w in inj), visible=sum("HIDDEN" not in w for w in inj))

    def _need_page(self):
        if not self.page or self.page.url in ("", "about:blank"):
            raise ZorkoError("no page open yet; call open(url) first")


def login(url: str, profile: str = "default") -> None:
    """Open a visible window so the user can sign in; the session is kept in the profile."""
    b = Browser(profile=profile, headless=False)
    b.start()
    if not re.match(r"^[a-z]+:", url):
        url = "https://" + url
    b.page.goto(url)
    print(f"Sign in in the browser window, then close it. Profile: {profile}")
    try:
        while b._ctx and b._ctx.pages:
            time.sleep(0.5)
            b._ctx.pages[0].wait_for_timeout(100)
    except Exception:
        pass
    b.close()
    print("Session saved.")
