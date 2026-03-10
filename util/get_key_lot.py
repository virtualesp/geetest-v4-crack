# -*- coding: utf-8 -*-
"""
极验4动态参数提取模块
"""
import requests
import execjs
import json
import re
import time
import random
import os
from loguru import logger

# 获取项目根目录（util 的上级目录）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DynamicParamsExtractor:
    """极验第四代验证码动态参数提取类"""

    def __init__(self, captcha_id, challenge=None, client_type='web', risk_type='slide', lang='zh', 
                 load_domain="gcaptcha4.geetest.com", static_domain="static.geetest.com"):
        self.captcha_id = captcha_id
        self.challenge = challenge or self._generate_uuid()
        self.client_type = client_type
        self.risk_type = risk_type
        self.lang = lang
        self.load_domain = load_domain
        self.static_domain = static_domain
        self.lot_number = None
        self.static_path = None
        self.js_url = None
        self.params = None
        self.load_url = f"https://{self.load_domain}/load"
        self.callback_name = f"geetest_{int(time.time() * 1000) + random.randint(100, 999)}"
        self.headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://gt4.geetest.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }

    @staticmethod
    def _generate_uuid():
        chars = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
        return ''.join(f'{random.randint(0, 15):x}' if c == 'x' else
                       f'{(random.randint(0, 15) & 0x3 | 0x8):x}' if c == 'y' else c
                       for c in chars)

    def _parse_response(self, response_text):
        json_str = re.sub(r'^geetest_\d+\(|\);?$', '', response_text).strip()
        json_str = re.sub(r'^botion_\d+\(|\);?$', '', json_str).strip()
        if not json_str:
            return False
        try:
            data = json.loads(json_str)
            if data.get('status') != 'success':
                return False
            self.lot_number = data['data']['lot_number']
            self.static_path = data['data']['static_path']
            self.js_url = f'https://{self.static_domain}{self.static_path}/js/gcaptcha4.js'
            return True
        except (KeyError, json.JSONDecodeError):
            return False

    def load_captcha_data(self):
        params = {
            'callback': self.callback_name,
            'captcha_id': self.captcha_id,
            'challenge': self.challenge,
            'client_type': self.client_type,
            'risk_type': self.risk_type,
            'lang': self.lang
        }
        try:
            response = requests.get(self.load_url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return self._parse_response(response.text)
        except requests.RequestException as e:
            logger.error(f"动态参数初始化请求失败: {e}")
            return False

    def get_params_from_js(self, lot_js_path='lot.js'):
        if not self.js_url:
            if self.static_path:
                self.js_url = f'https://{self.static_domain}{self.static_path}/js/gcaptcha4.js'
            else:
                logger.error("缺少 static_path")
                return None

        if not os.path.isabs(lot_js_path):
            lot_js_path = os.path.join(_BASE_DIR, lot_js_path)
        gcaptcha4_path = os.path.join(_BASE_DIR, 'gcaptcha4.js')

        try:
            js_content = requests.get(self.js_url, headers=self.headers, timeout=10).text
            with open(gcaptcha4_path, 'w', encoding='utf-8') as f:
                f.write(js_content)
        except requests.RequestException as e:
            logger.error(f"下载 JS 失败: {e}")
            return None
        except IOError as e:
            logger.error(f"写入文件失败: {e}")
            return None

        try:
            with open(lot_js_path, 'r', encoding='utf-8') as f:
                code = f.read()

            node_modules_path = os.path.join(_BASE_DIR, 'node_modules')
            original_cwd = os.getcwd()
            original_node_path = os.environ.get('NODE_PATH', '')
            
            try:
                os.chdir(_BASE_DIR)
                os.environ['NODE_PATH'] = node_modules_path
                ctx = execjs.compile(code)
                lot_num = self.lot_number or "0" * 32
                self.params = ctx.call('getParams', js_content, lot_num)
                return self.params
            finally:
                os.chdir(original_cwd)
                os.environ['NODE_PATH'] = original_node_path

        except execjs.ProgramError as e:
            logger.error(f"执行 JS 失败: {e}")
            return None
        except FileNotFoundError:
            logger.error(f"找不到 lot.js 文件")
            return None


def compute_lot_dict(lot_number, rules):
    """根据规则和 lot_number 计算嵌套的 lot 字典"""
    if not rules:
        return {}
    
    key_index = rules.get('keyIndex', [])
    is_split = rules.get('isSplit', [])
    value_rule = rules.get('valueRule', '')
    
    key_res = ''
    handler_num = 0
    
    for i, idx_pair in enumerate(key_index):
        first = int(idx_pair[0])
        two = int(idx_pair[1]) + 1 if len(idx_pair) > 1 else first + 1
        tmp = lot_number[first:two]
        if (i + 1 + handler_num) in is_split:
            handler_num += 1
            tmp += '.'
        key_res += tmp
    
    match = re.match(r'n\[(\d+):(\d+)\]', value_rule)
    if match:
        final_value = lot_number[int(match.group(1)):int(match.group(2)) + 1]
    else:
        final_value = value_rule
    
    keys = key_res.split('.')
    result = final_value
    while keys:
        result = {keys.pop(): result}
    
    return result


def extract_dynamic_params(captcha_id, lot_js_path='lot.js', load_domain="gcaptcha4.geetest.com", static_domain="static.geetest.com"):
    """提取极验4动态加密参数"""
    extractor = DynamicParamsExtractor(captcha_id=captcha_id, load_domain=load_domain, static_domain=static_domain)
    
    if not extractor.load_captcha_data():
        raise Exception("加载验证码初始化数据失败")
    
    params = extractor.get_params_from_js(lot_js_path)
    if not params:
        raise Exception("从 JS 提取动态参数失败")
    
    logger.success(f"动态参数提取成功: {params.get('first')},{params.get('rules')}")
    return {'first': params.get('first', {}), 'rules': params.get('rules', {})}


def extract_params_by_path(static_path, lot_js_path='lot.js', static_domain="static.geetest.com"):
    """已知 static_path，直接下载 JS 并提取参数"""
    extractor = DynamicParamsExtractor(captcha_id="dummy", static_domain=static_domain)
    extractor.static_path = static_path
    
    params = extractor.get_params_from_js(lot_js_path)
    if not params:
        raise Exception("从 JS 提取动态参数失败")
    
    logger.success(f"动态参数提取成功: {params.get('first')}")
    return {'first': params.get('first', {}), 'rules': params.get('rules', {})}


if __name__ == '__main__':
    try:
        res = extract_dynamic_params('8b4a2bef633eb0264367b3ba9fa1dd3d')
        print("提取成功:", json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print("测试失败:", e)
