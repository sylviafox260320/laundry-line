"""跟你家小机的系统接线（都可选）：
  · 他睡没睡：睡着了下雨不叫他（[companion] sleeping_url / sleeping_file + sleeping_key）
  · 下雨那一下叫他：[rain] webhook 设了就 POST 过去；没设就留着，等你的系统来 GET /api/notice 取
"""

from __future__ import annotations

import json
import urllib.request


def _dig(d, key: str):
    for k in key.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


class Hooks:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def sleeping(self) -> bool:
        c = self.cfg.get("companion", {})
        key = c.get("sleeping_key") or "sleeping"
        try:
            if c.get("sleeping_url"):
                with urllib.request.urlopen(c["sleeping_url"], timeout=5) as r:
                    return bool(_dig(json.load(r), key))
            if c.get("sleeping_file"):
                with open(c["sleeping_file"], encoding="utf-8") as f:
                    return bool(_dig(json.load(f), key))
        except Exception:
            return False
        return False

    def has_webhook(self) -> bool:
        return bool(self.cfg.get("rain", {}).get("webhook"))

    def rain(self, text: str) -> bool:
        url = self.cfg.get("rain", {}).get("webhook")
        if not url:
            return False
        try:
            req = urllib.request.Request(url, data=json.dumps({"event": "rain", "text": text}, ensure_ascii=False).encode("utf-8"),
                                         method="POST", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
            return True
        except Exception:
            return False
