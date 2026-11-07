# -*- coding: utf-8 -*-
"""영드레이더 — 라필 「영드짜 예능 뽀개기」와 슈드종신자 「저작권 박살내기」 기준으로 작품마다 '지금 들어가도 되나'를 잰다.
   한 번 돌 때(--once): 오래된 작품부터 쇼츠 검색·최근 업로드·#해시태그를 긁고(쿼터 없음), 조회수·날짜는 videos.list(50개당 1유닛),
   정답지 채널들의 RSS 로 '막 뜨는 작품'을 잡고, 결과를 비밀번호로 잠가 data.enc.js(화면용)·state.enc.json(기록)에 쓴다.
   깃허브 Actions(.github/workflows/scan.yml)가 30분마다 부른다.
   사용: python scan.py --out site --once [--limit N] [--all]
   비밀번호: 환경변수 RADAR_PASSWORD → 없으면 password.txt / 유튜브 키: YOUTUBE_API_KEY → 없으면 youtube_key.txt (둘 다 저장소에 안 올림)"""
import os, re, sys, json, math, time, argparse, urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
import yt, lock, actors, discover, ott

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
FEED, SEEN = {}, set()  # 병행 운행(ledger.py)에 넘길 것: 이번 회차에 API 로 받은 영상 · 검색에 보인 영상. 옛 숫자엔 안 쓴다
# 장부(ledger.py)가 찾은 최근 60일 영상 — 작품 id → 영상 줄. 검색은 한 번에 50~70개뿐이라 경쟁이 적게 잡혀서(11-07 브로큰 또바바 2편 ↔ 실제 5편) 합쳐 판정한다.
# main 에서 merge.enc.json 을 읽어 채운다. 장부(ledger.py)가 scan.judge 를 부를 땐 비어 있어 장부만 본 값이 나온다.
MERGE = {}
KST = timezone(timedelta(hours=9))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
R, RUN, E = CFG["rule"], CFG["run"], CFG["entry"]
ST_RANK = {"꿀통": 0, "심정지 재진입": 1, "막 뜸": 2, "후보": 3, "경쟁 중": 4, "수요 약함": 5, "쇼츠 거의 없음": 6, "아직": 7}
# 방송사·배급사·OTT 공식 채널 (제3자 기록에서 뺀다) — 영드짜\tools\step2_shorts.py 에서 옮김
OFFICIAL = re.compile(r"(SBS|KBS|MBC|tvN|JTBC|TV\s?CHOSUN|TV조선|채널A|MBN|ENA|OCN|Netflix|넷플릭스|Disney|디즈니|wavve|웨이브|TVING|티빙|"
                      r"쿠팡|Coupang|KOCOWA|Viki|iQIYI|Studio Dragon|스튜디오드래곤|CJ ENM|U\+|Btv|Seezn|KBS WORLD|Kakao|카카오|Mnet|"
                      r"디글|Diggle|옛드|옛능|스브스|오분순삭|엠뚜루마뚜루|깔깔티비|플레이무비|PLAYMOVIE|콘텐츠판다|Contents Panda|"
                      r"롯데엔터|Lotte Entertainment|쇼박스|SHOWBOX|NEW 공식|Plus M|플러스엠|메가박스|"
                      r"애니플러스|ANIPLUS|애니맥스|ANIMAX|애니박스|ANIBOX|라프텔|Laftel|뮤즈코리아|Muse Asia|Muse Korea|투니버스|Tooniverse|애니플렉스|Aniplex|TOHO animation|Toei Animation|토에이 애니메이션|Crunchyroll|Studio Ghibli|스튜디오 지브리|Pixar|DreamWorks|Illumination|"
                      r"NBC|Universal|Warner|HBO|Paramount|Sony Pictures|Lionsgate|20th Century|Peacock|Prime Video|AMC|BBC|ABC|CBS|FOX|USA Network)", re.I)
# 수요 숫자에서 뺄 영상 — 작품 장면이 아닌 것. OFFICIAL 과 달리 잴 때(v[6])가 아니라 판정할 때 보므로 옛 기록에도 바로 적용된다.
# 11-05 썸네일로 분류한 표본 200개로 시험: 목록의 비장면 24% → 약 10%. 다른 작품이 섞인 영상·이름만 같은 영상은 못 잡는다.
# «제목에 작품명 없음 + 좁은 채널» 은 12개 중 3개만 맞아 버렸다. 인성(조인성)·화보(영화보러)·캐스팅·공항은 멀쩡한 제목에 걸려서 뺐다.
KIN_CH = re.compile(r"에나 ?클립|바이포엠|BY4M|메리크리스마스|마인드마크|EBS|열린공감", re.I)  # 배급사 관계 채널
EVENT_T = re.compile(r"인터뷰|시사회|무대인사|제작발표|오픈토크|레드카펫|실물|직캠|쇼케이스|\bGV\b|뒤풀이|수상소감|시상식|청룡영화|부산국제영화제|BIFF|예고편|티저|최신 ?근황|배우 근황", re.I)
EVENT_CH = re.compile(r"뉴스|news|ytn|star\b|스타|연예|셀럽|아이닷컴|top ?daily|톱데일리|k-culture|일상|비하인드 아카이빙|mtn", re.I)
FILM_CH = re.compile(r"무비|영화|씬|시네|드라마|컷|movie|cine|film|애니|만화|anime|toon", re.I)  # 이름에 영화 낱말이 있으면 장면 채널 (무비맛스타·스타한컷)


# 애니만: 포켓몬·디즈니·케데헌 숫자에 코스프레·카드·만들기·노래가 많이 섞인다(10-13 조사)
ANI_T = re.compile(r"코스프레|코스어|cosplay|피규어|굿즈|언박싱|개봉기|팩 ?개봉|카드 ?(?:개봉|깡|팩)|레고|뜨개|그리기|만들기|클레이|가챠|성우|커버|cover|챌린지|challenge|댄스|안무|\bOST\b|주제가|오프닝|엔딩곡|노래방|공략|콘서트|팬미팅|실사|현실판|뮤지컬|라이브|겟레디|성지순례|렌즈|스티커|종이구관|페이퍼|paper|diy|메이크업|sing-along", re.I)


def not_scene(v, w):
    """v = 기록 한 줄, w = 작품. 수요에서 뺄 영상이면 True"""
    t, ch = v[1] or "", v[2] or ""
    nn = norm(w["n"])  # 작품 이름이 채널 이름에 있으면 공식·전용 채널이지 남의 클립이 아니다 (별난 가족 byulna, 로보카폴리 TV)
    if len(nn) >= 3 and nn in norm(ch):
        return True
    if KIN_CH.search(ch) or (EVENT_CH.search(ch) and not FILM_CH.search(ch)):
        return True
    for nm in {w["n"], w.get("tag") or "", re.split(r"[:：]", w["n"])[0]}:  # 작품 이름 속 낱말은 빼고 본다: 굿뉴스 ≠ 뉴스
        if nm:
            t = re.sub(re.escape(nm), " ", t, flags=re.I)
    if w.get("k") == "애니" and ANI_T.search(t):
        return True
    return bool(EVENT_T.search(t))


def now_min():
    return int(time.time() // 60)


def kst(m):
    return datetime.fromtimestamp(m * 60, KST)


def quota_day():
    """유튜브 키의 하루 = 태평양 시간 자정 기준(한국 오후 4~5시에 초기화). 한국 날짜로 세면 그 사이 몫이 겹쳐 실제 한도를 넘는다 (11-06 quotaExceeded)"""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        tz = timezone(timedelta(hours=-8))
    return datetime.now(tz).date().isoformat()


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def tags_in(s):
    return {norm(t) for t in re.findall(r"#([^\s#]+)", s or "")}


def age_days(pub, now):
    try:
        t = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except Exception:
        return None
    return (now * 60 - t.timestamp()) / 86400


# ── 작품 ──────────────────────────────────────────────
def load_works():
    out = []
    for line in open(os.path.join(HERE, "works.txt"), encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = [x.strip() for x in line.split("|")] + [""] * 7
        g, k, d, y, n, q, al = p[:7]
        tag = n.replace(" ", "")
        names = [n, tag] + [a.strip() for a in al.split(",") if a.strip()]
        out.append({"i": norm(n) or n, "n": n, "g": g, "k": k, "d": d or "?", "y": y, "tag": tag,
                    "q": q or "#" + tag, "ht_ok": not q or " " not in q, "names": names})
    return out


def auto_works(ac, base):
    """배우 타이밍으로 찾은 지난 영화 → 작품 목록에 보탬(결 '배우 타이밍'). works.txt 에 이미 있으면 그걸 가리킨다.
       돌려주는 것: (새 작품들, 위키 제목 → 작품 id)"""
    if not ac:
        return [], {}
    have = {norm(n): w["i"] for w in base for n in w["names"][:2] if norm(n)}
    who = defaultdict(list)
    for t in ac.get("titles", []):
        for l in t["leads"]:
            for f in l["films"]:
                who[f].append(l["n"])
    out, ids = [], {}
    for f, info in ac.get("films", {}).items():
        nn = norm(info["n"])
        if not nn:
            continue
        if nn in have:
            ids[f] = have[nn]
            continue
        tag = re.sub(r"[^0-9A-Za-z가-힣_]", "", info["n"])
        al = re.split(r"\s*[(:：\-–]", info["n"])[0].strip()
        q = "#" + tag if len(nn) >= 3 else f"#{tag} {who[f][0] if who[f] else ''}".strip()  # 짧은 제목은 배우 이름이 같이 보여야 인정
        out.append({"i": nn, "n": info["n"], "g": "배우 타이밍", "k": "영화", "d": info["d"] or "?", "y": str(info["y"]),
                    "tag": tag, "q": q, "ht_ok": " " not in q, "auto": True,
                    "names": [info["n"], tag] + ([al] if al != info["n"] and len(norm(al)) >= 3 else [])})
        have[nn] = ids[f] = nn
    return out, ids


def matcher(w):
    keys = []
    for nm in w["names"]:
        hashonly = nm.startswith("#")
        nn = norm(nm)
        if nn:
            keys.append((nn, hashonly or len(nn) <= 2))
    # 흔한 낱말 제목(사랑·친구·강릉…)은 검색어에 덧붙인 배우·감독 이름 중 하나도 같이 보여야 인정
    extra = [e for e in (norm(x) for x in w["q"].lstrip("#").split()) if len(e) >= 2 and e not in {k for k, _ in keys}]

    def ok(title, desc="", tags=()):
        body = norm(title + " " + desc)
        ht = tags_in(title + " " + desc) | {norm(t) for t in tags}
        brk = {norm(x) for x in re.findall(r"[\[《<「『【(]([^\]》>」』】)]{1,30})[\]》>」』】)]", title + " " + desc)}
        if extra and not any(e in body or e in ht for e in extra):
            return False
        for nn, strict in keys:
            if nn in ht or nn in brk or (not strict and nn in body):
                return True
        return False
    return ok


def risk_of(w, chans):
    if w["k"] == "방송":
        return "높음", "방송사 화면 — 방송사 금지 규칙"  # 빼지 않고 표시만 한다(쓸 수도 있음 — 11-05 사용자)
    if w["k"] == "애니":  # 라필 책은 영화 배급사만 다룬다. 위험해도 빼지 않고 표시만 한다(쓸 수도 있음 — 11-05 사용자)
        for x, why in CFG["risk_anime"].items():
            if x.lower() in w["d"].lower():
                return "높음", why
        return "중간", "애니 원본은 무단 사용 — 2026 단속 늘어남 · " + ("권리사 확인 필요" if w["d"] == "?" else "권리: " + w["d"])
    hit = [c for c in chans if any(x.lower() in c.lower() for x in CFG["risk_channels"])]
    if hit:
        return "높음", f"{hit[0]} 채널에 이 작품 영상이 있음 (라필 책 18쪽 더블 체크)"
    for lv in ("높음", "중간"):
        for x in CFG["risk"][lv]:
            if x.lower() in w["d"].lower():
                why = {"HBO": "박살내기 책 저자 채널이 HBO 에 싹 쓸림", "쇼박스": "라필 책: 쇼박스는 특정 작품만 골라 지움"}.get(
                    x, "라필 책: NEW·KT(플레이무비)·콘텐츠판다는 경고 3개를 한 번에 → 채널 삭제")
                return lv, why
    if w["d"] == "?":
        return "?", "배급사 확인 필요"
    return "낮음", "책에서 피하라고 한 배급사가 아님"


# ── 한 작품 재기 ─────────────────────────────────────────
def scan_work(w, key, mode, log, prev=None):
    """검색·최근 업로드·#해시태그 화면에서 쇼츠를 모아 이 작품 것만 남긴다.
       키 아끼기: 전에 본 영상(맞은 것 v · 아닌 것 no)은 다시 묻지 않고, 조회수는 긁은 화면 숫자로 올린다.
       일주일에 한 번만 전에 찾은 10만+(최대 50개)를 API 로 다시 확인 — 정확한 조회수, 지워진 건 빠짐.
       검색은 매번 일부만 보여 줘서, 맞은 쇼츠는 버리지 않고 이어 센다."""
    now = now_min()
    sig = norm("|".join(w["names"]) + "|" + w["q"])
    if (prev or {}).get("sig") != sig:
        prev = {}  # 작품 이름·검색어가 바뀌면 처음부터
    if mode == "scrape":
        r = yt.search(w["q"], pages=2, sleep=RUN["sleep_sec"])
        src = r["shorts"] + r["recent"]
    else:
        src = yt.api_search(w["q"].lstrip("#"), key, "viewCount") + yt.api_search(w["q"].lstrip("#"), key, "date")
    ht = [None, None]
    if mode == "scrape":  # 검색어에 배우 이름을 덧붙인 작품도 #화면은 본다 (#브로큰 화면엔 또바바 5편이 다 있었다). 영상은 matcher 가 거르고, 흔한 낱말의 개수만 안 믿는다
        time.sleep(RUN["sleep_sec"])
        try:
            a_, b_, more = yt.hashtag_page(w["tag"])
        except yt.Blocked:
            raise
        except Exception:
            a_, b_, more = None, None, []
        if w["ht_ok"]:
            ht = [a_, b_]
        src += more
    seen_v = {}
    for x in src:
        if x.get("id") and x.get("v"):
            seen_v[x["id"]] = max(seen_v.get(x["id"], 0), x["v"])
    found = list(dict.fromkeys(x["id"] for x in src if x.get("id")))
    known = {v[0]: v for v in prev.get("v", [])}
    no = dict.fromkeys(prev.get("no", []))
    new = [i for i in found if i not in known and i not in no]
    refresh = now - prev.get("rf", 0) >= 7 * 1440 and known
    again = [v[0] for v in prev.get("v", []) if v[4] >= 100000][:50] if refresh else []
    ask = new + again
    meta = yt.videos(ask, key) if ask else {}
    FEED.update(meta); SEEN.update(found)
    ok = matcher(w)
    vids, off_ch = {}, set(prev.get("off", []))
    for i, v in known.items():
        if i in again and i not in meta:
            continue  # 지워졌거나 비공개
        v = list(v)
        if i in meta:
            v[4] = meta[i]["v"]
        elif i in seen_v:
            v[4] = max(v[4], seen_v[i])  # 긁은 숫자는 '12만'처럼 반올림이라 큰 쪽
        vids[i] = v
    for i in new:
        m = meta.get(i)
        if not m:
            no[i] = None
            continue
        if not ok(m["t"], m["desc"], m["tags"]):
            no[i] = None
            continue
        off = bool(OFFICIAL.search(m["ch"]))
        if off:
            off_ch.add(m["ch"])
        if not m["dur"] or m["dur"] > 180:
            no[i] = None
            continue
        vids[i] = [i, m["t"][:60], m["ch"], m["cid"], m["v"], m["pub"][:19], int(off)]
    # 기록이 커지지 않게: 10만+ 위쪽 60개 + 최근 60일 40개
    vs = sorted(vids.values(), key=lambda v: -v[4])
    keep = vs[:60] + [v for v in vs[60:] if (age_days(v[5], now) or 999) <= R["recent_days"]][:40]
    calls = (len(ask) + 49) // 50
    return {"at": now, "mode": mode, "seen": len(found), "units": calls + (200 if mode == "api" else 0), "sig": sig,
            "rf": now if (refresh or not prev.get("rf")) else prev["rf"],
            "ht": list(ht), "off": sorted(off_ch)[:8], "v": keep, "no": list(no)[-500:]}


def judge(w, rec, now):
    """책 기준으로 상태를 정한다"""
    if not rec:
        return {"st": "아직"}
    third = [v for v in rec["v"] if not v[6]]
    if MERGE.get(w["i"]):
        have = {v[0] for v in rec["v"]}  # 공식 채널로 뺀 영상이 장부로 되살아나지 않게 v[6] 인 것까지 본다
        third = sorted(third + [v for v in MERGE[w["i"]] if v[0] not in have], key=lambda v: -v[4])
    vs = [v[:7] + [age_days(v[5], now)] for v in third if not not_scene(v, w)]  # 제3자의 장면만, 끝에 며칠 전인지
    big = [v for v in vs if v[4] >= R["big"]]
    alive = [v for v in big if v[7] is not None and v[7] >= R["alive_days"]]
    r60 = [v for v in vs if v[7] is not None and v[7] <= R["recent_days"]]
    r60big = [v for v in r60 if v[4] >= R["mid"]]
    hot = [v for v in vs if v[7] is not None and v[7] <= R["hot_days"] and v[4] >= R["hot_views"]]
    ages = [v[7] for v in vs if v[7] is not None]
    gap = round(min(ages)) if ages else None
    ans = Counter((v[3], v[2]) for v in big).most_common(1)
    top = vs[0] if vs else None
    n100, n50 = len(big), sum(v[4] >= R["mid"] for v in vs)
    if len(vs) < R["few_shorts"]:
        st = "쇼츠 거의 없음"
    elif n100 == 0 and n50 < 2:
        st = "수요 약함"
    elif hot:
        st = "막 뜸"
    elif r60big:
        st = "경쟁 중"
    elif n100 >= 1 and gap is not None and gap >= R["revive_gap_days"]:
        st = "심정지 재진입"
    elif n100 >= 2 and alive:
        st = "꿀통"
    else:
        st = "후보"
    why = []
    if n100: why.append(f"남의 100만+ {n100}편")
    if alive: why.append(f"6개월 넘게 생존 {len(alive)}편")
    elif big: why.append("100만+가 아직 6개월 안 됨")
    why.append(f"최근 {R['recent_days']}일 50만+ " + (f"{len(r60big)}편" if r60big else "없음"))
    if gap is not None: why.append(f"마지막 업로드 {gap}일 전")
    hv = rec["ht"][0]
    if hv is not None: why.append(f"#{w['tag']} 동영상 {hv:,}개")
    cut = sum(v[4] >= R["big"] for v in third) - n100
    if cut: why.append(f"행사·관계사 영상 100만+ {cut}편은 수요에서 뺌")
    pv = lambda v: {"id": v[0], "t": v[1], "ch": v[2], "cid": v[3], "v": v[4], "pub": v[5][:10], "age": round(v[7] or 0, 1)}
    return {"st": st, "why": why, "n100": n100, "n50": n50, "nshort": len(vs), "alive": len(alive),
            "r60": len(r60), "r60big": len(r60big), "r60ch": len({v[3] for v in r60}), "gap": gap,
            "r60m": sum(v[4] >= R["big"] for v in r60), "cp": compete(vs),
            "top": pv(top) if top else None, "ans": {"cid": ans[0][0][0], "ch": ans[0][0][1], "n": ans[0][1]} if ans else None,
            "hot": [pv(v) for v in hot[:4]], "vids": [pv(v) for v in vs[:8]], "ht": rec["ht"],
            "beginner": hv is not None and hv < R["hashtag_beginner"], "off": rec.get("off", [])}


def compete(vs):
    """경쟁강도(아모르 꿀통레이더 STEP 4): 최근 30일에 남이 올린 쇼츠 — 채널 수·편수·1위 몫·지난주 급증.
       검색·최근 업로드 표본이라 실제보다 적게 잡힐 수 있다(하한)."""
    days, wk = E["comp_days"], E["surge_days"]
    r30 = [v for v in vs if v[7] is not None and v[7] <= days]
    by, best, names = Counter(), {}, {}
    for v in r30:
        by[v[3]] += 1; best[v[3]] = max(best.get(v[3], 0), v[4]); names[v[3]] = v[2]
    r7 = sum(v[7] <= wk for v in r30)
    prior = (len(r30) - r7) * wk / (days - wk)  # 이전 23일을 한 주 몫으로
    surge = r7 >= 2 and r7 > 2 * prior
    score = min(100, E["w_channel"] * len(by) + E["w_post"] * len(r30) + (E["w_surge"] if surge else 0))
    return {"s": score, "ch": len(by), "n": len(r30), "r7": r7, "surge": surge,
            "share": round(100 * by.most_common(1)[0][1] / len(r30)) if r30 else 0,
            "m30": max((v[4] for v in r30), default=0),
            "riv": [{"ch": names[c], "cid": c, "n": n, "v": best[c]} for c, n in by.most_common(5)]}


def entry(j, timing):
    """진입 판정(아모르 STEP 5): 막 튀었나? 블루오션인가? 둘 중 하나면 GO.
       점수 = 수요 40% + 온도 20% + 여유(100-경쟁강도) 40% - 저작권 감점. 상태(책 기준)와 따로 본다."""
    if j["st"] == "아직":
        return {"v": "미확인", "s": None, "why": "아직 안 잼"}
    cp, top = j.get("cp") or {}, (j.get("top") or {}).get("v") or 0
    clamp = lambda x: max(0, min(100, x))
    dem = clamp(40 * math.log10(top / 1e5) + 3 * min(j.get("n100", 0), 5)) if top else 0  # 10만 0 · 100만 40 · 1000만 80
    tmp, hows = (clamp(30 * math.log10(cp["m30"] / 1e4)) if cp.get("m30") else 0), []  # 30일 최고 10만 30 · 100만 60
    if j.get("hot"):
        tmp += 20; hows.append(f"{ago_txt(j['hot'][0]['age'])} {fmt_v(j['hot'][0]['v'])} 뜸")
    tmp += timing.get(j["i"], (0, []))[0]
    hows += timing.get(j["i"], (0, []))[1]
    tmp = clamp(tmp)
    comp = cp.get("s", 0)
    pen = {"높음": 15, "방송": 15, "중간": 5}.get(j.get("risk"), 0)
    s = round(0.4 * dem + 0.2 * tmp + 0.4 * (100 - comp) - pen, 1)
    c30 = f"최근 30일 찾은 경쟁 최소 {cp.get('ch', 0)}곳·{cp.get('n', 0)}편"
    demand = j.get("n100", 0) >= 1 or j.get("n50", 0) >= 2
    popped = bool(j.get("hot")) or bool(hows) or cp.get("m30", 0) >= R["big"]
    if j["st"] == "쇼츠 거의 없음":
        v, why = "피함", "쇼츠 5개 미만 — 배급사가 지운 것일 수 있음"
    elif j.get("risk") in ("높음", "방송") and j.get("k") not in ("애니", "방송"):  # 애니·방송은 저작권 높음 표시만 하고 경쟁으로 판정(점수에서 15 깎임)
        v, why = "피함", ("방송사 작품 — 우리 규칙 X" if j["risk"] == "방송" else "저작권 높음 — " + j.get("riskwhy", ""))
    elif comp >= E["avoid_comp"]:
        v, why = "피함", f"붐빔 · {c30}" + (" · 지난주 급증" if cp.get("surge") else "")
    elif not demand:
        v, why = "보류", f"수요 미검증 · 남의 최고 {fmt_v(top)}"
    elif cp.get("ch", 0) <= E["blue_max_ch"] and cp.get("n", 0) <= E["blue_max_posts"]:
        v, why = "GO", f"블루오션 · {c30} · 남의 최고 {fmt_v(top)}"
    elif popped and comp < E["go_max_comp"]:
        v, why = "GO", "막 튐 · " + " · ".join((hows or [f"30일 최고 {fmt_v(cp.get('m30', 0))}"])[:2]) + f" · 경쟁 최소 {cp.get('ch', 0)}곳 {cp.get('n', 0)}편"
    else:
        v, why = "차선", f"{c30} · 경쟁강도 {comp}"
    return {"v": v, "s": s, "dem": round(dem), "tmp": round(tmp), "cmp": comp, "why": why, "how": hows}


def probe(n, q="", key="", log=print):
    """레이더 «찾기»에서 목록에 없는 작품을 지금 재 본다 — PC의 원클릭 제작 도우미가 부른다(키 몇 유닛)."""
    tag = n.replace(" ", "")
    w = {"i": norm(n) or n, "n": n, "g": "?", "k": "?", "d": "?", "y": "", "tag": tag, "q": q or "#" + tag,
         "ht_ok": not q or " " not in q, "names": [n, tag]}
    rec = scan_work(w, key, "scrape", log)
    j = dict(judge(w, rec, now_min()), **{k: w[k] for k in ("i", "n", "g", "k", "d", "y", "tag", "q")})
    j["at"] = kst(rec["at"]).strftime("%m-%d %H:%M")
    j["risk"], j["riskwhy"] = risk_of(w, [v[2] for v in rec["v"]] + rec.get("off", []))
    j["en"] = entry(j, {})
    return j


def fmt_v(v):
    v = v or 0
    return f"{v / 1e8:.1f}억".replace(".0억", "억") if v >= 1e8 else f"{round(v / 1e4):,}만" if v >= 1e4 else f"{v:,}"


def ago_txt(d):
    return f"{round(d * 24)}시간 전" if d < 1 else f"{round(d)}일 전"


# ── 정답지 채널 RSS → 막 뜨는 작품 ─────────────────────────────
def watch_round(st, works, log):
    big_ch = Counter()
    names = {}
    wn = {w["i"]: w for w in works}
    for wi, rec in st["works"].items():
        for v in rec["v"]:
            if not v[6] and v[4] >= R["big"] and wi in wn and not not_scene(v, wn[wi]):
                big_ch[v[3]] += 1; names[v[3]] = v[2]
    cids = [c for c, _ in big_ch.most_common(RUN["watch_max"])]
    st["watch"] = {c: {"t": names[c], "n100": big_ch[c]} for c in cids}
    oks = [(w, matcher(w)) for w in works]
    now, fails = now_min(), 0
    for c in cids:
        try:
            title, items = yt.channel_rss(c)
        except yt.Blocked:
            raise
        except Exception:
            fails += 1
            continue
        keep = []
        for it in items:
            a = age_days(it["pub"], now)
            if a is None or a > 7:
                continue
            hit = [w["i"] for w, ok in oks if ok(it["title"], it["desc"])]
            keep.append({"id": it["id"], "t": it["title"][:90], "v": it["v"], "pub": it["pub"][:19], "short": it["short"],
                         "w": hit[:3], "tags": sorted(tags_in(it["title"] + " " + it["desc"]))[:12]})
        st["rss"][c] = {"t": title or names[c], "at": now, "items": keep}
        time.sleep(0.25)
    for c in list(st["rss"]):
        if c not in st["watch"]:
            st["rss"].pop(c)
    log(f"감시 채널 {len(cids)}곳 RSS (실패 {fails})")


# ── 화면에 줄 것 ────────────────────────────────────────
def season_list(today):
    out = []
    for s in CFG["seasons"]:
        d = s["date"]
        if len(d) == 5:
            dt = datetime.strptime(f"{today.year}-{d}", "%Y-%m-%d").date()
            if (dt - today).days < -1:
                dt = dt.replace(year=today.year + 1)
        else:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
        left = (dt - today).days
        if left >= -1:
            out.append({"n": s["n"], "date": dt.isoformat(), "left": left, "g": s["g"],
                        "soon": left <= CFG["season_lead_days"]})
    return sorted(out, key=lambda x: x["left"])


def issues(works, log):
    try:
        req = urllib.request.Request(CFG["issues_url"], headers={"User-Agent": yt.UA})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        log(f"오늘의 흐름 이슈 못 받음: {e}")
        return {}
    texts = []
    for geo in (d.get("trends") or {}).values():
        for it in geo.get("items", []):
            texts.append((it.get("title", ""), " ".join(n.get("title", "") for n in it.get("news", []))))
    out = {}
    for w in works:
        nn = norm(w["n"])
        if len(nn) < 3:
            continue
        for t, news in texts:
            if nn in norm(t + " " + news):
                out[w["i"]] = t
                break
    return out


PLAT = [("넷플릭스", r"넷플릭스|netflix"), ("티빙", r"티빙|tving"), ("디즈니+", r"디즈니|disney"), ("쿠팡플레이", r"쿠팡"),
        ("웨이브", r"웨이브|wavve"), ("왓챠", r"왓챠|watcha"), ("애플TV+", r"애플|apple")]


def plat_of(t):
    if t["kind"] == "영화":
        return "극장"
    for n, pat in PLAT:
        if re.search(pat, t["ch"], re.I):
            return n
    return "OTT" if t["ott"] else (re.split(r"[,·/ ]", t["ch"].strip())[0] or "방송사")


def actor_view(ac, ids, J, today):
    """배우 타이밍: 끝나지 않은 드라마·영화마다 주연과 그 지난 영화(작품 id). 작품에도 어느 배우·작품 덕인지 붙인다.
       신작 달력(아모르 시즌·오픈): 최근 공개 ~ 곧 공개 작품 전부 — 주연의 지난 영화가 목록에 없어도 넣는다.
       → (배우 타이밍, 신작 달력, {작품 id: (온도 더할 값, [이유])})"""
    out, cal, timing = [], [], {}
    for t in (ac or {}).get("titles", []):
        s, e = date.fromisoformat(t["start"]), date.fromisoformat(t["end"])
        if e < today:
            continue
        d = (s - today).days
        leads = [{"n": l["n"], "w": list(dict.fromkeys(ids[f] for f in l["films"] if ids.get(f) in J))} for l in t["leads"]]
        cal.append({k: t[k] for k in ("t", "n", "kind", "ch", "ott", "start", "end", "est")} | {"d": d, "p": plat_of(t), "leads": leads})
        leads = [l for l in leads if l["w"]]
        if not leads:
            continue
        out.append({k: t[k] for k in ("n", "kind", "ch", "ott", "start", "end", "est")} | {"d": d, "leads": leads})
        when = f"D-{d}" if d > 0 else "D-DAY" if d == 0 else f"{-d // 7 + 1}주차"
        prime = -21 <= d <= 7  # 첫 공개 1주 전 ~ 3주차
        for l in leads:
            for i in l["w"]:
                J[i].setdefault("act", []).append(f"{l['n']} «{t['n']}» {when}")
                b, why = timing.get(i, (0, []))
                timing[i] = (max(b, 25 if prime else 10), why + ([f"배우 타이밍 {l['n']} «{t['n']}» {when}"] if prime else []))
    return sorted(out, key=lambda x: x["start"]), sorted(cal, key=lambda x: x["start"]), timing


def build(st, works, iss, mode_note, errs, film_ids=None):
    now = now_min()
    wn = {w["i"]: w for w in works}
    J = {w["i"]: dict(judge(w, st["works"].get(w["i"]), now),
                      **{k: w[k] for k in ("i", "n", "g", "k", "d", "y", "tag", "q")},
                      auto="disc" if w.get("auto") == "disc" else "actor" if w.get("auto") else "")
         for w in works}
    for w in works:
        j = J[w["i"]]
        rec = st["works"].get(w["i"])
        j["at"] = kst(rec["at"]).strftime("%m-%d %H:%M") if rec else None
        if rec:
            rec["s"] = j["st"]  # 다음 회차에 다시 잴 주기를 정할 때 쓴다
        j["risk"], j["riskwhy"] = risk_of(w, [v[2] for v in (rec or {}).get("v", [])] + (rec or {}).get("off", []))
        o = (st.get("ott") or {}).get(w["i"])
        if o:
            j["ott"] = o["s"] if o["f"] else None
        if w["i"] in iss:
            j["issue"] = iss[w["i"]]
    # RSS 로 잡힌 급상승 → 작품에 붙이고, 못 알아본 건 소재 피드로
    feed, rss_hot = [], defaultdict(list)
    for c, ch in st["rss"].items():
        for it in ch["items"]:
            a = age_days(it["pub"], now)
            if it["v"] is None or a is None or a > R["hot_days"] or it["v"] < R["hot_views"]:
                continue
            row = {"id": it["id"], "t": it["t"], "ch": ch["t"], "cid": c, "v": it["v"], "pub": it["pub"][:10],
                   "age": round(a, 1), "tags": it["tags"]}
            if it["w"]:
                for wi in it["w"]:
                    if wi in wn and not not_scene([row["id"], row["t"], row["ch"]], wn[wi]):
                        rss_hot[wi].append(row)
            else:
                feed.append(row)
    for wi, rows in rss_hot.items():
        if wi in J:
            seen = {h["id"] for h in J[wi].get("hot", [])}
            J[wi]["hot"] = sorted(J[wi].get("hot", []) + [r for r in rows if r["id"] not in seen], key=lambda r: -r["v"])[:4]
    # 연관작: 같은 결 + 같은 채널이 함께 올린 작품
    chan_works = defaultdict(set)
    for wi, rec in st["works"].items():
        for v in rec["v"]:
            if not v[6] and v[4] >= 100000 and wi in wn and not not_scene(v, wn[wi]):
                chan_works[v[3]].add(wi)
    good = ("꿀통", "심정지 재진입", "후보")
    for j in J.values():
        share = Counter()
        for c, ws in chan_works.items():
            if j["i"] in ws:
                for o in ws - {j["i"]}:
                    share[o] += 1
        cands = {}
        for o, n in share.items():
            if o in J and J[o]["st"] in good:
                cands[o] = f"같은 채널 {n}곳"
        for o in J.values():
            if o["g"] == j["g"] and o["i"] != j["i"] and o["st"] in good and o["i"] not in cands:
                cands[o["i"]] = "같은 결"
        rank = lambda o: (ST_RANK[J[o]["st"]], -share.get(o, 0), -(J[o].get("n100") or 0))
        j["rel"] = [{"i": o, "why": cands[o]} for o in sorted(cands, key=rank)[:6]]
    hot = sorted([j["i"] for j in J.values() if j.get("hot")], key=lambda i: -max(h["v"] for h in J[i]["hot"]))
    gy = []
    for g in CFG["gyeol"]:
        ids = sorted([j["i"] for j in J.values() if j["g"] == g["k"]],
                     key=lambda i: (ST_RANK[J[i]["st"]], -(J[i].get("n100") or 0), -((J[i].get("top") or {}).get("v") or 0)))
        gy.append(dict(g, ids=ids, pass_=sum(J[i]["st"] in ("꿀통", "심정지 재진입") for i in ids),
                       cand=sum(J[i]["st"] == "후보" for i in ids)))
    chans = sorted(({"cid": c, "t": v["t"], "n100": v["n100"],
                     "works": sorted({J[wi]["n"] for wi in chan_works.get(c, ()) if wi in J})[:8]}
                    for c, v in st.get("watch", {}).items()), key=lambda x: -x["n100"])
    today = kst(now).date()
    act, cal, timing = actor_view(st.get("actors"), film_ids or {}, J, today)
    seas = season_list(today)
    # 온도에 더할 '때': 배우 타이밍(위) · 다가오는 시즌의 결 · 오늘의 흐름 구글 트렌드
    for s in seas:
        if s["soon"]:
            for j in J.values():
                if j["g"] in s["g"]:
                    b, why = timing.get(j["i"], (0, []))
                    timing[j["i"]] = (b + 10, why + [f"{s['n']} D-{s['left']}"])
    for j in J.values():
        if j.get("issue"):
            b, why = timing.get(j["i"], (0, []))
            timing[j["i"]] = (b + 15, why + [f"구글 트렌드 «{j['issue']}»"])
        j["en"] = entry(j, timing)
    # 요즘 떡상 쇼츠(아모르 데일리 떡상쇼츠): 최근 30일 남의 10만+ 쇼츠를 작품과 함께
    rise, seen = [], set()
    for wi, rec in st["works"].items():
        if wi not in J:
            continue
        for v in rec["v"]:
            a = age_days(v[5], now)
            if v[6] or a is None or a > E["rise_days"] or v[4] < E["rise_views"] or v[0] in seen or not_scene(v, wn[wi]):
                continue
            seen.add(v[0])
            rise.append({"id": v[0], "t": v[1], "ch": v[2], "v": v[4], "age": round(a, 1), "w": wi})
    for wi, rows in rss_hot.items():
        for r in rows:
            if wi in J and r["id"] not in seen:
                seen.add(r["id"])
                rise.append({"id": r["id"], "t": r["t"], "ch": r["ch"], "v": r["v"], "age": r["age"], "w": wi})
    return {"at": kst(now).strftime("%Y-%m-%d %H:%M"), "mode": mode_note, "err": errs[-12:], "rule": R, "entry": E,
            "works": list(J.values()), "hot": hot, "feed": sorted(feed, key=lambda r: -r["v"])[:60],
            "rise": sorted(rise, key=lambda r: -r["v"])[:E["rise_max"]],
            "actors": act, "cal": cal, "actors_at": (st.get("actors") or {}).get("at"),
            "gyeol": gy, "seasons": seas, "channels": chans,
            "scanned": sum(1 for w in works if w["i"] in st["works"]), "total": len(works),
            "units": st["units"].get(quota_day(), 0)}


# ── 한 번 돌기 ─────────────────────────────────────────
def secret(env, fname):
    v = os.environ.get(env, "").strip()
    if not v and os.path.exists(os.path.join(HERE, fname)):
        v = open(os.path.join(HERE, fname), encoding="utf-8").read().strip()
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="오래된 순서 무시하고 전부")
    ap.add_argument("--minutes", type=float, default=24, help="작품 재기에 쓸 최대 시간")
    a = ap.parse_args()
    pw, key = secret("RADAR_PASSWORD", "password.txt"), secret("YOUTUBE_API_KEY", "youtube_key.txt")
    if not pw or not key:
        sys.exit("비밀번호(RADAR_PASSWORD) 나 유튜브 키(YOUTUBE_API_KEY) 가 없음")
    os.makedirs(a.out, exist_ok=True)
    sp = os.path.join(a.out, "state.enc.json")
    log = lambda m: print(f"[{datetime.now(KST):%H:%M:%S}] {m}", flush=True)
    st = {}
    if os.path.exists(sp):
        try:
            st = lock.open_(json.load(open(sp, encoding="utf-8")), pw)
        except Exception:
            log("지난 기록을 못 풂(비밀번호가 바뀜?) → 새로 시작")
    for k in ("works", "rss", "watch", "units"):
        st.setdefault(k, {})
    mp = os.path.join(a.out, "merge.enc.json")
    if os.path.exists(mp):
        try:
            MERGE.update(lock.open_(json.load(open(mp, encoding="utf-8")), pw))
            log(f"장부 합치기: 작품 {len(MERGE)}편 · 영상 {sum(map(len, MERGE.values()))}편")
        except Exception as e:
            log(f"장부 합치기 못 풂 → 검색 숫자만 ({e})")
    st.setdefault("err", [])
    now, today = now_min(), kst(now_min()).date().isoformat()
    AC = CFG.get("actors")
    if AC and (now - (st.get("actors") or {}).get("m", 0) >= AC["refresh_hours"] * 60 or (st.get("actors") or {}).get("v") != actors.VER):
        try:
            st["actors"] = dict(actors.refresh(AC, log, kst(now).date()), m=now)
        except Exception as e:
            st["err"].append(f"{today} 배우 타이밍: {type(e).__name__} {e}"[:200])
            log(f"배우 타이밍 못 받음: {e}")
    base = load_works()
    # 작품 늘리기: 위키백과 후보(한 달에 한 번) → #제목 쇼츠 화면으로 거르기(키 안 씀, 회차마다 몇 분) → 큰 쇼츠 있는 것만 작품으로
    DC = CFG.get("discover")
    dw = []
    if DC:
        d = st.setdefault("disc", {})
        for k in ("cand", "seen", "dist"):
            d.setdefault(k, {})
        try:
            if now - d.get("m", 0) >= DC["refresh_days"] * 1440 or d.get("ver") != discover.VER:
                d["cand"], d["m"] = {**{k: c for k, c in d["cand"].items() if c.get("k") in ("애니", "방송")}, **discover.candidates(DC, log, kst(now).date())}, now
                if d.get("ver") != discover.VER:  # 찾는 법이 바뀌었으니 전에 아무것도 못 본 작품은 바로 다시
                    d["seen"] = {k: s for k, s in d["seen"].items() if s[1] is not None or s[2]}
                    d["ver"] = discover.VER
            if DC.get("anime_from_year"):
                discover.anime_step(st, DC, log, kst(now).date(), DC.get("anime_minutes", 6))
            if DC.get("drama_from_year"):
                discover.drama_step(st, DC, log, kst(now).date(), DC.get("drama_minutes", 3))
            # 직접 넣은 애니·방송의 다른 이름(심슨 가족·포켓몬스터·스카이캐슬)이 자동 발굴에서 또 올라오지 않게
            discover.screen(st, DC, {w["tag"] for w in base} | {re.sub(r"\s", "", a) for w in base if w["k"] in ("애니", "방송") for a in w["names"]}, DC["screen_minutes"], log)
            discover.fill_dist(st, [x["key"] for x in discover.works(st, DC)], log)
        except Exception as e:
            st["err"].append(f"{today} 작품 늘리기: {type(e).__name__} {e}"[:200])
            log(f"작품 늘리기 못 함: {e}")
        have = {w["i"] for w in base} | {norm(a) for w in base if w["k"] in ("애니", "방송") for a in w["names"]}
        for x in discover.works(st, DC):
            i = norm(x["n"])
            if not i or i in have:
                continue
            have.add(i)
            al = re.split(r"\s*[(:：\-–]", x["n"])[0].strip()
            dw.append({"i": i, "n": x["n"], "g": x["g"], "k": x["k"], "d": x["d"] or "?", "y": x["y"], "tag": x["tag"],
                       "q": x["q"], "ht_ok": " " not in x["q"], "auto": "disc",
                       "names": [x["n"], x["tag"]] + ([al] if al != x["n"] and len(norm(al)) >= 3 else [])})
    extra, ids = auto_works(st.get("actors"), base + dw)
    works = base + dw + extra
    order = {True: 0, "disc": 2}  # 같은 때면 배우 타이밍(때가 있음) → 고른 작품 → 자동 발굴
    def due(w):  # 수요가 약한 자동 발굴 작품은 주 1회만 다시 잰다 (키·시간 아끼기)
        r = st["works"].get(w["i"], {})
        low = w.get("auto") == "disc" and r.get("s") in ("쇼츠 거의 없음", "수요 약함")
        return now - r.get("at", 0) >= (RUN.get("rescan_low_hours", 168) if low else RUN["rescan_hours"]) * 60
    qday = quota_day()
    stale = sorted((w for w in works if a.all or due(w)),
                   key=lambda w: (st["works"].get(w["i"], {}).get("at", 0), order.get(w.get("auto"), 1)))
    if a.limit:
        stale = stale[:a.limit]
    elif st["works"]:
        stale = stale[:RUN["per_round"]]
    mode, blocks, done, t0 = st.get("mode", "scrape"), 0, 0, time.time()
    if mode == "api" and st.get("mode_day") != today:
        mode = "scrape"  # 하루 지나면 다시 긁기부터 해 본다
    log(f"작품 {len(works)}편 중 {len(stale)}편 재기 ({'긁기' if mode == 'scrape' else 'API 검색'})")
    for w in stale:
        if time.time() - t0 > a.minutes * 60:
            log("시간이 다 돼서 나머지는 다음 회차에")
            break
        if mode == "api" and st["units"].get(qday, 0) + 202 > 6000:
            log("오늘 API 검색 몫(6,000유닛)을 다 씀 → 다음 회차에")
            break
        if st["units"].get(qday, 0) >= RUN["unit_budget"]:
            log(f"오늘 유튜브 키 몫({RUN['unit_budget']:,}유닛)을 다 씀 → 내일 이어서 (오늘의 흐름·채널 레이더 몫 남겨 둠)")
            break
        try:
            rec = scan_work(w, key, mode, log, st["works"].get(w["i"]))
            blocks = 0
        except yt.Blocked as e:
            blocks += 1
            st["err"].append(f"{today} {w['n']}: 긁기 막힘 {e}")
            if blocks >= 3 and mode == "scrape":
                mode = "api"; st["mode_day"] = today
                log("유튜브가 긁기를 막음 → 오늘은 API 검색(작품당 200유닛)으로")
            continue
        except Exception as e:
            st["err"].append(f"{today} {w['n']}: {type(e).__name__} {e}"[:200])
            if "quota" in str(e).lower():
                log("유튜브 키 쿼터 다 씀"); break
            continue
        st["works"][w["i"]] = rec
        st["units"][qday] = st["units"].get(qday, 0) + rec["units"]
        done += 1
        j = judge(w, rec, now_min())
        log(f"  {w['n']}: {j['st']} · 100만+ {j.get('n100', 0)} · 최근60일 50만+ {j.get('r60big', 0)} · 확인 {len(rec['v'])}/{rec['seen']}")
    st["mode"] = mode
    try:
        watch_round(st, works, log)
    except yt.Blocked as e:
        st["err"].append(f"{today} RSS 막힘 {e}")
    if CFG.get("ott"):
        try:
            ott.refresh(st, works, CFG["ott"], now_min(), log)
        except Exception as e:
            st["err"].append(f"{today} 시청처: {type(e).__name__} {e}"[:200])
            log(f"시청처 못 받음: {e}")
    keep = {w["i"] for w in works}
    st["works"] = {k: v for k, v in st["works"].items() if k in keep}
    st["units"] = dict(sorted(st["units"].items())[-10:])
    st["err"] = st["err"][-40:]
    note = "긁기" if mode == "scrape" else "API 검색 (긁기 막힘)"
    data = build(st, works, issues(base, log), note, st["err"], ids)
    for path, body in ((sp, json.dumps(lock.seal(st, pw))),
                       (os.path.join(a.out, "data.enc.js"), "window.YD_BOX = " + json.dumps(lock.seal(data, pw)) + ";\n"),
                       (os.path.join(a.out, "status.json"), json.dumps({"at": data["at"], "mode": note, "done": done,
                                                                         "scanned": data["scanned"], "total": data["total"],
                                                                         "errors": len(st["err"]), "errors_today": sum(e.startswith(today) for e in st["err"]),
                                                                         "units_today": st["units"].get(qday, 0)}, ensure_ascii=False))):
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(path + ".tmp", path)
    log(f"끝: 이번 {done}편, 누적 {data['scanned']}/{data['total']}편, 막 뜸 {len(data['hot'])}, 감시 채널 {len(data['channels'])}, 오늘 {data['units']}유닛")
    try:  # 병행 운행에 넘김 — 실패해도 옛 숫자와 상관없음
        p = os.path.join(a.out, "ledger_in.enc.json")
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            f.write(json.dumps(lock.seal({"feed": FEED, "seen": sorted(SEEN)}, pw)))
        os.replace(p + ".tmp", p)
    except Exception as e:
        log(f"장부 넘기기 실패: {e}")


if __name__ == "__main__":
    main()
