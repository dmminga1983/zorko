# Changelog

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
