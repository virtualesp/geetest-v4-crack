
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import json
import rsa
import hashlib
import re
import time
import random
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
from loguru import logger
from util.get_key_lot import extract_dynamic_params, compute_lot_dict
from util.word_siamese import WordMatcher

# ============ 国际版(botion) 配置 ============
LOAD_DOMAIN = "bcaptcha.botion.com"
STATIC_DOMAIN = "static.botion.com"
JS_FILENAME = "bcaptcha.js"
REFERER = "https://bcaptcha.botion.com/"
LANG = "zh-cn"
STATIC_BASE_URL = f"https://{STATIC_DOMAIN}/"
LOAD_URL = f"https://{LOAD_DOMAIN}/load"
VERIFY_URL = f"https://{LOAD_DOMAIN}/verify"
# =============================================

DYNAMIC_KV, DYNAMIC_RULES = {}, {}
session = requests.session()
word_matcher = None


def get_key():
    return ''.join([hex(int(65536 * (1.0 + random.random())))[3:] for _ in range(4)])


def rsa_public_encrypt(plain_text):
    n = int("00C1E3934D1614465B33053E7F48EE4EC87B14B95EF88947713D25EECBFF7E74C7977D02DC1D9451F79DD5D1C10C29ACB6A9B4D6FB7D0A0279B6719E1772565F09AF627715919221AEF91899CAE08C0D686D748B20A3603BE2318CA6BC2B59706592A9219D0BF05C9F65023A21D2330807252AE0066D59CEEFA5F2748EA80BAB81", 16)
    return rsa.encrypt(plain_text.encode('utf8'), rsa.PublicKey(n, int("10001", 16))).hex()


def aes_encrypt(word, key, iv="0000000000000000"):
    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    return binascii.hexlify(cipher.encrypt(pad(word.encode(), AES.block_size))).decode()


def generate_uuid():
    chars = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
    return ''.join(f'{random.randint(0, 15):x}' if c == 'x' else f'{(random.randint(0, 15) & 0x3 | 0x8):x}' if c == 'y' else c for c in chars)


def get_sign(lot_number, captcha_id, hashfunc, version, bits, datetime_str):
    a, q = bits % 4, bits // 4
    prefix, base = '0' * q, f"{version}|{bits}|{hashfunc}|{datetime_str}|{captcha_id}|{lot_number}||"
    while True:
        h = get_key()
        msg = base + h
        digest = getattr(hashlib, hashfunc)(msg.encode()).hexdigest()
        if digest.startswith(prefix):
            if a == 0 or (q < len(digest) and int(digest[q], 16) <= {1: 7, 2: 3, 3: 1}.get(a, 0)):
                return {"pow_msg": msg, "pow_sign": digest}


def get_w(data, captcha_id):
    lot_number = data['lot_number']
    sign = get_sign(lot_number, captcha_id, data['pow_detail']['hashfunc'],
                    data['pow_detail']['version'], data['pow_detail']['bits'], data['pow_detail']['datetime'])
    bg_url = STATIC_BASE_URL + data['imgs']
    result = word_matcher.match_words(bg_url, data['ques'])
    logger.debug(f"文字点选识别结果: {result}")

    obj = {
        "device_id": "", "lot_number": lot_number, "pow_msg": sign['pow_msg'], "pow_sign": sign['pow_sign'],
        "geetest": "captcha", "lang": "zh", "ep": "123", "biht": "1426265548",
        "gee_guard": {"roe": {"aup": "3", "sep": "3", "egp": "3", "auh": "3", "rew": "3", "snh": "3", "res": "3", "cdc": "3"}},
        **DYNAMIC_KV, "em": {"ph": 0, "cp": 0, "ek": "11", "wd": 1, "nt": 0, "si": 0, "sc": 0},
        **compute_lot_dict(lot_number, DYNAMIC_RULES),
        "passtime": random.randint(1280, 7900), "userresponse": result
    }
    key = get_key()
    return aes_encrypt(json.dumps(obj, separators=(',', ':')), key) + rsa_public_encrypt(key)


def parse_response(response_text):
    json_str = re.sub(r'^(geetest|botion)_\d+\(|\);?$', '', response_text)
    result = json.loads(json_str)
    if result.get('status') != 'success':
        raise Exception(f"请求失败: {result.get('msg', result)}")
    return result.get('data', result)


def load_first(risk_type, captcha_id):
    params = {'callback': f'botion_{int(time.time() * 1000)}', 'captcha_id': captcha_id,
              'challenge': generate_uuid(), 'client_type': 'web', 'risk_type': risk_type, 'lang': LANG}
    resp = session.get(LOAD_URL, params=params,
                       headers={'User-Agent': 'Mozilla/5.0', 'Referer': REFERER})
    return parse_response(resp.text)


def load_second(data, captcha_id):
    params = {"callback": f"botion_{int(time.time() * 1000)}", "captcha_id": captcha_id, "client_type": "web",
              "lot_number": data['lot_number'], "pt": "1", "lang": LANG, "payload": data['payload'],
              "process_token": data['process_token'], "payload_protocol": "1"}
    resp = session.get(LOAD_URL, params=params,
                       headers={'User-Agent': 'Mozilla/5.0', 'Referer': REFERER})
    return parse_response(resp.text)


def verify(data, w, captcha_id):
    params = {"callback": f"botion_{int(time.time() * 1000)}", "captcha_id": captcha_id, "client_type": "web",
              "lot_number": data['lot_number'], "payload": data['payload'], "process_token": data['process_token'],
              "payload_protocol": "1", "pt": "1", "w": w}
    resp = session.get(VERIFY_URL, params=params,
                       headers={'User-Agent': 'Mozilla/5.0', 'Referer': REFERER})
    return parse_response(resp.text)


def word_verify(captcha_id, risk_type='word'):
    global DYNAMIC_KV, DYNAMIC_RULES, word_matcher
    if not DYNAMIC_KV:
        params = extract_dynamic_params(
            captcha_id, load_domain=LOAD_DOMAIN, static_domain=STATIC_DOMAIN,
            js_filename=JS_FILENAME, referer=REFERER, lang=LANG)
        DYNAMIC_KV, DYNAMIC_RULES = params['first'], params['rules']
    if word_matcher is None:
        # 使用当前目录下的 model 文件夹
        base_dir = os.path.dirname(os.path.abspath(__file__))
        word_matcher = WordMatcher(
            yolo_model_path=os.path.join(base_dir, "model", "yolo_word.onnx"),
            resnet_model_path=os.path.join(base_dir, "model", "siamese_word.onnx"),
            static_base_url=STATIC_BASE_URL,
            referer=REFERER
        )

    res = load_first(risk_type, captcha_id)
    if res.get('captcha_type') != 'word':
        raise ValueError(f"验证码类型不是word，而是: {res.get('captcha_type')}")

    w = get_w(res, captcha_id)
    verify_res = verify(res, w, captcha_id)

    if verify_res.get('result') == 'continue':
        res = load_second(verify_res, captcha_id)
        w = get_w(res, captcha_id)
        verify_res = verify(res, w, captcha_id)

    return verify_res


if __name__ == '__main__':
    CAPTCHA_ID = '283ed0bd78efd3d7899888027e9a851f'
    result = word_verify(CAPTCHA_ID)
    logger.info(f"验证结果: {json.dumps(result)}")
