# -*- coding: utf-8 -*-
"""장면 판정 — 남의 쇼츠가 정말 작품 화면(장면)으로 만든 것인지 그림으로 본다.
   11-08 설계자: 수요로 센 620만·89.8만이 강동원 핑계고(예능) 화면이었고, 나머지도 제작보고회·무대인사라 «심정지 재진입 · GO 75» 가 나왔다.
   제목·채널만으론 못 거르니, 유튜브가 영상마다 공개해 둔 자동 캡처 3장(hq1·hq2·hq3 = 앞·가운데·뒤 화면, 키 안 씀)을
   무료 그림 AI(CLIP ViT-L/14, ONNX 8비트, 그림 모델만 307MB)로 «영화·드라마·애니 장면» ↔ «행사·예능·무대·장난감…» 점수를 매긴다.
   채점(채점/장면, 132개를 그림 보고 정답 매김): 장면 아닌 29개 중 21개를 빼고, 장면 103개 중 1개(다른 시즌 화면)만 같이 빠졌다.
   같은 표본으로 기준을 정했으니 처음 보는 영상에선 조금 덜 맞을 수 있다. 메이킹(촬영장)·직접 그린 패러디·다른 작품 장면은 못 잡는다."""
import os, io, re, json, time, base64, urllib.request, concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_URL = ("https://huggingface.co/Xenova/clip-vit-large-patch14/resolve/"
             "c307790166907339eed5a9a53a249af534102536/onnx/vision_model_quantized.onnx")
MODEL = os.environ.get("YD_SCENE_MODEL") or os.path.join(os.path.expanduser("~"), ".cache", "yd-scene", "clip-l14-vision-q8.onnx")
CUT = 0.5          # 장면 점수가 이보다 낮으면 장면 아님
CUT_PERSON = 0.8   # 제목에 배우 이름만 있고 작품 이름이 없으면 이보다 낮을 때 장면 아님 (무비젤리 «하정우…» 같은 진짜 장면 쇼츠는 0.9 넘게 나옴)
SURE = 0.9         # 채널 투표로 빼더라도 이 점수 넘는 영상은 남김
CH_MIN, CH_RATE = 3, 0.6  # 그림으로 본 영상이 3편 이상이고 60% 넘게 장면 아님 → 그 채널은 통째로 장면 채널 아님
UA = {"User-Agent": "yd-radar-check"}
MEAN = (0.48145466, 0.4578275, 0.40821073)
STD = (0.26862954, 0.26130258, 0.27577711)
_S = {}


def ensure_model(log=print):
    if os.path.exists(MODEL):
        return MODEL
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    log("장면 판정 그림 모델 받는 중 (307MB, 처음 한 번)")
    tmp = MODEL + ".part"
    with urllib.request.urlopen(urllib.request.Request(MODEL_URL, headers=UA), timeout=600) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, MODEL)
    return MODEL


def _load(log=print):
    if not _S:
        import numpy as np, onnxruntime as ort
        t = json.load(open(os.path.join(HERE, "scene_text.json"), encoding="utf-8"))
        te = np.frombuffer(base64.b64decode(t["emb"]), "<f4").reshape(-1, t["dim"])
        _S.update(np=np, sess=ort.InferenceSession(ensure_model(log), providers=["CPUExecutionProvider"]), te=te, ns=len(t["scene"]))
    return _S


def _frames(vid):
    from PIL import Image
    out = []
    for f in ("hq1", "hq2", "hq3"):
        try:
            b = urllib.request.urlopen(urllib.request.Request(f"https://i.ytimg.com/vi/{vid}/{f}.jpg", headers=UA), timeout=20).read()
            out.append(Image.open(io.BytesIO(b)).convert("RGB"))
        except Exception:
            pass
    return out


def _prep(im, np):
    from PIL import Image
    w, h = im.size  # 쇼츠 그림은 세로 화면이 가운데에 있고 양옆은 흐린 채움 → 가운데 세로 화면에서 가운데 정사각형만
    sw = min(w, int(h * 9 / 16))
    x0, y0 = (w - sw) // 2, (h - sw) // 2
    im = im.crop((x0, y0, x0 + sw, y0 + sw)).resize((224, 224), Image.BICUBIC)
    a = (np.asarray(im, np.float32) / 255 - np.array(MEAN, np.float32)) / np.array(STD, np.float32)
    return a.transpose(2, 0, 1)


def score(vids, deadline, log=print):
    """영상 id 들 → {id: 장면 점수 0~1 (그림을 못 받으면 None)}. deadline(time.time()) 넘으면 거기서 멈춤"""
    S = _load(log)
    np, out = S["np"], {}
    with cf.ThreadPoolExecutor(12) as ex:
        for i in range(0, len(vids), 8):
            if time.time() > deadline:
                break
            part = vids[i:i + 8]
            fr = list(ex.map(_frames, part))
            X, own = [], []
            for vid, ims in zip(part, fr):
                for im in ims:
                    X.append(_prep(im, np)); own.append(vid)
                if not ims:
                    out[vid] = None
            if not X:
                continue
            # 한 장씩 돌린다: 8비트 모델은 한꺼번에 넣은 그림들에 맞춰 눈금을 정해서, 같이 넣은 그림에 따라 점수가 0.05쯤 흔들린다
            e = np.concatenate([S["sess"].run(None, {"pixel_values": x[None]})[0] for x in X])
            e = e / np.linalg.norm(e, axis=1, keepdims=True)
            lg = 100 * e @ S["te"].T
            p = np.exp(lg - lg.max(1, keepdims=True))
            p /= p.sum(1, keepdims=True)
            sc = p[:, :S["ns"]].sum(1)
            for vid in part:
                if vid not in out:
                    v = [float(s) for s, o in zip(sc, own) if o == vid]
                    out[vid] = round(sum(v) / len(v), 3)
    return out


def _nz(s):
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


STOP = {"영화", "드라마", "애니", "시즌", "극장판", "위안부"}


def cast_of(w):
    """검색어에 덧붙인 배우 이름 («#설계자 강동원 이무생» → 강동원·이무생)"""
    return [x for x in (w.get("q") or "").lstrip("#").split()[1:] if len(_nz(x)) >= 2 and x not in STOP]


def person_title(title, w):
    """제목에 그 작품 배우 이름만 있고 작품 이름은 없다 (여기 강동원 이써여! · 말 많은 아이유가 신기한 강동원)"""
    cast = cast_of(w)
    if not title or not cast:
        return False
    t = _nz(title)
    names = set(w.get("names") or []) | {w.get("n") or "", w.get("tag") or "", re.split(r"[:：]", w.get("n") or "")[0]}
    if any(len(_nz(n)) >= 2 and _nz(n) in t for n in names):
        return False
    return any(_nz(c) in t for c in cast)


def bad_of(s, title, w):
    return s is not None and (s < CUT or (s < CUT_PERSON and person_title(title, w)))


def bad_channels(cache):
    """cache = {영상: [점수, 장면아님 0/1, 채널id]} → 장면 아닌 영상이 대부분인 채널"""
    n, b = {}, {}
    for s, bad, cid in cache.values():
        if s is None or not cid:
            continue
        n[cid] = n.get(cid, 0) + 1
        b[cid] = b.get(cid, 0) + bad
    return {c for c in n if n[c] >= CH_MIN and b[c] / n[c] >= CH_RATE}


def is_out(v, cache, bad_ch):
    """수요·경쟁에서 뺄 영상인가 (v = 기록 한 줄: [id, 제목, 채널, 채널id, 조회수, 올린 때, …])"""
    e = cache.get(v[0])
    if e and e[1]:
        return True
    return v[3] in bad_ch and not (e and e[0] is not None and e[0] >= SURE)
