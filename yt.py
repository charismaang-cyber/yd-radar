# -*- coding: utf-8 -*-
"""유튜브에서 받아오는 것들 — 쿼터 없이 긁는 검색·해시태그·채널 RSS 와, 쿼터를 조금 쓰는 videos.list.
   검색 결과 형식은 2026-10-13 바뀐 것(shortsLockupViewModel) 기준(카테고리조사/애니/tools/probe2.py 에서 옮김)."""
import re, json, time, base64, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
HEAD = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Cookie": "PREF=hl=ko&gl=KR; CONSENT=YES+1"}
API = "https://www.googleapis.com/youtube/v3/"


class Blocked(Exception):
    """유튜브가 로봇 확인·동의 화면을 내밀었다(서버 IP 차단)"""


def fetch(url, data=None, headers=None, tries=3):
    for i in range(tries):
        req = urllib.request.Request(url, data=data, headers=dict(HEAD, **(headers or {})))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            if "consent.youtube.com" in body[:3000] or "/sorry/" in body[:3000]:
                raise Blocked("consent/sorry")
            return body
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise Blocked("429")
            if e.code >= 500 and i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            raise


def initial_data(html):
    m = re.search(r"ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S)
    return json.loads(m.group(1)) if m else None


def walk(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            else:
                yield from walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


def text(node):
    if not node: return ""
    if isinstance(node, str): return node
    if "simpleText" in node: return node["simpleText"]
    if "runs" in node: return "".join(r.get("text", "") for r in node["runs"])
    if "content" in node: return node["content"]
    return ""


def innertube(endpoint, body):
    body = dict(body, context={"client": {"clientName": "WEB", "clientVersion": "2.20251020.00.00", "hl": "ko", "gl": "KR"}})
    raw = fetch("https://www.youtube.com/youtubei/v1/" + endpoint + "?prettyPrint=false",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Origin": "https://www.youtube.com"})
    return json.loads(raw)


def num(s):
    """'864만' '1.2천' '3,456' '조회수 12만회' → 정수"""
    s = (s or "").replace(",", "")
    m = re.search(r"([\d.]+)\s*(억|만|천)?", s)
    if not m: return None
    return int(float(m.group(1)) * {"억": 1e8, "만": 1e4, "천": 1e3, None: 1}[m.group(2)])


def _lockups(d):
    out = []
    for s in walk(d, "shortsLockupViewModel"):
        try:
            ep = s["onTap"]["innertubeCommand"]["reelWatchEndpoint"]
        except Exception:
            continue
        acc = s.get("accessibilityText") or ""
        m = re.match(r"(.*), 조회수 ([^ ]+?)회? - Shorts", acc, re.S)
        out.append({"id": ep.get("videoId"), "title": m.group(1) if m else acc, "v": num(m.group(2)) if m else None})
    return out


def _videos(d):
    out = []
    for v in walk(d, "videoRenderer"):
        out.append({"id": v.get("videoId"), "title": text(v.get("title")), "v": num(text(v.get("viewCountText")))})
    return out


def _next_token(d):
    for c in walk(d, "continuationCommand"):
        if c.get("request") == "CONTINUATION_REQUEST_TYPE_SEARCH":
            return c.get("token")


def search(query, pages=2, sleep=1.2):
    """검색 한 번으로 두 가지를 받는다.
       shorts = 'Shorts' 칩(관련도순, 남이 터뜨린 쇼츠) / recent = '최근에 업로드된 동영상' 칩(날짜순, 지금 올리는 사람)
       조회수·날짜·채널은 videos.list 로 따로 채운다."""
    d = initial_data(fetch("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + "&hl=ko&gl=KR"))
    if not d:
        raise Blocked("no ytInitialData")
    chips = {}
    for c in walk(d, "chipCloudChipRenderer"):
        tok = (c.get("navigationEndpoint", {}).get("continuationCommand", {}) or {}).get("token")
        if tok:
            chips[text(c.get("text"))] = tok
    res = {}
    for key, label in (("shorts", "Shorts"), ("recent", "최근에 업로드된 동영상")):
        token, got = chips.get(label), []
        for _ in range(pages if token else 0):
            time.sleep(sleep)
            r = innertube("search", {"continuation": token})
            got += _lockups(r) + _videos(r)
            token = _next_token(r)
            if not token:
                break
        res[key] = got
    if not chips.get("Shorts"):  # 칩이 없는 검색어(드물다)는 첫 화면이라도
        res["shorts"] = _lockups(d) + _videos(d)
    return res


def hashtag_page(tag):
    """#태그 쇼츠 페이지 → (동영상 수, 채널 수, 이 페이지에 뜬 쇼츠 id들)
       머리의 '동영상 403개 • 채널 138개' 와, 아래 쇼츠 칸(인기 쇼츠가 많이 뜸 — 검색에 안 잡힌 1,000만+ 도 여기서 나옴)"""
    h = fetch("https://www.youtube.com/hashtag/" + urllib.parse.quote(tag) + "/shorts?hl=ko&gl=KR")
    d = initial_data(h)
    ids = (_lockups(d) + _videos(d)) if d else []  # [{id, title, v(긁은 조회수)}]
    for s in re.findall(r'"content":"([^"]*동영상[^"]*)"', h):
        m = re.search(r"동영상\s*([\d.,]+\s*[만천]?)개(?:\s*•\s*채널\s*([\d.,]+\s*[만천]?)개)?", s)
        if m:
            return num(m.group(1)), num(m.group(2)) if m.group(2) else None, ids
    return None, None, ids


def channel_rss(cid):
    """채널 최신 15개 (쇼츠 포함, 조회수까지). 쿼터 없음."""
    xml = fetch("https://www.youtube.com/feeds/videos.xml?channel_id=" + cid)
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("a:entry", ns):
        st = e.find("m:group/m:community/m:statistics", ns)
        link = e.find("a:link", ns)
        out.append({"id": e.findtext("yt:videoId", "", ns), "title": e.findtext("a:title", "", ns),
                    "desc": e.findtext("m:group/m:description", "", ns) or "",
                    "pub": e.findtext("a:published", "", ns),
                    "v": int(st.get("views")) if st is not None and st.get("views") else None,
                    "short": "/shorts/" in (link.get("href", "") if link is not None else "")})
    return root.findtext("a:title", "", ns), out


# ── 공식 API (쿼터) ──
def api(endpoint, key, **params):
    url = API + endpoint + "?" + urllib.parse.urlencode(dict(params, key=key))
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read())["error"]["errors"][0]["reason"]
        except Exception:
            reason = str(e.code)
        raise RuntimeError(reason)


def iso_dur(s):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m: return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def videos(ids, key):
    """영상 50개당 1유닛. id → {t, desc, tags, cid, ch, pub, v, dur}"""
    out, ids = {}, [i for i in dict.fromkeys(ids) if i]
    for i in range(0, len(ids), 50):
        j = api("videos", key, part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]), maxResults=50)
        for v in j.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            out[v["id"]] = {"t": sn.get("title", ""), "desc": sn.get("description", "")[:1500],
                            "tags": sn.get("tags", [])[:30], "cid": sn.get("channelId", ""),
                            "ch": sn.get("channelTitle", ""), "pub": sn.get("publishedAt", ""),
                            "v": int(st.get("viewCount", 0)),
                            "dur": iso_dur(v.get("contentDetails", {}).get("duration"))}
    return out


def api_search(query, key, order):
    """긁기가 막혔을 때만 쓰는 대신 길: search.list 1번 = 100유닛"""
    j = api("search", key, part="id", q=query, type="video", videoDuration="short", order=order,
            regionCode="KR", relevanceLanguage="ko", maxResults=50)
    return [{"id": it["id"]["videoId"], "title": ""} for it in j.get("items", []) if it.get("id", {}).get("videoId")]
