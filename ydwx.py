#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一点万象 每日签到
=================
H5 应用（非小程序），通过 deviceParams + token 直接签到。
合并优化自 bash 版（签名逻辑更完整）和 Python 版（青龙兼容）。

环境变量:
  ydwx_deviceParams — 多账号 deviceParams，用 & 分隔
  ydwx_token        — 多账号 token，用 & 分隔（与 deviceParams 一一对应）
  ydwx_mallNo       — 商场编号，默认 20014
  PLUSPLUS_TOKEN    — PushPlus 推送 token（可选）

cron: 17 8 * * *
"""

import os
import sys
import json
import hashlib
import time
import urllib.parse
from datetime import datetime

import requests

# ════════════════════════════════════
# 配置
# ════════════════════════════════════
DEVICE_PARAMS_LIST = os.getenv("ydwx_deviceParams", "")
TOKEN_LIST = os.getenv("ydwx_token", "")
MALL_NO = os.getenv("ydwx_mallNo", "20014")
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

APP_ID = "68a91a5bac6a4f3e91bf4b42856785c6"
SIGN_SECRET = "P@Gkbu0shTNHjhM!7F"
SWIMLANE = "s1"
API_VERSION = "1.0"
ACTION = "mixc.app.memberSign.sign"
PLATFORM = "h5"
APP_VERSION = "4.0.12"
OS_VERSION = "16.6.1"
IMEI = "2333"
URL = "https://app.mixcapp.com/mixc/gateway"

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 crland/4.4.0 grayscale/0 /MIXCAPP/4.0.12 AnalysysAgent/Hybrid")

PARAMS_BASE = urllib.parse.quote(json.dumps({"mallNo": MALL_NO}, separators=(",", ":")))


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def build_sign(device_params: str, token: str, timestamp: str) -> str:
    """按 key 排序后拼接 MD5，与 bash 版一致。签名时使用 URL 解码后的值。"""
    t = str(int(timestamp) + 25)
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fields = {
        "X-Mixc-Swimlane": SWIMLANE,
        "action": ACTION,
        "apiVersion": API_VERSION,
        "appId": APP_ID,
        "appVersion": APP_VERSION,
        "date": date,
        "deviceParams": urllib.parse.unquote(device_params),
        "imei": IMEI,
        "mallNo": MALL_NO,
        "osVersion": OS_VERSION,
        "params": urllib.parse.unquote(PARAMS_BASE),
        "platform": PLATFORM,
        "t": t,
        "timestamp": timestamp,
        "token": token,
    }

    sign_src = "&".join(f"{k}={fields[k]}" for k in sorted(fields)) + f"&{SIGN_SECRET}"
    return hashlib.md5(sign_src.encode("utf-8")).hexdigest(), t, date


def build_body(device_params: str, token: str, timestamp: str) -> str:
    """构建请求体，deviceParams/params 保持 URL 编码。"""
    sign, t, date = build_sign(device_params, token, timestamp)

    body_parts = [
        ("mallNo", MALL_NO),
        ("appId", APP_ID),
        ("platform", PLATFORM),
        ("imei", IMEI),
        ("appVersion", APP_VERSION),
        ("osVersion", OS_VERSION),
        ("action", ACTION),
        ("apiVersion", API_VERSION),
        ("timestamp", timestamp),
        ("deviceParams", device_params),
        ("X-Mixc-Swimlane", SWIMLANE),
        ("t", t),
        ("date", urllib.parse.quote(date)),
        ("token", token),
        ("params", PARAMS_BASE),
        ("sign", sign),
    ]
    return "&".join(f"{k}={v}" for k, v in body_parts)


def build_referer(timestamp: str) -> str:
    return (f"https://app.mixcapp.com/m/m-{MALL_NO}/signIn?"
            f"appVersion={APP_VERSION}&mallNo={MALL_NO}&timestamp={timestamp}"
            f"&showWebNavigation=true&hideNativeNavigation=true")


def sign_once(device_params: str, token: str, index: int) -> str:
    """单账号签到，返回结果摘要。"""
    label = f"账号{index}"
    timestamp = str(int(time.time() * 1000))

    body = build_body(device_params, token, timestamp)
    referer = build_referer(timestamp)

    headers = {
        "Host": "app.mixcapp.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Origin": "https://app.mixcapp.com",
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": referer,
    }

    try:
        resp = requests.post(URL, headers=headers, data=body, timeout=30)
        data = resp.json()
    except requests.RequestException as e:
        log(f"  ❌ [{label}] 请求异常: {e}")
        return f"[{label}] 请求异常: {e}"
    except json.JSONDecodeError:
        log(f"  ❌ [{label}] 响应非JSON: {resp.text[:200]}")
        return f"[{label}] 响应非JSON"

    msg = data.get("message", "")
    code = data.get("code")

    if code == 0 or data.get("success") is True:
        point = data.get("data", {}).get("point")
        extra = f" +{point}积分" if point else ""
        log(f"  ✅ [{label}] 签到成功{extra}")
        return f"[{label}] 签到成功{extra}"

    if "已签到" in msg or "不可重复签到" in msg:
        log(f"  ℹ️ [{label}] 今日已签到")
        return f"[{label}] 今日已签到"

    if "请求频繁" in msg:
        log(f"  ⚠️ [{label}] 请求频繁，签名通过但需稍后重试")
        return f"[{label}] 请求频繁"

    log(f"  ❌ [{label}] 失败: {msg}")
    return f"[{label}] {msg}"


def send_notify(content: str) -> None:
    if not PLUSPLUS_TOKEN:
        return
    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": PLUSPLUS_TOKEN, "title": "一点万象签到", "content": content, "template": "txt"},
            timeout=10,
        )
        if resp.status_code == 200:
            log("✅ PushPlus 推送成功")
    except Exception as e:
        log(f"❌ PushPlus 推送失败: {e}")


# ════════════════════════════════════
# 主流程
# ════════════════════════════════════
def main() -> None:
    log("===== 一点万象签到 =====")

    device_list = [x.strip() for x in DEVICE_PARAMS_LIST.split("&") if x.strip()]
    token_list = [x.strip() for x in TOKEN_LIST.split("&") if x.strip()]

    if not device_list or not token_list:
        log("❌ 未配置 ydwx_deviceParams 或 ydwx_token")
        sys.exit(1)

    if len(device_list) != len(token_list):
        log(f"⚠️ deviceParams({len(device_list)}个) 与 token({len(token_list)}个) 数量不一致，按较短的执行")

    n = min(len(device_list), len(token_list))
    log(f"共 {n} 个账号 | mallNo={MALL_NO}\n")

    results = []
    for i in range(n):
        results.append(sign_once(device_list[i], token_list[i], i + 1))
        if i < n - 1:
            time.sleep(2)

    log("\n" + "=" * 40)
    summary = "\n".join(results)
    log(f"执行完毕\n{summary}")

    send_notify(summary.replace("\n", "<br>"))


if __name__ == "__main__":
    main()
