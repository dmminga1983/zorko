import json

import pytest

from zorko import ZorkoError
from zorko.observe import load, report


def kinds(zhome):
    return [r["kind"] for r in load()]


def test_open_is_observed_without_content(browser, site, zhome):
    browser.open(site + "/shop.html")
    recs = load()
    rec = next(r for r in recs if r["kind"] == "open")
    assert rec["host"] == "127.0.0.1" and rec["tokens"] > 0 and rec["elements"] > 10
    raw = json.dumps(recs, ensure_ascii=False)
    assert "Скважинный" not in raw and "/shop.html" not in raw  # no page text, no paths


def test_failures_and_refusals_observed(browser, site, zhome):
    out = browser.open(site + "/login.html")
    pw = int(out.split('input "Пароль"')[0].rsplit("[", 1)[1].split("]")[0])
    with pytest.raises(ZorkoError):
        browser.type(pw, "secret")
    raw = json.dumps(load(), ensure_ascii=False)
    assert '"refused"' in raw and '"password"' in raw and "secret" not in raw


def test_injection_observed(browser, site, zhome):
    browser.open(site + "/inject.html")
    rec = next(r for r in load() if r["kind"] == "injection")
    assert rec["hidden"] == 3 and rec["visible"] == 1


def test_feedback_and_report(browser, site, zhome):
    browser.open(site + "/news.html")
    browser.feedback("map did not show the comment count")
    text = report()
    assert "Pages opened: 1" in text and "map did not show the comment count" in text


def test_observe_off(site, zhome):
    (zhome / "config.json").write_text('{"observe": false, "allow_private": true}', encoding="utf-8")
    from zorko import Browser

    with Browser(persist=False) as b:
        b.open(site + "/news.html")
    assert load() == []


def test_empty_report(zhome):
    assert "No observations yet" in report()
