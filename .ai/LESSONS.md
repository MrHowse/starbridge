# Lessons Learned

> **APPEND-ONLY** — Add new lessons at the bottom. Never modify or remove existing entries.
> Record anything that went wrong, caused confusion, or wasted time so future sessions avoid repeating it.

---

## Template

Copy this template when adding a new entry:

```
## [Date] — [Brief title]

**Issue**: What went wrong
**Cause**: Why it happened
**Fix**: How it was resolved
**Prevention**: How to avoid this in future sessions
```

---

## 2026-02-18 — Pyright false positive on field_validator import

**Issue**: Pyright reported `field_validator` as "not accessed" even though it was used as a decorator (`@field_validator("player_name")`).
**Cause**: Pyright's analysis of decorator-factory usage can miss the reference in some configurations, especially with `from __future__ import annotations` in scope.
**Fix**: The code was functionally correct and all tests passed. Treated as a known false positive and proceeded.
**Prevention**: If this recurs, try suppressing with `# type: ignore[reportUnusedImport]` on the import line, or restructure to use `model_validator` instead if it avoids the issue.

---

## 2026-02-18 — Late-join clients miss one-shot broadcasts

**Issue**: Station pages (helm, captain, etc.) load fresh after the lobby redirect, opening a new WebSocket. By the time they connect, `game.started` has already been broadcast and will never be sent again — the station stays on its standby screen indefinitely.
**Cause**: One-shot broadcast pattern: `game.started` fires once when the host launches. Any client connecting afterward never receives it.
**Fix**: Store the `game.started` payload in `lobby._game_payload`. In `on_connect()`, if the game is already running, send `game.started` directly to the new connection and return early (skipping `lobby.state`).
**Prevention**: Any one-shot server→client message that must reach future joiners needs a stored copy. Pattern: store payload at broadcast time, re-send to every new connect when game is active.

---

## 2026-02-18 — Wrong station page due to role confusion in the lobby redirect

**Issue**: User claimed the Captain role and was redirected to `/client/captain/` — a placeholder page with no content. They expected to see the Helm station. Debugging consumed multiple rounds.
**Cause**: `lobby.js` calls `redirectToStation(myRole)` on `game.started`. `myRole` is determined by matching the callsign input against the server's role list. If the user claims Captain, they go to the Captain page, not Helm.
**Fix**: No code fix needed in the redirect logic. Fixed by:
  1. Adding "← RETURN TO LOBBY" link to all placeholder station pages
  2. Changing standby text to "This station is not yet operational" for unimplemented stations
**Prevention**: Make placeholder pages clearly distinct from working stations. All placeholder standby screens must have a lobby return link. Test the full role-claim → redirect flow explicitly, not just the helm-specific path.

---

## 2026-02-18 — TestClient WebSocket message counting requires careful tracing

**Issue**: Integration tests with multiple WebSocket clients need careful accounting of which broadcasts arrive on which connection. Easy to off-by-one the `receive_json()` calls.
**Cause**: `on_connect` sends a welcome to the new client then broadcasts `lobby.state` to ALL connected clients. In a two-client test, the first client gets an extra `lobby.state` when the second client connects.
**Fix**: Trace the message sequence per-client before writing receive calls. Only consume what a given client actually receives.
**Prevention**: Add a comment per `receive_json()` call explaining which server event produced it. Leave unread messages on older clients if you're only testing the newer client's responses.
