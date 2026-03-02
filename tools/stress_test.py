#!/usr/bin/env python3
"""
Starbridge stress test — v0.04i

Simulates 12 simultaneous WebSocket clients playing a full game session and
measures server performance.

Usage:
    python tools/stress_test.py [--url WS_URL] [--duration SECONDS] [--report]

Options:
    --url       WebSocket URL  (default: ws://localhost:8000/ws)
    --duration  Test duration in seconds  (default: 60)
    --report    Print detailed report at end  (default: True)

Requires: websockets>=11.0  (pip install websockets)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time as _time
from dataclasses import dataclass, field
from typing import Any

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print(
        "ERROR: 'websockets' package not found. Install with: pip install websockets",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import psutil  # optional — for memory/CPU tracking
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# ---------------------------------------------------------------------------
# Client role definitions + message patterns
# ---------------------------------------------------------------------------

ROLES = [
    "captain", "helm", "weapons", "engineering",
    "science", "medical", "security", "comms",
    "flight_ops", "electronic_warfare", "operations", "damage_control",
]

ROLE_CALLSIGNS = {r: f"Bot_{r[:4].upper()}" for r in ROLES}

# (message_type, payload_fn, send_interval_s)
# payload_fn receives no args, returns dict
_ROLE_MESSAGES: dict[str, list[tuple[str, Any, float]]] = {
    "helm": [
        ("helm.set_heading", lambda: {"heading": random.uniform(0, 360)}, 3.0),
        ("helm.set_throttle", lambda: {"throttle": random.uniform(0.2, 0.8)}, 5.0),
    ],
    "engineering": [
        ("engineering.set_power", lambda: {
            "system": random.choice(["engines", "beams", "shields"]),
            "level": random.uniform(40, 100),
        }, 4.0),
    ],
    "weapons": [
        ("weapons.fire_beams", lambda: {"beam_frequency": random.choice(["alpha", "beta"])}, 6.0),
    ],
    "science": [
        ("science.start_scan", lambda: {"entity_id": "signal", "scan_mode": "em"}, 10.0),
    ],
    "captain": [],
    "medical": [],
    "security": [],
    "comms": [
        ("comms.tune_frequency", lambda: {"frequency": random.uniform(0, 1)}, 8.0),
    ],
    "flight_ops": [],
    "electronic_warfare": [],
    "operations": [],
    "damage_control": [],
}

# ---------------------------------------------------------------------------
# Per-client stats
# ---------------------------------------------------------------------------


@dataclass
class ClientStats:
    role: str
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    connect_time_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Single simulated client
# ---------------------------------------------------------------------------


async def run_client(
    url: str,
    role: str,
    duration: float,
    stats: ClientStats,
    start_event: asyncio.Event,
    stop_event: asyncio.Event,
    is_host: bool = False,
    mission_id: str = "sandbox",
) -> None:
    """Simulate one player connected to Starbridge."""
    callsign = ROLE_CALLSIGNS[role]
    connect_start = _time.monotonic()

    try:
        async with websockets.connect(url, ping_interval=20) as ws:
            stats.connect_time_ms = (_time.monotonic() - connect_start) * 1000

            # Wait for welcome
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(raw)
            if data.get("type") != "lobby.welcome":
                stats.errors += 1
                return

            is_host_actual = data.get("payload", {}).get("is_host", False)

            # Claim role
            await ws.send(json.dumps({
                "type": "lobby.claim_role",
                "payload": {"role": role, "player_name": callsign, "additional": False},
            }))
            stats.messages_sent += 1

            # Host starts game after all clients have signalled ready
            if is_host_actual:
                await asyncio.sleep(1.5)  # wait for other clients to connect
                await ws.send(json.dumps({
                    "type": "lobby.start_game",
                    "payload": {
                        "mission_id": mission_id,
                        "difficulty": "officer",
                        "ship_class": "frigate",
                    },
                }))
                stats.messages_sent += 1

            # Wait for game.started
            game_started = False
            deadline = _time.monotonic() + 10.0
            while _time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    stats.messages_received += 1
                    data = json.loads(raw)
                    if data.get("type") == "game.started":
                        game_started = True
                        break
                except asyncio.TimeoutError:
                    continue

            if not game_started:
                stats.errors += 1
                return

            # Signal that game is live
            start_event.set()

            # --- Main message loop ---
            patterns = _ROLE_MESSAGES.get(role, [])
            _next_send: dict[int, float] = {i: _time.monotonic() + p[2] for i, p in enumerate(patterns)}
            recv_task = asyncio.create_task(_receive_loop(ws, stats, stop_event))

            end_time = _time.monotonic() + duration
            while _time.monotonic() < end_time and not stop_event.is_set():
                now = _time.monotonic()
                for i, (msg_type, payload_fn, interval) in enumerate(patterns):
                    if now >= _next_send.get(i, 0):
                        t_send = _time.monotonic()
                        try:
                            await ws.send(json.dumps({
                                "type": msg_type,
                                "payload": payload_fn(),
                                "_sent_at": t_send,
                            }))
                            stats.messages_sent += 1
                        except ConnectionClosed:
                            break
                        _next_send[i] = now + interval

                await asyncio.sleep(0.1)

            recv_task.cancel()
            try:
                await recv_task
            except asyncio.CancelledError:
                pass

    except ConnectionClosed as exc:
        stats.errors += 1
    except Exception as exc:
        stats.errors += 1


async def _receive_loop(
    ws: websockets.WebSocketClientProtocol,
    stats: ClientStats,
    stop_event: asyncio.Event,
) -> None:
    """Drain incoming messages and record receipt counts."""
    while not stop_event.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            stats.messages_received += 1
            try:
                data = json.loads(raw)
                # Measure latency if server echoes _sent_at (it doesn't by default —
                # but we can approximate by comparing game tick timestamps).
                if data.get("type") == "game.over":
                    stop_event.set()
            except json.JSONDecodeError:
                pass
        except asyncio.TimeoutError:
            continue
        except ConnectionClosed:
            break
        except Exception:
            break


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_stress_test(
    url: str,
    duration: float,
    mission_id: str = "sandbox",
) -> list[ClientStats]:
    """Launch all clients concurrently and collect stats."""
    all_stats = [ClientStats(role=r) for r in ROLES]
    start_event = asyncio.Event()
    stop_event  = asyncio.Event()

    tasks = []
    for i, (role, stats) in enumerate(zip(ROLES, all_stats)):
        is_host = (i == 0)
        task = asyncio.create_task(
            run_client(
                url=url,
                role=role,
                duration=duration,
                stats=stats,
                start_event=start_event,
                stop_event=stop_event,
                is_host=is_host,
                mission_id=mission_id,
            ),
            name=f"client-{role}",
        )
        tasks.append(task)
        # Stagger connections slightly to avoid thundering herd
        await asyncio.sleep(0.1)

    # Wait for game to start (or timeout)
    try:
        await asyncio.wait_for(start_event.wait(), timeout=15.0)
        print(f"  Game started — running for {duration}s…", flush=True)
    except asyncio.TimeoutError:
        print("  WARNING: game did not start within 15s — server may not be running.")
        stop_event.set()

    # Wait for all tasks
    await asyncio.gather(*tasks, return_exceptions=True)
    return all_stats


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(
    all_stats: list[ClientStats],
    duration: float,
    wall_time: float,
    start_mem_mb: float,
    end_mem_mb: float,
) -> None:
    total_sent     = sum(s.messages_sent     for s in all_stats)
    total_received = sum(s.messages_received for s in all_stats)
    total_errors   = sum(s.errors           for s in all_stats)
    avg_connect    = statistics.mean(s.connect_time_ms for s in all_stats)

    print()
    print("=" * 60)
    print("  STARBRIDGE STRESS TEST REPORT")
    print("=" * 60)
    print(f"  Duration:          {duration}s planned / {wall_time:.1f}s actual")
    print(f"  Clients:           {len(all_stats)}")
    print(f"  Messages sent:     {total_sent}")
    print(f"  Messages received: {total_received}")
    print(f"  Errors:            {total_errors}")
    print(f"  Avg connect time:  {avg_connect:.0f} ms")
    if _PSUTIL:
        mem_growth = end_mem_mb - start_mem_mb
        print(f"  Memory start:      {start_mem_mb:.1f} MB")
        print(f"  Memory end:        {end_mem_mb:.1f} MB")
        print(f"  Memory growth:     {mem_growth:+.1f} MB")
    print()
    print(f"  {'ROLE':<20} {'SENT':>6} {'RECV':>6} {'ERR':>4} {'CONNECT':>8}")
    print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*4} {'-'*8}")
    for s in all_stats:
        print(f"  {s.role:<20} {s.messages_sent:>6} {s.messages_received:>6} "
              f"{s.errors:>4} {s.connect_time_ms:>7.0f}ms")
    print()

    # Performance assessment
    recv_per_s = total_received / max(wall_time, 1)
    print("  PERFORMANCE ASSESSMENT")
    print(f"  Recv throughput:   {recv_per_s:.0f} msg/s")
    if total_errors == 0:
        print("  Connections:       ✓ ALL STABLE")
    else:
        print(f"  Connections:       ✗ {total_errors} ERRORS")
    if _PSUTIL and end_mem_mb < 500:
        print(f"  Memory:            ✓ < 500 MB")
    elif _PSUTIL:
        print(f"  Memory:            ✗ > 500 MB (check for leaks)")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Starbridge stress test")
    parser.add_argument("--url",      default="ws://localhost:8000/ws", help="WebSocket URL")
    parser.add_argument("--duration", default=60, type=float, help="Test duration in seconds")
    parser.add_argument("--mission",  default="sandbox", help="Mission ID")
    args = parser.parse_args()

    print(f"Starbridge Stress Test — {args.duration}s, {len(ROLES)} clients")
    print(f"Connecting to: {args.url}")
    print()

    # Memory baseline (if psutil available)
    start_mem_mb = 0.0
    end_mem_mb   = 0.0
    if _PSUTIL:
        import os
        proc = psutil.Process(os.getpid())
        start_mem_mb = proc.memory_info().rss / 1_048_576

    t0 = _time.monotonic()
    all_stats = asyncio.run(run_stress_test(
        url=args.url,
        duration=args.duration,
        mission_id=args.mission,
    ))
    wall_time = _time.monotonic() - t0

    if _PSUTIL:
        end_mem_mb = proc.memory_info().rss / 1_048_576

    print_report(all_stats, args.duration, wall_time, start_mem_mb, end_mem_mb)


if __name__ == "__main__":
    main()
