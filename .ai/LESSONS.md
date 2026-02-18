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

## 2026-02-18 — TestClient WebSocket message counting requires careful tracing

**Issue**: Integration tests with multiple WebSocket clients need careful accounting of which broadcasts arrive on which connection. Easy to off-by-one the `receive_json()` calls.
**Cause**: `on_connect` sends a welcome to the new client then broadcasts `lobby.state` to ALL connected clients. In a two-client test, the first client gets an extra `lobby.state` when the second client connects.
**Fix**: Trace the message sequence per-client before writing receive calls. Only consume what a given client actually receives.
**Prevention**: Add a comment per `receive_json()` call explaining which server event produced it. Leave unread messages on older clients if you're only testing the newer client's responses.
