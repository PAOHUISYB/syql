#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一点万象 每日签到
=================
H5 应用，通过 deviceParams + token 直接签到。

抓包: App 内点签到 → 筛选 app.mixcapp.com/mixc/gateway → POST 请求体

环境变量:
  ydwx_deviceParams — 多账号 deviceParams，用 & 分隔
  ydwx_token        — 多账号 token，用 & 分隔（与 deviceParams 一一对应）
  ydwx_mallNo       — 商场编号，默认 20014
  ydwx_imei         — 设备 IMEI，默认从 deviceParams 提取
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
# 环境变量
# ════════════════════════════════════
DEVICE_PARAMS_LIST = os.getenv("ydwx_deviceParams", "")
TOKEN_LIST = os.getenv("ydwx_token", "")
MALL_NO = os.getenv("ydwx_mallNo", "20014")
IMEI = os.getenv("ydwx_imei", "")  # 留空则自动从 deviceParams JSON 提取
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# ════════════════════════════════════
# 固定配置
# ════════════════════════════════════
APP_ID = "68a91a5bac6a4f3e91bf4b42856785c6"
APP_VERSION = "4.1.9"
OS_VERSION = "26.4"
SIGN_SECRET = "P@Gkbu0shTNHjhM!7F"
SWIMLANE = "s1"
URL = "https://app.mixcapp.com/mixc/gateway"

# 2026-05 HAR 实测 action 已从 mixc.app.memberSign.sign 变为 signDate
ACTION = "mixc.app.memberSign.signDate"

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) crland/4.4.0 grayscale/0 /MIXCAPP/4.1.9 AnalysysAgent/Hybrid")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def extract_imei(device_params: str) -> str:
    """尝试从 deviceParams JSON 中提取 deviceId 作为 imei。"""
    try:
        decoded = urllib.parse.unquote(device_params)
        data = json.loads(decoded)
        return data.get("deviceId", "")
    except Exception:
        return ""


def sign_once(device_params: str, token: str, index: int) -> str:
    """单账号签到。签名算法：所有字段按 key 排序，URL 解码后拼接 + secret，MD5。"""
    label = f"账号{index}"
    timestamp = str(int(time.time() * 1000))
    t = str(int(timestamp) + 25)
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    imei = IMEI or extract_imei(device_params)
    params_raw = urllib.parse.quote(json.dumps({"mallNo": MALL_NO}, separators=(",", ":")))

    # 签名字段（按 key 排序，URL 解码后参与签名）
    fields = {
        "X-Mixc-Swimlane": SWIMLANE,
        "action": ACTION,
        "apiVersion": "1.0",
        "appId": APP_ID,
        "appVersion": APP_VERSION,
        "date": date,
        "deviceParams": urllib.parse.unquote(device_params),
        "imei": imei,
        "mallNo": MALL_NO,
        "osVersion": OS_VERSION,
        "params": urllib.parse.unquote(params_raw),
        "platform": "h5",
        "t": t,
        "timestamp": timestamp,
        "token": token,
    }

    sign_src = "&".join(f"{k}={fields[k]}" for k in sorted(fields)) + f"&{SIGN_SECRET}"
    sign = hashlib.md5(sign_src.encode("utf-8")).hexdigest()

    # 请求体（deviceParams/params 保持 URL 编码）
    body = (
        f"mallNo={MALL_NO}"
        f"&appId={APP_ID}"
        f"&platform=h5"
        f"&imei={imei}"
        f"&appVersion={APP_VERSION}"
        f"&osVersion={OS_VERSION}"
        f"&action={ACTION}"
        f"&apiVersion=1.0"
        f"&timestamp={timestamp}"
        f"&deviceParams={device_params}"
        f"&X-Mixc-Swimlane={SWIMLANE}"
        f"&t={t}"
        f"&date={urllib.parse.quote(date)}"
        f"&token={token}"
        f"&params={params_raw}"
        f"&sign={sign}"
    )

    headers = {
        "Host": "app.mixcapp.com",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://app.mixcapp.com",
        "User-Agent": UA,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Referer": (f"https://app.mixcapp.com/m/m-{MALL_NO}/signIn?"
                    f"mallNo={MALL_NO}&appVersion={APP_VERSION}&timestamp={timestamp}"),
    }

    try:
        resp = requests.post(URL, headers=headers, data=body, timeout=30)
        data = resp.json()
    except requests.RequestException as e:
        log(f"  ❌ [{label}] 请求异常: {e}")
        return f"[{label}] 请求异常"
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
        log(f"  ⚠️ [{label}] 请求频繁")
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

    n = min(len(device_list), len(token_list))
    if len(device_list) != len(token_list):
        log(f"⚠️ deviceParams({len(device_list)}个) 与 token({len(token_list)}个) 数量不一致，执行前 {n} 个")

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
