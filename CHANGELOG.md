# Changelog

## 0.1.1 (2026-10-29)

From the first test run on real sites (Wikipedia, Habr, GitHub, Python docs, Gismeteo, Avito, Ozon):

- Links inside sentences stay in the text as `[text](#id)` instead of breaking paragraphs into separate lines. On Wikipedia this was most of the map.
- `read()` keeps the words of links, so sentences are whole, and long paragraphs are no longer cut.
- Long menus (for example navigation tables with 60+ links) show 12 links and a note; `find()` still searches all of them.
- A heading that is a link (news and blog lists) is one line, and an image whose caption repeats the heading is dropped.
- Bot-check and rate-limit pages are recognized and reported as such instead of being shown as content. Zorko still does not bypass them.

## 0.1.0 (2026-10-29)

First release.

- Compact page map with stable element numbers, menus folded, card links merged, tracking parameters stripped, long pages in parts.
- Actions return only what changed on the page.
- Shadow DOM, iframes and JavaScript-rendered pages.
- Prompt-injection guard (hidden text excluded and reported, Russian and English patterns).
- `!confirm` on pay, send, delete and publish; no passwords or card numbers; `zorko login` for sign-in.
- Private network blocked, robots.txt respected, action log, per-site notes.
- Self-improvement with explicit consent: `zorko consent` (off, local, share); nothing recorded until the user answers. Local journal, `zorko report`, `feedback` tool, and `zorko share` that shows the whole report and opens it as a GitHub issue draft for the user to submit.
- MCP server for Claude Code without extra dependencies; `look`, `read`, `bench`, `config` commands.
