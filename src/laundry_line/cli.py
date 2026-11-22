"""命令行：
  laundry-line init                 在当前目录写一份 laundry-line.toml（照着改）
  laundry-line serve [-c 文件] [--data 目录]   开洗衣房
  laundry-line demo [--port 8791]   开一间临时洗衣房 + 快进钟演示页（不碰你自己的数据）
  laundry-line tick  [-c 文件] [--data 目录]   走一次钟（serve 自己会走，一般用不着）
  laundry-line bed <哪套>           告诉它床上现在铺的是哪套
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import tempfile

from . import config as C


def _room(args):
    from .core import LaundryRoom
    from .hooks import Hooks
    from .weather import Weather
    cfg = C.load(args.config)
    return LaundryRoom(cfg, args.data, Weather(cfg), Hooks(cfg))


def cmd_init(args):
    if os.path.exists(C.USER_NAME) and not args.force:
        print(f"{C.USER_NAME} 已经有了（要覆盖加 --force）")
        return 1
    with open(C.USER_NAME, "w", encoding="utf-8") as f:
        f.write(C.default_text())
    print(f"写好了 {C.USER_NAME}：改住哪儿、有没有猫、几套四件套、屋里的规矩，然后 laundry-line serve")
    return 0


def cmd_serve(args):
    import uvicorn
    from .server import build, start_ticker
    cfg = C.load(args.config)
    if args.port:
        cfg["server"]["port"] = args.port
    app, room, clock, _ = build(cfg, args.data)
    start_ticker(room, clock, float(cfg["server"].get("tick_minutes", 5)))
    print(f"🧺 晾衣绳开张：http://{cfg['server']['host']}:{cfg['server']['port']}  （MCP 在 /mcp，数据在 {os.path.abspath(args.data)}）")
    uvicorn.run(app, host=cfg["server"]["host"], port=int(cfg["server"]["port"]), log_level="warning")
    return 0


DEMO = {
    "home": {"pet": "团子"},
    "weather": {"provider": "manual"},
    "rules": {"text": "屋里的规矩（演示用）：\n· 床单被套过冷水。\n· 天好就晾出来，烘干机留给下雨天、阴潮天。\n· 睡衣不进烘干机。\n· 内裤手洗。",
              "never_dry": ["睡衣", "睡裙"], "handwash_only": ["内裤"]},
    "bed_sets": [
        {"name": "小猫", "keywords": ["小猫", "猫"], "cover": "#F6F1E4", "sheet": "#A9BEA4", "pattern": "cats"},
        {"name": "小狗", "keywords": ["小狗", "狗"], "cover": "#F7F2EA", "sheet": "#A58C7C", "pattern": "dogs"},
    ],
    "blanket": {"color": "#F3C3CE", "pattern": "kitty"},
    "demo_bed": "小猫",
}


def cmd_demo(args):
    import uvicorn
    from .server import Clock, build
    cfg = C.override(C.load(None) if args.config is None else C.load(args.config), DEMO)
    cfg["server"]["port"] = args.port
    cfg["server"]["token"] = ""
    data = tempfile.mkdtemp(prefix="laundry-line-demo-")
    # 快进钟从今天上午十点开始
    now = _dt.datetime.now()
    clock = Clock(_dt.datetime(now.year, now.month, now.day, 10, 0).timestamp() - now.timestamp())
    app, room, clock, weather = build(cfg, data, demo=True, clock=clock)
    weather.set("晴", 16, 50, 12, at=clock.now())
    room.set_bed("小猫")
    print(f"🧺 演示洗衣房：http://127.0.0.1:{args.port}/demo  （临时目录 {data}，关掉就没了）")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_tick(args):
    print(_room(args).tick())
    return 0


def cmd_bed(args):
    _room(args).set_bed(args.name)
    print(f"记下了：床上现在铺的是{args.name}那套")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="laundry-line", description="晾衣绳：给你的小机一间洗衣房")
    sub = p.add_subparsers(dest="cmd")
    for name in ("serve", "tick", "bed"):
        sp = sub.add_parser(name)
        sp.add_argument("-c", "--config", default=None, help="设置文件（默认当前目录的 laundry-line.toml）")
        sp.add_argument("--data", default="data", help="洗衣房的状态存在哪个目录（默认 ./data）")
        if name == "serve":
            sp.add_argument("--port", type=int, default=None)
        if name == "bed":
            sp.add_argument("name")
    si = sub.add_parser("init")
    si.add_argument("--force", action="store_true")
    sd = sub.add_parser("demo")
    sd.add_argument("--port", type=int, default=8791)
    sd.add_argument("-c", "--config", default=None)
    args = p.parse_args(argv)
    fn = {"init": cmd_init, "serve": cmd_serve, "demo": cmd_demo, "tick": cmd_tick, "bed": cmd_bed}.get(args.cmd)
    if not fn:
        p.print_help()
        return 0
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
