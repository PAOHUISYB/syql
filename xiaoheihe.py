#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小黑盒（Xiaoheihe）每日签到
==========================
自包含脚本，合并 pure_signin 签名算法 + 签到逻辑。
来源作者：Chankin026  linuxdo-v2ex-checkin
抓包: 小黑盒 App → api.xiaoheihe.cn 请求 → Cookie 中取 pkey 和 x_xhh_tokenid

环境变量:
  XIAOHEIHE_COOKIE   — Cookie，含 pkey 和 x_xhh_tokenid（必填）
  示例: pkey=xxx; x_xhh_tokenid=yyy
  多账号用 & 或换行分隔

  XIAOHEIHE_KEY      — 签名密钥，默认 "chenjian"（通常不需要改）
  PLUSPLUS_TOKEN     — PushPlus 推送 token（可选）

青龙依赖:
  curl_cffi, cryptography

cron: 30 8 * * *
"""

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as plain_requests
from curl_cffi import requests as cffi_requests
from cryptography.fernet import Fernet

# 青龙通知（内置 notify 模块，仅在青龙环境可用）
try:
    from notify import send as ql_notify_send
except ImportError:
    ql_notify_send = None

# ════════════════════════════════════
# 环境变量
# ════════════════════════════════════
COOKIE_LIST = os.getenv("XIAOHEIHE_COOKIE", "")
XIAOHEIHE_KEY = os.getenv("XIAOHEIHE_KEY", "chenjian")
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# ════════════════════════════════════
# 常量
# ════════════════════════════════════
API_BASE = "https://api.xiaoheihe.cn"
SIGN_STATE_PATH = "/task/sign_v3/get_sign_state"
SIGN_PATH = "/task/sign_v3/sign"
DEFAULT_ANDROID_ID = "493245af067c9e43"
UINT32_MASK = (1 << 32) - 1

_CIPHER = b"gAAAAABqCWTXgttlWdvxF8DBZA7pQlY_fK1SJPnkExLeuI7IfBM4RkKGNUlZPqarmCbHN7VBdA1c2PQft_yfFEbhRBIp43QfWGNnIoYrkw6sx7Ft6W1EQcj7l5rq-GcEAUmmQpFMNk-_smJATqF70Ilvj6F-uijz6TWpwKBFy8KFXrBkn10248i2SdZzTLjGJZOtFaiN9pbtAdTQ9x6DVPElkFFru-d8SxYRNhZ6fogqyAFbb2ykJSs_pC-4NMQA0bPlo-U63adV9kTFvO5erZwz4ciYoXwl6RLMPfJiHGiWnn5qR2WbdLwu0hY4wVotFIZRX_II36dcipRMLQniVvDXpSruSSArAjO8i_Dk1yFmShWQlxutk8x3v93pwK4JexxsyyYwbmocs2dwoa8yc7DdBr5ixQnYqYkFkJ1iFZlc4GC2PFth9plcNHGkbE9YBiYXUEZrZqXOe58xeDl5auZ1h7mCay6tPfNT63rd6e9nGHVoSJytENSv-ioOD3fqmp35MNdBLsx4-sNdJ_k3u2mQaUWPju1Lzn9pmfCEWCgRkss-I5atww52lxf5ob4J2emlw58OkB9a3eial3nI8SvSL9W0f_otodqtVEDIfo0a1XSCqBi0BpErx4zHtDlegdUhfKH-Ngjm0M5aZd85E0lMQLtfGw-NEdvHCfZNO6HfVOua1rJ36G1KRdZVE-AXpbuD1iWY6Ee-a_d7nayFJBDIz28URloYwhD5_rAzdx_wpCVYcfC5Jz_G793ZyNlCZ3B-AGP6WmLsPGTIyU0vussWjf0Zgr2478xjRsNi1T-fNrPl78URz4WnPDgoTBvdj7d78qYGALaA012GITkzEsPrV6WlqgJXHXthn3VY1ZqFLISUJNFt0YANVdu9lEX-CJQrlR5rxKrj6DvT5KtcSMJ8p6AF-ZK4fSQ78oTUZY6ZgRlMmL0IPuiJumM4zkPA119HB5CczU5vD9B_it5pbHIFSMOSMbVFw7sef9p1Wqhb77ZeubJJKu9GTkHS8M9bKsnnna4qnMW-rVDRRJcwZoZ2rOXQ9gr5ieRgpDlEtGuqhRF1O4-Wig8="


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ════════════════════════════════════
# 解密签名常量
# ════════════════════════════════════
def _decrypt_constants():
    key_bytes = hashlib.sha256(XIAOHEIHE_KEY.encode()).digest()
    f = Fernet(base64.urlsafe_b64encode(key_bytes))
    return json.loads(f.decrypt(_CIPHER))


_c = _decrypt_constants()
HMAC_KEY = _c["HMAC_KEY"].encode()
FALSE_CRC32_POLY_REFLECTED = _c["FALSE_CRC32_POLY_REFLECTED"]
FALSE_CRC32_INIT = _c["FALSE_CRC32_INIT"]
FALSE_CRC32_XOROUT = _c["FALSE_CRC32_XOROUT"]
STATE_BLOCK_LEN = _c["STATE_BLOCK_LEN"]
TRUE_CRC32_POLY_REFLECTED = _c["TRUE_CRC32_POLY_REFLECTED"]
TRUE_CRC32_INIT = _c["TRUE_CRC32_INIT"]
TRUE_CRC32_XOROUT = _c["TRUE_CRC32_XOROUT"]
BASE62 = _c["BASE62"].encode()
IDX_SEED_BASE = _c["IDX_SEED_BASE"]
PURE_IDX_G_TABLE = _c["PURE_IDX_G_TABLE"]
PURE_CHUNK = _c["PURE_CHUNK"]


# ════════════════════════════════════
# 工具函数
# ════════════════════════════════════
def u32(value: int) -> int:
    return value & UINT32_MASK


def pad_base64(value: str) -> str:
    s = value.strip()
    return s + ("=" * ((4 - len(s) % 4) % 4))


def now_timestamp() -> str:
    return str(int(time.time()))


def merge_query_params(url: str, extra_params: dict) -> str:
    if not extra_params:
        return url
    parts = urlsplit(url)
    current = dict(parse_qsl(parts.query, keep_blank_values=True))
    for k, v in extra_params.items():
        if v is not None:
            current[str(k)] = str(v)
    query = urlencode(list(current.items()))
    suffix = f"?{query}" if query else ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}{suffix}"


def ensure_trailing_slash(path: str) -> str:
    p = path.strip()
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    if not p.endswith("/"):
        p += "/"
    return p


# ════════════════════════════════════
# Cookie 解析
# ════════════════════════════════════
def parse_cookie(cookie_text: str) -> Dict[str, str]:
    text = cookie_text.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    cookies: Dict[str, str] = {}
    for fragment in text.split(";"):
        item = fragment.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        if k:
            cookies[k] = v.strip()
    return cookies


def decode_pkey_text(pkey: str) -> str:
    for candidate in (pkey, pkey.replace("-", "+").replace("_", "/")):
        try:
            raw = base64.b64decode(pad_base64(candidate))
        except Exception:
            continue
        decoded = raw.decode("utf-8", errors="ignore").strip()
        if decoded:
            return decoded
    return ""


def derive_heybox_id(pkey: str, cookies: Dict[str, str]) -> str:
    for key in ("heybox_id", "x_heybox_id"):
        value = str(cookies.get(key, "")).strip()
        if value:
            return value
    decoded = decode_pkey_text(pkey)
    for pattern in (r"_(\d{5,})[A-Za-z]+$", r"_(\d{5,})(?:\D|$)", r"\.(\d{5,})[A-Za-z]+$"):
        match = re.search(pattern, decoded)
        if match:
            return match.group(1)
    long_numbers = re.findall(r"\d{5,}", decoded)
    if long_numbers:
        return long_numbers[-1]
    fallback = re.findall(r"\d{5,}", pkey)
    if fallback:
        return fallback[-1]
    raise RuntimeError("无法从 Cookie 中提取 heybox_id")


# ════════════════════════════════════
# 签名算法
# ════════════════════════════════════
def compute_idx_seed(request_time: str) -> int:
    ts = int(request_time)
    tm = time.gmtime(ts)
    c_year = tm.tm_year - 1900
    c_mon = tm.tm_mon - 1
    return c_year * 10000 + c_mon * 100 + tm.tm_mday + IDX_SEED_BASE


def build_idx(request_time: str) -> str:
    seed = compute_idx_seed(request_time)
    chars = []
    for g in PURE_IDX_G_TABLE:
        chars.append(chr(BASE62[(g + seed) % 62]))
    return "".join(chars)


def build_seed_text(request_path: str, request_time: str, heybox_id: str, android_id: str) -> str:
    return ensure_trailing_slash(request_path) + str(request_time) + android_id + heybox_id


def _crc32(data: bytes, poly: int, init: int, xorout: int) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
            crc &= UINT32_MASK
    return u32(crc ^ xorout)


def build_hkey(request_path: str, request_time: str, heybox_id: str, android_id: str) -> str:
    seed_text = build_seed_text(request_path, request_time, heybox_id, android_id).encode("utf-8")
    state_block = hmac.new(HMAC_KEY, seed_text, hashlib.sha512).digest()
    crc = _crc32(state_block, FALSE_CRC32_POLY_REFLECTED, FALSE_CRC32_INIT, FALSE_CRC32_XOROUT)
    return f"{crc:X}"


def build_rnd(request_path: str, request_time: str, heybox_id: str, android_id: str) -> str:
    seed_text = build_seed_text(request_path, request_time, heybox_id, android_id)
    data = seed_text.encode("utf-8")
    crc = _crc32(data, TRUE_CRC32_POLY_REFLECTED, TRUE_CRC32_INIT, TRUE_CRC32_XOROUT)
    return f"{crc:X}"


def build_signed_url(
    request_path: str,
    heybox_id: str,
    android_id: str = DEFAULT_ANDROID_ID,
    device_model: str = "SM-S9210",
):
    request_time = now_timestamp()
    hkey = build_hkey(request_path, request_time, heybox_id, android_id)
    rnd = "14:" + build_rnd(request_path, request_time, heybox_id, android_id)
    idx = build_idx(request_time)

    url = merge_query_params(
        urljoin(API_BASE, request_path),
        {
            "heybox_id": heybox_id,
            "imei": android_id,
            "device_info": device_model,
            "nonce": idx,
            "hkey": hkey,
            "os_type": "Android",
            "x_os_type": "Android",
            "x_client_type": "mobile",
            "os_version": "12",
            "version": "1.3.385",
            "build": "834",
            "_time": request_time,
            "dw": "617",
            "channel": "heybox",
            "x_app": "heybox",
            "time_zone": "Asia/Shanghai",
        },
    )
    url = merge_query_params(url, {"_rnd": rnd})
    return url, {"time": request_time, "nonce": idx, "hkey": hkey, "rnd": rnd}


# ════════════════════════════════════
# HTTP 请求
# ════════════════════════════════════
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S9210) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36",
    "Referer": "https://api.xiaoheihe.cn/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def api_get(url: str, cookies: Dict[str, str]) -> dict:
    try:
        resp = cffi_requests.get(
            url, headers=HEADERS, cookies=cookies,
            timeout=30, impersonate="chrome120"
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"  curl_cffi 请求失败，回退普通请求: {e}")
        resp = plain_requests.get(
            url, headers=HEADERS, cookies=cookies, timeout=30
        )
        resp.raise_for_status()
        return resp.json()


# ════════════════════════════════════
# 签到流程
# ════════════════════════════════════
def sign_one(cookie_text: str, index: int) -> str:
    label = f"账号{index}"

    # 解析 cookie
    try:
        cookies = parse_cookie(cookie_text)
    except Exception as e:
        log(f"  ❌ [{label}] Cookie 解析失败: {e}")
        return f"[{label}] Cookie无效"

    pkey = cookies.get("pkey", "")
    if not pkey:
        log(f"  ❌ [{label}] Cookie 缺少 pkey")
        return f"[{label}] 缺少pkey"

    try:
        heybox_id = derive_heybox_id(pkey, cookies)
    except Exception as e:
        log(f"  ❌ [{label}] 提取 heybox_id 失败: {e}")
        return f"[{label}] heybox_id提取失败"

    token_id = cookies.get("x_xhh_tokenid", "")
    log(f"\n===== [{label}] heybox_id={heybox_id} =====")

    # 查询签到状态
    try:
        state_url, _ = build_signed_url(
            request_path=SIGN_STATE_PATH,
            heybox_id=heybox_id,
        )
        state_resp = api_get(state_url, cookies)
    except Exception as e:
        log(f"  ❌ [{label}] 查询签到状态失败: {e}")
        return f"[{label}] 状态查询失败"

    state_status = state_resp.get("status", "")
    result = state_resp.get("result", {})
    state = result.get("state", "")

    if state == "ok":
        streak = result.get("sign_in_streak", 0)
        coin = result.get("sign_in_coin", 0)
        exp = result.get("sign_in_exp", 0)
        log(f"  ℹ️ [{label}] 已签到 | 连续{streak}天 +{coin}H币 +{exp}exp")
        return f"[{label}] 已签到({streak}天)"

    if state == "ignore":
        log(f"  ℹ️ [{label}] 今日已签到")
        return f"[{label}] 今日已签到"

    if state_status == "failed":
        msg = state_resp.get("msg", "未知")
        log(f"  ❌ [{label}] 状态查询失败: {msg}")
        return f"[{label}] 失败: {msg}"

    # 执行签到
    try:
        sign_url, _ = build_signed_url(
            request_path=SIGN_PATH,
            heybox_id=heybox_id,
        )
        sign_resp = api_get(sign_url, cookies)
    except Exception as e:
        log(f"  ❌ [{label}] 签到失败: {e}")
        return f"[{label}] 签到请求异常"

    sign_status = sign_resp.get("status", "")
    result = sign_resp.get("result", {})
    state = result.get("state", "")
    msg = sign_resp.get("msg", "")

    if state == "ok" or sign_status == "ok":
        streak = result.get("sign_in_streak", 0)
        coin = result.get("sign_in_coin", 0)
        exp = result.get("sign_in_exp", 0)
        log(f"  ✅ [{label}] 签到成功 | 连续{streak}天 +{coin}H币 +{exp}exp")
        return f"[{label}] 签到成功({streak}天)"
    if state == "ignore":
        log(f"  ℹ️ [{label}] 今日已签到")
        return f"[{label}] 今日已签到"

    log(f"  ❌ [{label}] 签到失败: {msg}")
    return f"[{label}] {msg}"


# ════════════════════════════════════
# 推送（青龙 notify 优先，PushPlus 兜底）
# ════════════════════════════════════
def send_notify(content: str) -> None:
    title = "小黑盒签到"
    # 方式1: 青龙内置 notify 模块
    if ql_notify_send:
        try:
            ql_notify_send(title, content)
            log("✅ 青龙通知推送成功")
            return
        except Exception as e:
            log(f"⚠️ 青龙通知推送失败: {e}")

    # 方式2: PushPlus
    if PLUSPLUS_TOKEN:
        try:
            plain_requests.post(
                "https://www.pushplus.plus/send",
                json={"token": PLUSPLUS_TOKEN, "title": title, "content": content.replace("\n", "<br>"), "template": "txt"},
                timeout=10,
            )
            log("✅ PushPlus 推送成功")
            return
        except Exception as e:
            log(f"⚠️ PushPlus 推送失败: {e}")

    log("ℹ️ 未配置推送通知")


# ════════════════════════════════════
# 主入口
# ════════════════════════════════════
def main():
    log("===== 小黑盒签到 =====")

    entries = [x.strip() for x in re.split(r'[&\n]', COOKIE_LIST) if x.strip()]
    if not entries:
        log("❌ 未配置 XIAOHEIHE_COOKIE")
        sys.exit(1)

    log(f"共 {len(entries)} 个账号\n")

    results = []
    for i, entry in enumerate(entries):
        results.append(sign_one(entry, i + 1))
        if i < len(entries) - 1:
            time.sleep(2)

    summary = "\n".join(results)
    log(f"\n{'=' * 40}\n执行完毕\n{summary}")

    send_notify(summary)


if __name__ == "__main__":
    main()
