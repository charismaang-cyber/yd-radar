# -*- coding: utf-8 -*-
"""작품 시청처 — 한국에서 구독으로 볼 수 있는 서비스. 저스트워치 GraphQL(키 없음, 공식 API 아님).
   회차마다 minutes 분만 묻고, 물어본 작품은 refresh_days 뒤에 다시 묻는다.
   한국 영화 중 로마자 제목으로만 등록된 것이 많아서(범죄도시3 → Beomjoidosi 3) 한글을 로마자로 바꿔서도 맞춰 본다.
   저스트워치에 구독 시청처가 없으면 보조로 두 군데 더 본다(11-08):
     키노라이츠 검색 화면(국내 OTT 모음, 쿠팡플레이·라프텔·씨네폭스와 대여·구매까지) — 기다리다 미쳐 → 왓챠 대여
     한국영상자료원 유튜브 «한국고전영화» 채널(한국 영화만, 전편 무료) — 노는 계집 창 → 창(노는계집 창) (1997)"""
import re, json, time, difflib, urllib.parse, urllib.request
import yt

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
SEASON = re.compile(r"\s*(시즌|season|class|클래스|파트|part)\s*\d+\s*$", re.I)
VER = 3  # 제목 맞추는 법이 바뀌면 올린다 → 못 찾았던 작품(구독 시청처가 없던 작품)만 다시 묻는다. 3: 키노라이츠·한국고전영화 보조

# 키노라이츠 — 검색 화면(Next.js)이 결과를 HTML 안에 실어 보낸다. 공식 API 아님
KL_URL = "https://kinolights.com/search?keyword="
KL_NAME = {"netflix": "넷플릭스", "disney": "디즈니+", "tving": "티빙", "watcha-play": "왓챠", "wavve": "웨이브",
           "coupang-play": "쿠팡플레이", "amazon": "프라임비디오", "apple": "애플TV", "laftel": "라프텔", "cinefox": "씨네폭스", "vigloo": "비글루"}
KL_SUB = ("streaming", "free", "ads")  # 대여 rental · 구매 buy 는 따로(r)
KL_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
# 한국영상자료원 유튜브 — 채널 안 검색. 영상 제목은 «창(노는계집 창) (1997) / Downfall (...)», «[4K] 은행나무 침대(1995) / ...»
KOFA = "유튜브 무료(영상자료원)"
KOFA_URL = "https://www.youtube.com/user/KoreanFilm/search?hl=ko&gl=KR&query="
KOFA_T = re.compile(r"^(?:\[[^\]]*\]\s*)*(.+?)\s*\((\d{4})\)")
ORDER = [show for _, show in SERVICES] + ["라프텔", "씨네폭스", KOFA]


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
    for n, c in cs:  # 로마자로만 등록된 한국 작품: 제목이나 원제가 로마자 (노량 → Noryang: Jugeumui Bada, 로얄로더 → Ro-yallodeo)
        latin = [norm(t) for t in (c["title"], c.get("originalTitle")) if t and t.isascii()]
        han = [roman(x) for x in names if not x.isascii()]
        if any(len(r) >= 5 and difflib.SequenceMatcher(None, r, t).ratio() >= .8 for r in han for t in latin):
            return n
    return None


def show_base(w):
    """드라마는 시즌마다 따로 등록되지 않는다: 오징어 게임 시즌 2 · 약한영웅 Class 1 · 모범택시 2 → 앞 이름으로 찾는다.
       영화는 속편이 다른 작품이라 하지 않는다."""
    if w.get("k") not in ("OTT", "방송", "미드", "애니"):
        return None
    s = SEASON.sub("", w["n"])
    if s == w["n"]:
        s = re.sub(r"\s+\d+\s*$", "", w["n"])
    return s if s != w["n"] and len(norm(s)) >= 2 else None


def pick_show(nodes, base, year):
    """시즌 붙은 드라마: 이름이 똑같고, 그 시즌과 같은 해거나 그 전에 시작한 것"""
    y = int(year) if str(year).isdigit() else None
    for n in nodes:
        c = n["content"]
        if norm(base) in (norm(c["title"]), norm(c.get("originalTitle"))) and (y is None or (c.get("originalReleaseYear") or 9999) <= y + 1):
            return n
    return None


def services(node):
    got = {o["package"]["clearName"] for o in node["offers"] if o["monetizationType"] in ("FLATRATE", "FREE", "ADS")}
    return [show for key, show in SERVICES if any(g.startswith(key) for g in got)]


def find(w, C, wait=.3):
    al = (C.get("alias") or {}).get(w["n"], [])
    names = list(w.get("names") or [w["n"]]) + al
    for q in al + [w["n"]] + ([w["n"].replace(" ", "")] if " " in w["n"] else []):  # 띄어쓰기만 다른 것: 후 아 유 ↔ 후아유
        hit = pick(ask(q), names, w.get("y"))
        if hit:
            return hit
        time.sleep(wait)
    base = show_base(w)
    if base:
        hit = pick_show(ask(base), base, w.get("y"))
        if hit:
            return hit
        time.sleep(wait)
    return None


def order(xs):
    return sorted(set(xs), key=lambda s: (ORDER.index(s) if s in ORDER else len(ORDER), s))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": yt.UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ── 보조 1: 키노라이츠 ──
def kl_ask(q):
    """키노라이츠 검색 상위 10편 → [{id, titleKr, openYear, contentTypes, vodOfferItems:[{providerTechnicalName, monetizationType}]}]"""
    fl = "".join(json.loads('"' + m + '"') for m in KL_PUSH.findall(get(KL_URL + urllib.parse.quote(q))))
    i = fl.find('"searchContentsByKeyword"')
    s = fl.rfind('{"type":"next"', 0, i) if i >= 0 else -1
    if s < 0:
        raise RuntimeError("검색 화면 모양이 바뀜")
    obj, _ = json.JSONDecoder().raw_decode(fl, s)
    return [it["content"] for it in obj["value"]["data"]["searchContentsByKeyword"]["items"]]


def kl_pick(cs, names, year, w):
    """저스트워치 pick 과 같은 기준(이름 같음 → 부제 뺀 이름, 연도 ±1). 키노라이츠는 드라마를 시즌마다 따로 올려서
       드라마는 «오징어 게임 시즌 1» 처럼 시즌 뗀 이름이 같아도 인정"""
    want = {norm(x) for x in names} - {""}
    y = int(year) if str(year).isdigit() else None
    oy = lambda c: int(c["openYear"]) if str(c.get("openYear") or "").isdigit() else 0
    cs = [c for c in cs if y is None or abs(oy(c) - y) <= 1]
    for c in cs:
        if norm(c.get("titleKr")) in want:
            return c
    for c in cs:
        if any(loose(x, c.get("titleKr") or "") for x in names):
            return c
    if w.get("k") in ("OTT", "방송", "미드", "애니"):
        for c in cs:
            if norm(SEASON.sub("", c.get("titleKr") or "")) in want:
                return c
    return None


def kl_offers(c):
    """→ (구독·무료 서비스, 대여·구매만 되는 서비스)"""
    name = lambda o: KL_NAME.get(o.get("providerTechnicalName"), o.get("providerTechnicalName") or "?")
    got = c.get("vodOfferItems") or []
    s = {name(o) for o in got if o.get("monetizationType") in KL_SUB}
    return s, {name(o) for o in got} - s


# ── 보조 2: 한국영상자료원 유튜브 (한국 영화만) ──
def secs(s):
    n = 0
    for p in (s or "").split(":"):
        n = n * 60 + int(p) if p.isdigit() else n
    return n


def kofa_ask(q):
    d = None
    for i in range(3):  # 가끔 자료 없는 화면이 온다(막힘 아님) → 조금 쉬었다 다시 (yt.search 와 같은 방식)
        d = yt.initial_data(yt.fetch(KOFA_URL + urllib.parse.quote(q)))
        if d:
            break
        time.sleep(2 + 2 * i)
    if not d:
        raise yt.Blocked("no ytInitialData")
    return [{"id": v.get("videoId"), "t": yt.text(v.get("title")), "dur": secs(yt.text(v.get("lengthText")))}
            for v in yt.walk(d, "videoRenderer")]


def kofa_pick(vs, names, year):
    """제목 앞부분(괄호 안 다른 이름까지)이 작품 이름과 같고, 연도 ±1, 50분 넘는 전편만"""
    if not str(year).isdigit():
        return None
    want = {norm(x) for x in names} - {""}
    for v in vs:
        m = KOFA_T.match(v["t"] or "")
        if not m or abs(int(m.group(2)) - int(year)) > 1 or v["dur"] < 50 * 60:
            continue
        kr = m.group(1)
        if want & ({norm(kr)} | {norm(p) for p in re.split(r"[()]", kr)}):
            return v
    return None


def look(w, C, wait=.3):
    """{f: 어디서든 찾음, s: 구독·무료 서비스, r: 대여·구매만, kl: 키노라이츠 작품 id, yt: 고전영화 영상 id, x: 보조 조회 오류}"""
    hit = find(w, C, wait)
    out = {"f": 1 if hit else 0, "s": services(hit) if hit else [], "r": []}
    if out["s"]:
        return out
    al = (C.get("alias") or {}).get(w["n"], [])
    names = list(w.get("names") or [w["n"]]) + al
    qs = list(dict.fromkeys(al + [w["n"]]))
    x = []
    try:
        for q in qs:
            c = kl_pick(kl_ask(q), names, w.get("y"), w)
            if c:
                s, r = kl_offers(c)
                out.update(f=1, kl=c["id"], s=order(s), r=order(r))
                break
            time.sleep(wait)
    except Exception as e:
        x.append(f"키노라이츠 {type(e).__name__} {e}"[:120])
    if w.get("k") == "영화" and not out["s"]:
        try:
            for q in qs:
                v = kofa_pick(kofa_ask(q), names, w.get("y"))
                if v:
                    out.update(f=1, yt=v["id"], s=order(out["s"] + [KOFA]))
                    break
                time.sleep(wait)
        except Exception as e:
            x.append(f"고전영화 {type(e).__name__} {e}"[:120])
    if x:
        out["x"] = x
    return out


def refresh(st, works, C, now, log):
    """st["ott"][작품] = {f: 찾음 여부, s: 서비스 목록, r: 대여·구매만, m: 물어본 때(분), sig: 이름|연도, v: 맞추는 법 판, x: 보조 조회 오류} (look 참고)"""
    o = st.setdefault("ott", {})
    keep = {w["i"] for w in works}
    for k in [k for k in o if k not in keep]:
        del o[k]
    sig = lambda w: f'{w["n"]}|{w.get("y")}'
    # 구독 시청처를 못 찾은 것은 맞추는 법이 바뀌면 바로 다시. 보조 조회가 오류 난 것은 하루 뒤 다시
    retry = lambda e: (not e["s"] and e.get("v", 1) < VER) or (e.get("x") and now - e["m"] >= 1440)
    old = lambda w: w["i"] not in o or o[w["i"]].get("sig") != sig(w) or retry(o[w["i"]]) or now - o[w["i"]]["m"] >= C["refresh_days"] * 1440
    due = sorted(filter(old, works), key=lambda w: (o.get(w["i"]) or {}).get("m", 0))
    t0, done, bad = time.time(), 0, 0
    for w in due:
        if time.time() - t0 > C["minutes"] * 60 or bad >= 3:
            break
        try:
            o[w["i"]] = dict(look(w, C), m=now, sig=sig(w), v=VER)
            done, bad = done + 1, 0
            for e in o[w["i"]].get("x", []):
                log(f"시청처 보조 조회 못 함 {w['n']}: {e}")
        except Exception as e:
            bad += 1
            log(f"시청처 못 물어봄 {w['n']}: {type(e).__name__} {e}")
        time.sleep(.3)
    log(f"시청처: 이번 {done}편, 남은 {len(due) - done}편")
