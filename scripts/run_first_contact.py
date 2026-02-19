"""
Automated run-through of the First Contact mission.
Connects via WebSocket, simulates all four crew actions,
and reports mission progress to stdout.

Objective sequence:
  1. Patrol to (30000, 20000), r=5000
  2. Scan enemy_1 (scout at 70000, 32000)
  3. Destroy all hostile contacts
  4. Return to (50000, 50000), r=8000
"""

import asyncio
import json
import math
import time
import urllib.request

import websockets

URI = "ws://localhost:8666/ws"
BASE = "http://localhost:8666"
TICK = 0.1   # seconds between polls


def http_post(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def build(msg_type: str, payload: dict) -> str:
    return json.dumps({"type": msg_type, "payload": payload, "timestamp": time.time()})


def distance(x1, y1, x2, y2):
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def bearing_to(x1, y1, x2, y2):
    """Same formula as server math_helpers.bearing_to."""
    return math.degrees(math.atan2(x2 - x1, y1 - y2)) % 360


async def run():
    print("Starting First Contact mission …")
    result = http_post("/debug/start_game?mission_id=first_contact")
    print(f"  Server: {result}")

    print("Connecting to Starbridge WebSocket …")
    async with websockets.connect(URI) as ws:

        # ── join lobby ────────────────────────────────────────────────────
        await ws.send(build("lobby.claim_role", {"role": "helm", "player_name": "AutoPilot"}))

        # State tracked from incoming messages
        ship_x, ship_y = 50000.0, 50000.0
        ship_heading = 0.0
        ship_hull = 100.0
        enemies: dict = {}          # id → {x, y, hull, ai_state, …}
        objectives: list = []
        game_over = False
        game_started = False
        scanned: set = set()
        beams_fired_count = 0
        last_print = ""

        def log(msg):
            nonlocal last_print
            if msg != last_print:
                print(msg)
                last_print = msg

        async def send_heading(h):
            await ws.send(build("helm.set_heading", {"heading": round(h, 1)}))

        async def send_throttle(t):
            await ws.send(build("helm.set_throttle", {"throttle": t}))

        # Background receiver task
        msg_queue: asyncio.Queue = asyncio.Queue()

        async def receiver():
            async for raw in ws:
                await msg_queue.put(raw)

        recv_task = asyncio.create_task(receiver())

        async def drain(timeout=0.15):
            """Drain pending messages from the queue, update shared state."""
            nonlocal ship_x, ship_y, ship_heading, ship_hull
            nonlocal game_over, game_started, beams_fired_count
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(msg_queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                t = msg.get("type", "")
                p = msg.get("payload", {})

                if t == "ship.state":
                    pos = p.get("position", {})
                    ship_x = pos.get("x", ship_x)
                    ship_y = pos.get("y", ship_y)
                    ship_heading = p.get("heading", ship_heading)
                    ship_hull = p.get("hull", ship_hull)

                elif t == "world.entities":
                    # world.entities has key "enemies" — full unfiltered list
                    current_ids = {e["id"] for e in p.get("enemies", [])}
                    for e in p.get("enemies", []):
                        enemies[e["id"]] = e
                    for dead_id in [k for k in list(enemies) if k not in current_ids]:
                        log(f"  ✓ {dead_id} gone (destroyed or fled)")
                        del enemies[dead_id]

                elif t == "weapons.beam_fired":
                    beams_fired_count += 1

                elif t == "science.scan_complete":
                    eid = p.get("entity_id", "")
                    scanned.add(eid)
                    log(f"  ✓ Scan complete: {eid} — type={p.get('entity_type', p.get('results', {}).get('type', '?'))}")

                elif t == "mission.objective_update":
                    for obj in p.get("objectives", []):
                        if obj.get("status") == "complete":
                            log(f"  ★ Objective COMPLETE: {obj['text']}")
                    objectives[:] = p.get("objectives", [])

                elif t == "game.over":
                    result = p.get("result", "?")
                    stats = p.get("stats", {})
                    dur = stats.get("duration_s", 0)
                    hull = stats.get("hull_remaining", 0)
                    print(f"\n{'═'*50}")
                    print(f"  GAME OVER — {result.upper()}")
                    print(f"  Duration : {int(dur//60)}:{int(dur%60):02d}")
                    print(f"  Hull     : {hull:.0f}%")
                    print(f"{'═'*50}\n")
                    game_over = True

                elif t == "game.started":
                    game_started = True
                    log(f"  ► Mission: {p.get('mission_name')} — {p.get('briefing_text')}")

        # ── wait for game loop to be live ─────────────────────────────────
        print("Waiting for game loop …")
        for _ in range(80):
            await drain(0.1)
            if game_started or enemies:
                break

        await asyncio.sleep(0.3)
        await drain()

        print(f"\nShip position: ({ship_x:.0f}, {ship_y:.0f})")
        print(f"Hull: {ship_hull:.0f}%")
        print(f"Enemies spawned: {list(enemies.keys())}\n")

        if game_over:
            recv_task.cancel()
            return

        # ═══════════════════════════════════════════════════════════════════
        # OBJECTIVE 1 — Patrol to waypoint Alpha (30000, 20000), r=5000
        # ═══════════════════════════════════════════════════════════════════
        print("── OBJECTIVE 1: Patrol to waypoint Alpha ──")
        target_x, target_y = 30000, 20000
        brg = bearing_to(ship_x, ship_y, target_x, target_y)
        await send_heading(brg)
        await send_throttle(100)

        while not game_over:
            await drain(TICK)
            d = distance(ship_x, ship_y, target_x, target_y)
            brg = bearing_to(ship_x, ship_y, target_x, target_y)
            await send_heading(brg)
            log(f"  pos=({ship_x:.0f},{ship_y:.0f})  heading={ship_heading:.1f}°  dist={d:.0f}  hull={ship_hull:.0f}")
            if d <= 5000:
                log("  ✓ Waypoint Alpha reached!")
                await send_throttle(0)
                break

        if game_over:
            recv_task.cancel()
            return

        await asyncio.sleep(1.0)
        await drain()

        # ═══════════════════════════════════════════════════════════════════
        # OBJECTIVE 2 — Scan the hostile scout (enemy_1)
        # enemy_1 is at (70000, 32000); from (30000, 20000) dist ≈ 41231 — too far
        # Drive to approach point (50000, 26000) — ~20880 from scout
        # ═══════════════════════════════════════════════════════════════════
        print("\n── OBJECTIVE 2: Scan the hostile scout (enemy_1) ──")

        approach_x, approach_y = 50000, 26000
        d_to_scout = distance(ship_x, ship_y, 70000, 32000)
        if d_to_scout > 28000:
            log(f"  Scout at dist={d_to_scout:.0f}, driving to approach point …")
            brg = bearing_to(ship_x, ship_y, approach_x, approach_y)
            await send_heading(brg)
            await send_throttle(100)
            while not game_over:
                await drain(TICK)
                d = distance(ship_x, ship_y, approach_x, approach_y)
                brg = bearing_to(ship_x, ship_y, approach_x, approach_y)
                await send_heading(brg)
                log(f"  pos=({ship_x:.0f},{ship_y:.0f})  dist_to_approach={d:.0f}")
                if d <= 3000:
                    await send_throttle(0)
                    log("  ✓ Approach position reached")
                    break

        if game_over:
            recv_task.cancel()
            return

        await asyncio.sleep(0.5)
        await drain()

        # Initiate scan on enemy_1
        log("  Initiating scan on enemy_1 …")
        await ws.send(build("science.start_scan", {"entity_id": "enemy_1"}))
        scan_start = asyncio.get_event_loop().time()

        while "enemy_1" not in scanned and not game_over:
            await drain(TICK)
            elapsed = asyncio.get_event_loop().time() - scan_start
            log(f"  Scanning … ({elapsed:.1f}s)")
            if elapsed > 15:
                log("  ! Scan timeout — proceeding anyway")
                break

        if game_over:
            recv_task.cancel()
            return

        await asyncio.sleep(0.3)
        await drain()

        # ═══════════════════════════════════════════════════════════════════
        # OBJECTIVE 3 — Destroy all hostile contacts
        # Chase the nearest living enemy, fire beams (range ≤ 8000, ±45° arc)
        # and torpedoes (range 20000, velocity 500). Scout flees below 30% hull
        # but despawns when 30000 away — mission engine counts that as destroyed.
        # Cruiser is slower (150 u/s vs player 200 u/s) — can always catch it.
        # ═══════════════════════════════════════════════════════════════════
        print("\n── OBJECTIVE 3: Destroy all hostile contacts ──")
        print(f"  Enemies at start: {list(enemies.keys())}")

        tube_idx = 1
        combat_start = asyncio.get_event_loop().time()
        COMBAT_TIMEOUT_S = 600   # 10-minute safety cap
        tick_counter = 0
        last_enemy_count = len(enemies)

        while enemies and not game_over:
            await drain(TICK)
            tick_counter += 1

            if not enemies:
                break

            # Target the nearest living enemy
            nearest = min(
                enemies.values(),
                key=lambda e: distance(ship_x, ship_y, e["x"], e["y"])
            )
            eid = nearest["id"]
            ex, ey = nearest["x"], nearest["y"]
            d = distance(ship_x, ship_y, ex, ey)
            hull = nearest.get("hull", 0)
            ai_state = nearest.get("ai_state", "?")

            # Report when enemy count changes
            if len(enemies) != last_enemy_count:
                last_enemy_count = len(enemies)
                print(f"  Enemies remaining: {list(enemies.keys())}")

            # Log every second (10 ticks)
            if tick_counter % 10 == 0:
                elapsed = asyncio.get_event_loop().time() - combat_start
                print(f"  t={elapsed:.0f}s  [{eid}] hull={hull:.0f}  dist={d:.0f}  state={ai_state}  beams={beams_fired_count}  ship_hull={ship_hull:.0f}")

            # Point heading at nearest enemy
            brg = bearing_to(ship_x, ship_y, ex, ey)
            await send_heading(brg)

            # Throttle: chase until within 5000, back off below 2000
            if d > 5000:
                await send_throttle(100)
            elif d < 2000:
                await send_throttle(0)
            # else hold current

            # Fire weapons (server enforces range / cooldown)
            await ws.send(build("weapons.select_target", {"entity_id": eid}))
            await ws.send(build("weapons.fire_beams", {}))
            await ws.send(build("weapons.fire_torpedo", {"tube": tube_idx}))
            tube_idx = 2 if tube_idx == 1 else 1

            # Safety timeout
            if asyncio.get_event_loop().time() - combat_start > COMBAT_TIMEOUT_S:
                print("  ! Combat timeout — moving on")
                break

        await send_throttle(0)
        print(f"  Combat phase done (enemies remaining: {list(enemies.keys())})")

        # Wait for mission engine to register all_enemies_destroyed and
        # send mission.objective_update, then game.over after obj4 completes.
        await asyncio.sleep(2.0)
        await drain(1.0)

        if game_over:
            recv_task.cancel()
            return

        # ═══════════════════════════════════════════════════════════════════
        # OBJECTIVE 4 — Return to sector origin (50000, 50000), r=8000
        # ═══════════════════════════════════════════════════════════════════
        print("\n── OBJECTIVE 4: Return to sector origin ──")
        target_x, target_y = 50000, 50000
        brg = bearing_to(ship_x, ship_y, target_x, target_y)
        await send_heading(brg)
        await send_throttle(100)

        while not game_over:
            await drain(TICK)
            d = distance(ship_x, ship_y, target_x, target_y)
            brg = bearing_to(ship_x, ship_y, target_x, target_y)
            await send_heading(brg)
            log(f"  pos=({ship_x:.0f},{ship_y:.0f})  dist_to_origin={d:.0f}")
            if d <= 8000:
                log("  ✓ Returned to sector origin!")
                await send_throttle(0)
                break

        # Wait for game.over
        for _ in range(50):
            await drain(0.2)
            if game_over:
                break

        if not game_over:
            print("  (game.over not received — mission may require more time)")
            for _ in range(50):
                await drain(0.2)
                if game_over:
                    break

        recv_task.cancel()
        print("Run complete.")


if __name__ == "__main__":
    asyncio.run(run())
