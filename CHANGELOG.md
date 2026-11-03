# Changelog

## 0.1.2 (2026-11-03)

Monthly self-improvement for October 2026. Data: the owner's local journal (25 pages, 10 sites, consent `local`), `zorko bench` on `benchmarks/sites.txt`, and a check of the commands on Windows. No user reports came in this month. Comes after 0.1.1 (PR #1).

- Picture links get names. Wikipedia file links have an empty or missing `alt`, so they were nameless (`unnamed`: 11 times on ru/en Wikipedia and Habr, up to 21 links on one page). An empty `alt` no longer stops the search for a name (a logo's named wordmark after an empty icon is found), an svg icon is named by its `<title>`, and a picture link with nothing else is named from its address: `image Old town square`. Hashes and ids are not used as names.
- Gismeteo (`weak_map` twice): the map held twice the page text, but the check counted only lines outside links, and on card-style pages most content is inside links. `weak_map` now counts link and button names too. The real weak spot was elsewhere: the current weather came as a column of one-word lines (`+9`, `Ветер`, `5`, `м/с`). Consecutive short fragments are now glued into one line, and the glued line is checked for prompt injection again, so a phrase split across fragments is still caught.
- `zorko consent` with no answer no longer crashes. On Windows `< nul` counts as a terminal, so the question was asked and the empty input ended in a traceback; now nothing changes and Zorko says how to choose later. The question is printed by Zorko itself, so the Russian part is no longer garbled on the Windows console.

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
