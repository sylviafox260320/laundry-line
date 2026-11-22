"""小服务：一个 MCP 接口给小机用，几个网页接口给晾衣绳小组件和演示页用，再加一个每隔几分钟自己走一次的钟。

  /mcp                    MCP（streamable http）：工具 laundry(action, items, mode)
  /api/state              晾衣绳小组件取数据：外面晾着的几缸、洗衣篮、画绳子要的样子
  /api/notice             你家系统递话给他之前调一下：刚下起雨、他醒着 → {"text": 雨声}，否则 {"text": ""}
  /widget/laundry-line.js 晾衣绳 + 满篮子小组件
  /demo …                 只在 `laundry-line demo` 时有：快进钟演示页
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hmac
import json
import os
import random
import threading
import time
from importlib import resources

from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response

from .core import LaundryRoom
from .hooks import Hooks
from .weather import Weather

TOOL_DOC = """家里的洗衣房：洗衣篮、洗衣机、手洗盆、烘干机、晾衣服的地方。时间按真的走，东西不会自己挪，也没人提醒你。屋里的规矩看 rules。
action：look 看一眼（默认）｜rules 屋里的规矩｜put 收进洗衣篮，items 写收了什么，顿号隔开（「床单、枕套、白T恤」）｜wash 洗：items 不写＝篮子里全洗，写了只洗那几件；mode 写「轻柔」走轻柔档｜handwash 手洗：泡、搓、冲、拧，一步调一次，泡要等十分钟｜hang 晾：天气好晾外面、不好晾屋里，mode 写「屋里」就晾屋里；下雨了再 hang 一次把外面的收进屋｜dry 放进烘干机｜fold 收下来叠好放回去。
深浅混洗会串色，娇气的（睡衣、丝的、毛衣）走轻柔档、别进烘干机。闷久了有味，下雨不收会淋脏。"""


class Clock:
    """演示用的快进钟：真实时间 + 拨快的秒数。正常跑时 offset 一直是 0。"""

    def __init__(self, offset: float = 0.0):
        self.offset = offset

    def now(self) -> float:
        return time.time() + self.offset


def _web(name: str) -> bytes:
    return resources.files("laundry_line").joinpath("web", name).read_bytes()


class _TokenGate:
    """设了 [server] token 就要带：Authorization: Bearer <token> 或 ?token=<token>（/widget 和 /demo 不拦）。"""

    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not self.token:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not (path.startswith("/api/") or path == "/mcp" or path.startswith("/mcp/")):
            return await self.app(scope, receive, send)
        if scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        given = headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not given:
            from urllib.parse import parse_qs
            given = (parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token") or [""])[0]
        if given and hmac.compare_digest(given, self.token):
            return await self.app(scope, receive, send)
        resp = JSONResponse({"error": "unauthorized"}, status_code=401)
        await resp(scope, receive, send)


def build(cfg: dict, data_dir: str, demo: bool = False, clock: Clock | None = None, weather: Weather | None = None,
          rng: random.Random | None = None):
    clock = clock or Clock()
    weather = weather or Weather(cfg)
    hooks = Hooks(cfg)
    room = LaundryRoom(cfg, data_dir, weather, hooks, rng=rng)
    srv = cfg["server"]
    mcp = FastMCP("laundry-line", host=srv["host"], port=int(srv["port"]))

    async def laundry(action: str = "look", items: str = "", mode: str = "") -> str:
        return await asyncio.to_thread(room.run, action, items, mode, clock.now())

    laundry.__doc__ = TOOL_DOC
    mcp.add_tool(laundry, name="laundry", description=TOOL_DOC)

    @mcp.custom_route("/", methods=["GET"])
    async def index(request):
        links = ['<a href="/demo">演示页</a>'] if demo else []
        return HTMLResponse("<meta charset=utf-8><title>晾衣绳 laundry-line</title>"
                            "<p>🧺 晾衣绳 laundry-line 在跑。MCP：<code>/mcp</code>　数据：<code>/api/state</code>　"
                            "小组件：<code>/widget/laundry-line.js</code>　" + "　".join(links) + "</p>")

    @mcp.custom_route("/api/state", methods=["GET"])
    async def api_state(request):
        return JSONResponse(await asyncio.to_thread(room.state_data, clock.now()))

    @mcp.custom_route("/api/notice", methods=["GET"])
    async def api_notice(request):
        return JSONResponse({"text": await asyncio.to_thread(room.notice, clock.now())})

    @mcp.custom_route("/widget/laundry-line.js", methods=["GET"])
    async def widget(request):
        return Response(_web("laundry-line.js"), media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})

    if demo:
        @mcp.custom_route("/demo", methods=["GET"])
        async def demo_page(request):
            return HTMLResponse(_web("demo.html").decode("utf-8"))

        def _clock_info():
            now = clock.now()
            d = _dt.datetime.fromtimestamp(now, room.tz)
            return {"now": now, "label": f"{d.month}月{d.day}日 {d:%H:%M}", "weather": weather.current(now)}

        @mcp.custom_route("/demo/clock", methods=["GET"])
        async def demo_clock(request):
            return JSONResponse(_clock_info())

        @mcp.custom_route("/demo/run", methods=["POST"])
        async def demo_run(request):
            b = await request.json()
            out = await asyncio.to_thread(room.run, b.get("action", "look"), b.get("items", ""), b.get("mode", ""), clock.now())
            return JSONResponse({"out": out, **_clock_info()})

        @mcp.custom_route("/demo/advance", methods=["POST"])
        async def demo_advance(request):
            b = await request.json()
            minutes = max(1, min(int(b.get("minutes", 60)), 48 * 60))
            step = int(cfg["server"].get("tick_minutes", 5)) * 60
            notes = []
            for _ in range(0, minutes * 60, step):          # 快进时照样每 5 分钟走一次钟
                clock.offset += step
                r = await asyncio.to_thread(room.tick, clock.now())
                if r.startswith("rain"):
                    notes.append("（他听见了雨：" + cfg["rain"]["hear_text"] + "）")
            hear = await asyncio.to_thread(room.notice, clock.now())
            if hear:
                notes.append("（他听见了雨：" + hear + "）")
            return JSONResponse({"out": "\n".join(notes), **_clock_info()})

        @mcp.custom_route("/demo/weather", methods=["POST"])
        async def demo_weather(request):
            b = await request.json()
            weather.set(b.get("sky", "晴"), b.get("temp", 15), b.get("rh", 50), b.get("wind", 10), at=clock.now())
            r = await asyncio.to_thread(room.tick, clock.now())
            hear = await asyncio.to_thread(room.notice, clock.now())     # 演示里当他下一回合就来了
            out = ("（他听见了雨：" + (hear or cfg["rain"]["hear_text"]) + "）") if (hear or r.startswith("rain")) else ""
            return JSONResponse({"out": out, **_clock_info()})

        @mcp.custom_route("/demo/reset", methods=["POST"])
        async def demo_reset(request):
            for f in ("state.json", "log.jsonl"):
                try:
                    os.remove(os.path.join(data_dir, f))
                except FileNotFoundError:
                    pass
            room.set_bed(cfg.get("demo_bed") or None)
            return JSONResponse({"out": "洗衣房清空了。", **_clock_info()})

    app = mcp.streamable_http_app()
    app.add_middleware(CORSMiddleware, allow_origins=list(srv.get("cors_origins") or ["*"]),
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])
    if srv.get("token"):
        app.add_middleware(_TokenGate, token=srv["token"])
    return app, room, clock, weather


def start_ticker(room: LaundryRoom, clock: Clock, minutes: float):
    """后台每隔 minutes 分钟 tick 一次（往前晾、看天、下雨叫人）。"""
    def loop():
        while True:
            time.sleep(max(30, minutes * 60))
            try:
                r = room.tick(clock.now())
                if r.startswith("rain"):
                    print(time.strftime("%F %T"), r, flush=True)
            except Exception as e:      # 钟不能停
                print("tick 出错：", e, flush=True)
    t = threading.Thread(target=loop, daemon=True, name="laundry-tick")
    t.start()
    return t
