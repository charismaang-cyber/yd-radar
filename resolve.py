# -*- coding: utf-8 -*-
"""영상 한 편 → 어느 작품인가. 화면은 안 보고 제목·설명·태그 글자만 읽어 작품마다 점수를 매긴다.
   연도 일치 +8 · 영화 X 문맥 +5 · 제목 끝 '| 작품' +5 · #태그 +1~4 · 주연 +3/+6 · 제목 낱말 +2 · 설명 낱말 +1 · 조연 +1 · 플랫폼 ±.
   4점 이상이고 2위와 2점 넘게 벌어지면 '확실', 같은 이름 동점이면 '판모름', 나머지는 '겹침'·'모름'(안 셈).
   병행 운행(ledger.py)만 쓴다 — 옛 숫자(scan.matcher)는 건드리지 않는다.
   처음 보는 60편 채점(11-05): 지정 38편 전부 맞음, 작품명이 적힌 45편 중 38편 지정."""
import re, zlib
from collections import Counter, defaultdict


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def tags_in(s):
    return {norm(t) for t in re.findall(r"#([^\s#]+)", s or "")}


OTT = {"디즈니": ("디즈니", "disney"), "넷플릭스": ("넷플릭스", "netflix"), "티빙": ("티빙", "tving"), "웨이브": ("웨이브", "wavve"), "쿠팡": ("쿠팡",), "왓챠": ("왓챠", "watcha")}
JOSA = r"(?:이|가|을|를|은|는|의|에|로|으로|와|과|도|만|에서|에게|처럼|보다|이랑|랑|까지|부터)?"
YEAR = re.compile(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ,:!?·.]{0,30}?)\s*\(\s*(?:[A-Za-z][^()\n]{0,50},\s*)?((?:19|20)\d\d)\s*년?\s*\)")
BR = re.compile(r"[\[《<「『【〈]([^\]》>」』】〉\n]{1,30})[\]》>」』】〉]")
QUOTE = re.compile(r"(?:영화|드라마|시리즈|작품명?|제목|영화명|드라마명)\s*[:：]?\s*[\"'“‘]([^\"'”’\n]{1,30})[\"'”’]")
PRE = re.compile(r"^(영화명|드라마명|작품명|영화|드라마|시리즈|작품|제목)")
HT = re.compile(r"#[^\s#]+")
SEASON = re.compile(r"^(.{2,}?)(?:시즌\d+|파트\d+|part\d+|season\d+|\d)$")
# 예능·행사·패러디: 작품 클립이 아니라서 경쟁·최고값에서 뺀다 (써니→아는 형님 753만, 킹덤→제작발표회 1,852만)
NC = re.compile(r"아는\s?형님|런닝맨|유\s?퀴즈|살롱드립|라디오스타|나\s?혼자\s?산다|짠한형|놀면\s?뭐하니|1박\s?2일|전지적\s?참견|전참시|미운\s?우리\s?새끼|미우새|동상이몽|신서유기|핑계고|피식대학|요정재형|제작발표회|제작보고회|무대인사|청룡영화상|시상식|수상소감|패러디|변천사|필모그래피|떡상\s?스토리|미친\s?서사|반전\s?서사")
FILMW = re.compile(r"영화|드라마|명장면|movie|film|넷플릭스|디즈니|티빙|왓챠|줄거리|결말", re.I)
# 쉼표 앞말을 저절로 별칭으로 쓰면 「우리, 집」이 '우리'로 잡힌다 → 쉼표는 직접 적은 것만
EXTRA_AL = {"수츠": ["슈츠"], "좋은 놈, 나쁜 놈, 이상한 놈": ["좋은 놈", "놈놈놈"], "광해, 왕이 된 남자": ["광해"], "미안하다, 사랑한다": ["미사"]}

E, by, by2, one, _pat = [], defaultdict(list), defaultdict(list), {}, {}


def load(cat):
    E.clear(); by.clear(); by2.clear(); one.clear(); _pat.clear()
    full = {norm(c["n"]) for k, c in cat.items() if not k.startswith("W:")}
    wiki_short = set()
    for k, c in cat.items():
        if not k.startswith("W:"):
            for part in re.split(r"\s*[:：(]\s*", c["n"])[:1]:
                if part != c["n"]:
                    wiki_short.add(norm(part))
    for k, c in cat.items():
        if k.startswith("W:") and (norm(c["n"]) in full or norm(c["n"]) in wiki_short) and not c.get("cast"):
            continue  # 같은 작품이 위키 쪽에 있음
        e = dict(c); e["key"] = k; e["nn"] = norm(c["n"])
        e["cnn"] = [norm(a) for a in c.get("cast") or [] if len(norm(a)) >= 2]
        al = list(c.get("al") or []) + EXTRA_AL.get(c["n"], [])
        for part in re.split(r"\s*[:：(]\s*", c["n"])[:1]:
            if part != c["n"] and len(norm(part)) >= 2:
                al.append(part)
        e["raw"] = [c["n"]] + al
        e["ann"] = list({norm(a) for a in al if len(norm(a)) >= 2 and norm(a) != e["nn"] and norm(a) not in full})
        e["plat"] = next((p for p, ws in OTT.items() if any(w in ((c.get("d") or "") + (c.get("tail") or "")).lower() for w in ws)), None)
        if not e["nn"]:
            continue
        E.append(e); by[e["nn"]].append(e)
        for a in e["ann"]:
            by[a].append(e)
    for nn in by:
        if len(nn) >= 2:
            by2[nn[:2]].append(nn)
        else:
            one[nn] = by[nn]


def name_pat(raw):
    if raw not in _pat:
        parts = [re.escape(x) for x in re.findall(r"[0-9A-Za-z가-힣]+", raw)]
        _pat[raw] = r"[\s:·,.!?\-]*".join(parts) if parts else None
    return _pat[raw]


def parse(v):
    t, d = v["t"], v.get("desc") or ""
    tags = v.get("tags") or []
    p = {"body": norm(t + " " + d + " " + " ".join(tags)), "rawT": HT.sub(" ", t), "rawD": HT.sub(" ", d), "raw": t + "\n" + d}
    H = tags_in(t + " " + d) | {norm(x) for x in tags}
    add = set()
    for h in H:  # #메이드인코리아2·#X시즌2 → X (X2 가 따로 있는 작품이면 그쪽이 우선)
        if h not in by:
            m = SEASON.match(h)
            if m and m.group(1) in by:
                add.add(m.group(1))
    for h in H:
        m = re.match(r"^(영화|드라마)(.+)$", h)
        if m and h not in by and m.group(2) in by:
            add.add(m.group(2))
    p["H"] = H | add
    p["TH"] = {norm(x) for x in HT.findall(t)} | {norm(x) for x in BR.findall(t)}
    p["B"] = {norm(x) for x in BR.findall(t + "\n" + d)} | {norm(x) for x in QUOTE.findall(t + "\n" + d)}
    p["Y"] = set()
    for line in d.split("\n"):
        for a, y in YEAR.findall(line):
            nm = re.split(r"[:：]\s*", a)[-1] if re.match(r"^(영화|드라마|작품|제목)", a) else a
            p["Y"].add((PRE.sub("", norm(nm)), int(y)))
    return p


def ctx_hit(e, p):
    if len(e["nn"]) <= 2:
        return e["nn"] in p["B"]
    for raw in e["raw"]:
        pat = name_pat(raw)
        if pat and re.search(r"(?:🎬|🎥|🎞|🍿|📽)️?\s*" + pat + r"(?![가-힣A-Za-z0-9])", p["raw"]):
            return True
        if pat and re.search(r"(?<!유튜브 )(?<!유튜브)(?<!웹)(?:영화|드라마|시리즈|작품명?|제목|영화명|드라마명)\s*[:：]?\s*[\"'“‘《「『\[<〈【(]*\s*" + pat + r"(?![가-힣A-Za-z0-9])", p["raw"]):
            return True
    return False


def word_hit(e, text):
    for raw in e["raw"]:
        pat = name_pat(raw)
        if pat and re.search(r"(?<![가-힣A-Za-z0-9])" + pat + JOSA + r"(?![가-힣A-Za-z0-9])", text):
            return True
    return False


def pipe_hit(e, t):
    for raw in e["raw"]:
        pat = name_pat(raw)
        if pat and len(e["nn"]) >= 3 and re.search(r"[|｜]\s*" + pat + r"\s*$", t.strip()):
            return True
    return False


def gen_add(p, gen):
    """낱말이 태그로 쓰일 때 배우도 같이 나오는 비율 — 흔한 낱말(#참교육·#가족) 태그를 약하게 보려고"""
    for nn in (p["H"] | p["B"]):
        if nn in by:
            g = gen.setdefault(nn, [0, 0])
            g[0] += 1
            if any(any(c in p["body"] for c in e["cnn"][:6]) for e in by[nn]):
                g[1] += 1


def tag_power(nn, gen):
    u, s = gen.get(nn, (0, 0))
    if u >= 8:
        r = s / u
        return 4 if r >= 0.4 else 3 if r >= 0.15 and len(nn) >= 4 else 2 if len(nn) >= 4 else 1
    return 4 if len(nn) >= 4 else 2


def score(e, nn, p, gen, longer):
    s = 0; why = []; strong = False
    ys = [y for n, y in p["Y"] if n == nn]
    if ys:
        if e.get("y") and any(abs(y - e["y"]) <= 1 for y in ys):
            s += 8; why.append("연도"); strong = True
        elif e.get("y"):
            s -= 3; why.append("연도다름")
        else:
            s += 5; why.append("(연도)"); strong = True
    shadow = any(nn in l and l in by for l in longer if l in p["H"] or l in p["B"])
    in_tag = (nn in p["H"] or nn in p["B"]) and not shadow
    if in_tag:
        s += tag_power(nn, gen); why.append("#")
    masked = shadow or (not in_tag and any(nn in l for l in longer))
    if not masked:
        if ctx_hit(e, p):
            s += 5; why.append("영화X"); strong = True
        if pipe_hit(e, p["rawT"]):
            s += 5; why.append("제목꼴"); strong = True
        elif word_hit(e, p["rawT"]):
            s += 2; why.append("제목")
        elif word_hit(e, p["rawD"]):
            s += 1; why.append("본문")
    lead = sum(c in p["body"] for c in e["cnn"][:4])
    rest = sum(c in p["body"] for c in e["cnn"][4:])
    if lead:
        s += 3 * min(lead, 2); why.append(f"주연{lead}"); strong = True
    if rest:
        s += 1; why.append(f"조연{rest}")
    pl = [q for q, ws in OTT.items() if any(w in p["body"] for w in ws)]
    if len(pl) == 1 and e.get("plat"):
        if pl[0] == e["plat"]:
            s += 2; why.append("플랫폼")
        else:
            s -= 3; why.append("플랫폼다름")
    return s, why, strong


def score_one(e, nn, p, gen):
    """한 글자 제목(돈·꾼): 낱말이 너무 흔해 #태그·문맥·연도 중 하나에 주연까지 있어야(연도는 혼자도) 인정. 20편 전부 맞음(11-05)"""
    raw = p["raw"]
    tag = nn in p["H"] or nn in p["B"]
    ctx = re.search(r"(?:영화|작품명?|제목|영화명)\s*[:：]?\s*[\"'“‘《「『\[<〈【(]*\s*" + re.escape(nn) + r"(?![가-힣A-Za-z0-9])", raw)
    yr = e.get("y") and any(n == nn and abs(y - e["y"]) <= 1 for n, y in p["Y"])
    lead = sum(c in p["body"] for c in e["cnn"][:4])
    if yr:
        return 8 + 3 * min(lead, 2), ["연도"] + ([f"주연{lead}"] if lead else []), True
    if (tag or ctx) and lead:
        return 3 * min(lead, 2) + (tag_power(nn, gen) if tag else 0) + (3 if ctx else 0), (["#"] if tag else []) + (["영화X"] if ctx else []) + [f"주연{lead}"], True
    return 0, [], False


def same_work(a, b):
    if a["key"] == b["key"]:
        return True
    if a["nn"] == b["nn"]:
        return False
    if (a["nn"] in b["nn"] or b["nn"] in a["nn"]) and (a.get("y") == b.get("y") or set(a["cnn"]) & set(b["cnn"])) and not re.search(r"\d$", a["nn"] + "|" + b["nn"]):
        return True
    return False


def candidates(p, gen):
    body = p["body"]
    grams = {body[i:i + 2] for i in range(len(body) - 1)}
    names = [nn for g in grams if g in by2 for nn in by2[g] if nn in body]
    res = []
    for nn in names:
        longer = [l for l in names if nn in l and nn != l] + [h for h in p["H"] if nn in h and nn != h]
        for e in by[nn]:
            s, why, strong = score(e, nn, p, gen, longer)
            if s > 0:
                res.append((s, e, why, nn, strong))
    for nn, es in one.items():
        if nn in body and (nn in p["H"] or nn in p["B"] or any(n == nn for n, _ in p["Y"]) or "영화" in body or "작품" in body or "제목" in body):
            for e in es:
                s, why, strong = score_one(e, nn, p, gen)
                if s > 0:
                    res.append((s, e, why, nn, strong))
    if not res:
        return []
    named = [x for x in res if any(w in x[2] for w in ("연도", "(연도)", "#", "영화X"))]
    if named:
        res = named
    # 제목 속 태그는 순서만 정한다 (점수를 올리면 #참교육·#가족이 작품이 된다)
    res.sort(key=lambda x: (-(x[0] >= 4 and x[3] in p["TH"]), -x[0], -len(x[3])))
    return res


def pick(res, film_ok=True, TH=frozenset()):
    """→ {w 작품 key, lv 확실|판모름|겹침|모름, why, nn, strong}"""
    d = {"w": None, "lv": "모름", "why": "", "nn": "", "strong": False}
    if not res:
        return d
    best = res[0]
    d["strong"] = bool(best[4]) and best[0] >= 4
    if not film_ok and not best[4]:
        d["why"] = "비영화채널"
        return d
    sec = [x for x in res[1:] if not same_work(x[1], best[1])]
    same = [x for x in sec if x[0] == best[0] and x[1]["nn"] == best[1]["nn"]]
    marg = best[0] - (sec[0][0] if sec else 0)
    if best[0] >= 4 and same:
        d.update(w=best[1]["n"], lv="판모름", why="+".join(best[2]), nn=best[1]["nn"])
    elif best[0] >= 4 and (marg >= 2 or (best[3] in TH and not any(x[3] in TH for x in sec))):
        d.update(w=best[1]["key"], lv="확실", why="+".join(best[2]), nn=best[1]["nn"])
    elif best[0] >= 4:
        d.update(lv="겹침", why=" / ".join(f"{x[1]['n']}:{x[0]}" for x in res[:3]))
    return d


def multi(res):
    """한 편에 작품이 3개 넘게 이름으로 나옴 → 작품 클립이 아니라 배우 인생 이야기일 가능성 (노정의 58.8만이 「하이라키」로 잡히던 문제)"""
    return len({x[3] for x in res if x[0] >= 4}) >= 3


def fingerprint(desc):
    """같은 채널의 같은 설명 = 같은 작품 (빼고 맞히기 3,060/3,069). 40자 미만이면 0 (상투 문구는 어차피 작품이 갈려 걸러진다)"""
    f = re.sub(r"\s+", "", re.sub(r"https?://\S+", " ", HT.sub(" ", desc or "")))[:200]
    return zlib.crc32(f.encode("utf-8")) if len(f) >= 40 else 0


# ── 시리즈 묶음 ─────────────────────────────────────────
SERIES_ADD = [("타짜", "타짜: 신의 손", "타짜: 원 아이드 잭"), ("가문의 영광", "가문의 위기", "가문의 부활", "가문의 수난", "가문의 귀환"),
              ("공공의 적", "공공의 적 2", "강철중", "강철중: 공공의 적 1-1"), ("신과함께", "신과함께-죄와 벌", "신과함께-인과 연"), ("부산행", "반도")]
SERIES_NOT = {frozenset(x) for x in (("레이디", "레이디두아"), ("드림", "드림하이"), ("시선", "시선사이"))}


def series(cat):
    """{작품 key: 묶음 대표 key}. 이름이 포함되거나 숫자 꼬리만 다르면 배우 1명, 앞 세 글자만 같으면 배우 2명 겹칠 때 묶는다 (47묶음 중 약 43개 맞음 → 틀린 건 SERIES_NOT)"""
    items = [(k, c["n"], norm(c["n"]), [norm(a) for a in (c.get("cast") or [])[:6]]) for k, c in cat.items() if norm(c["n"])]
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    stem = lambda s: re.sub(r"(시즌|파트|part|class|season)?\d+$", "", s)
    head = lambda n: norm(re.split(r"[:：,\-]", n)[0])
    buckets = defaultdict(list)
    for it in items:
        buckets[it[2][:2]].append(it)
    for l in buckets.values():
        if len(l) < 2:
            continue
        for a in range(len(l)):
            ka, na, nna, ca = l[a]
            for b in range(a + 1, len(l)):
                kb, nb, nnb, cb = l[b]
                if nna == nnb or frozenset((nna, nnb)) in SERIES_NOT:
                    continue
                s = len(set(ca) & set(cb))
                ha, hb = head(na), head(nb)
                contain = (len(ha) >= 2 and hb.startswith(ha) and len(ha) >= len(hb) * 0.5) or (len(hb) >= 2 and ha.startswith(hb) and len(hb) >= len(ha) * 0.5)
                st = stem(nna) == stem(nnb) and len(stem(nna)) >= 2
                three = nna[:3] == nnb[:3] and len(nna) >= 4 and len(nnb) >= 4
                if ((contain or st) and (s >= 1 or not ca or not cb)) or (three and s >= 2):
                    par[find(ka)] = find(kb)
    idx = defaultdict(list)
    for k, n, nn, _ in items:
        idx[nn].append(k)
    for grp in SERIES_ADD:
        ks = [k for n in grp for k in idx.get(norm(n), [])]
        for k in ks[1:]:
            par[find(k)] = find(ks[0])
    return {k: find(k) for k in par}
