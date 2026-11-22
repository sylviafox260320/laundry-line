"""天气：晾干快慢、下没下雨都看这个。

三种来源（设置里 [weather] provider）：
  open-meteo  按 [home] 经纬度去 Open-Meteo 取现在的天气（免费、不用注册），缓存 cache_minutes 分钟
  file        读一个 JSON 文件（你家已经有天气数据时用），字段：
              {"fetched_ts": 秒, "sky": "晴", "temp": 15, "rh": 50, "wind": 10, "rain": false}
              （rain 可省，sky 里带 雨/雪/雷 就算下雨）
  manual      演示 / 测试用：程序里直接 set()

拿到的都整理成 {"sky", "temp", "rh", "wind", "rain"}；拿不到或太旧 → None。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

RAINY = re.compile(r"雨|雪|雹|雷|霰")

# WMO 天气代码 → 中文（Open-Meteo 用的就是这套）
WMO = {0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾",
       51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻雨", 57: "冻雨",
       61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
       71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
       80: "阵雨", 81: "阵雨", 82: "暴雨", 85: "阵雪", 86: "阵雪",
       95: "雷雨", 96: "雷雨", 99: "雷雨"}


def _norm(sky, temp, rh, wind, rain=None):
    sky = str(sky or "")
    return {"sky": sky, "temp": temp, "rh": 60.0 if rh is None else rh, "wind": wind or 0.0,
            "rain": bool(rain) if rain is not None else bool(RAINY.search(sky))}


class Weather:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        w = cfg.get("weather", {})
        self.provider = w.get("provider", "open-meteo")
        self.cache_s = float(w.get("cache_minutes", 15)) * 60
        self.stale_s = float(w.get("stale_hours", 3)) * 3600
        self._cache = None          # (取到的时间, dict)
        self._manual = None
        self._lock = threading.Lock()

    # 演示 / 测试
    def set(self, sky="晴", temp=15, rh=50, wind=10, rain=None, at=None):
        self._manual = (at if at is not None else time.time(), _norm(sky, temp, rh, wind, rain))

    def current(self, now: float | None = None):
        now = time.time() if now is None else now
        if self.provider == "manual":           # 演示 / 测试：手动设的天气不过期
            return dict(self._manual[1]) if self._manual else None
        if self.provider == "file":
            return self._from_file(now)
        return self._from_open_meteo(now)

    def _from_file(self, now):
        try:
            with open(self.cfg["weather"]["file"], encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return None
        if now - float(d.get("fetched_ts") or 0) > self.stale_s:
            return None
        return _norm(d.get("sky"), d.get("temp"), d.get("rh"), d.get("wind"), d.get("rain"))

    def _from_open_meteo(self, now):
        with self._lock:
            if self._cache and time.time() - self._cache[0] < self.cache_s:
                return dict(self._cache[1])
            h = self.cfg["home"]
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
                   "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,precipitation"
                   "&wind_speed_unit=kmh" % (h["latitude"], h["longitude"]))
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "laundry-line"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    cur = json.load(r).get("current") or {}
            except Exception:
                # 取不到：上次的还不算太旧就接着用
                if self._cache and time.time() - self._cache[0] < self.stale_s:
                    return dict(self._cache[1])
                return None
            code = cur.get("weather_code")
            w = _norm(WMO.get(code, ""), cur.get("temperature_2m"), cur.get("relative_humidity_2m"),
                      cur.get("wind_speed_10m"), (cur.get("precipitation") or 0) > 0 or bool(RAINY.search(WMO.get(code, ""))))
            self._cache = (time.time(), w)
            return dict(w)
