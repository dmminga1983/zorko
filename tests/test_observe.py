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


# -- consent ----------------------------------------------------------------------

def test_nothing_recorded_without_consent(site, zhome):
    (zhome / "config.json").write_text('{"allow_private": true}', encoding="utf-8")
    from zorko import Browser

    with Browser(persist=False) as b:
        out = b.open(site + "/news.html")
        assert "Zorko asks the user once" in out
        assert "not saved" in b.feedback("something")
        assert "Zorko asks" not in b.open(site + "/shop.html")  # asked once per session
    assert load() == []


def test_set_consent_aliases(zhome):
    from zorko.observe import consent, set_consent

    assert set_consent("нет") == "off" and consent() == "off"
    assert set_consent("share") == "share"
    with pytest.raises(ValueError):
        set_consent("maybe")


def test_share_is_reviewable_and_can_hide_sites(browser, site, zhome):
    from zorko.observe import mark_shared, set_consent, share_pending, share_url

    set_consent("share")
    browser.open(site + "/news.html")
    browser.feedback("comment count missing")
    month = load()[0]["ts"][:7]
    text, url = share_url(month)
    assert "127.0.0.1" in text and url.startswith("https://github.com/dmminga1983/zorko/issues/new?")
    text2, url2 = share_url(month, include_sites=False)
    assert "127.0.0.1" not in text2 and "comment count" not in text2
    mark_shared(month)
    assert share_pending() is None
