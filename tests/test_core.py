"""洗衣房的测试：假天气、假钟点、假的「他睡没睡」。跑法：python tests/test_core.py（或 pytest）"""

import datetime as dt
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from laundry_line import config as C          # noqa: E402
from laundry_line.core import LaundryRoom     # noqa: E402
from laundry_line.weather import Weather      # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))


def at(h, m=0, day=21):
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ).timestamp()


class FakeHooks:
    def __init__(self, sleeping=False, webhook=True):
        self.asleep, self.hook, self.sent = sleeping, webhook, []

    def sleeping(self):
        return self.asleep

    def has_webhook(self):
        return self.hook

    def rain(self, text):
        self.sent.append(text)
        return True


def room(patch=None, seed=1, **hk):
    cfg = C.override(C.load(None), {"home": {"timezone": "Asia/Shanghai", "pet": "团子"},
                                    "weather": {"provider": "manual", "stale_hours": 100},
                                    "mishaps": {"p": 0}, "sorting": {"bleed_p": 0, "delicate_wash_p": 0, "delicate_dry_p": 0},
                                    **(patch or {})})
    w = Weather(cfg)
    w.set("晴", 15, 50, 10, at=0)
    r = LaundryRoom(cfg, tempfile.mkdtemp(prefix="ll-test-"), w, FakeHooks(**hk), rng=random.Random(seed))
    return r, w


def ticks(r, t0, t1):
    t = t0
    while t <= t1:
        r.tick(now=t)
        t += 300


def test_sunny_dries_in_a_few_hours():
    r, w = room()
    w.set("晴", 15, 50, 20, at=0)
    t = at(10)
    r.run("put", "床单、枕套、T恤", now=t)
    r.run("wash", now=t + 60)
    assert "晾起来了" in r.run("hang", now=t + 50 * 60)
    ticks(r, t + 55 * 60, t + 4 * 3600)
    assert "收下来了" in r.run("fold", now=t + 4 * 3600)


def test_night_still_damp_by_morning():
    r, w = room()
    w.set("晴", 8, 70, 3, at=0)
    t = at(21)
    r.run("put", "床单、被套", now=t)
    r.run("wash", now=t + 60)
    assert "明天" in r.run("hang", now=t + 50 * 60)
    ticks(r, t + 55 * 60, at(7, 0, day=22))
    assert "没有干了的" in r.run("fold", now=at(7, 1, day=22))


def test_rain_awake_webhook_then_bring_in():
    r, w = room()
    t = at(13)
    r.run("put", "毯子、T恤", now=t); r.run("wash", now=t + 60); r.run("hang", now=t + 50 * 60)
    w.set("小雨", 15, 80, 5, at=0)
    assert r.tick(now=t + 75 * 60).startswith("rain → webhook ok")
    assert len(r.hooks.sent) == 1
    assert r.notice(now=t + 76 * 60) == ""                       # 已经听见过了
    assert "正淋着雨" in r.run("look", now=t + 80 * 60)
    assert "收进屋" in r.run("hang", now=t + 90 * 60)
    assert "脏" not in r.run("look", now=t + 3 * 3600)


def test_rain_asleep_gets_dirty_and_back_to_basket():
    r, w = room(sleeping=True)
    t = at(14)
    r.run("put", "床单、枕套", now=t); r.run("wash", now=t + 60); r.run("hang", now=t + 50 * 60)
    w.set("中雨", 15, 90, 5, at=0)
    ticks(r, t + 60 * 60, t + 100 * 60)
    assert r.hooks.sent == [] and r.notice(now=t + 101 * 60) == ""
    assert r.state_data(now=t + 102 * 60)["loads"][0]["dirty"]
    assert "扔回洗衣篮" in r.run("fold", now=t + 2 * 3600)
    assert "床单" in r.run("look", now=t + 2 * 3600 + 60).splitlines()[0]


def test_rain_without_webhook_goes_to_notice_once():
    r, w = room(webhook=False)
    t = at(15)
    r.run("put", "T恤", now=t); r.run("wash", now=t + 60); r.run("hang", now=t + 50 * 60)
    w.set("阵雨", 15, 80, 5, at=0)
    assert r.tick(now=t + 60 * 60) == "ticked"
    assert r.notice(now=t + 61 * 60) == r.cfg["rain"]["hear_text"]
    assert r.notice(now=t + 62 * 60) == ""


def test_bleed_tints_the_light_one():
    r, w = room({"sorting": {"bleed_p": 1.0}})
    t = at(10)
    r.run("put", "我的黑T恤、她的白T恤", now=t)
    r.run("wash", now=t + 60)
    assert "染上一层淡淡的灰" in r.run("hang", now=t + 50 * 60)
    assert r.state_data(now=t + 51 * 60)["loads"][0]["tint"] == [{"n": "她的白T恤", "c": "grey"}]


def test_never_dry_leaves_a_scar():
    r, w = room({"rules": {"never_dry": ["睡衣"]}})
    t = at(11)
    r.run("put", "黑睡衣", now=t)
    r.run("wash", "", "轻柔", now=t + 60)
    assert "天好" in r.run("dry", now=t + 45 * 60)
    assert "穿不上了" in r.run("fold", now=t + 100 * 60)
    assert "长记性" in r.run("look", now=t + 101 * 60)


def test_handwash_four_steps():
    r, w = room({"rules": {"handwash_only": ["内裤"]}})
    t = at(10)
    r.run("put", "内裤、内裤、床单", now=t)
    assert "泡上了：内裤、内裤" in r.run("handwash", now=t + 60)
    assert "还在泡" in r.run("handwash", now=t + 3 * 60)
    assert r.run("handwash", now=t + 12 * 60).startswith("搓")
    assert r.run("handwash", now=t + 16 * 60).startswith("冲")
    assert r.run("handwash", now=t + 20 * 60).startswith("拧")
    assert "晾起来了：内裤、内裤" in r.run("hang", now=t + 21 * 60)
    assert "走冷水" in r.run("wash", now=t + 22 * 60)


def test_bed_set_is_remembered():
    r, w = room({"bed_sets": [{"name": "小猫", "keywords": ["小猫"], "cover": "#fff", "sheet": "#9b9", "pattern": "cats"}]})
    t = at(10)
    r.run("put", "小猫床单、小猫被套", now=t); r.run("wash", now=t + 60); r.run("dry", now=t + 50 * 60)
    assert "现在床上铺的是小猫那套" in r.run("fold", now=t + 2 * 3600)
    assert "床单（小猫那套）" in r.run("put", "床单", now=t + 3 * 3600)


def test_basket_cap_big_counts_two():
    r, w = room()
    t = at(10)
    r.run("put", "床单 被套 毯子", now=t)
    out = r.run("put", "枕套 枕套 浴巾 袜子", now=t + 60)
    assert "10/10" in out and "袜子塞不进去" in out


def test_no_pet_no_pet_lines():
    r, w = room({"home": {"pet": ""}}, seed=7)
    t = at(10)
    for k in range(30):
        tt = t + k * 4 * 3600
        out = r.run("put", "毯子", now=tt) + r.run("wash", now=tt + 60) + r.run("dry", now=tt + 50 * 60) + r.run("fold", now=tt + 2 * 3600)
        assert "团子" not in out and "趴在" not in out


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("✓", name)
    print(f"{n} 个都过了")
