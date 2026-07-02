import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from aiohttp import WSMsgType, web
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServer, WebSocketServerProtocol, serve


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
HTTP_PORT = 8765
MINECRAFT_WS_PORT = 8766
LOGO_CANDIDATES = ("logo.png", "logo.webp", "logo.jpg", "logo.jpeg", "logo.svg")


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file(BASE_DIR / ".env")


def clean_token(value: str) -> str:
    cleaned = re.sub(r'[^0-9A-Za-z_\-]', "", value)
    return cleaned or value.strip()


def normalize_pit_action(value: str) -> str:
    lowered = value.strip().lower()
    if "out" in lowered or "exit" in lowered or "leave" in lowered:
        return "out"
    if "in" in lowered or "enter" in lowered or "entry" in lowered:
        return "in"
    return clean_token(lowered)


@dataclass
class DriverState:
    player: str
    lap: int = 0
    lap_time_ms: int | None = None
    best_lap_ms: int | None = None
    total_time_ms: int | None = None
    last_crossing_ms: int | None = None
    last_event_source: str = "unknown"
    position: int = 0
    gap_to_leader_ms: int | None = None
    interval_ahead_ms: int | None = None
    in_pit: bool = False
    status: str = "RUN"


@dataclass
class Notice:
    category: str
    title: str
    message: str
    created_at_ms: int
    accent: str = "neutral"


@dataclass
class RaceState:
    title: str = os.getenv("MCWEC_TITLE", "MCWEC Live Timing")
    session: str = os.getenv("MCWEC_SESSION", "RACE")
    track_name: str = os.getenv("MCWEC_TRACK_NAME", "Minecraft Circuit")
    total_laps: int = int(os.getenv("MCWEC_TOTAL_LAPS", "20"))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    total_events: int = 0
    drivers: dict[str, DriverState] = field(default_factory=dict)
    flag_state: str = "green"
    flag_label: str = "GREEN FLAG"
    flag_message: str = "Track clear"
    flag_changed_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    notices: list[Notice] = field(default_factory=list)
    final_lap_announced: bool = False

    def upsert_event(self, event: dict[str, Any]) -> dict[str, Any]:
        player = str(event["player"]).strip()
        lap = int(event["lap"])
        crossing_ms = int(event.get("crossing_time_ms") or int(time.time() * 1000))
        lap_time_ms = event.get("lap_time_ms")
        total_time_ms = event.get("total_time_ms")
        source = str(event.get("source", "manual"))

        if lap_time_ms is not None:
            lap_time_ms = int(lap_time_ms)
        if total_time_ms is not None:
            total_time_ms = int(total_time_ms)

        driver = self.drivers.get(player, DriverState(player=player))

        previous_lap = driver.lap
        previous_total = driver.total_time_ms

        if lap < previous_lap:
            return {
                "accepted": False,
                "reason": "lap regressed",
                "player": player,
                "current_lap": previous_lap,
            }

        if lap == previous_lap and driver.last_crossing_ms and crossing_ms <= driver.last_crossing_ms:
            return {
                "accepted": False,
                "reason": "stale event",
                "player": player,
                "current_lap": previous_lap,
            }

        driver.lap = lap
        driver.lap_time_ms = lap_time_ms
        driver.last_crossing_ms = crossing_ms
        driver.last_event_source = source

        if total_time_ms is None:
            if previous_total is not None and lap_time_ms is not None and lap == previous_lap + 1:
                total_time_ms = previous_total + lap_time_ms
            elif lap_time_ms is not None and lap <= 1:
                total_time_ms = lap_time_ms

        driver.total_time_ms = total_time_ms

        if lap_time_ms is not None:
            if driver.best_lap_ms is None or lap_time_ms < driver.best_lap_ms:
                driver.best_lap_ms = lap_time_ms

        self.drivers[player] = driver
        self.total_events += 1
        self.updated_at_ms = int(time.time() * 1000)
        self._recalculate_positions()
        self._maybe_announce_final_lap()
        return {"accepted": True, "player": player, "lap": lap}

    def apply_control_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("type", "")).strip().lower()
        self.updated_at_ms = int(time.time() * 1000)

        if event_type == "flag":
            flag = str(event.get("flag", "green")).strip().lower()
            title, accent = self._resolve_flag(flag)
            message = str(event.get("message") or self._default_flag_message(flag))
            self.flag_state = flag
            self.flag_label = title
            self.flag_message = message
            self.flag_changed_at_ms = int(time.time() * 1000)
            self.total_events += 1
            return {"accepted": True, "type": "flag", "flag": flag}

        if event_type == "pit":
            player = clean_token(str(event["player"]))
            driver = self.drivers.get(player, DriverState(player=player))
            action = normalize_pit_action(str(event.get("action", "in")))
            if action in {"in", "enter", "entry"}:
                driver.in_pit = True
                driver.status = "PIT"
            elif action in {"out", "exit", "leave"}:
                driver.in_pit = False
                driver.status = "RUN"
            else:
                return {"accepted": False, "reason": "unknown pit action", "player": player}

            self.drivers[player] = driver
            self.total_events += 1
            self._recalculate_positions()
            return {"accepted": True, "type": "pit", "player": player, "action": action}

        if event_type == "notice":
            title = str(event.get("title", "RACE CONTROL")).strip()
            message = str(event.get("message", "")).strip()
            accent = str(event.get("accent", "neutral")).strip().lower()
            self.total_events += 1
            self._append_notice(category="notice", title=title, message=message, accent=accent)
            return {"accepted": True, "type": "notice"}

        return {"accepted": False, "reason": "unknown control event type"}

    def reset(self) -> None:
        self.updated_at_ms = int(time.time() * 1000)
        self.total_events = 0
        self.drivers.clear()
        self.flag_state = "green"
        self.flag_label = "GREEN FLAG"
        self.flag_message = "Track clear"
        self.flag_changed_at_ms = int(time.time() * 1000)
        self.notices.clear()
        self.final_lap_announced = False

    def snapshot(self) -> dict[str, Any]:
        ordered = self._ordered_drivers()
        leader_lap = ordered[0].lap if ordered else 0
        remaining_laps = max(self.total_laps - leader_lap, 0) if self.total_laps > 0 else None
        final_lap_active = remaining_laps == 1 if remaining_laps is not None else False
        global_best = min(
            (driver.best_lap_ms for driver in ordered if driver.best_lap_ms is not None),
            default=None,
        )
        global_best_holder = next(
            (driver.player for driver in ordered if driver.best_lap_ms is not None and driver.best_lap_ms == global_best),
            None,
        )
        return {
            "title": self.title,
            "session": self.session,
            "track_name": self.track_name,
            "total_laps": self.total_laps,
            "leader_lap": leader_lap,
            "remaining_laps": remaining_laps,
            "final_lap_active": final_lap_active,
            "updated_at_ms": self.updated_at_ms,
            "total_events": self.total_events,
            "leader": ordered[0].player if ordered else None,
            "flag_state": self.flag_state,
            "flag_label": self.flag_label,
            "flag_message": self.flag_message,
            "flag_changed_at_ms": self.flag_changed_at_ms,
            "global_best_lap_ms": global_best,
            "global_best_holder": global_best_holder,
            "notices": [asdict(notice) for notice in self.notices],
            "drivers": [asdict(driver) for driver in ordered],
        }

    def _ordered_drivers(self) -> list[DriverState]:
        return sorted(
            self.drivers.values(),
            key=lambda driver: (
                -driver.lap,
                driver.total_time_ms if driver.total_time_ms is not None else float("inf"),
                driver.last_crossing_ms if driver.last_crossing_ms is not None else float("inf"),
                driver.player.lower(),
            ),
        )

    def _recalculate_positions(self) -> None:
        ordered = self._ordered_drivers()
        if not ordered:
            return

        leader = ordered[0]
        prev = None
        for idx, driver in enumerate(ordered, start=1):
            driver.position = idx

            if idx == 1:
                driver.gap_to_leader_ms = 0
                driver.interval_ahead_ms = 0
            else:
                driver.gap_to_leader_ms = self._calculate_gap(leader, driver)
                driver.interval_ahead_ms = self._calculate_gap(prev, driver)
            prev = driver

    def _append_notice(self, category: str, title: str, message: str, accent: str = "neutral") -> None:
        self.notices.insert(
            0,
            Notice(
                category=category,
                title=title,
                message=message,
                created_at_ms=int(time.time() * 1000),
                accent=accent,
            ),
        )
        del self.notices[6:]

    def _maybe_announce_final_lap(self) -> None:
        if self.total_laps <= 0:
            return
        ordered = self._ordered_drivers()
        if not ordered:
            return
        remaining_laps = max(self.total_laps - ordered[0].lap, 0)
        if remaining_laps == 1 and not self.final_lap_announced:
            self.final_lap_announced = True

    @staticmethod
    def _calculate_gap(front: DriverState | None, back: DriverState) -> int | None:
        if front is None:
            return None
        if front.lap != back.lap:
            return None
        if front.total_time_ms is None or back.total_time_ms is None:
            return None
        return max(0, back.total_time_ms - front.total_time_ms)

    @staticmethod
    def _resolve_flag(flag: str) -> tuple[str, str]:
        mapping = {
            "green": ("GREEN FLAG", "green"),
            "yellow": ("YELLOW FLAG", "yellow"),
            "red": ("RED FLAG", "red"),
            "sc": ("SAFETY CAR", "yellow"),
            "safety_car": ("SAFETY CAR", "yellow"),
            "vsc": ("VIRTUAL SAFETY CAR", "yellow"),
            "virtual_safety_car": ("VIRTUAL SAFETY CAR", "yellow"),
        }
        return mapping.get(flag, ("RACE CONTROL", "neutral"))

    @staticmethod
    def _default_flag_message(flag: str) -> str:
        mapping = {
            "green": "Track clear",
            "yellow": "Incident on track, no overtaking",
            "red": "Session stopped",
            "sc": "Safety car deployed",
            "safety_car": "Safety car deployed",
            "vsc": "Virtual safety car deployed",
            "virtual_safety_car": "Virtual safety car deployed",
        }
        return mapping.get(flag, "Race control message")


class HUDServer:
    def __init__(self) -> None:
        self.state = RaceState()
        self.browser_clients: set[web.WebSocketResponse] = set()
        self.minecraft_clients: set[WebSocketServerProtocol] = set()
        self.minecraft_ws_server: WebSocketServer | None = None
        self.logger = logging.getLogger("mcwec.hud")

    async def handle_index(self, request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def handle_static(self, request: web.Request) -> web.FileResponse:
        filename = request.match_info["filename"]
        return web.FileResponse(STATIC_DIR / filename)

    async def handle_state(self, request: web.Request) -> web.Response:
        return web.json_response(self.build_snapshot())

    async def handle_event(self, request: web.Request) -> web.Response:
        payload = await request.json()
        event_type = str(payload.get("type", "lap")).strip().lower()
        if event_type in {"lap", ""}:
            result = self.state.upsert_event(payload)
        else:
            result = self.state.apply_control_event(payload)
        if result["accepted"]:
            await self.broadcast_state()
        return web.json_response({"result": result, "state": self.build_snapshot()})

    async def handle_reset(self, request: web.Request) -> web.Response:
        self.state.reset()
        await self.broadcast_state()
        return web.json_response({"ok": True, "state": self.build_snapshot()})

    async def handle_command(self, request: web.Request) -> web.Response:
        payload = await request.json()
        command = str(payload["command"]).strip()
        sent = await self.send_minecraft_command(command)
        return web.json_response({"ok": sent, "command": command})

    async def hud_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.browser_clients.add(ws)
        await ws.send_json({"type": "state", "payload": self.build_snapshot()})

        async for msg in ws:
            if msg.type == WSMsgType.TEXT and msg.data == "ping":
                await ws.send_str("pong")
            elif msg.type == WSMsgType.ERROR:
                self.logger.warning("HUD websocket error: %s", ws.exception())

        self.browser_clients.discard(ws)
        return ws

    async def handle_minecraft_message(self, raw_text: str) -> None:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            self.logger.debug("Ignored non-JSON minecraft message: %s", raw_text)
            return

        header = payload.get("header", {})
        body = payload.get("body", {})
        purpose = header.get("messagePurpose") or payload.get("eventName")
        event_name = header.get("eventName") or body.get("eventName")
        sender = self._guess_sender(body)
        hud_messages = self._extract_hud_messages(body)

        if purpose == "commandResponse" and hud_messages:
            self.logger.info("HUD command response captured: %s", hud_messages)

        if hud_messages:
            accepted_any = False
            for message in hud_messages:
                parsed = self.parse_hud_chat(message, sender)
                if not parsed:
                    continue
                event_type = str(parsed.get("type", "lap")).strip().lower()
                if event_type in {"lap", ""}:
                    result = self.state.upsert_event(parsed)
                else:
                    result = self.state.apply_control_event(parsed)
                self.logger.info("HUD event from minecraft (%s): %s", event_name or purpose, result)
                accepted_any = accepted_any or bool(result.get("accepted"))
            if accepted_any:
                await self.broadcast_state()
            return

        if purpose == "commandResponse":
            self.logger.info("Command response: %s", body)
            return

        self.logger.debug("Unhandled minecraft payload: %s", payload)

    def parse_hud_chat(self, message: str, sender: str) -> dict[str, Any] | None:
        content = message.removeprefix("[HUD]").strip()
        if not content:
            return None

        if content.startswith("{"):
            parsed = json.loads(content)
        else:
            normalized = self._normalize_hud_text(content)
            parsed = self._parse_key_value_text(normalized)

        parsed.setdefault("player", parsed.get("driver") or sender)
        parsed.setdefault("source", "minecraft")
        return parsed

    async def subscribe_minecraft_event(self, ws: WebSocketServerProtocol, event_name: str) -> None:
        message = {
            "header": {
                "version": 1,
                "requestId": str(uuid.uuid4()),
                "messagePurpose": "subscribe",
                "messageType": "commandRequest",
            },
            "body": {"eventName": event_name},
        }
        await ws.send(json.dumps(message))

    async def send_minecraft_command(self, command: str) -> bool:
        if not self.minecraft_clients:
            return False

        message = {
            "header": {
                "version": 1,
                "requestId": str(uuid.uuid4()),
                "messagePurpose": "commandRequest",
                "messageType": "commandRequest",
            },
            "body": {
                "version": 1,
                "commandLine": command,
                "origin": {"type": "player"},
            },
        }

        stale_clients = []
        for client in self.minecraft_clients:
            try:
                await client.send(json.dumps(message))
            except ConnectionClosed:
                stale_clients.append(client)

        for client in stale_clients:
            self.minecraft_clients.discard(client)

        return bool(self.minecraft_clients)

    async def minecraft_ws_handler(self, websocket: WebSocketServerProtocol, path: str) -> None:
        self.minecraft_clients.add(websocket)
        remote = getattr(websocket, "remote_address", None)
        self.logger.info("Minecraft client connected: %s path=%s", remote, path)

        try:
            await self.subscribe_minecraft_event(websocket, "PlayerMessage")
            await self.subscribe_minecraft_event(websocket, "CommandOutput")
            async for message in websocket:
                if isinstance(message, str):
                    await self.handle_minecraft_message(message)
                else:
                    self.logger.debug("Ignored binary minecraft message: %s bytes", len(message))
        except ConnectionClosed as exc:
            self.logger.info("Minecraft client disconnected: code=%s reason=%s", exc.code, exc.reason)
        except Exception:
            self.logger.exception("Unhandled minecraft websocket error")
        finally:
            self.minecraft_clients.discard(websocket)

    async def start_minecraft_server(self) -> None:
        self.minecraft_ws_server = await serve(
            self.minecraft_ws_handler,
            host="0.0.0.0",
            port=MINECRAFT_WS_PORT,
            ping_interval=None,
            ping_timeout=None,
            max_size=None,
        )
        self.logger.info("Minecraft websocket server listening on ws://0.0.0.0:%s", MINECRAFT_WS_PORT)

    async def stop_minecraft_server(self) -> None:
        if self.minecraft_ws_server is None:
            return
        self.minecraft_ws_server.close()
        await self.minecraft_ws_server.wait_closed()
        self.minecraft_ws_server = None

    async def broadcast_state(self) -> None:
        snapshot = {"type": "state", "payload": self.build_snapshot()}
        stale_clients = []
        for client in self.browser_clients:
            try:
                await client.send_json(snapshot)
            except ConnectionResetError:
                stale_clients.append(client)

        for client in stale_clients:
            self.browser_clients.discard(client)

    def build_snapshot(self) -> dict[str, Any]:
        snapshot = self.state.snapshot()
        snapshot["logo_url"] = self._resolve_logo_url()
        return snapshot

    def _resolve_logo_url(self) -> str | None:
        for candidate in LOGO_CANDIDATES:
            if (STATIC_DIR / candidate).exists():
                return f"/static/{candidate}"
        return None

    def _extract_hud_messages(self, value: Any) -> list[str]:
        messages: list[str] = []
        for text in self._walk_text_values(value):
            if "[HUD]" in text:
                start = text.index("[HUD]")
                messages.append(text[start:].strip())
        return messages

    def _walk_text_values(self, value: Any) -> Iterable[str]:
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from self._walk_text_values(item)
            return
        if isinstance(value, list):
            for item in value:
                yield from self._walk_text_values(item)

    def _guess_sender(self, body: dict[str, Any]) -> str:
        properties = body.get("properties", {})
        return (
            body.get("sender")
            or properties.get("Sender")
            or properties.get("sender")
            or body.get("player")
            or "minecraft"
        )

    def _normalize_hud_text(self, content: str) -> str:
        normalized = content
        normalized = re.sub(r'"\},\{"text":"', "", normalized)
        normalized = re.sub(r'"\},\{"selector":"[^"]+"\},\{"text":"', " ", normalized)
        normalized = normalized.replace('{"text":"', "")
        normalized = normalized.replace('"}', "")
        normalized = normalized.replace('\\"', '"')
        normalized = normalized.strip()
        return normalized

    def _parse_key_value_text(self, content: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        matches = list(re.finditer(r"(\w+)=", content))

        for idx, match in enumerate(matches):
            key = match.group(1).strip()
            value_start = match.end()
            value_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            value = content[value_start:value_end].strip()
            parsed[key] = value

        return parsed



def create_app() -> web.Application:
    server = HUDServer()
    app = web.Application()
    app["hud_server"] = server
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", server.handle_index)
    app.router.add_get("/api/state", server.handle_state)
    app.router.add_post("/api/event", server.handle_event)
    app.router.add_post("/api/reset", server.handle_reset)
    app.router.add_post("/api/command", server.handle_command)
    app.router.add_get("/ws/hud", server.hud_ws)
    app.router.add_get("/static/{filename}", server.handle_static)
    return app


async def on_startup(app: web.Application) -> None:
    server: HUDServer = app["hud_server"]
    await server.start_minecraft_server()


async def on_cleanup(app: web.Application) -> None:
    server: HUDServer = app["hud_server"]
    await server.stop_minecraft_server()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=HTTP_PORT)


if __name__ == "__main__":
    main()
