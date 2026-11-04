# -*- coding: utf-8 -*-
"""작품 시청처 — 한국에서 구독으로 볼 수 있는 서비스. 저스트워치 GraphQL(키 없음, 공식 API 아님).
   회차마다 minutes 분만 묻고, 물어본 작품은 refresh_days 뒤에 다시 묻는다.
   한국 영화 중 로마자 제목으로만 등록된 것이 많아서(범죄도시3 → Beomjoidosi 3) 한글을 로마자로 바꿔서도 맞춰 본다."""
import re, json, time, difflib, urllib.request

URL = "https://apis.justwatch.com/graphql"
QUERY = ("query S($f:TitleFilter!,$c:Country!,$l:Language!,$n:Int!){popularTitles(country:$c,filter:$f,first:$n,sortBy:POPULAR,sortRandomSeed:0)"
         "{edges{node{content(country:$c,language:$l){title originalTitle originalReleaseYear}"
         "offers(country:$c,platform:WEB){monetizationType package{clearName}}}}}}")
# 저스트워치 이름 앞부분 → 화면 이름 (이 순서대로 보여 줌)
SERVICES = [("Netflix", "넷플릭스"), ("Disney Plus", "디즈니+"), ("TVING", "티빙"), ("Watcha", "왓챠"), ("wavve", "웨이브"),
            ("Coupang Play", "쿠팡플레이"), ("Amazon Prime Video", "프라임비디오"), ("Apple TV", "애플TV")]
CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def norm(s):
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


def roman(s):
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        out.append(CHO[c // 588] + JUNG[c % 588 // 28] + JONG[c % 28] if 0 <= c < 11172 else ch)
    return norm("".join(out))


def ask(q):
    body = json.dumps({"query": QUERY, "variables": {"f": {"searchQuery": q}, "c": "KR", "l": "ko", "n": 6}}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return [e["node"] for e in json.load(r)["data"]["popularTitles"]["edges"]]


def parts(s):
    return [norm(p) for p in re.split(r"[:：]", s or "")]


def loose(name, title):
    """부제 빼면 같은 제목 — 가문의 위기 ↔ 가문의 영광 2: 가문의 위기, 이퀄라이저 ↔ 더 이퀄라이저"""
    w, a = norm(name), norm(title)
    if len(w) < 3 or len(a) < 3:
        return False
    return w in parts(title) or w == norm(re.sub(r"^(더|The)\s+", "", title)) or a in parts(name) or (w.startswith(a) and len(a) / len(w) >= .7)


def pick(nodes, names, year):
    want = {norm(x) for x in names} - {""}
    y = int(year) if str(year).isdigit() else None
    near = lambda c: y is None or abs((c.get("originalReleaseYear") or 0) - y) <= 1
    cs = [(n, n["content"]) for n in nodes if near(n["content"])]
    for n, c in cs:
        if norm(c["title"]) in want or norm(c.get("originalTitle")) in want:
            return n
    for n, c in cs:
        if any(loose(x, c["title"]) for x in names):
            return n
    if y is None:
        return None
    for n, c in cs:
        if c["title"].isascii() and any(difflib.SequenceMatcher(None, roman(x), norm(c["title"])).ratio() >= .8 for x in names if not x.isascii()):
            return n
    return None


def services(node):
    got = {o["package"]["clearName"] for o in node["offers"] if o["monetizationType"] in ("FLATRATE", "FREE", "ADS")}
    return [show for key, show in SERVICES if any(g.startswith(key) for g in got)]


def look(w, C, wait=.3):
    al = (C.get("alias") or {}).get(w["n"], [])
    names = list(w.get("names") or [w["n"]]) + al
    for q in al + [w["n"]]:
        hit = pick(ask(q), names, w.get("y"))
        if hit:
            return {"f": 1, "s": services(hit)}
        time.sleep(wait)
    return {"f": 0, "s": []}


def refresh(st, works, C, now, log):
    """st["ott"][작품] = {f: 찾음 여부, s: 서비스 목록, m: 물어본 때(분), sig: 이름|연도}"""
    o = st.setdefault("ott", {})
    keep = {w["i"] for w in works}
    for k in [k for k in o if k not in keep]:
        del o[k]
    sig = lambda w: f'{w["n"]}|{w.get("y")}'
    old = lambda w: w["i"] not in o or o[w["i"]].get("sig") != sig(w) or now - o[w["i"]]["m"] >= C["refresh_days"] * 1440
    due = sorted(filter(old, works), key=lambda w: (o.get(w["i"]) or {}).get("m", 0))
    t0, done, bad = time.time(), 0, 0
    for w in due:
        if time.time() - t0 > C["minutes"] * 60 or bad >= 3:
            break
        try:
            o[w["i"]] = dict(look(w, C), m=now, sig=sig(w))
            done, bad = done + 1, 0
        except Exception as e:
            bad += 1
            log(f"시청처 못 물어봄 {w['n']}: {type(e).__name__} {e}")
        time.sleep(.3)
    log(f"시청처: 이번 {done}편, 남은 {len(due) - done}편")
