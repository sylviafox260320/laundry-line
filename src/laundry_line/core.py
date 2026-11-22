"""洗衣房本体：洗衣篮 → 洗衣机 / 手洗盆 → 晾（天好晾外面＝你聊天页上那根绳子 / 屋里晾衣架）或烘干机 → 叠好收回去。

时间按真的走，东西不会自己挪，也没人提醒他——一按就好的活儿不算活儿。
  · 晾干跟真天气走：tick() 每隔几分钟按当时的天、风、湿度、气温往前晾一点；夜里晾出去到早上还潮
  · 不提醒：洗好、烘好、晾干、淋脏都不说。只留下雨：下起来那会儿外面挂着东西、他醒着 → 让他听见雨
  · 下雨后 grace_min 分钟内不收进屋＝淋脏了，得重洗
  · 分缸：深浅混洗会串色；娇气的进标准档、进烘干机会出事；never_dry 进了烘干机＝大事故，一直记着
  · 手洗盆：泡、搓、冲、拧，一步一调
  · 小意外：开洗那一刻就定，不改结果，只多一句画面
  · 家里有猫：它会来捣乱

状态存在 data_dir/state.json，流水 data_dir/log.jsonl。所有动作都能传 now（演示的快进钟、测试用）。
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import random
import re
import time

OUTDOOR = "外面"
INDOOR = "屋里的晾衣架"
BED = re.compile(r"床单|被套|枕套|床笠|枕巾|床罩")

# 小意外：stage out＝从洗衣机拿出来时发现；fold＝叠的时候才发现。need：这缸里得有的东西，{x} 换成对上的那件
MISHAPS = [
    {"id": "tissue", "stage": "out", "text": "一开门，满滚筒白色纸屑——哪个口袋里忘了掏纸巾，挨件抖了一遍。"},
    {"id": "hairtie", "stage": "out", "text": "滚筒缝里卡着一根发圈，抠出来了。"},
    {"id": "coin", "stage": "out", "text": "拿衣服时叮当一声，滚筒里滚出来一枚硬币。"},
    {"id": "walk", "stage": "out", "text": "洗衣机甩干时咣当咣当，自己往前挪了半步，推回去了。"},
    {"id": "twist", "stage": "out", "need": r"床单", "min": 2, "text": "{x}拧成了一根大麻花，别的小件全卷在里面，抖了半天才抖开。"},
    {"id": "duvet", "stage": "out", "need": r"被套", "min": 2, "text": "{x}把别的小件全吞了进去，伸手进去掏了好一会儿。"},
    {"id": "sock_lost", "stage": "fold", "need": r"袜", "text": "配对的时候少了一只袜子，翻遍了也没找着。"},
    {"id": "sock_extra", "stage": "fold", "need": r"袜", "text": "叠到最后，袜子堆里多出一只没见过的。"},
    {"id": "shrink", "stage": "fold", "need": r"T恤|卫衣|衬衫", "text": "{x}好像缩了一点点，比原来短了一截。"},
    {"id": "fade", "stage": "fold", "need": r"T恤|衬衫|卫衣|裙|牛仔|裤|衣", "text": "{x}洗得有点褪色了，颜色比原来浅了一层。"},
    {"id": "old_sock", "stage": "fold", "need": r"被套|床单|被子|毯", "text": "抖{x}的时候掉出来一只早就找不到的袜子。"},
]

ACTIONS = ("look", "rules", "put", "wash", "handwash", "hang", "dry", "fold")


def _re(words):
    words = [re.escape(w) for w in (words or []) if w]
    return re.compile("|".join(words)) if words else re.compile(r"(?!x)x")


class _Locked:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        os.makedirs(self.d, exist_ok=True)
        self.f = open(os.path.join(self.d, ".lock"), "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


class LaundryRoom:
    def __init__(self, cfg: dict, data_dir: str, weather, hooks, rng: random.Random | None = None):
        self.cfg = cfg
        self.dir = data_dir
        self.weather = weather
        self.hooks = hooks
        self.rng = rng or random.Random()
        self.STATE = os.path.join(data_dir, "state.json")
        self.LOG = os.path.join(data_dir, "log.jsonl")
        c = cfg
        self.big = _re(c["basket"]["big"])
        self.dark = _re(c["sorting"]["dark"])
        self.light = _re(c["sorting"]["light"])
        self.delicate = _re(c["sorting"]["delicate"])
        self.never_dry = _re(c["rules"].get("never_dry"))
        self.handwash_only = _re(c["rules"].get("handwash_only"))
        self.cold_water = _re(c["rules"].get("cold_water"))
        self.sets = [(s["name"], _re(s.get("keywords") or [s["name"]])) for s in c.get("bed_sets", [])]
        self.pet = (c["home"].get("pet") or "").strip()
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(c["home"]["timezone"])
        except Exception:
            self.tz = _dt.timezone(_dt.timedelta(hours=-5))

    # ───────── 存取 ─────────
    def _empty(self):
        return {"basket": [], "washer": None, "dryer": None, "sink": None, "line": [], "pile": [], "cat": None,
                "bed_set": None, "rain": None, "scars": []}

    def _read(self):
        try:
            with open(self.STATE, encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            return self._empty()
        for k, v in self._empty().items():
            s.setdefault(k, v)
        return s

    def _write(self, s):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.STATE)

    def _log(self, action, items, mode, out, now):
        try:
            with open(self.LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(now, 1), "action": action, "items": items, "mode": mode,
                                    "out": out[:400]}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def set_bed(self, name):
        """设一下床上现在铺的是哪套（比如装好时告诉它）。"""
        with _Locked(self.dir):
            s = self._read()
            s["bed_set"] = name or None
            self._write(s)

    # ───────── 小工具 ─────────
    def _hm(self, ts):
        return _dt.datetime.fromtimestamp(ts, self.tz).strftime("%H:%M")

    def _when(self, ts, now):
        a = _dt.datetime.fromtimestamp(now, self.tz).date()
        b = _dt.datetime.fromtimestamp(ts, self.tz).date()
        d = (b - a).days
        return ({0: "", 1: "明天 ", 2: "后天 "}.get(d, f"{b.month}月{b.day}日 ")) + self._hm(ts)

    def _is_day(self, now):
        h = _dt.datetime.fromtimestamp(now, self.tz).hour
        return self.cfg["home"]["day_start"] <= h < self.cfg["home"]["day_end"]

    @staticmethod
    def _names(items):
        return "、".join(items) if items else "（空的）"

    @staticmethod
    def _left(end, now):
        m = max(1, int(round((end - now) / 60)))
        if m < 60:
            return f"{m} 分钟"
        h, mm = divmod(m, 60)
        return f"{h} 小时" + (f" {mm} 分钟" if mm else "")

    def _weight(self, n):
        return 2 if self.big.search(n) else 1

    def _basket_load(self, s):
        return sum(self._weight(x["n"]) for x in s["basket"])

    @staticmethod
    def _parse(items):
        out = []
        for p in re.split(r"[、，,；;/\n]+|\s+", items or ""):
            p = p.strip(" 。.「」\"'")
            if p:
                out.append(p[:20])
        return out[:15]

    def _weather_line(self, w, now):
        if not w:
            return "外面：天气这会儿没拿到。"
        t = f"，{int(round(w['temp']))}°" if w.get("temp") is not None else ""
        return f"外面：{w['sky'] or '说不清'}{t}{'' if self._is_day(now) else '（天黑了）'}。"

    @staticmethod
    def _dry_word(d):
        if d >= 1:
            return "干了"
        if d < 0.15:
            return "还湿着"
        if d < 0.4:
            return "干了两三成"
        if d < 0.6:
            return "半干"
        if d < 0.85:
            return "干了七八成"
        return "快干了"

    def _bed_set(self, n):
        for name, rx in self.sets:
            if rx.search(n):
                return name
        return None

    def _color(self, n):
        """dark / light / mid。被套枕套按米白底算浅色；床单按 mid；四件套名字里的字不算颜色。"""
        bare = n
        for name, rx in self.sets:
            bare = rx.sub("", bare)
        if re.search(r"被套|枕套", bare):
            return "light"
        if "床单" in bare and self._bed_set(n):
            return "mid"
        if re.search(r"毯", bare) and not self.dark.search(bare):
            return "light"
        if self.dark.search(bare):
            return "dark"
        if self.light.search(bare):
            return "light"
        return "mid"

    @staticmethod
    def _tint_of(dark_name):
        if re.search(r"牛仔|藏青|海军", dark_name):
            return "blue", "灰蓝"
        if re.search(r"红", dark_name):
            return "pink", "粉"
        return "grey", "灰"

    @staticmethod
    def _delicate_wash_text(x):
        if re.search(r"羊毛|羊绒|毛衣", x):
            return f"{x}缩了一圈，袖子短了一截。"
        if "蕾丝" in x:
            return f"{x}的蕾丝边勾了丝。"
        return f"{x}在标准档里搓得起了一层小球，摸上去不滑了。"

    def _sort_accidents(self, load, gentle):
        so = self.cfg["sorting"]
        ev = []
        darks = [n for n in load if self._color(n) == "dark"]
        lights = [n for n in load if self._color(n) == "light"]
        if darks and lights and self.rng.random() < so["bleed_p"]:
            d, l = self.rng.choice(darks), self.rng.choice(lights)
            c, word = self._tint_of(d)
            ev.append({"stage": "out", "text": f"{d}掉色了，{l}被染上一层淡淡的{word}。", "tint": {"n": l, "c": c}})
        if not gentle:
            for x in [n for n in load if self.delicate.search(n)]:
                if self.rng.random() < so["delicate_wash_p"]:
                    ev.append({"stage": "out", "text": self._delicate_wash_text(x)})
        return ev

    def _roll_mishap(self, load):
        if self.rng.random() >= self.cfg["mishaps"]["p"]:
            return None
        ok = []
        for m in MISHAPS + list(self.cfg["mishaps"].get("extra") or []):
            if len(load) < m.get("min", 1):
                continue
            x = ""
            if m.get("need"):
                hit = [n for n in load if re.search(m["need"], n)]
                if not hit:
                    continue
                x = hit[0]
            ok.append((m, x))
        if not ok:
            return None
        m, x = self.rng.choice(ok)
        return {"stage": m.get("stage", "out"), "text": m["text"].replace("{x}", x)}

    def _take_out(self, s, wa):
        texts, tints = [], []
        for e in (wa or {}).get("events") or []:
            if e.get("tint"):
                tints.append(e["tint"])
            if e["stage"] == "out":
                texts.append(e["text"])
            else:
                s.setdefault("mishap_fold", []).append(e["text"])
        return "\n".join(texts), tints

    def _washer_state(self, s, now):
        wa = s.get("washer")
        if not wa:
            return None
        if now < wa["end"]:
            return "running"
        if now - wa["end"] > self.cfg["washer"]["musty_after_hours"] * 3600:
            return "musty"
        return "done"

    def _ready(self, s, now):
        """洗好能晾/能烘的那一批：先看洗衣机，再看手洗盆 → (状态, 那一批, 'washer'/'sink'/None)。"""
        st = self._washer_state(s, now)
        if st in ("done", "musty"):
            return st, s["washer"], "washer"
        sk = s.get("sink")
        if sk and sk.get("stage") == "done":
            musty = now - sk["done"] > self.cfg["washer"]["musty_after_hours"] * 3600
            return ("musty" if musty else "done"), {"items": sk["items"], "events": []}, "sink"
        return st, None, None

    # ───────── 晾干 / 下雨 ─────────
    def _dry_rate(self, ld, w, now):
        d = self.cfg["drying"]
        big = d["big"] if any(self.big.search(n) for n in ld["items"]) else 1.0
        rh = (w or {}).get("rh") or 60.0
        if ld["where"] != OUTDOOR:
            hum = min(1.2, max(0.75, 1.2 - rh / 100 * 0.4))
            return d["indoor"] * hum * (1.0 if self._is_day(now) else 0.9) * big
        if w and w["rain"]:
            return 0.0
        sky = (w or {}).get("sky") or ""
        base = next((v for k, v in d["sky"] if re.search(k, sky)), d["sky_else"])
        wind = 1 + min((w or {}).get("wind") or 0, 30) / 30 * 0.7
        hum = min(1.25, max(0.6, 1.35 - rh / 100 * 0.7))
        t = (w or {}).get("temp")
        temp = 0.9 if t is None else (0.4 if t < 3 else 0.7 if t < 10 else 0.9 if t < 18 else 1.0 if t <= 26 else 1.15)
        night = 1.0 if self._is_day(now) else d["night"]
        return base * wind * hum * temp * night * big

    def _advance(self, s, w, now):
        raining = bool(w and w["rain"])
        grace = self.cfg["rain"]["grace_min"] * 60
        outs = [ld for ld in s["line"] if ld["where"] == OUTDOOR and not ld.get("dirty")]
        for ld in s["line"]:
            last = ld.get("tick") or ld.get("start") or now
            dt = max(0.0, min(now - last, 6 * 3600)) / 3600
            ld["tick"] = round(now)
            out = ld["where"] == OUTDOOR
            if out and raining and not ld.get("raining"):
                ld["raining"] = True
                ld["wet"] = True
                ld.setdefault("rain_since", round(now))
                ld["dry"] = round(ld.get("dry", 0) * 0.3, 3)
            elif out and not raining:
                ld.pop("raining", None)
            if out and ld.get("rain_since") and not ld.get("dirty") and now - ld["rain_since"] > grace:
                ld["dirty"] = True
            rate = self._dry_rate(ld, w, now)
            if not ld.get("dirty") and dt and ld.get("dry", 0) < 1:
                ld["dry"] = round(min(1.0, ld.get("dry", 0) + rate * dt), 3)
            if ld.get("dry", 0) >= 1:
                ld["end"] = ld.get("end") if (ld.get("end") or now + 1) <= now else round(now)
            elif rate > 0:
                ld["end"] = round(now + (1 - ld.get("dry", 0)) / rate * 3600)
            else:
                ld["end"] = round(now + 12 * 3600)
        if raining and outs and not s.get("rain"):
            s["rain"] = {"since": round(now), "awake": not self.hooks.sleeping(), "heard": False}
        if not raining:
            s["rain"] = None

    def _dirty_to_basket(self, s, now):
        dirty = [ld for ld in s["line"] if ld.get("dirty")]
        if not dirty:
            return ""
        names = []
        for ld in dirty:
            for n in ld["items"]:
                s["basket"].append({"n": n, "ts": round(now)})
                names.append(n)
        s["line"] = [ld for ld in s["line"] if not ld.get("dirty")]
        return f"{self._names(names)}淋了雨，脏了，收下来扔回洗衣篮了，得重洗。"

    # ───────── 动作 ─────────
    def _look(self, s, w, now):
        cap = self.cfg["basket"]["cap"]
        L = []
        if s["basket"]:
            full = "（满了）" if self._basket_load(s) >= cap else ""
            L.append(f"洗衣篮：{self._basket_load(s)}/{cap}（大件算两件），{self._names([x['n'] for x in s['basket']])}{full}")
        else:
            L.append("洗衣篮：空的")
        st = self._washer_state(s, now)
        wa = s.get("washer")
        if st == "running":
            g = "（轻柔档）" if wa.get("gentle") else ""
            L.append(f"洗衣机{g}：{self._names(wa['items'])}，还在转，还剩 {self._left(wa['end'], now)}（{self._hm(wa['end'])} 好）")
        elif st == "done":
            L.append(f"洗衣机：{self._names(wa['items'])}，{self._hm(wa['end'])} 就洗好了，在里面等着")
        elif st == "musty":
            L.append(f"洗衣机：{self._names(wa['items'])}，{self._hm(wa['end'])} 洗好后一直闷在里面，有股闷味了")
        else:
            L.append("洗衣机：空着")
        dr = s.get("dryer")
        if dr:
            L.append(f"烘干机：{self._names(dr['items'])}，" + (f"还剩 {self._left(dr['end'], now)}" if now < dr["end"] else f"{self._hm(dr['end'])} 烘好了"))
        else:
            L.append("烘干机：空着")
        for ld in s["line"]:
            out = ld["where"] == OUTDOOR
            label = "晾起来的" if out else INDOOR
            rained = "，淋过雨" if ld.get("wet") else ""
            if ld.get("dirty"):
                L.append(f"晾起来的{self._names(ld['items'])}淋了半天雨，脏了")
            elif out and ld.get("raining"):
                L.append(f"晾起来的：{self._names(ld['items'])}，正淋着雨")
            elif ld.get("dry", 0) >= 1:
                L.append(f"{label}：{self._names(ld['items'])}干了{rained}")
            else:
                L.append(f"{label}：{self._names(ld['items'])}{rained}，{self._dry_word(ld.get('dry', 0))}，照现在的天气大概 {self._when(ld['end'], now)} 干")
        if not s["line"]:
            L.append("晾衣服的地方：空着")
        if s.get("pile"):
            L.append("拿出来放在一边、等着叠的：" + self._names([x["n"] for x in s["pile"]]))
        sk = s.get("sink")
        if sk:
            if sk["stage"] == "done":
                musty = now - sk["done"] > self.cfg["washer"]["musty_after_hours"] * 3600
                L.append(f"手洗盆：{self._names(sk['items'])}手洗好了，" + ("闷了好久，有股味了" if musty else "等着晾"))
            else:
                word = {"soak": "泡着", "scrub": "搓好了", "rinse": "冲好了"}[sk["stage"]]
                L.append(f"手洗盆：{self._names(sk['items'])}{word}" + (f"，还要 {self._left(sk['ready'], now)}" if now < sk["ready"] else "，等你下一步"))
        if s.get("cat") and self.pet:
            L.append(f"{self.pet}趴在{s['cat']['on']}上")
        if s.get("bed_set"):
            L.append(f"床上铺的：{s['bed_set']}那套")
        for sc in (s.get("scars") or [])[-5:]:
            d = _dt.datetime.fromtimestamp(sc["ts"], self.tz)
            L.append(f"长记性：{d.month}月{d.day}日，{sc['n']}{sc['what']}。")
        L.append(self._weather_line(w, now))
        return "\n".join(L)

    def _put(self, s, items, now):
        got = self._parse(items)
        if not got:
            return "要收什么？items 里写上，比如「床单、枕套、毯子」。"
        if s.get("bed_set"):      # 从床上扒下来的床品没写是哪套 → 就是现在床上那套
            got = [f"{n}（{s['bed_set']}那套）" if BED.search(n) and not self._bed_set(n) else n for n in got]
        cap = self.cfg["basket"]["cap"]
        load = self._basket_load(s)
        fit, over = [], []
        for n in got:
            if not over and load + self._weight(n) <= cap:
                fit.append(n)
                load += self._weight(n)
            else:
                over.append(n)
        if not fit:
            return (f"洗衣篮满了（{self._basket_load(s)}/{cap}，大件算两件），{self._names(over)}塞不进去。先洗一批（wash）再收。"
                    f"篮子里：{self._names([x['n'] for x in s['basket']])}。")
        for n in fit:
            s["basket"].append({"n": n, "ts": round(now)})
        out = f"收进洗衣篮了：{self._names(fit)}。篮子里现在 {load}/{cap}（大件算两件）：{self._names([x['n'] for x in s['basket']])}。"
        if over:
            out += f"\n篮子满了，{self._names(over)}塞不进去，先洗一批再收。"
        elif load >= cap:
            out += "\n篮子满了。"
        if self.pet and self.rng.random() < 0.08:
            out += f"\n{self.pet}跟过来，往篮子里探头闻了闻。"
        return out

    @staticmethod
    def _pick(basket, wanted):
        left = list(basket)
        took, miss = [], []
        for w_ in wanted:
            hit = next((x for x in left if x["n"] == w_), None) or next((x for x in left if w_ in x["n"] or x["n"] in w_), None)
            if hit:
                took.append(hit)
                left.remove(hit)
            else:
                miss.append(w_)
        return took, left, miss

    def _wash(self, s, items, gentle, now):
        st = self._washer_state(s, now)
        wa = s.get("washer")
        if st == "running":
            return f"洗衣机还在转（{self._names(wa['items'])}），还剩 {self._left(wa['end'], now)}。"
        wanted = [x for x in self._parse(items) if not re.fullmatch(r"轻柔|轻柔档|手洗|标准|标准档", x)]
        rewash = []
        if st in ("done", "musty"):
            if s["basket"] and st == "done":
                return f"洗衣机里还有上一缸洗好的{self._names(wa['items'])}，先拿出来晾或烘（hang / dry），再洗篮子里的。"
            rewash = list(wa["items"])
        miss = []
        if wanted:
            took, left, miss = self._pick(s["basket"], wanted)
            if not took and not rewash:
                return f"篮子里没找到{self._names(miss)}。篮子里有：{self._names([x['n'] for x in s['basket']]) if s['basket'] else '（空的）'}。"
            s["basket"] = left
        else:
            took, s["basket"] = list(s["basket"]), []
        load = rewash + [x["n"] for x in took]
        if not load:
            return "洗衣篮是空的，没东西可洗。先 put 收点东西进来。"
        mins = self.cfg["washer"]["gentle_min"] if gentle else self.cfg["washer"]["wash_min"]
        events = self._sort_accidents(load, gentle)
        mx = self._roll_mishap(load)
        if mx:
            events.append(mx)
        s["washer"] = {"items": load, "start": round(now), "end": round(now + mins * 60), "gentle": bool(gentle), "events": events}
        again = "（原来那缸再洗一遍）" if rewash else ""
        msg = f"扔进洗衣机了{again}，{'轻柔档' if gentle else '标准档'}：{self._names(load)}。洗一缸 {mins} 分钟，{self._hm(s['washer']['end'])} 好。"
        cold = [n for n in load if self.cold_water.search(n)]
        if cold:
            msg += f"{self._names(sorted({self.cold_water.search(n).group(0) for n in cold}, key=lambda x: x))}走冷水。"
        hw = [n for n in load if self.handwash_only.search(n)]
        if hw:
            msg += f"\n{self._names(hw)}也进了洗衣机——屋里的规矩是这件手洗。"
        if miss:
            msg += f"\n篮子里没找到：{self._names(miss)}。"
        if s["basket"]:
            msg += f"\n篮子里还剩：{self._names([x['n'] for x in s['basket']])}。"
        return msg

    def _handwash(self, s, items, now):
        h = self.cfg["handwash"]
        sk = s.get("sink")
        if sk and sk["stage"] == "done":
            return f"盆里手洗好的{self._names(sk['items'])}还没晾，先 hang（或者 dry）。"
        if sk:
            if now < sk["ready"]:
                word = {"soak": "泡", "scrub": "搓", "rinse": "冲"}[sk["stage"]]
                return f"还在{word}，再等 {self._left(sk['ready'], now)}。"
            if sk["stage"] == "soak":
                sk.update(stage="scrub", ready=round(now + h["scrub_min"] * 60))
                return f"搓：一件一件拎出来，领口袖口、贴身的地方多搓了几遍，搓到指腹泡皱。（{h['scrub_min']} 分钟后冲）"
            if sk["stage"] == "scrub":
                sk.update(stage="rinse", ready=round(now + h["rinse_min"] * 60))
                return f"冲：换了两盆清水，冲到没有泡沫。（{h['rinse_min']} 分钟后拧）"
            sk.update(stage="done", done=round(now))
            return f"拧：攥在手心里轻轻挤，不拧麻花，挤到不滴水。{self._names(sk['items'])}手洗好了，可以晾了。"
        wanted = self._parse(items)
        if wanted:
            took, s["basket"], miss = self._pick(s["basket"], wanted)
            names = [x["n"] for x in took] + miss
        else:
            took = [x for x in s["basket"] if self.handwash_only.search(x["n"])]
            if not took:
                return "要手洗什么？items 里写上。"
            s["basket"] = [x for x in s["basket"] if x not in took]
            names = [x["n"] for x in took]
        s["sink"] = {"items": names, "stage": "soak", "ready": round(now + h["soak_min"] * 60)}
        msg = f"泡上了：{self._names(names)}。盆里接水，挤一点洗衣液，先泡 {h['soak_min']} 分钟（{self._hm(s['sink']['ready'])} 好）。"
        if self.pet and self.rng.random() < 0.1:
            msg += f"\n{self.pet}跳上洗手台，蹲在盆边看水。"
        return msg

    def _hang(self, s, items, force_in, w, now):
        st, src, srcname = self._ready(s, now)
        if st in (None, "running"):
            pre = self._dirty_to_basket(s, now)
            outs = [ld for ld in s["line"] if ld["where"] == OUTDOOR]
            if pre and not outs:
                return pre
            if outs and (force_in or (w and w["rain"])):
                moved = []
                for ld in outs:
                    ld["where"] = INDOOR
                    ld.pop("raining", None)
                    ld.pop("rain_since", None)
                    moved += ld["items"]
                self._advance(s, w, now)
                eta = max(ld["end"] for ld in outs)
                return (pre + "\n" if pre else "") + f"把晾在外面的{self._names(moved)}收进屋，挂到{INDOOR}上了，大概 {self._when(eta, now)} 干。"
            if pre:
                return pre
            if st == "running":
                return f"洗衣机还在转，还剩 {self._left(s['washer']['end'], now)}，洗好了才能晾。"
            return "洗衣机里没有洗好的东西可晾。"
        why = ""
        if force_in:
            where = INDOOR
        elif not w:
            where, why = INDOOR, "不知道外面天气"
        elif w["rain"]:
            where, why = INDOOR, f"外面{w['sky'] or '在下雨'}"
        elif w.get("temp") is not None and w["temp"] < 3:
            where, why = INDOOR, f"外面才 {int(round(w['temp']))}°，会冻上"
        else:
            where = OUTDOOR
        ld = {"items": src["items"], "where": where, "start": round(now), "tick": round(now), "dry": 0.0, "musty": st == "musty"}
        text, tints = self._take_out(s, src)
        if tints:
            ld["tint"] = tints
        s["line"].append(ld)
        s[srcname] = None
        self._advance(s, w, now)
        eta = self._when(ld["end"], now)
        msg = (f"晾起来了：{self._names(ld['items'])}。照现在的天气，大概 {eta} 干。" if where == OUTDOOR
               else f"晾在{INDOOR}上了：{self._names(ld['items'])}。大概 {eta} 干。")
        if text:
            msg += "\n" + text
        if why:
            msg += f"（{why}，没晾出去。）"
        if ld["musty"]:
            msg += "\n闷过的味道还在，晾干了也会带着一点。"
        if where == OUTDOOR and self.pet and self.rng.random() < 0.1:
            msg += f"\n{self.pet}蹲在底下，盯着被风吹起来的衣角。"
        return msg

    def _dry(self, s, w, now):
        dr = s.get("dryer")
        st, src, srcname = self._ready(s, now)
        if dr and now < dr["end"]:
            return f"烘干机还在转（{self._names(dr['items'])}），还剩 {self._left(dr['end'], now)}。"
        pre = self._dirty_to_basket(s, now)
        if dr:
            s.setdefault("pile", []).extend({"n": n, "ts": round(now), "warm": dr["end"]} for n in dr["items"])
            pre = (pre + "\n" if pre else "") + f"先把烘好的{self._names(dr['items'])}拿出来放一边。"
            s["dryer"] = None
        load, musty, text = [], False, ""
        if st in ("done", "musty"):
            load = list(src["items"])
            musty = st == "musty"
            text, _ = self._take_out(s, src)
            s[srcname] = None
        else:
            wet = [ld for ld in s["line"] if ld.get("dry", 0) < 1]
            for ld in wet:
                load += ld["items"]
                musty = musty or ld.get("musty", False)
            s["line"] = [ld for ld in s["line"] if ld not in wet]
            if not load:
                if pre:
                    return pre + "\n" + ("洗衣机里也没有要烘的。" if st is None else f"洗衣机还在转，还剩 {self._left(s['washer']['end'], now)}。")
                if st == "running":
                    return f"洗衣机还在转，还剩 {self._left(s['washer']['end'], now)}，洗好了才能烘。"
                return "没有湿的东西要烘。"
        for x in [n for n in load if self.delicate.search(n) or self.never_dry.search(n)]:
            if self.never_dry.search(x):
                s.setdefault("mishap_fold", []).append(f"{x}进了烘干机——缩了一大圈，领口的边烫得卷了起来，穿不上了。")
                s.setdefault("scar_pending", []).append({"n": x, "what": "进了烘干机，缩得穿不上了"})
            elif self.rng.random() < self.cfg["sorting"]["delicate_dry_p"]:
                s.setdefault("mishap_fold", []).append(f"{x}进了烘干机，出来小了一圈，形也走了。")
        mins = self.cfg["washer"]["dryer_min"]
        s["dryer"] = {"items": load, "start": round(now), "end": round(now + mins * 60), "musty": musty}
        msg = (pre + "\n" if pre else "") + f"放进烘干机了：{self._names(load)}。烘 {mins} 分钟，{self._hm(s['dryer']['end'])} 好。"
        if text:
            msg += "\n" + text
        if musty:
            msg += "\n闷过的味道烘完也不会全散。"
        if self.cfg["rules"].get("prefer_line_dry") and w and not w["rain"] and self._is_day(now) \
                and (w.get("temp") or 0) >= 3 and not re.search(r"阴|雾", w.get("sky") or "") and (w.get("rh") or 0) < 85:
            msg += "\n（外面天好——屋里的规矩是天好就晾，烘干机留给下雨天、阴潮天。）"
        return msg

    @staticmethod
    def _put_away(n):
        if BED.search(n):
            return "铺回床上"
        if re.search(r"被子|毯", n):
            return "叠好放回床尾"
        return "叠好收进柜子"

    def _fold(self, s, now):
        dm = self._dirty_to_basket(s, now)
        ready, warm = [], {}
        dr = s.get("dryer")
        musty = False
        if dr and now >= dr["end"]:
            for n in dr["items"]:
                ready.append(n)
                warm[n] = dr["end"]
            musty = bool(dr.get("musty"))
            s["dryer"] = None
        for x in s.get("pile", []):
            ready.append(x["n"])
            if x.get("warm"):
                warm[x["n"]] = x["warm"]
        s["pile"] = []
        keep = []
        for ld in s["line"]:
            if ld.get("dry", 0) >= 1:
                ready += ld["items"]
                musty = musty or ld.get("musty", False)
            else:
                keep.append(ld)
        s["line"] = keep
        lines, after = ([dm] if dm else []), []
        cat = s.get("cat")
        cat_left = False
        if cat and self.pet:
            if now - cat["since"] >= 10 * 60 and self.rng.random() < 0.7:
                ready.append(cat["on"])
                lines.append(f"{self.pet}终于挪窝了，{cat['on']}上留了一层毛，抖了抖。")
                s["cat"] = None
                cat_left = True
            else:
                lines.append(f"{self.pet}还趴在{cat['on']}上，呼噜打得很响，这件先叠不了。")
        if not ready:
            if not lines:
                pending = []
                if s.get("dryer"):
                    pending.append(f"烘干机还剩 {self._left(s['dryer']['end'], now)}")
                for ld in s["line"]:
                    pending.append(f"{'晾起来的' if ld['where'] == OUTDOOR else INDOOR + '上的'}{self._dry_word(ld.get('dry', 0))}")
                return "没有干了的可以收。" + ("（" + "；".join(pending) + "）" if pending else "")
            return "\n".join(lines)
        if self.pet and not s.get("cat") and not cat_left:
            big = [n for n in ready if self.big.search(n)]
            hot = [n for n in big if n in warm and now - warm[n] < 3600]
            p = 0.4 if hot else (0.12 if big else 0)
            if p and self.rng.random() < p:
                on = (hot or big)[0]
                ready.remove(on)
                s["cat"] = {"on": on, "since": round(now)}
                after.append(f"刚摊开，{self.pet}就跳上来趴在{on}上{'，还热乎着' if on in hot else ''}，不肯走。这件先留着。")
        groups = {}
        for n in ready:
            groups.setdefault(self._put_away(n), []).append(n)
        done = "；".join(f"{self._names(v)}{k}" for k, v in groups.items())
        out = f"收下来了：{done}。" if done else ""
        sets = {self._bed_set(n) for n in groups.get("铺回床上", [])} - {None}
        if len(sets) == 1:
            s["bed_set"] = sets.pop()
            out += f"现在床上铺的是{s['bed_set']}那套。"
        if musty and done:
            out += "有几件还带着一点闷味。"
        if done and s.get("mishap_fold"):
            out += "\n" + "\n".join(s.pop("mishap_fold"))
            for sc in s.pop("scar_pending", []):
                s.setdefault("scars", []).append({**sc, "ts": round(now)})
        return "\n".join([x for x in lines + [out] + after if x])

    # ───────── 对外 ─────────
    def run(self, action="look", items="", mode="", now=None):
        now = time.time() if now is None else now
        action = (action or "look").strip().lower()
        mode = (mode or "").strip()
        if action not in ACTIONS:
            return "action 只认：" + " / ".join(ACTIONS) + "。"
        gentle = bool(re.search(r"轻柔|手洗", mode + " " + (items or "")))
        force_in = "屋里" in mode or "屋里" in (items or "")
        with _Locked(self.dir):
            s = self._read()
            w = self.weather.current(now)
            self._advance(s, w, now)
            if action == "look":
                out = self._look(s, w, now)
            elif action == "rules":
                out = self.cfg["rules"]["text"]
            elif action == "put":
                out = self._put(s, items, now)
            elif action == "wash":
                out = self._wash(s, items, gentle, now)
            elif action == "handwash":
                out = self._handwash(s, items, now)
            elif action == "hang":
                out = self._hang(s, items, force_in, w, now)
            elif action == "dry":
                out = self._dry(s, w, now)
            else:
                out = self._fold(s, now)
            self._write(s)
        self._log(action, items, mode, out, now)
        return out

    def tick(self, now=None):
        """每隔几分钟：往前晾、看下没下雨。下雨时外面挂着东西、他醒着 → 有 webhook 就叫他，没有就留给 notice()。"""
        now = time.time() if now is None else now
        if not os.path.exists(self.STATE):
            return "no state"
        fire = False
        with _Locked(self.dir):
            s = self._read()
            if not s["line"] and not s.get("rain"):
                return "nothing hanging"
            self._advance(s, self.weather.current(now), now)
            r = s.get("rain")
            outs = [ld for ld in s["line"] if ld["where"] == OUTDOOR and not ld.get("dirty")]
            if r and r.get("awake") and not r.get("heard") and outs and self.hooks.has_webhook() \
                    and now - r["since"] < self.cfg["rain"]["grace_min"] * 60:
                r["heard"] = "webhook"
                fire = True
            self._write(s)
        if fire:
            ok = self.hooks.rain(self.cfg["rain"]["hear_text"])
            if not ok:
                with _Locked(self.dir):
                    s = self._read()
                    if s.get("rain"):
                        s["rain"]["heard"] = False
                    self._write(s)
            return "rain → webhook " + ("ok" if ok else "FAILED")
        return "ticked"

    def notice(self, now=None):
        """给你家系统在递话给他之前调一下：刚下起雨、他醒着、外面还挂着东西、还没听见过 → 返回那句雨声；否则 ''。"""
        now = time.time() if now is None else now
        if not os.path.exists(self.STATE):
            return ""
        with _Locked(self.dir):
            s = self._read()
            self._advance(s, self.weather.current(now), now)
            r = s.get("rain")
            outs = [ld for ld in s["line"] if ld["where"] == OUTDOOR and not ld.get("dirty")]
            hear = bool(r and r.get("awake") and not r.get("heard") and outs)
            if hear:
                r["heard"] = "notice"
            self._write(s)
        return self.cfg["rain"]["hear_text"] if hear else ""

    def state_data(self, now=None):
        """给晾衣绳小组件：外面晾着的几缸 + 洗衣篮 + 画绳子要的样子（四件套、毯子）。"""
        now = time.time() if now is None else now
        look = {"bed_sets": [{k: b.get(k) for k in ("name", "keywords", "cover", "sheet", "pattern")} for b in self.cfg.get("bed_sets", [])],
                "blanket": self.cfg.get("blanket", {}), "big": self.cfg["basket"]["big"]}
        cap = self.cfg["basket"]["cap"]
        if not os.path.exists(self.STATE):
            return {"now": now, "loads": [], "basket": {"n": 0, "cap": cap, "items": 0}, "bed_set": None, "look": look}
        with _Locked(self.dir):
            s = self._read()
            self._advance(s, self.weather.current(now), now)
            self._write(s)
        loads = [{"items": ld["items"], "start": ld["start"], "end": ld.get("end"), "dry": ld.get("dry", 0),
                  "wet": bool(ld.get("wet")), "dirty": bool(ld.get("dirty")), "tint": ld.get("tint") or []}
                 for ld in s["line"] if ld["where"] == OUTDOOR]
        return {"now": now, "loads": loads, "basket": {"n": self._basket_load(s), "cap": cap, "items": len(s["basket"])},
                "bed_set": s.get("bed_set"), "look": look}
