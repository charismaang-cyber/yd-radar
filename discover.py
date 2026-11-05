# -*- coding: utf-8 -*-
"""작품 늘리기 — 사람이 고른 works.txt 밖의 작품을 저절로 찾는다.
   1) 후보(한 달에 한 번): 위키백과 '분류:N년 영화' 중 한국어 영화(1990년~작년),
      '분류:N년 시작한 대한민국의 텔레비전 프로그램' 중 OTT 오리지널 드라마(넷플릭스·티빙·디즈니+ 등).
      결은 위키백과 분류(조폭 영화·학교 폭력·일제 강점기 …)로 짐작한다.
   2) 거르기(회차마다 몇 분씩, 키 안 씀): #제목 쇼츠 화면을 긁어 제일 큰 조회수를 본다.
   3) 큰 쇼츠(min_top 넘음)가 있는 것만 작품 목록에 올려 보통 작품처럼 잰다. 배급사는 그때 위키백과 정보상자에서."""
import re, json, time, urllib.parse, urllib.request
from datetime import date
import actors, yt

VER = 2  # 후보 고르는 법이 바뀌면 올린다 → 다음 회차에 후보를 새로 받고, 전에 못 봤던 작품을 바로 거른다 (2: 두 글자 제목·주연 빈칸)
SEC = re.compile(r"^==+\s*(출연|출연진|배역|등장\s*인물|캐스트|캐스팅|주요\s*인물)\s*==+\s*$(.*?)(?=^==[^=]|\Z)", re.M | re.S)
NAME = re.compile(r"[가-힣]{2,5}")

OTT_CAT = re.compile(r"넷플릭스|티빙|TVING|디즈니|쿠팡플레이|웨이브|wavve|왓챠|오리지널")
# 위키백과 분류 낱말 → 우리 결 (위에서부터 먼저 맞는 것)
GYEOL = [("조폭·양아치 코미디", r"(조폭|깡패|건달|갱스터).*코미디|코미디.*(조폭|깡패|건달)"),
         ("조폭·건달", r"조폭|깡패|건달|갱스터|폭력 조직"),
         ("일제강점기", r"일제 ?강점기|독립운동|일본 제국|항일"),
         ("전쟁·군대·북한", r"전쟁|군대|군인|북한|남북|분단|첩보|한국 전쟁"),
         ("학교·학폭 응징", r"학교 폭력|괴롭힘|따돌림"),
         ("정치·권력", r"정치|대통령|민주화|쿠데타|5·18|광주 민주화|권력"),
         ("계급·금수저 역전", r"재벌|빈부|계급"),
         ("형사·범죄", r"경찰|형사|범죄|수사|살인|연쇄|사기|강도|복수|교도소|감옥|마약|검사"),
         ("직장·갑질 참교육", r"직장|회사원|노동"),
         ("한국 코미디", r"코미디"),
         ("멜로", r"로맨스|멜로|사랑"),
         ("고부갈등·가족", r"고부|시어머니|며느리"),
         ("감동·인생", r"가족|어머니|아버지|실화|휴먼|드라마 영화|장애|노인|성장")]


# 애니 후보 — 저작권 위험이 있어도 빼지 않는다(화면에 저작권 높음으로 표시). 성인물·단편·목록 문서만 뺀다.
ANI_DOC_SKIP = re.compile(r"목록|등장인물|에피소드|주제가|의 음악|사운드트랙|OST")
ANI_CAT_SKIP = re.compile(r"성인 애니메이션|포르노|에로|헨타이|단편 애니메이션|다큐멘터리")
ANI_TREE_SKIP = re.compile(r"목록|등장인물|에피소드|음악|성우|제작사|제작자|단체|학교|잡지|토막글|포스터|캐릭터|감독")
ANI_D = [("애니플렉스", r"애니플렉스|A-1|클로버웍스|CloverWorks"), ("투니버스", r"투니버스"), ("KBS", r"KBS"), ("MBC", r"MBC"), ("SBS", r"SBS"), ("EBS", r"EBS"),
         ("넷플릭스", r"넷플릭스"), ("지브리", r"지브리"), ("픽사", r"픽사"), ("디즈니", r"디즈니"), ("드림웍스", r"드림웍스"), ("일루미네이션", r"일루미네이션"),
         ("소니 애니", r"소니 픽처스 애니메이션"), ("토에이", r"도에이|토에이"), ("워너", r"워너 브라더스"), ("니켈로디언", r"니켈로디언")]
ANI_GYEOL = [("애니 로맨스·일상", r"로맨스|연애|러브 코미디|순정|일상물"), ("애니 스포츠", r"스포츠|야구|농구|축구|배구|테니스|복싱|권투"),
             ("애니 미스터리·다크", r"추리|미스터리|호러|공포|스릴러|심리"), ("애니 이세계·판타지", r"이세계|판타지"),
             ("애니 액션·배틀", r"액션|전투|격투|닌자|메카|로봇"), ("애니 개그·추억", r"코미디|개그|시트콤|부조리")]


def anime_gyeol(cats, y):
    s = " ".join(cats)
    if "애니메이션 영화" in s:
        return "애니 영화(일본)" if re.search(r"일본|지브리|도호|도에이|쇼치쿠", s) else "애니 영화(일본 밖)"
    for g, pat in ANI_GYEOL:
        if re.search(pat, s):
            return g
    return "추억 만화(옛날)" if y and y < 2005 else "애니 기타"


def _subcats(cat):
    out, cont = [], {}
    while True:
        r = actors.api(action="query", list="categorymembers", cmtitle="분류:" + cat, cmlimit="max", cmtype="subcat", **cont)
        out += [m["title"].split(":", 1)[-1] for m in r.get("query", {}).get("categorymembers", [])]
        if "continue" not in r:
            return out
        cont = r["continue"]


def _anime_make(t, cats):
    """위키 문서 하나 → 후보. 틀·목록·성인물은 None"""
    if re.match(r"(틀|위키백과|포털|사용자|모듈|도움말|파일|분류):", t) or ANI_DOC_SKIP.search(t) or any(ANI_CAT_SKIP.search(c) for c in cats):
        return None
    ys = [int(m.group(1)) for c in cats for m in [re.match(r"(\d{4})년 (?:컴퓨터 )?애니메이션", c)] if m] \
        or [int(m.group(1)) for c in cats for m in [re.match(r"(\d{4})년 (?:시작한|만화)", c)] if m]
    y, s, n = min(ys) if ys else 0, " ".join(cats), actors.short(t)
    c = {"n": n, "y": y, "k": "애니", "g": anime_gyeol(cats, y), "d": next((d for d, p in ANI_D if re.search(p, s)), "")}
    if n != t or plain_len(n) < 3:  # 흔한 제목은 '#제목 애니' 로 재서 '애니'도 보여야 인정
        c.update(amb=True, cast=[])
    return c


def anime_step(st, cfg, log, today, minutes):
    """애니 후보 모으기: 연도 분류(N년 애니메이션·애니메이션 영화·만화) + 방송 애니 분류 나무(둘째 단까지).
       문서가 6천 편이 넘어 한 번에 받으면 오래 걸린다(집에서 36분) → 회차마다 minutes 분씩 이어 받아 다른 작품 재기를 안 막는다."""
    d, now, t0 = st["disc"], int(time.time() // 60), time.time()
    a = d.setdefault("ani", {"m": 0, "tree": [], "roots": [], "done": []})
    if not a["tree"] and not a["roots"]:
        if now - a["m"] < cfg["refresh_days"] * 1440:
            return
        a.update(m=now, done=[], tree=[[c, 0] for c in cfg.get("anime_trees") or []],
                 roots=[f"{y}년 {x}" for y in range(cfg["anime_from_year"], today.year + 1) for x in ("만화", "컴퓨터 애니메이션 영화", "애니메이션 영화", "애니메이션")])
    while (a["tree"] or a["roots"]) and time.time() - t0 < minutes * 60:
        try:
            if a["tree"]:
                c, depth = a["tree"].pop()
                if c not in a["done"]:
                    a["done"].append(c)
                    a["roots"].append(c)
                    if depth < 2:
                        a["tree"] += [[x, depth + 1] for x in _subcats(c) if not ANI_TREE_SKIP.search(x)]
                continue
            for t, cats in _members_with_cats(a["roots"].pop()).items():
                if t not in d["cand"]:
                    c = _anime_make(t, cats)
                    if c:
                        d["cand"][t] = c
        except Exception as e:
            log(f"작품 늘리기: 애니 분류 못 받음 {e}")
    log(f"작품 늘리기: 애니 후보 {sum(c.get('k') == '애니' for c in d['cand'].values())}편 · 남은 분류 {len(a['tree']) + len(a['roots'])}개")


def gyeol_of(cats):
    s = " ".join(cats)
    for g, pat in GYEOL:
        if re.search(pat, s):
            return g
    return "기타(자동)"


def _members_with_cats(cat, only=None):
    """분류 안의 문서마다 그 문서의 분류들 (generator 로 한 번에 500개). only 를 주면 그 분류들만 물어봐서 가볍게."""
    out, cont = {}, {}
    extra = {"clcategories": "|".join("분류:" + c for c in only)} if only else {}
    while True:
        r = actors.api(action="query", generator="categorymembers", gcmtitle="분류:" + cat, gcmlimit="max", gcmtype="page",
                       prop="categories", cllimit="max", **extra, **cont)
        for p in r.get("query", {}).get("pages", []):
            out.setdefault(p["title"], []).extend(c["title"].split(":", 1)[-1] for c in p.get("categories", []))
        if "continue" not in r:
            return out
        cont = r["continue"]


def _cats(titles):
    """문서들의 분류 전부 (50개씩)"""
    out, titles = {}, list(titles)
    for i in range(0, len(titles), 50):
        cont = {}
        while True:
            r = actors.api(action="query", titles="|".join(titles[i:i + 50]), prop="categories", cllimit="max", **cont)
            for p in r.get("query", {}).get("pages", []):
                out.setdefault(p["title"], []).extend(c["title"].split(":", 1)[-1] for c in p.get("categories", []))
            if "continue" not in r:
                break
            cont = r["continue"]
    return out


def candidates(cfg, log, today=None):
    """{위키 제목: {n 이름, y 연도, k 영화/OTT, g 결, d 배급·플랫폼}}"""
    today = today or date.today()
    out = {}
    for y in range(cfg["from_year"], today.year):
        try:  # 그해 영화 중 한국 영화만 먼저 고르고(가볍게), 그것들의 분류를 다 받는다
            kor = [t for t, c in _members_with_cats(f"{y}년 영화", ["한국어 영화 작품", "대한민국의 영화 작품"]).items() if c]
            got = _cats(kor)
        except Exception as e:
            log(f"작품 늘리기: {y}년 영화 분류 못 받음 {e}")
            continue
        for t, cats in got.items():
            if any(re.search(r"애니메이션|다큐멘터리|단편 영화|포르노|에로", c) for c in cats):
                continue
            dist = next((m.group(1) for c in cats for m in [re.match(r"(.+?) 영화$", c)]
                         if m and re.search(r"엔터테인먼트|ENM|쇼박스|NEW|롯데|플러스엠|메가박스|시네마서비스|CJ|워너|소니|KT|콘텐츠판다|넥스트", m.group(1))), "")
            out[t] = {"n": actors.short(t), "y": y, "k": "영화", "g": gyeol_of(cats), "d": dist}
    for y in range(cfg["ott_from_year"], today.year + 1):
        try:
            got = _members_with_cats(f"{y}년 시작한 대한민국의 텔레비전 프로그램")
        except Exception as e:
            log(f"작품 늘리기: {y}년 OTT 분류 못 받음 {e}")
            continue
        for t, cats in got.items():
            plat = next((m.group(0) for c in cats for m in [OTT_CAT.search(c)] if m), "")
            if not plat or not any("드라마" in c for c in cats) or any("예능" in c for c in cats):
                continue
            out[t] = {"n": actors.short(t), "y": y, "k": "OTT", "g": gyeol_of(cats), "d": plat.replace("오리지널", "OTT")}
    # 위키백과 제목에 '(2023년 영화)' 같은 꼬리가 붙은 건 흔한 낱말(스위치·사마귀·스캔들…) → 주연 배우 이름을 같이 써야 다른 영상과 안 섞임
    # 두 글자 제목(곡성·명량·무빙)은 #태그가 너무 흔해서 같은 길로 찾는다
    amb = [t for t in out if actors.short(t) != t or plain_len(out[t]["n"]) < 3]
    who = casts(amb, log)
    for t in amb:
        out[t].update(amb=True, cast=who[t])
    log(f"작품 늘리기: 후보 {len(out)}편 (영화 {sum(v['k'] == '영화' for v in out.values())}, OTT {sum(v['k'] == 'OTT' for v in out.values())}, "
        f"흔한 제목 {len(amb)}편은 배우 이름 붙여 찾음)")
    return out


def tag_of(n):
    return re.sub(r"[^0-9A-Za-z가-힣_]", "", n)


def plain_len(n):
    return len(re.sub(r"[^0-9a-z가-힣]", "", n.lower()))


def wikidata_cast(qids):
    """위키데이터 '출연'(P161) → {qid: 한국어 이름들}. 못 받으면 그 묶음만 건너뜀."""
    out = {}
    get = lambda **p: json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(dict(p, action="wbgetentities", format="json")), headers=actors.UA), timeout=40).read())
    qids = list(qids)
    for i in range(0, len(qids), 40):
        try:
            d = get(ids="|".join(qids[i:i + 40]), props="claims")
            who = {q: [c["mainsnak"]["datavalue"]["value"]["id"] for c in d.get("entities", {}).get(q, {}).get("claims", {}).get("P161", [])
                       if c["mainsnak"].get("datavalue")][:6] for q in qids[i:i + 40]}
            ids, lab = sorted({x for v in who.values() for x in v}), {}
            for j in range(0, len(ids), 50):
                time.sleep(.3)
                for a, b in get(ids="|".join(ids[j:j + 50]), props="labels", languages="ko").get("entities", {}).items():
                    if b.get("labels", {}).get("ko"):
                        lab[a] = b["labels"]["ko"]["value"]
            for q, v in who.items():
                out[q] = [actors.short(lab[x]) for x in v if x in lab]
        except Exception:
            pass
        time.sleep(.3)
    return out


def casts(titles, log):
    """제목과 함께 검색할 이름 2명: 정보상자 출연 → 다른 칸·출연 절 → 위키데이터 → 그래도 없으면 감독.
       정보상자 출연이 읽히는 작품은 예전과 똑같이 둔다(검색어가 바뀌면 재 둔 기록이 처음부터 다시 시작된다)."""
    got, out, need = actors.pages(titles), {}, {}
    ok = lambda xs: [x for x in xs if NAME.search(x) and "[" not in x and "참조" not in x]
    for t in titles:
        w = got.get(t, {}).get("w", "")
        c = ok([actors.short(a) for a in actors.people(actors.field(w, "출연", "출연자", "주연"), 2)])
        if not c:
            c = ok([actors.short(a) for a in actors.people(actors.field(w, "배우", "출연진"), 2)])
        if not c:
            m = SEC.search(w)
            links = actors.LINK.findall(m.group(2)) if m else []
            c = list(dict.fromkeys(a for a in (actors.short(x[0].strip()) for x in links) if NAME.fullmatch(a)))[:2]
        out[t] = c
        if not c and got.get(t, {}).get("qid"):
            need[t] = got[t]["qid"]
    wd = wikidata_cast(need.values())
    filled = 0
    for t, q in need.items():
        out[t] = [a for a in wd.get(q, []) if NAME.fullmatch(a)][:2]
        filled += bool(out[t])
    boss = 0
    for t in titles:
        if not out[t]:  # 옛 영화·작은 영화는 배우 칸이 없기도 하다
            out[t] = ok([actors.short(a) for a in actors.people(actors.field(got.get(t, {}).get("w", ""), "감독"), 1)])
            boss += bool(out[t])
    log(f"작품 늘리기: 함께 검색할 이름 {sum(bool(v) for v in out.values())}/{len(titles)}편 (위키데이터 {filled}, 감독 {boss})")
    return out


def screen(st, cfg, have, minutes, log):
    """아직 안 본(또는 오래된) 후보의 #제목 쇼츠 화면을 긁어 제일 큰 조회수를 적는다. 키 안 씀."""
    d, now, t0, n = st["disc"], int(time.time() // 60), time.time(), 0
    soon = now - (cfg["rescreen_days"] - 7) * 1440  # 빈 화면·오류는 일시적일 때가 많아(명량·승부) 60일 말고 7일 뒤 다시
    todo = [k for k, c in d["cand"].items()
            if (plain_len(c["n"]) >= 3 or c.get("cast") or c.get("k") == "애니") and c["n"].replace(" ", "") not in have
            and now - d["seen"].get(k, [0])[0] >= cfg["rescreen_days"] * 1440]
    todo.sort(key=lambda k: (d["seen"].get(k, [0])[0], -d["cand"][k]["y"]))  # 처음 보는 것·최근 작품부터
    for k in todo:
        if time.time() - t0 > minutes * 60:
            break
        c = d["cand"][k]
        try:
            ani = c.get("k") == "애니"  # 애니는 #제목이 같은 영화·낱말과 섞이기 쉬워 전부 '제목 애니' 검색으로 본다
            if c.get("amb") or ani:  # 흔한 제목: '제목 + 주연' 검색 첫 화면 (배우를 모르면 건너뜀)
                who = "애니" if ani else (c.get("cast") or [""])[0]
                if not who:
                    d["seen"][k] = [now, None, 0]
                    continue
                r = yt.initial_data(yt.fetch("https://www.youtube.com/results?search_query="
                                             + urllib.parse.quote(f"{c['n']} {who}") + "&hl=ko&gl=KR")) or {}
                v, items = None, yt._lockups(r) + yt._videos(r)
                blank = not items
                if plain_len(c["n"]) < 3 or ani:  # 두 글자는 낱말이 흔하다: 결과 제목에 작품 이름이 있는 것만 (승부 이병헌 → 이병헌의 다른 영상 빼기)
                    want = c["n"].replace(" ", "").lower()
                    items = [x for x in items if want in (x.get("title") or "").replace(" ", "").lower()]
            else:
                v, _, items = yt.hashtag_page(tag_of(c["n"]))
                blank = not items and v is None
        except yt.Blocked:
            raise
        except Exception:
            d["seen"][k] = [soon, None, 0]
            continue
        d["seen"][k] = [soon if blank else now, v, max((x["v"] or 0 for x in items), default=0)]
        n += 1
        time.sleep(1.0)
    passed = sum(1 for s in d["seen"].values() if s[2] >= cfg["min_top"])
    log(f"작품 늘리기: 이번에 {n}편 거름 · 지금까지 {len(d['seen'])}/{len(d['cand'])}편 봄 · 큰 쇼츠 있음 {passed}편")


def fill_dist(st, keys, log, limit=100):
    """올라간 작품의 배급사를 정보상자에서 (분류로 못 정한 것만, 회차마다 limit 편)"""
    d = st["disc"]
    need = [k for k in keys if not d["cand"][k]["d"] and k not in d["dist"]][:limit]
    if not need:
        return
    got = actors.pages(need)
    for k in need:
        w = got.get(k, {}).get("w", "")
        names = ("제작사", "스튜디오", "애니메이션 제작", "방송사", "방송국", "방송 채널", "채널", "배급", "배급사") if d["cand"][k].get("k") == "애니" else ("배급", "배급사", "방송 채널", "채널")
        d["dist"][k] = actors.plain(actors.field(w, *names))[:40] or "?"
    log(f"작품 늘리기: 배급사 {len(need)}편 확인")


def works(st, cfg):
    """큰 쇼츠가 있는 후보 → 작품 목록 (min_top 넘는 것 중 조회수 큰 순 max_works 편)"""
    d = st.get("disc") or {}
    ok = [(k, s[2]) for k, s in d.get("seen", {}).items() if s[2] >= cfg["min_top"] and k in d.get("cand", {})]
    ok.sort(key=lambda x: -x[1])
    out = []
    plain = lambda n: re.sub(r"[^0-9a-z가-힣]", "", n.lower())
    films = {plain(c["n"]) for c in d.get("cand", {}).values() if c.get("k") != "애니"}  # 같은 이름 한국 영화·드라마가 있는 애니
    for k, top in ok[:cfg["max_works"]]:
        c = d["cand"][k]
        tag = tag_of(c["n"])
        ani = c.get("k") == "애니"
        who = ["애니"] if ani and (c.get("amb") or plain(c["n"]) in films) else c.get("cast", [])[:2] if c.get("amb") else []
        q = "#" + tag + "".join(" " + a for a in who)  # 흔한 제목은 배우 이름(애니는 '애니')도 보여야 인정
        out.append({"key": k, "n": c["n"], "g": c["g"], "k": c["k"], "d": c["d"] or d.get("dist", {}).get(k, "?"),
                    "y": str(c["y"] or ""), "tag": tag, "q": q, "top0": top})
    return out
