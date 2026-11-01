# -*- coding: utf-8 -*-
"""배우 타이밍 — 곧 시작하거나 방영·상영 중인 드라마(TV·OTT)와 영화의 주연을 위키백과에서 모으고,
   그 배우들의 지난 한국 영화를 찾아(위키데이터 '출연' + 배우 문서의 '영화' 칸) 영드레이더가 재도록 작품 목록에 보탠다.
   - 드라마: '분류:N년 시작한 대한민국의 텔레비전 프로그램' 중 '드라마' 분류 (TV·넷플릭스·티빙·디즈니+·쿠팡플레이·웨이브 다 들어 있음)
   - 영화: 'N년 대한민국의 영화 목록' 의 개봉일 표
   키 없음, 하루 한 번. 위키백과는 빨리 물으면 429 를 주므로 1.2초씩 띄우고, 429 면 시키는 만큼 기다린다."""
import re, json, time, urllib.request, urllib.parse, urllib.error
from datetime import date, timedelta

UA = {"User-Agent": "yd-radar/0.1 (personal dashboard; https://github.com/charismaang-cyber/yd-radar)"}
WIKI = "https://ko.wikipedia.org/w/api.php"
OTT = ("넷플릭스", "티빙", "TVING", "디즈니", "쿠팡플레이", "웨이브", "wavve", "왓챠", "애플 TV", "프라임 비디오", "U+")
LINK = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")


def api(**p):
    url = WIKI + "?" + urllib.parse.urlencode(dict(p, format="json", formatversion=2))
    for _ in range(6):
        time.sleep(1.2)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("retry-after") or 20) + 1)
                continue
            raise
    raise RuntimeError("위키백과가 계속 429")


def pages(titles):
    """문서를 50개씩 한 번에 → 물은 제목: {t 실제 제목, w 위키 문법, cats 분류, qid, dis 동음이의}. 넘겨주기는 따라간다."""
    out, titles = {}, list(dict.fromkeys(t for t in titles if t))
    for i in range(0, len(titles), 50):
        chunk, got, alias, cont = titles[i:i + 50], {}, {}, {}
        while True:
            r = api(action="query", prop="revisions|categories|pageprops", titles="|".join(chunk), rvprop="content",
                    rvslots="main", cllimit="max", ppprop="wikibase_item|disambiguation", redirects=1, **cont)
            q = r.get("query", {})
            for k in ("normalized", "redirects"):
                for x in q.get(k, []):
                    alias[x["from"]] = x["to"]
            for p in q.get("pages", []):
                if p.get("missing"):
                    continue
                g = got.setdefault(p["title"], {"t": p["title"], "w": "", "cats": [], "qid": None, "dis": False})
                if p.get("revisions"):
                    g["w"] = p["revisions"][0]["slots"]["main"]["content"]
                g["cats"] += [c["title"].split(":", 1)[-1] for c in p.get("categories", [])]
                pp = p.get("pageprops", {})
                g["qid"] = g["qid"] or pp.get("wikibase_item")
                g["dis"] = g["dis"] or "disambiguation" in pp
            if "continue" not in r:
                break
            cont = r["continue"]
        for t in chunk:
            u = t
            for _ in range(3):
                u = alias.get(u, u)
            if got.get(u, {}).get("w"):
                out[t] = got[u]
    return out


def members(cat):
    out, cont = [], {}
    while True:
        r = api(action="query", list="categorymembers", cmtitle="분류:" + cat, cmlimit="max", cmtype="page", **cont)
        out += [m["title"] for m in r.get("query", {}).get("categorymembers", [])]
        if "continue" not in r:
            return out
        cont = r["continue"]


# ── 위키 문법 읽기 ─────────────────────────────────────
def field(w, *names):
    """정보상자 칸 값 — {{ }}·[[ ]] 안의 | 와 줄바꿈은 건너뛰고, 밖에서 | 나 줄바꿈이 나오면 끝"""
    for n in names:
        m = re.search(r"\|\s*" + re.escape(n) + r"\s*=", w)
        if not m:
            continue
        i, depth, out = m.end(), 0, []
        while i < len(w):
            two = w[i:i + 2]
            if two in ("{{", "[["):
                depth += 1; out.append(two); i += 2; continue
            if two in ("}}", "]]"):
                if depth == 0:
                    break
                depth -= 1; out.append(two); i += 2; continue
            if depth == 0 and w[i] in "|\n":
                break
            out.append(w[i]); i += 1
        v = "".join(out).strip()
        if v:
            return v
    return ""


def _tpl(m):
    name, *args = m.group(1).split("|")
    if re.search(r"목록|list|ubl", name, re.I):  # {{단순목록|가|나}} → 가, 나
        return ", ".join(a.strip(" *\n") for a in args if "=" not in a)
    return " "


def plain(s):
    s = re.sub(r"\[\[(?:파일|그림|File|Image):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", " ", s or "", flags=re.I)  # 등급 그림 등
    s = LINK.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", " ", s, flags=re.S)
    for _ in range(4):
        s = re.sub(r"\{\{([^{}]*)\}\}", _tpl, s)
    s = re.sub(r"<[^>]+>|'''?|\(주\)|㈜|^\s*\*\s*", " ", s, flags=re.M)
    s = re.sub(r"\s*\n\s*\*?\s*", ", ", s.strip())
    return re.sub(r"\s+", " ", s).strip(" ,·")


def dates(s):
    s = LINK.sub(lambda m: m.group(2) or m.group(1), s or "")
    out = []
    for m in re.finditer(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일|(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})"
                         r"|\{\{[^{}|]*(?:날짜|date)[^{}|]*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", s, re.I):
        g = [x for x in m.groups() if x]
        try:
            out.append(date(int(g[0]), int(g[1]), int(g[2])))
        except ValueError:
            pass
    return out


def people(s, n):
    """출연 칸 → 앞에서 n명 (링크면 문서 제목, 아니면 이름 그대로)"""
    out = [m.group(1).strip() for m in LINK.finditer(s or "") if not re.fullmatch(r"\d.*|.*년|.*월.*일", m.group(1))]
    if not out:
        out = [x.strip() for x in re.split(r"[,、·/]|<br\s*/?>", plain(s)) if x.strip()]
    out = [re.sub(r"\s*외$", "", x) for x in out if x and x not in ("외", "등")]
    return list(dict.fromkeys(out))[:n]


def short(t):
    return re.sub(r"\s*\([^)]*\)$", "", t)


# ── 1) 일정: 드라마(TV·OTT) + 영화 ─────────────────────────
def dramas(years, lo, hi, leads, log):
    titles = []
    for y in years:
        try:
            titles += members(f"{y}년 시작한 대한민국의 텔레비전 프로그램")
        except Exception as e:
            log(f"배우 타이밍: {y}년 드라마 분류 못 받음 {e}")
    out = []
    for t, p in pages(titles).items():
        if not any("드라마" in c for c in p["cats"]) or any("예능" in c for c in p["cats"]):
            continue
        w = p["w"]
        ch = plain(field(w, "방송 채널", "채널", "방송사", "플랫폼", "공개 플랫폼"))
        ds = dates(field(w, "방송 기간", "방영 기간", "공개일", "공개 기간", "방송일"))
        if not ds:
            continue
        start = ds[0]
        ott = any(o.lower() in ch.lower() for o in OTT) or any("오리지널" in c for c in p["cats"])
        if len(ds) > 1 and ds[-1] > start:
            end, est = ds[-1], False
        else:  # 끝 날짜가 없으면: OTT 는 한꺼번에 공개 → 4주, TV 는 주 2회로 셈
            n = re.search(r"(\d+)", field(w, "방송 횟수", "에피소드 수", "회차"))
            end, est = start + timedelta(days=28 if ott else max(4, -(-int(n.group(1)) // 2) if n else 8) * 7), True
        if end < lo or start > hi:
            continue
        cast = people(field(w, "출연자", "출연", "주연"), leads)
        if cast:
            out.append({"t": p["t"], "n": plain(field(w, "방송명", "제목")) or short(p["t"]),
                        "kind": "드라마", "ch": ch[:30], "ott": ott, "start": start.isoformat(), "end": end.isoformat(),
                        "est": est, "cast": cast})
    return out


def films(years, lo, hi, leads, log):
    rows = []
    for y in years:
        try:
            w = api(action="parse", page=f"{y}년 대한민국의 영화 목록", prop="wikitext", redirects=1)["parse"]["wikitext"]
        except Exception as e:
            log(f"배우 타이밍: {y}년 영화 목록 못 받음 {e}")
            continue
        month = None
        for line in w.splitlines():
            m = re.search(r"\|\s*(\d{1,2})\s*월\s*$", line)
            if m and "||" not in line:
                month = int(m.group(1))
                continue
            if "||" not in line or not month:
                continue
            cells = [c.strip() for c in line.lstrip("|").split("||")]
            d = re.search(r"(\d{1,2})\s*일", cells[0].split("|")[-1])
            lk = LINK.search(cells[1]) if len(cells) > 1 else None
            if not d or not lk:
                continue
            try:
                start = date(y, month, int(d.group(1)))
            except ValueError:
                continue
            if lo <= start <= hi:
                rows.append({"t": lk.group(1).strip(), "n": (lk.group(2) or short(lk.group(1))).strip(), "start": start,
                             "dist": plain(cells[2]) if len(cells) > 2 else "", "cast0": cells[4] if len(cells) > 4 else ""})
    got = pages([r["t"] for r in rows])
    out = []
    for r in rows:
        w = got.get(r["t"], {}).get("w", "")
        cast = people(field(w, "출연", "출연자", "주연"), leads) or people(r["cast0"], leads)
        if cast:
            out.append({"t": r["t"], "n": r["n"], "kind": "영화", "ch": r["dist"][:30], "ott": False,
                        "start": r["start"].isoformat(), "end": (r["start"] + timedelta(days=28)).isoformat(), "est": True,
                        "cast": cast})
    return out


# ── 2) 배우 → 지난 영화 ───────────────────────────────────
def film_section_links(w):
    """배우 문서(또는 'X의 작품 목록')에서 '영화' 칸 안의 링크"""
    out = []
    for m in re.finditer(r"\n(={2,5})\s*([^=\n]+?)\s*\1[ \t]*(?=\n)", w):
        if not re.fullmatch(r"(장편\s*)?(출연\s*)?영화(\s*출연)?(\s*작품)?", m.group(2).strip()):
            continue
        lvl, rest = len(m.group(1)), w[m.end():]
        nxt = re.search(r"\n={2,%d}[^=]" % lvl, rest)
        out += [x.group(1).strip() for x in LINK.finditer(rest[:nxt.start()] if nxt else rest)]
    return out


def wikidata_films(qids, log):
    """위키데이터: 이 배우들이 '출연'(P161)한 영화의 한국어 위키백과 문서 제목"""
    if not qids:
        return {}
    out = {}
    q = list(qids)
    for i in range(0, len(q), 60):
        sparql = ("SELECT ?actor ?article WHERE { VALUES ?actor { %s } ?film wdt:P161 ?actor; wdt:P31 wd:Q11424. "
                  "?article schema:about ?film; schema:isPartOf <https://ko.wikipedia.org/>. }") % " ".join("wd:" + x for x in q[i:i + 60])
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": sparql, "format": "json"})
        try:
            time.sleep(1)
            d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
        except Exception as e:
            log(f"배우 타이밍: 위키데이터 못 받음 {e}")
            continue
        for b in d["results"]["bindings"]:
            a = b["actor"]["value"].rsplit("/", 1)[1]
            out.setdefault(a, []).append(urllib.parse.unquote(b["article"]["value"].rsplit("/", 1)[1]).replace("_", " "))
    return out


def film_info(p, today):
    """영화 문서면 {n 이름, y 연도, d 배급} — 한국 영화·개봉 1년 넘은 것만"""
    w = p["w"]
    if not re.search(r"\{\{\s*영화\s*정보", w):
        return None
    nat = field(w, "국가", "제작 국가")
    if not (re.search(r"대한민국|KOR|한국", nat) if nat else any(re.match(r"(대한민국|한국)의 .*영화$", c) for c in p["cats"])):
        return None  # 한국 영화만 (외국 영화 목소리 출연 등은 뺌)
    ds = dates(field(w, "개봉일", "개봉", "공개일"))
    y = ds[0].year if ds else next((int(m.group(1)) for c in p["cats"] for m in [re.match(r"(\d{4})년 영화", c)] if m), None)
    if not y or (ds and ds[0] > today - timedelta(days=365)) or (not ds and y >= today.year):
        return None
    return {"n": short(plain(field(w, "제목")) or p["t"]) or short(p["t"]), "y": y, "d": plain(field(w, "배급", "배급사"))[:40]}


def refresh(cfg, log, today=None):
    """하루 한 번: {at, titles:[…], films:{위키 제목: {n,y,d}}}"""
    today = today or date.today()
    lo, hi = today - timedelta(days=cfg["after_days"]), today + timedelta(days=cfg["before_days"])
    years = sorted({lo.year, today.year, hi.year})
    titles = {}
    for t in dramas(years, lo, hi, cfg["leads"], log) + films(years, lo, hi, cfg["leads"], log):
        k = re.sub(r"[^0-9a-z가-힣]", "", t["n"].lower())
        if k not in titles or t["start"] > titles[k]["start"]:  # 같은 작품 문서가 둘이면 늦은 날짜(고쳐진 쪽)
            titles[k] = t
    titles = list(titles.values())
    log(f"배우 타이밍: 드라마·영화 {len(titles)}편 (OTT {sum(t['ott'] for t in titles)})")
    actors = pages({a for t in titles for a in t["cast"]})
    actors = {a: p for a, p in actors.items() if not p["dis"] and re.search(r"배우|태어남|출생|가수|사람", " ".join(p["cats"]))}
    subs = {}
    for a, p in actors.items():
        m = re.search(r"\{\{\s*(?:본문|주요 문서)\s*\|\s*([^}|]*작품[^}|]*)", p["w"])
        if m:
            subs[a] = m.group(1).strip()
    subp = pages(subs.values())
    wd = wikidata_films({p["qid"] for p in actors.values() if p["qid"]}, log)
    cand = {}
    for a, p in actors.items():
        links = film_section_links(p["w"]) + film_section_links(subp.get(subs.get(a), {}).get("w", "")) + wd.get(p["qid"], [])
        cand[a] = list(dict.fromkeys(links))
    fp = pages({f for fs in cand.values() for f in fs})
    films_out, per = {}, cfg["films_per_actor"]
    for t in titles:
        for lead in t["cast"]:
            a = actors.get(lead)
            fs = []
            for f in cand.get(lead, []):
                info = film_info(fp[f], today) if f in fp else None
                if info:
                    fs.append((fp[f]["t"], info))
            fs = sorted(dict(fs).items(), key=lambda kv: -kv[1]["y"])[:per]
            for k, info in fs:
                films_out[k] = info
            t.setdefault("leads", []).append({"a": lead, "n": short(a["t"]) if a else short(lead), "films": [k for k, _ in fs]})
        t.pop("cast")
    titles = [t for t in titles if any(l["films"] for l in t["leads"])]
    log(f"배우 타이밍: 주연 {len(actors)}명 · 지난 영화 {len(films_out)}편 · 쓸 만한 작품 {len(titles)}편")
    return {"at": today.isoformat(), "titles": titles, "films": films_out}
