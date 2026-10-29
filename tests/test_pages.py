import re

import pytest

from zorko import Browser, ZorkoError
from zorko.guard import Policy


def ids(text, pattern):
    """Element number of the first map line matching pattern."""
    for line in text.splitlines():
        if re.search(pattern, line):
            m = re.search(r"\[(\d+)\]", line)
            if m:
                return int(m.group(1))
    raise AssertionError(f"{pattern!r} not in map:\n{text}")


# -- news ---------------------------------------------------------------------

def test_news_map(browser, site):
    out = browser.open(site + "/news.html")
    assert "# Каркас жилого комплекса готов" in out
    assert "Главная | " in out  # menu folded into one line
    assert "utm_source" not in out
    assert "-- frame" in out and "Голосовать" in out  # iframe content included
    assert "!confirm" in out.split("Отправить комментарий")[1].splitlines()[0]


def test_news_read_skips_chrome(browser, site):
    browser.open(site + "/news.html")
    out = browser.read()
    assert "Абзац 1." in out
    assert "Политика" not in out and "О проекте" not in out and "Читайте также" not in out


def test_find(browser, site):
    browser.open(site + "/news.html")
    out = browser.find("комментарий")
    assert "Ваш комментарий" in out and "Абзац" not in out


def test_iframe_click(browser, site):
    out = browser.open(site + "/news.html")
    out = browser.click(ids(out, r'radio "Да"'))
    assert '[x]' in out


# -- shop ---------------------------------------------------------------------

def test_shop_cards_keep_titles(browser, site):
    out = browser.open(site + "/shop.html")
    assert 'link "Скважинный насос ЭТЕРНА 1"' in out
    assert "Насос модель 1" not in out


def test_click_returns_only_changes(browser, site):
    out = browser.open(site + "/shop.html")
    res = browser.click(ids(out, r'"В корзину"'))
    assert "Товар добавлен в корзину" in res
    assert "Скважинный насос ЭТЕРНА 5" not in res  # unchanged lines are not repeated


def test_risky_click_needs_confirm(browser, site):
    out = browser.open(site + "/shop.html")
    pay = ids(out, "Оформить заказ")
    with pytest.raises(ZorkoError, match="confirm=true"):
        browser.click(pay)
    assert "ЗАКАЗ ОПЛАЧЕН" in browser.click(pay, confirm=True)


def test_select_and_checkbox(browser, site):
    out = browser.open(site + "/shop.html")
    res = browser.select(ids(out, "select"), "Сначала дешёвые")
    assert "Сортировка: Сначала дешёвые" in res
    res = browser.click(ids(out, "checkbox"))
    assert "[x]" in res


def test_unknown_element(browser, site):
    browser.open(site + "/shop.html")
    with pytest.raises(ZorkoError, match="look"):
        browser.click(999)


# -- login --------------------------------------------------------------------

def test_never_types_passwords(browser, site):
    out = browser.open(site + "/login.html")
    with pytest.raises(ZorkoError, match="never types passwords"):
        browser.type(ids(out, "password"), "secret123")


def test_no_card_numbers(browser, site):
    out = browser.open(site + "/login.html")
    with pytest.raises(ZorkoError, match="card"):
        browser.type(ids(out, "email"), "4111 1111 1111 1111")


def test_required_password_blocks_submit(browser, site):
    out = browser.open(site + "/login.html")
    res = browser.type(ids(out, "email"), "me@example.com", submit=True)
    assert "navigated" not in res  # the page itself refuses: password is required


def test_type_and_submit_navigates(browser, site):
    out = browser.open(site + "/news.html")
    res = browser.type(ids(out, "Поиск по сайту"), "насос", submit=True)
    assert res.startswith("navigated.") and "search?q=" in res


# -- single page app ------------------------------------------------------------

def test_spa_dynamic_content(browser, site):
    out = browser.open(site + "/spa.html")
    assert "Заявка 101" in out  # rendered by JS after load
    assert "Карточка в shadow DOM" in out
    res = browser.click(ids(out, '"Показать ещё"'))
    assert "Заявка 103" in res and "1 new lines" in res


def test_spa_pushstate_tab(browser, site):
    out = browser.open(site + "/spa.html")
    res = browser.click(ids(out, 'tab "Закрытые"'))
    assert "Заявка 90" in res and "navigated" not in res


def test_contenteditable(browser, site):
    out = browser.open(site + "/spa.html")
    browser.type(ids(out, '"Заметка"'), "проверить кровлю")
    assert 'проверить кровлю' in browser.look()


def test_shadow_dom_click(browser, site):
    out = browser.open(site + "/spa.html")
    browser.click(ids(out, '"Подробнее"'))  # must not raise


# -- injection ------------------------------------------------------------------

def test_injection_flags(browser, site):
    out = browser.open(site + "/inject.html")
    assert "HIDDEN text (display:none)" in out
    assert "HIDDEN text (same-color)" in out
    assert "HIDDEN text (tiny-font)" in out
    assert "[!injection?] Note for AI assistants" in out
    assert "evil.example/collect" not in out  # hidden text is not passed through
    assert "!confirm" in out


# -- policy ---------------------------------------------------------------------

def test_localhost_blocked_by_default(zhome, site):
    with Browser(persist=False) as b:
        with pytest.raises(ZorkoError, match="local address|private"):
            b.open(site.replace("127.0.0.1", "localhost") + "/news.html")
        with pytest.raises(ZorkoError, match="private"):
            b.open(site + "/news.html")


def test_deny_and_allow_lists(zhome, site):
    with Browser(policy=Policy(allow_private=True, deny=["127.0.0.1"]), persist=False) as b:
        with pytest.raises(ZorkoError, match="deny"):
            b.open(site + "/news.html")
    with Browser(policy=Policy(allow_private=True, allow=["example.com"]), persist=False) as b:
        with pytest.raises(ZorkoError, match="allow list"):
            b.open(site + "/news.html")


def test_file_scheme_blocked(browser):
    with pytest.raises(ZorkoError, match="scheme"):
        browser.open("file:///etc/passwd")


def test_notes_and_log(browser, site, zhome):
    browser.open(site + "/shop.html")
    browser.note("каталог в /catalog, корзина вверху")
    out = browser.open(site + "/news.html")
    assert "каталог в /catalog" in out
    logs = list((zhome / "log").glob("*.jsonl"))
    assert logs and '"action": "open"' in logs[0].read_text(encoding="utf-8")


def test_dialog_dismissed(browser, site):
    browser.open(site + "/shop.html")
    browser.page.evaluate("setTimeout(() => confirm('Удалить всё?'), 0)")
    res = browser.wait(seconds=0.5)
    assert "dismissed" in res and "Удалить всё?" in res


# -- found on real sites (2026-10-29 test run) -----------------------------------

def test_inline_links_stay_in_sentence(browser, site):
    out = browser.open(site + "/wiki.html")
    assert "склоне [Среднего Урала](#" in out and "](#" in out
    assert 'link "Среднего Урала"' not in out  # not split into its own line
    res = browser.click(int(re.search(r"\[Исеть\]\(#(\d+)\)", out).group(1)))
    assert "navigated" in res


def test_read_keeps_link_words(browser, site):
    browser.open(site + "/wiki.html")
    out = browser.read()
    assert "на восточном склоне Среднего Урала, на реке Исеть, и является" in out
    assert "](#" not in out


def test_long_menu_folded_but_searchable(browser, site):
    out = browser.open(site + "/wiki.html")
    assert "(+48 more links, find(text) to search them)" in out
    assert "Город 55" not in out
    assert "Город 55" in browser.find("Город 55")


def test_link_heading_one_line_and_no_repeated_alt(browser, site):
    out = browser.open(site + "/blog.html")
    assert "## [Как выбрать скважинный насос](#" in out
    assert 'link "Как выбрать скважинный насос"' not in out
    assert '[img "Как выбрать скважинный насос"]' not in out


def test_bot_check_reported_and_observed(browser, site, zhome):
    from zorko.observe import load

    out = browser.open(site + "/botcheck.html")
    assert "bot check" in out and "does not bypass" in out
    assert any(r["kind"] == "blocked" for r in load())
