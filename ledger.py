# -*- coding: utf-8 -*-
"""채널 장부 — 옛 숫자와 나란히 돌리는 새 방식(병행 운행).
   옛 방식은 작품마다 검색해서 찾는다. 시험해 보니(11-05) 검색과 장부는 서로 다른 영상을 찾아서, 둘을 합쳐야 한다:
     · 영화 채널 RSS(쿼터 없음) · 채널 Shorts 탭 첫 등록 · 이번 달 필터 검색 · 옛 방식이 찾은 영상을 새 규칙으로 다시 판정
   옛 자료(state.enc.json·data.enc.js)는 읽기만 하고 절대 안 고친다. 결과는 따로: ledger.enc.json(장부) · new.enc.js(화면용).
   이 파일이 실패해도 옛 숫자는 그대로다 (scan.yml 에서 따로 돈다).
   사용: python ledger.py --out site [--minutes 8]"""
import os, re, sys, json, time, argparse, urllib.parse, urllib.error
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import actors, discover, lock, scan, yt
import resolve as R

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
C = scan.CFG.get("ledger") or {}
UNIT_DAY = C.get("unit_day", 2000)  # 장부 몫 (옛 방식과 따로 셈)
ALL_CAP = C.get("all_cap", 7000)  # 옛 방식까지 합쳐 이만큼 쓰면 멈춤 (오늘의 흐름·채널 레이더 몫)
THREADS = C.get("rss_threads", 4)
FILTER_PER_ROUND, TAB_PER_ROUND = C.get("filter_per_round", 30), C.get("tab_per_round", 40)
CAT_DAYS = C.get("cat_refresh_days", 30)
SP_MONTH = "EgYIBBABGAE%3D"  # 이번 달 + 4분 미만 (쇼츠 종류 필터는 날짜가 안 듣는다 — 11-05 시험)
OFF = re.compile(scan.OFFICIAL.pattern + r"|소니픽쳐스|Sony|왓챠|watcha", re.I)
SEC = re.compile(r"^==+\s*(출연|출연진|배역|등장\s*인물|캐스트|캐스팅|주요\s*인물)\s*==+\s*$(.*?)(?=^==[^=]|\Z)", re.M | re.S)
# 영상 줄: [0 작품 key, 1 채널, 2 조회수, 3 올린 때, 4 제목, 5 표시(1 예능·행사 2 강한 증거), 6 찾은 길(1 검색 2 RSS 4 탭), 7 마지막 확인(분)]
K, CID, VIEWS, PUB, TITLE, FLAG, SRC, SEEN = range(8)
PAN = "판:"  # 같은 이름 작품이 갈리지 않은 영상의 작품 key 앞머리
now_min, kst, age_days = scan.now_min, scan.kst, scan.age_days


def log(m):
    print(f"[{datetime.now(scan.KST):%H:%M:%S}] 장부: {m}", flush=True)


# ── 작품 목록 ────────────────────────────────────────────
def cast_of(wiki, fallback=()):
    cast = [actors.short(a) for a in actors.people(actors.field(wiki, "출연", "출연자", "주연", "배우", "출연진"), 8)]
    cast = [a for a in cast if 2 <= len(a) <= 12 and not re.search(r"[|{}=<>]", a)]
    if not cast:
        m = SEC.search(wiki or "")
        if m:
            for x in actors.LINK.finditer(m.group(2)):
                a = actors.short(x.group(1).strip())
                if re.fullmatch(r"[가-힣]{2,5}", a) and a not in cast:
                    cast.append(a)
            cast = cast[:8]
    return cast or list(fallback)


def catalog_sources(st, today):
    """위키 제목 → {n,y,k,d}: 자동 발굴 후보 + 올해 영화(후보는 작년까지) + 방송 드라마(알아보기만, 화면엔 안 나옴)"""
    src = dict((st.get("disc") or {}).get("cand") or {})
    try:
        kor = [t for t, c in discover._members_with_cats(f"{today.year}년 영화", ["한국어 영화 작품", "대한민국의 영화 작품"]).items() if c]
        for t, cats in discover._cats(kor).items():
            if not any(re.search(r"애니메이션|다큐멘터리|단편 영화|포르노|에로", c) for c in cats):
                src.setdefault(t, {"n": actors.short(t), "y": today.year, "k": "영화", "d": ""})
    except Exception as e:
        log(f"올해 영화 못 받음 {e}")
    for y in range(2000, today.year + 1):
        try:
            got = discover._members_with_cats(f"{y}년 시작한 대한민국의 텔레비전 프로그램")
        except Exception as e:
            log(f"{y}년 드라마 못 받음 {e}")
            continue
        for t, cats in got.items():
            if any("드라마" in c for c in cats) and not any("예능" in c for c in cats):
                plat = next((m.group(0) for c in cats for m in [discover.OTT_CAT.search(c)] if m), "")
                src.setdefault(t, {"n": actors.short(t), "y": y, "k": "OTT" if plat else "방송", "d": plat})
    return src


def ensure_catalog(L, st, works, deadline):
    """작품 목록을 채운다. 다 차기 전엔 판정을 안 한다(판정은 다시 못 하니까). → 다 찼으면 True"""
    cat, todo, now = L["cat"], L["cat_todo"], now_min()
    if now - L.get("cat_m", 0) >= CAT_DAYS * 1440:
        src = catalog_sources(st, kst(now).date())
        todo.update({t: c for t, c in src.items() if t not in cat and t not in todo})
        L["cat_m"] = now
        log(f"작품 후보 {len(src)}편 · 주연 받을 것 {len(todo)}편")
    # 지금 레이더에 있는 작품은 위키 후보에 없어도 넣는다 (works.txt·배우 타이밍)
    names = {R.norm(c["n"]) for c in cat.values()} | {R.norm(c["n"]) for c in todo.values()}
    for w in works:
        nn = R.norm(w["n"])
        if nn and nn not in names:
            extra = [e for e in w["q"].lstrip("#").split() if R.norm(e) and R.norm(e) != nn]
            cat["W:" + w["n"]] = {"n": w["n"], "y": int(w["y"]) if str(w["y"]).isdigit() else None, "k": w["k"], "d": w["d"], "cast": extra, "al": [], "try": 0 if not extra else 1}
            names.add(nn)
    keys = list(todo)
    for i in range(0, len(keys), 50):
        if time.time() > deadline:
            break
        chunk = keys[i:i + 50]
        got = actors.pages(chunk)
        for k in chunk:
            c = todo.pop(k)
            al = []
            m = re.split(r"\s*[(:：]", c["n"])[0].strip()
            if m != c["n"] and len(R.norm(m)) >= 2:
                al.append(m)
            cat[k] = {"n": c["n"], "y": c.get("y"), "k": c.get("k"), "d": c.get("d") or "", "cast": cast_of(got.get(k, {}).get("w", ""), c.get("cast") or []), "al": al,
                      "tail": k[len(c["n"]):].strip(" ()") if k != c["n"] else ""}
    # 위키 제목을 몰라 주연이 빈 작품: 이름으로 찾아본다 (회차마다 조금씩)
    blank = [k for k, c in cat.items() if k.startswith("W:") and not c.get("cast") and not c.get("try")][:60]
    if blank and time.time() < deadline:
        tries = {}
        for k in blank:
            c = cat[k]; sfx = "드라마" if c.get("k") in ("OTT", "방송") else "영화"
            tries[k] = [c["n"], f"{c['n']} ({sfx})", f"{c['n']} ({c.get('y')}년 {sfx})"]
        got = actors.pages([t for l in tries.values() for t in l])
        for k in blank:
            cat[k]["try"] = 1
            for t in tries[k]:
                d = got.get(t)
                if d and not d.get("dis"):
                    cast = cast_of(d.get("w", ""))
                    if cast:
                        cat[k]["cast"] = cast
                        break
    return not todo


def work_keys(cat, works):
    """작품 id → 장부의 작품 key. 같은 이름이 여럿이면 연도·플랫폼이 가까운 쪽 (넷플릭스 「트리거」 / 디즈니 「트리거」)"""
    idx = defaultdict(list)
    for k, c in cat.items():
        idx[R.norm(c["n"])].append(k)
    out = {}
    for w in works:
        cand = idx.get(R.norm(w["n"]), [])
        if not cand:
            continue
        y = int(w["y"]) if str(w.get("y")).isdigit() else None
        d = (w.get("d") or "").lower()

        def rank(k):
            c = cat[k]
            return (abs((c.get("y") or 0) - y) if y and c.get("y") else 99, 0 if d and any(p in d and p in (k + (c.get("d") or "")).lower() for p in ("넷플릭스", "디즈니", "티빙", "쿠팡", "웨이브", "왓챠")) else 1, k.startswith("W:"))
        out[w["i"]] = sorted(cand, key=rank)[0]
    return out


# ── 영상 판정 ────────────────────────────────────────────
def film(x):
    """평소 영화·드라마 채널인가 (모르는 채널은 일단 그렇다고 친다 — 줄을 셀 때 다시 본다)"""
    if not x or x.get("n", 0) < 4:
        return True
    return x.get("s", 0) >= 0.2 * x["n"] or x.get("w", 0) >= 0.3 * x["n"]


def person(x):
    """배우 인생 이야기 채널: 한 편에 작품 여럿이 자주 나오고, 영상마다 작품이 다르다.
       영화 클립 채널은 한 작품을 여러 편 올리므로 안 걸린다 (11-05: 6,476곳 중 16곳, 읽어 보니 전부 인물·목록 채널)"""
    if not x or x.get("n", 0) < 5 or x.get("m", 0) < 0.3 * x["n"]:
        return False
    wk = x.get("wk") or {}
    a = sum(wk.values())
    return a == 0 or len(wk) >= 0.6 * a


def add_channel(L, cid, title, now):
    if cid and cid not in L["ch"] and cid not in L["dead"]:
        L["ch"][cid] = {"t": title, "a": now, "n": 0, "s": 0, "w": 0, "nx": 0, "tab": 0}
    if title:
        L["nm"][cid] = title


def judge(L, x, src, now, count=True):
    """영상 한 편 판정. x = {i,t,desc,tags,cid,ch,pub,v}. 작품이 잡히면 장부에 넣고 True"""
    cid, title = x["cid"], x["ch"]
    if OFF.search(title or ""):
        return False
    p = R.parse(x)
    res = R.candidates(p, L["gen"])
    chx = L["ch"].get(cid)
    if count:
        R.gen_add(p, L["gen"])
        if chx is not None:
            chx["n"] += 1
            chx["w"] += bool(R.FILMW.search(x["t"] + " " + (x.get("desc") or "")))
            chx["s"] += bool(res and res[0][4] and res[0][0] >= 4)
            chx["m"] = chx.get("m", 0) + R.multi(res)
    d = R.pick(res, film(chx), p["TH"])
    key = d["w"] if d["lv"] == "확실" else PAN + d["nn"] if d["lv"] == "판모름" else None
    f = R.fingerprint(x.get("desc"))
    if key is None:
        if chx is not None and f and film(chx) and (age_days(x["pub"], now) or 99) <= 60:
            q = chx.setdefault("pd", [])
            if not any(a[0] == x["i"] for a in q):
                q.append([x["i"], f, x.get("v") or 0, x["pub"][:19], x["t"][:60]])
                del q[:-20]
        return False
    nc = bool(R.NC.search(x["t"] + " " + " ".join(R.HT.findall(x.get("desc") or "")) + " " + " ".join(x.get("tags") or [])))
    L["v"][x["i"]] = [key, cid, x.get("v") or 0, x["pub"][:19], x["t"][:60], int(nc) | (2 if d["strong"] else 0), src, now]
    if chx is not None and count:
        wk = chx.setdefault("wk", {})
        wk[key] = wk.get(key, 0) + 1
    if chx is not None and f:
        chx.setdefault("fp", {}).setdefault(str(f), []).append(key)
        del chx["fp"][str(f)][:-6]
    add_channel(L, cid, title, now)
    return True


def inherit(L, now):
    """같은 채널·같은 설명인 영상이 2편 넘게 한 작품이면 나머지도 그 작품 (켓플릭스 탈주 330만)"""
    n = 0
    for cid, x in L["ch"].items():
        if not x.get("pd") or not x.get("fp"):
            continue
        rest = []
        for vid, f, v, pub, t in x["pd"]:
            keys = Counter(x["fp"].get(str(f), []))
            if keys:
                top, c = keys.most_common(1)[0]
                if c >= 2 and c / sum(keys.values()) >= 0.8:
                    L["v"].setdefault(vid, [top, cid, v, pub, t, 2, 2, now])
                    n += 1
                    continue
            rest.append([vid, f, v, pub, t])
        x["pd"] = rest
    return n


# ── 유닛 ────────────────────────────────────────────────
def units_left(L, st, today, want):
    old = (st.get("units") or {}).get(today, 0)
    used = L["units"].get(today, 0)
    return max(0, min(want, UNIT_DAY - used, ALL_CAP - old - used))


def api_videos(L, ids, key, today):
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    m = yt.videos(ids, key)
    L["units"][today] = L["units"].get(today, 0) + (len(ids) + 49) // 50
    return m


# ── 회차 ────────────────────────────────────────────────
def feed_round(L, inp, now):
    n = hit = 0
    for i, m in (inp.get("feed") or {}).items():
        if i in L["v"] or not m.get("dur") or m["dur"] > 180:
            continue
        n += 1
        hit += judge(L, dict(m, i=i), 1, now)
    for i in inp.get("seen") or []:
        r = L["v"].get(i)
        if r:
            r[SRC] |= 1
    log(f"검색이 찾은 새 영상 {n}편 판정 → 작품 {hit}편")


def seed_channels(L, st, now):
    """처음: 옛 방식이 찾은 채널 + 시험 때 모은 영화 채널 (seed_channels.txt)"""
    if L.get("seeded"):
        return
    n0 = len(L["ch"])
    for rec in (st.get("works") or {}).values():
        for v in rec.get("v", []):
            if not v[6] and not OFF.search(v[2] or ""):
                add_channel(L, v[3], v[2], now)
    p = os.path.join(HERE, "seed_channels.txt")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            c = line.split("#")[0].strip()
            if c:
                add_channel(L, c, "", now)
    p = os.path.join(HERE, "seed_gen.json")
    if os.path.exists(p):
        for nn, g in json.load(open(p, encoding="utf-8")).items():
            L["gen"].setdefault(nn, list(g))
    L["seeded"] = True
    log(f"처음 채널 {len(L['ch']) - n0}곳 넣음")


def rss_round(L, now, deadline):
    """오래 안 읽은 채널부터. 많이 올리는 채널일수록 자주 읽는다 (15편 한도 안에서 놓치지 않게)"""
    ch = L["ch"]
    due = sorted((c for c, x in ch.items() if x.get("nx", 0) <= now), key=lambda c: ch[c].get("nx", 0))
    done = fails = hit = new = 0
    need = L.setdefault("need", [])

    def one(c):
        try:
            return c, yt.channel_rss(c)
        except Exception as e:
            return c, e
    with ThreadPoolExecutor(THREADS) as ex:
        for i in range(0, len(due), 40):
            if time.time() > deadline:
                break
            got = list(ex.map(one, due[i:i + 40]))
            bad = sum(isinstance(r, Exception) for _, r in got)
            if bad >= 30:  # 채널 탓이 아니라 RSS 가 통째로 막힌 것 → 실패로 안 세고 그만
                fails += bad
                log("RSS 가 연달아 막힘 → 이번 회차는 그만")
                L["block"] = L.get("block", 0) + 1
                break
            for c, r in got:
                x = ch.get(c)
                if x is None:
                    continue
                if isinstance(r, Exception):
                    x["fail"] = x.get("fail", 0) + 1
                    x["nx"] = now + min(1440, 60 * x["fail"] * x["fail"])
                    if x["fail"] >= 6:  # 없어진 채널
                        L["dead"][c] = now
                        ch.pop(c)
                    continue
                title, items = r
                done += 1
                x.pop("fail", None)
                if title:
                    x["t"] = title; L["nm"][c] = title
                prev = set(x.get("ids") or [])
                for it in items:
                    vid = it["id"]
                    row = L["v"].get(vid)
                    if row:
                        if it["v"] is not None:
                            row[VIEWS] = it["v"]
                        row[SRC] |= 2; row[SEEN] = now
                        continue
                    if vid in prev or not it["short"]:
                        continue
                    new += 1
                    ok = judge(L, {"i": vid, "t": it["title"], "desc": it["desc"], "tags": [], "cid": c, "ch": x["t"] or title, "pub": it["pub"], "v": it["v"]}, 2, now)
                    hit += ok
                    # RSS 엔 태그가 없다 → 영화 채널인데 못 알아본 최근 영상은 API 로 태그까지 받아 다시 본다
                    if not ok and film(x) and (age_days(it["pub"], now) or 99) <= 60:
                        need.append(vid)
                x["ids"] = [it["id"] for it in items]
                pubs = [age_days(it["pub"], now) for it in items if it["pub"]]
                pubs = [a for a in pubs if a is not None]
                if pubs and min(pubs) > 30:
                    gap = 3 * 1440  # 한 달 넘게 안 올림
                elif len(items) >= 15 and pubs:
                    gap = (max(pubs) - min(pubs)) * 1440 / 3
                else:
                    gap = 1440
                x["nx"] = now + int(max(60, min(1440 * 3, gap)))
                x["r"] = now
                if x["n"] >= 10 and x["s"] == 0 and x["w"] < 0.1 * x["n"] and c not in L["v_ch"]:
                    L["dead"][c] = now  # 영화 채널이 아님
                    ch.pop(c)
            fails += bad
    del need[:-2000]
    log(f"RSS {done}곳 읽음 (남은 {max(0, len(due) - done - fails)}곳 · 실패 {fails}) · 새 쇼츠 {new}편 → 작품 {hit}편")


def need_round(L, st, key, now, today, budget):
    q, n, hit = L.get("need") or [], 0, 0
    if not q or budget <= 0:
        return 0
    ask = q[:budget * 50]
    del q[:len(ask)]
    m = api_videos(L, ask, key, today)
    for i, x in m.items():
        if x.get("dur") and x["dur"] <= 180 and i not in L["v"]:
            n += 1
            hit += judge(L, dict(x, i=i), 2, now, count=False)
    log(f"태그까지 다시 본 영상 {n}편 → 작품 {hit}편")
    return (len(ask) + 49) // 50


def backfill_round(L, st, key, now, today, budget):
    """옛 방식이 찾은 영상을 새 규칙으로 다시 판정 (설명·태그가 필요해 API)"""
    rej = L["rej"]
    want = []
    keep = set()
    for rec in (st.get("works") or {}).values():
        for v in rec.get("v", []):
            if v[6]:
                continue
            keep.add(v[0])
            if v[0] not in L["v"] and v[0] not in rej:
                want.append(v[0])
    L["rej"] = {i: 1 for i in rej if i in keep}
    L["old_left"] = len(want)
    for row_id in keep:
        r = L["v"].get(row_id)
        if r:
            r[SRC] |= 1
    if budget <= 0 or not want:
        return 0
    ask = want[:budget * 50]
    m = api_videos(L, ask, key, today)
    hit = 0
    for i in ask:
        x = m.get(i)
        if x and x.get("dur") and x["dur"] <= 180 and judge(L, dict(x, i=i), 1, now):
            hit += 1
        else:
            L["rej"][i] = 1
    L["old_left"] = len(want) - len(ask)
    log(f"옛 방식 영상 {len(ask)}편 다시 판정 → 맞는 작품 {hit}편 (남은 {L['old_left']}편)")
    return (len(ask) + 49) // 50


def refresh_round(L, key, now, today, budget):
    """조회수: 15일 안 된 영상은 하루에 한 번, 카드 최고값 영상은 주 한 번 (지워졌으면 뺀다). 31일 넘으면 거의 안 변한다(11-05 측정)."""
    if budget <= 0:
        return 0
    young, tops = [], defaultdict(list)
    for i, r in L["v"].items():
        a = age_days(r[PUB], now)
        if a is not None and a <= 15 and now - r[SEEN] >= 1440:
            young.append(i)
        if r[VIEWS] >= 100000 and now - r[SEEN] >= 7 * 1440:
            tops[r[K]].append(i)
    old = [i for l in tops.values() for i in sorted(l, key=lambda i: -L["v"][i][VIEWS])[:10]]
    ask = (young + old)[:budget * 50]
    if not ask:
        return 0
    m = api_videos(L, ask, key, today)
    gone = 0
    for i in ask:
        x = m.get(i)
        if x:
            L["v"][i][VIEWS] = x["v"]; L["v"][i][SEEN] = now
        else:
            L["v"].pop(i, None); gone += 1
    log(f"조회수 {len(ask)}편 새로 받음 (지워짐 {gone})")
    return (len(ask) + 49) // 50


def is_block(e):
    return isinstance(e, yt.Blocked) or (isinstance(e, urllib.error.HTTPError) and e.code in (403, 429))


def filter_round(L, st, works, wk, key, now, today, deadline):
    """이번 달 + 4분 미만 검색 — 옛 검색에 안 나온 최근 영상과 모르는 채널을 찾는다"""
    done = L["flt"]
    order = sorted((w for w in works if now - done.get(w["i"], 0) >= 20 * 60), key=lambda w: done.get(w["i"], 0))[:FILTER_PER_ROUND]
    n = hit = did = 0
    for w in order:
        if time.time() > deadline or units_left(L, st, today, 2) <= 0:
            break
        did += 1
        c = L["cat"].get(wk.get(w["i"]), {})
        q = w["n"] + (" " + c["cast"][0] if c.get("cast") else "")
        try:
            d = yt.initial_data(yt.fetch("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&sp=" + SP_MONTH + "&hl=ko&gl=KR", tries=1))
            ids = [x["id"] for x in (yt._videos(d) + yt._lockups(d) if d else []) if x.get("id")]
        except Exception as e:
            if is_block(e):
                L["block"] = L.get("block", 0) + 1
                log(f"검색이 막힘 ({e}) → 필터 검색은 다음 회차에")
                break
            done[w["i"]] = now
            continue
        done[w["i"]] = now
        new = [i for i in ids if i not in L["v"] and i not in L["rej"]]
        for i in ids:
            if i in L["v"]:
                L["v"][i][SRC] |= 1
        m = api_videos(L, new, key, today)
        for i, x in m.items():
            if x.get("dur") and x["dur"] <= 180:
                n += 1
                if judge(L, dict(x, i=i), 1, now):
                    hit += 1
                else:
                    L["rej"][i] = 1
        time.sleep(1.5)
    log(f"이번 달 필터 검색 {did}작품 · 새 영상 {n}편 → 작품 {hit}편")


def tab_round(L, st, key, now, today, deadline):
    """첫 등록: 채널 Shorts 탭 첫 화면(48편) — RSS 15편으로는 30일이 안 보이는 채널이 많다 (39곳 대조에서 30%만 보임)"""
    ch = L["ch"]
    todo = sorted((c for c, x in ch.items() if not x.get("tab") and x.get("n", 0) >= 4 and film(x) and not person(x) and x.get("s", 0) >= 1), key=lambda c: -ch[c].get("s", 0))[:TAB_PER_ROUND]
    done = n = hit = 0
    for c in todo:
        if time.time() > deadline or units_left(L, st, today, 2) <= 0:
            break
        try:
            d = yt.initial_data(yt.fetch(f"https://www.youtube.com/channel/{c}/shorts?hl=ko&gl=KR", tries=1))
            ids = [x["id"] for x in yt._lockups(d or {}) if x.get("id")]
        except Exception as e:
            if is_block(e):
                L["block"] = L.get("block", 0) + 1
                log(f"채널 탭이 막힘 ({e}) → 다음 회차에")
                break
            ch[c]["tab"] = now
            continue
        ch[c]["tab"] = now
        done += 1
        prev = set(ch[c].get("ids") or [])
        new = [i for i in ids if i not in L["v"] and i not in prev and i not in L["rej"]]
        for i in ids:
            if i in L["v"]:
                L["v"][i][SRC] |= 4
        m = api_videos(L, new, key, today)
        for i, x in m.items():
            if x.get("dur") and x["dur"] <= 180:
                n += 1
                if judge(L, dict(x, i=i), 4, now):
                    hit += 1
                else:
                    L["rej"][i] = 1
        time.sleep(0.8)
    left = sum(1 for x in ch.values() if not x.get("tab") and x.get("n", 0) >= 4 and film(x) and not person(x) and x.get("s", 0) >= 1)
    L["tab_left"] = left
    log(f"채널 탭 첫 등록 {done}곳 · 영상 {n}편 → 작품 {hit}편 (남은 {left}곳)")


def prune(L, now):
    """장부가 커지지 않게: 40일 안 영상 + 작품마다 조회수 큰 60편만"""
    by = defaultdict(list)
    for i, r in L["v"].items():
        by[r[K]].append(i)
    for k, ids in by.items():
        if len(ids) <= 60:
            continue
        ids.sort(key=lambda i: -L["v"][i][VIEWS])
        for i in ids[60:]:
            a = age_days(L["v"][i][PUB], now)
            if a is None or a > 40:
                del L["v"][i]
    for c in list(L["dead"]):
        if now - L["dead"][c] > 90 * 1440:
            del L["dead"][c]
    L["units"] = dict(sorted(L["units"].items())[-10:])
    keep = {w for w, t in L["flt"].items() if now - t < 7 * 1440}
    L["flt"] = {w: L["flt"][w] for w in keep}


# ── 화면에 줄 것 ─────────────────────────────────────────
def cards(L, st, data, works, wk):
    now = now_min()
    ch = L["ch"]
    ser = R.series(L["cat"])
    members = defaultdict(list)
    for k, g in ser.items():
        members[g].append(k)
    by = defaultdict(list)
    for i, r in L["v"].items():
        x = ch.get(r[CID])
        if (r[FLAG] & 2) or film(x):
            by[r[K]].append((i, r))
    name = lambda c: L["nm"].get(c, "") or (ch.get(c) or {}).get("t", "")
    isnc = lambda r: bool(r[FLAG] & 1) or person(ch.get(r[CID]))
    out, totals = {}, Counter()
    names = defaultdict(list)
    for k, c in L["cat"].items():
        names[R.norm(c["n"])].append(k)
    bucket = lambda v: "b10" if v >= 100000 else "b1" if v >= 10000 else "b0"
    for i, r in L["v"].items():
        a = age_days(r[PUB], now)
        if a is None or a > 30 or isnc(r) or OFF.search(name(r[CID])):
            continue
        s, l = bool(r[SRC] & 1), bool(r[SRC] & 6)
        b = bucket(r[VIEWS])
        totals[b + "S"] += s; totals[b + "L"] += l; totals[b + "B"] += s and l; totals[b + "U"] += 1
    for w in data.get("works", []):
        k = wk.get(w["i"])
        if not k:
            continue
        group = members.get(ser.get(k), [k]) if k in ser else [k]
        rows, own, nc = [], [], []
        for g in group:
            for i, r in by.get(g, []):
                row = [i, r[TITLE], name(r[CID]), r[CID], r[VIEWS], r[PUB], 0]
                if isnc(r):
                    nc.append(row)
                    continue
                rows.append(row)
                if g == k:
                    own.append(row)
        pan = [(i, r) for i, r in by.get(PAN + R.norm(w["n"]), []) if not isnc(r)]
        # 같은 이름을 못 가른 영상: 다른 작품 쪽이 거의 안 잡히면 이 작품으로 친다 (탈주 2024 — 330만이 여기 있었음). 비슷하게 잡히면 안 센다 (트리거)
        others = sum(len(by.get(o, [])) for o in names.get(R.norm(w["n"]), []) if o != k)
        pan_in = bool(pan) and len(by.get(k, [])) >= 5 * others
        if pan_in:
            rows += [[i, r[TITLE], name(r[CID]), r[CID], r[VIEWS], r[PUB], 0] for i, r in pan]
        rows.sort(key=lambda v: -v[4])
        rec = {"v": rows, "ht": w.get("ht") or [None, None], "off": w.get("off") or [], "at": now}
        j = scan.judge(w, rec, now)
        j.update(i=w["i"], n=w["n"], risk=w.get("risk"), riskwhy=w.get("riskwhy", ""))
        how = [h for h in (w.get("en") or {}).get("how", []) if not h.endswith("뜸")]
        e = scan.entry(j, {w["i"]: (10 if how else 0, how)})
        c = j.get("cp") or {}
        r30 = lambda l: [v for v in l if (age_days(v[5], now) or 999) <= 30]
        o30 = r30(own)
        src = Counter()
        for g in group + ([PAN + R.norm(w["n"])] if pan_in else []):
            for i, r in by.get(g, []):
                if (age_days(r[PUB], now) or 999) <= 30 and not isnc(r):
                    src["s"] += bool(r[SRC] & 1); src["l"] += bool(r[SRC] & 6); src["b"] += bool(r[SRC] & 1 and r[SRC] & 6)
        out[w["i"]] = {"st": j.get("st"), "v": e.get("v"), "s": e.get("s"), "why": e.get("why"), "ch": c.get("ch", 0), "n": c.get("n", 0), "m30": c.get("m30", 0), "cs": c.get("s", 0),
                       "n100": j.get("n100", 0), "top": ({"id": rows[0][0], "t": rows[0][1], "ch": rows[0][2], "v": rows[0][4]} if rows else None),
                       "riv": c.get("riv", [])[:6], "src": dict(src),
                       "own": ({"ch": len({v[3] for v in o30}), "n": len(o30), "m30": max((v[4] for v in o30), default=0)} if len(group) > 1 else None),
                       "ser": ([L["cat"][g]["n"] for g in group if g in L["cat"]][:6] if len(group) > 1 else None),
                       "nc": ({"n": len(nc), "top": max(v[4] for v in nc)} if nc else None),
                       "pan": ({"n": len(pan), "top": max(r[VIEWS] for _, r in pan), "inc": pan_in} if pan else None)}
    today = kst(now).date().isoformat()
    active = sum(1 for x in ch.values() if x.get("r"))
    stat = {"at": kst(now).strftime("%Y-%m-%d %H:%M"), "ch": len(ch), "film": sum(1 for x in ch.values() if x.get("n", 0) >= 4 and film(x) and not person(x)), "person": sum(1 for x in ch.values() if person(x)), "read": active,
            "vids": len(L["v"]), "cat": len(L["cat"]), "cat_todo": len(L["cat_todo"]), "units": L["units"].get(today, 0), "old_left": L.get("old_left", 0),
            "tab_left": L.get("tab_left", 0), "block": L.get("block", 0), "tot": dict(totals), "since": L.get("since")}
    return {"stat": stat, "w": out}


# ── 한 번 돌기 ──────────────────────────────────────────
def fresh():
    return {"ver": 1, "since": kst(now_min()).strftime("%Y-%m-%d"), "cat": {}, "cat_todo": {}, "ch": {}, "dead": {}, "nm": {}, "v": {}, "gen": {}, "rej": {}, "flt": {}, "units": {}}


def read_box(path, pw):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    return lock.open_(json.loads(s[s.index("{"):].rstrip().rstrip(";")), pw)


def write(path, body):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(path + ".tmp", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    ap.add_argument("--minutes", type=float, default=8)
    a = ap.parse_args()
    pw, key = scan.secret("RADAR_PASSWORD", "password.txt"), scan.secret("YOUTUBE_API_KEY", "youtube_key.txt")
    if not pw or not key:
        sys.exit("비밀번호나 유튜브 키가 없음")
    t0 = time.time()
    deadline = t0 + a.minutes * 60
    lp, inp_p = os.path.join(a.out, "ledger.enc.json"), os.path.join(a.out, "ledger_in.enc.json")
    st = read_box(os.path.join(a.out, "state.enc.json"), pw)
    data = read_box(os.path.join(a.out, "data.enc.js"), pw)
    works = data.get("works", [])
    L = fresh()
    if os.path.exists(lp):
        try:
            L = read_box(lp, pw)
        except Exception as e:
            log(f"지난 장부를 못 풂 → 새로 시작 ({e})")
    inp = {}
    if os.path.exists(inp_p):
        try:
            inp = read_box(inp_p, pw)
        except Exception as e:
            log(f"검색 넘겨받기 못 풂 ({e})")
    now, today = now_min(), kst(now_min()).date().isoformat()
    ready = ensure_catalog(L, st, works, t0 + min(a.minutes, 7) * 60)
    log(f"작품 목록 {len(L['cat'])}편 · 주연 받을 것 {len(L['cat_todo'])}편")
    if ready:
        R.load(L["cat"])
        L["v_ch"] = {r[CID] for r in L["v"].values()}
        wk = work_keys(L["cat"], works)
        seed_channels(L, st, now)
        feed_round(L, inp, now)
        round_units = max(60, UNIT_DAY // 24)
        # 긁기(필터·탭)는 시간의 절반까지만, 나머지는 RSS
        rss_round(L, now, t0 + a.minutes * 60 * 0.55)
        L["v_ch"] = {r[CID] for r in L["v"].values()}
        left = units_left(L, st, today, round_units)
        left -= need_round(L, st, key, now, today, min(left, round_units // 8))
        left -= refresh_round(L, key, now, today, min(left, round_units // 6))
        left -= backfill_round(L, st, key, now, today, min(left, round_units // 2))
        filter_round(L, st, works, wk, key, now, today, t0 + a.minutes * 60 * 0.8)
        tab_round(L, st, key, now, today, deadline)
        n = inherit(L, now)
        if n:
            log(f"같은 설명으로 {n}편 더 잡음")
        L.pop("v_ch", None)
        prune(L, now)
    else:
        L.pop("v_ch", None)
        log("작품 목록을 다 못 받음 → 다음 회차에 이어서")
    write(lp, json.dumps(lock.seal(L, pw)))  # 카드를 만들다 실패해도 이번 회차에 모은 건 남게 먼저 저장
    if ready and os.path.exists(inp_p):
        os.remove(inp_p)
    if ready:
        out = cards(L, st, data, works, wk)
        write(os.path.join(a.out, "new.enc.js"), "window.YD_NEW = " + json.dumps(lock.seal(out, pw)) + ";\n")
        diff = sum(1 for w in works if w["i"] in out["w"] and (w.get("en") or {}).get("v") != out["w"][w["i"]]["v"])
        log(f"끝: 채널 {out['stat']['ch']}곳 · 영상 {out['stat']['vids']}편 · 오늘 {out['stat']['units']}유닛 · 판정 다른 작품 {diff}/{len(out['w'])}편 · {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
