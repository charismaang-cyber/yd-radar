# -*- coding: utf-8 -*-
"""자료 잠그기 — 저장소가 공개라서 gh-pages 에 올리는 자료는 비밀번호로 암호화한다.
   gzip → AES-256-GCM, 열쇠는 PBKDF2-SHA256(비밀번호, salt, 200,000번). 화면(index.html)이 같은 방식으로 푼다."""
import os, json, gzip, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 200_000


def _key(pw, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode("utf-8"))


def seal(obj, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    raw = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    ct = AESGCM(_key(pw, salt)).encrypt(iv, raw, None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "iter": ITER, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def open_(box, pw):
    d = lambda k: base64.b64decode(box[k])
    raw = AESGCM(_key(pw, d("salt"))).decrypt(d("iv"), d("ct"), None)
    return json.loads(gzip.decompress(raw))
