# -*- coding: utf-8 -*-
"""작품 늘리기 — 사람이 고른 works.txt 밖의 작품을 저절로 찾는다.
   1) 후보(한 달에 한 번): 위키백과 '분류:N년 영화' 중 한국어 영화(1990년~작년),
      '분류:N년 시작한 대한민국의 텔레비전 프로그램' 중 OTT 오리지널 드라마(넷플릭스·티빙·디즈니+ 등).
      결은 위키백과 분류(조폭 영화·학교 폭력·일제 강점기 …)로 짐작한다.
   2) 거르기(회차마다 몇 분씩, 키 안 씀): #제목 쇼츠 화면을 긁어 제일 큰 조회수를 본다.
   3) 큰 쇼츠(min_top 넘음)가 있는 것만 작품 목록에 올려 보통 작품처럼 잰다. 배급사는 그때 위키백과 정보상자에서."""
import re, time, urllib.parse
from datetime import date
import actors, yt

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
    amb = [t for t in out if actors.short(t) != t]
    got = actors.pages(amb)
    for t in amb:
        cast = [actors.short(a) for a in actors.people(actors.field(got.get(t, {}).get("w", ""), "출연", "출연자", "주연"), 2)]
        out[t].update(amb=True, cast=cast)
    log(f"작품 늘리기: 후보 {len(out)}편 (영화 {sum(v['k'] == '영화' for v in out.values())}, OTT {sum(v['k'] == 'OTT' for v in out.values())}, "
        f"흔한 제목 {len(amb)}편은 배우 이름 붙여 찾음)")
    return out


def tag_of(n):
    return re.sub(r"[^0-9A-Za-z가-힣_]", "", n)


def screen(st, cfg, have, minutes, log):
    """아직 안 본(또는 오래된) 후보의 #제목 쇼츠 화면을 긁어 제일 큰 조회수를 적는다. 키 안 씀."""
    d, now, t0, n = st["disc"], int(time.time() // 60), time.time(), 0
    todo = [k for k, c in d["cand"].items()
            if len(re.sub(r"[^0-9a-z가-힣]", "", c["n"].lower())) >= 3 and c["n"].replace(" ", "") not in have
            and now - d["seen"].get(k, [0])[0] >= cfg["rescreen_days"] * 1440]
    todo.sort(key=lambda k: (d["seen"].get(k, [0])[0], -d["cand"][k]["y"]))  # 처음 보는 것·최근 작품부터
    for k in todo:
        if time.time() - t0 > minutes * 60:
            break
        c = d["cand"][k]
        try:
            if c.get("amb"):  # 흔한 제목: '제목 + 주연' 검색 첫 화면 (배우를 모르면 건너뜀)
                if not c.get("cast"):
                    d["seen"][k] = [now, None, 0]
                    continue
                r = yt.initial_data(yt.fetch("https://www.youtube.com/results?search_query="
                                             + urllib.parse.quote(f"{c['n']} {c['cast'][0]}") + "&hl=ko&gl=KR")) or {}
                v, items = None, yt._lockups(r) + yt._videos(r)
            else:
                v, _, items = yt.hashtag_page(tag_of(c["n"]))
        except yt.Blocked:
            raise
        except Exception:
            d["seen"][k] = [now, None, 0]
            continue
        d["seen"][k] = [now, v, max((x["v"] or 0 for x in items), default=0)]
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
        d["dist"][k] = actors.plain(actors.field(w, "배급", "배급사", "방송 채널", "채널"))[:40] or "?"
    log(f"작품 늘리기: 배급사 {len(need)}편 확인")


def works(st, cfg):
    """큰 쇼츠가 있는 후보 → 작품 목록 (min_top 넘는 것 중 조회수 큰 순 max_works 편)"""
    d = st.get("disc") or {}
    ok = [(k, s[2]) for k, s in d.get("seen", {}).items() if s[2] >= cfg["min_top"] and k in d.get("cand", {})]
    ok.sort(key=lambda x: -x[1])
    out = []
    for k, top in ok[:cfg["max_works"]]:
        c = d["cand"][k]
        tag = tag_of(c["n"])
        q = "#" + tag + ("".join(" " + a for a in c.get("cast", [])[:2]) if c.get("amb") else "")  # 흔한 제목은 배우 이름도 보여야 인정
        out.append({"key": k, "n": c["n"], "g": c["g"], "k": c["k"], "d": c["d"] or d.get("dist", {}).get(k, "?"),
                    "y": str(c["y"]), "tag": tag, "q": q, "top0": top})
    return out
