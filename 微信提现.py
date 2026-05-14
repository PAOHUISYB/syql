#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信支付日常赠金/免单券 领取脚本（WCS版）

通过 WCS (WeChatCodeServer) 获取 wx.login code，
自动登录微信支付领券小程序并领取每日赠金。

cron: "20 9 * * *"  每天 9:20 执行

环境变量：
  wx_server_url   WCS 服务端地址（必填，如 http://192.168.1.4:8787）
  wx_auth          WCS API Key（必填）
  wxpay            用户 openid（推荐，多账号用 # 分隔；如 6b9112d0）
  WX_OPENIDS       备选：用户 openid（多账号 # 或 , 分隔）
"""

from __future__ import annotations

import os
import secrets
import string
import sys
import time
from typing import Any

import requests

# ══════════════════════════════════════
# WCS 客户端（内联，避免青龙 import 路径问题）
# ══════════════════════════════════════

WCS_URL = os.environ.get("wx_server_url", "").rstrip("/")
WCS_AUTH = os.environ.get("wx_auth", "")


def _wcs_base_urls() -> list[str]:
    if WCS_URL:
        return [WCS_URL]
    return []


def _wcs_debug(action: str, response: requests.Response) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        body = response.text[:500] if response.text else "(empty)"
    except Exception:
        body = "(unreadable)"
    print(f"  [{ts}] {action} ← HTTP {response.status_code} | {body}", file=sys.stderr)


def resolve_openids() -> list[str]:
    """优先读环境变量 wxpay / WX_OPENIDS，回退调 /api/accounts"""
    for env_key in ("wxpay", "WX_OPENIDS"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            ids = [s.strip() for s in raw.replace(",", "#").split("#") if s.strip()]
            if ids:
                return ids
    for url in _wcs_base_urls():
        try:
            resp = requests.get(f"{url}/api/accounts", headers={"auth": WCS_AUTH}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [str(item) for item in data]
            if isinstance(data, dict) and "data" in data:
                accounts = data["data"]
                if isinstance(accounts, list):
                    return [str(a.get("openid", a)) for a in accounts if a]
        except Exception as err:
            print(f"⚠️ /api/accounts 失败：{err}", file=sys.stderr)
    return []


def get_login_codes(
    appid: str,
    openid: str,
    *,
    code_count: int = 1,
    base_url: str | list[str] | None = None,
    timeout: int = 90,
    init_retries: int = 2,
) -> list[str]:
    """通过 WCS /wx/code 获取 wx.login code 列表"""
    urls: list[str] = []
    if base_url is None:
        urls = _wcs_base_urls()
    elif isinstance(base_url, str):
        urls = [base_url]
    elif isinstance(base_url, list):
        urls = base_url
    else:
        raise ValueError(f"无效的 base_url 类型：{type(base_url)}")

    if not urls:
        raise RuntimeError("未配置 WCS 服务端地址（wx_server_url）")

    codes: list[str] = []

    for url in urls:
        for attempt in range(init_retries + 1):
            try:
                endpoint = f"{url.rstrip('/')}/wx/code"
                print(
                    f"  📡 POST {endpoint} appid={appid} openid={_mask(openid)}"
                    + (f" (重试 {attempt}/{init_retries})" if attempt else ""),
                    file=sys.stderr,
                )
                resp = requests.post(
                    endpoint,
                    headers={"auth": WCS_AUTH, "Content-Type": "application/json"},
                    json={"appid": appid, "openid": openid},
                    timeout=timeout,
                )
                resp.raise_for_status()
                payload = resp.json()
                _wcs_debug("/wx/code", resp)

                status = payload.get("status")
                message = payload.get("message", "")
                data = payload.get("data")

                if not status or not data:
                    raise RuntimeError(f"WCS 返回失败：status={status}, message={message}")

                code = data.get("code", "")
                if not code:
                    lr = data.get("loginResponse") or {}
                    auth_failed = lr.get("authFailedLine", "")
                    cached = lr.get("cachedLoginFallback", False)
                    detail = f" (cachedFallback={cached}, authFailed={auth_failed})" if lr else ""
                    raise RuntimeError(f"data.code 为空{detail}")

                codes.append(code)
                print(f"  ✅ 获取 code 成功：{code[:20]}...", file=sys.stderr)

                if len(codes) >= code_count:
                    return codes
                break

            except requests.exceptions.Timeout:
                print(f"  ⏰ 超时 ({timeout}s)" + (f"，重试..." if attempt < init_retries else "，放弃"), file=sys.stderr)
            except requests.exceptions.HTTPError as e:
                body = e.response.text[:200] if e.response.text else ""
                print(f"  🔴 HTTP {e.response.status_code} {body}" + (f"，重试..." if attempt < init_retries else "，放弃"), file=sys.stderr)
            except Exception as e:
                print(f"  ❌ {e}" + (f"，重试..." if attempt < init_retries else "，放弃"), file=sys.stderr)

    if not codes:
        raise RuntimeError(f"未能获取到任何 code（已尝试 {len(urls)} 个节点）")
    return codes


def _mask(openid: str) -> str:
    if len(openid) <= 12:
        return openid
    return f"{openid[:6]}...{openid[-4:]}"


# ══════════════════════════════════════
# 微信支付领券业务逻辑
# ══════════════════════════════════════

APPID = "wxdb3c0e388702f785"
CODE_COUNT = 1
TARGET_COUPON_ID: int | None = None
API_TIMEOUT = 15
BRIDGE_TIMEOUT = 90
BRIDGE_INIT_RETRIES = 2

DOMAIN = "https://discount.wxpapp.wechatpay.cn"
PAGE = "pages/gift/index"
MODULE_NAME = "mmpaytxbbsmp"
PAGE_FRAME_VERSION = "180"
SESSION_SCENE = "daily_reward"

USER_AGENT_LIST = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 "
    "MicroMessenger/8.0.71 NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 13; Redmi K60) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/130.0.6723.102 Mobile Safari/537.36 "
    "MicroMessenger/8.0.50 NetType/WIFI Language/zh_CN ABI/arm64v8a MiniProgramEnv/android",
    "Mozilla/5.0 (Linux; Android 12; MI 11) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/125.0.6422.111 Mobile Safari/537.36 "
    "MicroMessenger/8.0.45 NetType/WIFI Language/zh_CN ABI/arm64-v8a MiniProgramEnv/android",
]


class ClaimError(RuntimeError):
    pass


def get_ua() -> str:
    return USER_AGENT_LIST[secrets.randbelow(len(USER_AGENT_LIST))]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    print("=" * 55)
    print("  🌸 微信支付日常赠金 领取脚本 (WCS版)")
    print(f"  ⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    if not os.environ.get("wx_server_url") or not os.environ.get("wx_auth"):
        print("\n❌ 未配置 WCS 环境变量（wx_server_url / wx_auth）")
        return 1

    openids = resolve_openids()
    if not openids:
        print("\n❌ 未获取到账号：请配置 wxpay 或 WX_OPENIDS 环境变量")
        return 1

    print(f"\n📋 共 {len(openids)} 个账号\n")

    ok_count = 0
    for index, openid in enumerate(openids, start=1):
        prefix = f"🌸 账号[{index}]"
        try:
            result = run_account(openid)
            print_success(prefix, openid, result)
            ok_count += 1
        except Exception as err:
            print(f"{prefix} ❌ 处理失败（{_mask(openid)}）")
            print(f"{prefix} 错误：{err}")

    print(f"\n{'=' * 55}")
    print(f"  结果：✅ {ok_count}/{len(openids)} 成功")
    print(f"{'=' * 55}")
    return 0 if ok_count == len(openids) else 1


def run_account(openid: str) -> dict[str, Any]:
    track_id = make_track_id()
    session = requests.Session()
    UA = get_ua()

    codes = get_login_codes(APPID, openid, code_count=CODE_COUNT, timeout=BRIDGE_TIMEOUT, init_retries=BRIDGE_INIT_RETRIES)
    session_token, used_code_index = login_with_codes(session, codes, track_id, UA)
    coupons = query_coupons(session, session_token, track_id, UA)
    coupon = select_coupon(coupons)

    if coupon is None:
        claimed_coupon = next((item for item in coupons if item.get("is_claimed")), None)
        return {"code_count": len(codes), "used_code_index": used_code_index,
                "status": "already_claimed" if claimed_coupon else "no_daily", "coupon": claimed_coupon}

    if coupon.get("is_claimed"):
        status = "already_claimed"
    else:
        claim_coupon(session, session_token, track_id, coupon, UA)
        status = "claimed"

    return {"code_count": len(codes), "used_code_index": used_code_index, "status": status, "coupon": coupon}


def login_with_codes(session: requests.Session, codes: list[str], track_id: str, UA: str) -> tuple[str, int]:
    errors: list[str] = []
    for index, code in enumerate(codes, start=1):
        try:
            data = api_get(session, "/txbbs-user/user/login", headers=make_headers(track_id, jscode=code, UA=UA), UA=UA)
            token = data.get("session_token")
            if not isinstance(token, str) or not token:
                raise ClaimError(f"登录返回缺少 session_token：{data}")
            return token, index
        except Exception as err:
            errors.append(f"第{index}个code失败：{err}")
    raise ClaimError("全部 code 登录失败：" + "；".join(errors))


def query_coupons(session: requests.Session, session_token: str, track_id: str, UA: str) -> list[dict[str, Any]]:
    data = api_get(session, "/txbbs-mall/coupon/querydailygiftcoupons",
                   headers=make_headers(track_id, session_token=session_token, UA=UA), UA=UA)
    items = data.get("coupon_items")
    if not isinstance(items, list):
        raise ClaimError(f"查询返回缺少 coupon_items：{data}")
    return [item for item in items if isinstance(item, dict)]


def select_coupon(coupons: list[dict[str, Any]]) -> dict[str, Any] | None:
    if TARGET_COUPON_ID is not None:
        return next((item for item in coupons if _coupon_id(item) == TARGET_COUPON_ID), None)
    return next((item for item in coupons if not item.get("is_claimed") and _coupon_id(item)), None)


def claim_coupon(session: requests.Session, session_token: str, track_id: str, coupon: dict[str, Any], UA: str) -> None:
    cid = _coupon_id(coupon)
    gift_type = coupon.get("daily_gift_type")
    amount = _face_value(coupon)
    if not isinstance(cid, int):
        raise ClaimError(f"券缺少 coupon_id：{coupon}")
    if not isinstance(gift_type, str) or not gift_type:
        raise ClaimError(f"券缺少 daily_gift_type：{coupon}")
    if not isinstance(amount, int):
        raise ClaimError(f"券缺少 face_value：{coupon}")
    api_post(session, "/txbbs-mall/coupon/claimdailygiftcoupon",
             headers=make_headers(track_id, session_token=session_token, session_id=make_session_id(), UA=UA),
             json={"daily_gift_type": gift_type, "coupon_id": cid, "expected_send_amount": amount}, UA=UA)


def print_success(prefix: str, openid: str, result: dict[str, Any]) -> None:
    print(f"\n{prefix} ✅ 登录成功（{_mask(openid)}）")
    print(f"{prefix} Code：共获取{result['code_count']}个，使用第{result['used_code_index']}个")
    coupon = result.get("coupon")
    if not isinstance(coupon, dict):
        print(f"{prefix} 未查询到每日额度")
        return
    name = _coupon_name(coupon)
    amount = _coupon_amount(coupon)
    status = result.get("status")
    if status == "claimed":
        print(f"{prefix} ✅ 领取成功：{name}")
        print(f"{prefix} 💰 到账额度：{amount}")
    elif status == "already_claimed":
        print(f"{prefix} 📋 今日已领取：{name}")
        print(f"{prefix} 💰 当前额度：{amount}")
    else:
        print(f"{prefix} ⚠️ 未查询到每日额度")


# ── HTTP 工具函数 ──

def api_get(session: requests.Session, path: str, *, headers: dict[str, str], UA: str) -> dict[str, Any]:
    response = session.get(f"{DOMAIN}{path}", headers=headers, timeout=API_TIMEOUT)
    return _unwrap(response, path)


def api_post(session: requests.Session, path: str, *, headers: dict[str, str], json: dict[str, Any], UA: str) -> dict[str, Any]:
    response = session.post(f"{DOMAIN}{path}", headers=headers, json=json, timeout=API_TIMEOUT)
    return _unwrap(response, path)


def _unwrap(response: requests.Response, action: str) -> dict[str, Any]:
    _wcs_debug(action, response)
    try:
        response.raise_for_status()
        payload = response.json()
    except Exception as err:
        raise ClaimError(f"{action} 请求失败：{err}，响应：{response.text}") from err
    if not isinstance(payload, dict):
        raise ClaimError(f"{action} 返回格式异常：{payload!r}")
    if payload.get("errcode") != 0:
        raise ClaimError(f"{action} 返回失败：errcode={payload.get('errcode')}，{payload}")
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def make_headers(track_id: str, *, jscode: str | None = None, session_token: str | None = None,
                 session_id: str | None = None, UA: str | None = None) -> dict[str, str]:
    effective_ua = UA or get_ua()
    h = {
        "User-Agent": effective_ua,
        "Content-Type": "application/json",
        "X-Page": PAGE,
        "X-Track-Id": track_id,
        "xweb_xhr": "1",
        "X-Module-Name": MODULE_NAME,
        "X-Appid": APPID,
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/{PAGE_FRAME_VERSION}/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if jscode:
        h["jscode"] = jscode
    if session_token:
        h["session-token"] = session_token
    if session_id:
        h["session-id"] = session_id
    return h


def make_track_id() -> str:
    return "T" + "".join(secrets.choice("0123456789ABCDEF") for _ in range(31))


def make_session_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    rp = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{SESSION_SCENE}-{int(time.time() * 1000)}-{rp}"


# ── 券信息辅助函数 ──

def _ci(coupon: dict[str, Any]) -> dict[str, Any]:
    v = coupon.get("coupon_info")
    return v if isinstance(v, dict) else {}


def _coupon_id(coupon: dict[str, Any]) -> int | None:
    return _ci(coupon).get("coupon_id") if isinstance(_ci(coupon).get("coupon_id"), int) else None


def _face_value(coupon: dict[str, Any]) -> int | None:
    return _ci(coupon).get("face_value") if isinstance(_ci(coupon).get("face_value"), int) else None


def _coupon_name(coupon: dict[str, Any]) -> str:
    name = _ci(coupon).get("name")
    return name if isinstance(name, str) and name else f"coupon_id={_coupon_id(coupon)}"


def _coupon_amount(coupon: dict[str, Any]) -> str:
    amount = _face_value(coupon)
    if not isinstance(amount, int):
        return "未知额度"
    return f"{amount // 100}元" if amount % 100 == 0 else f"{amount / 100:.2f}元"


if __name__ == "__main__":
    raise SystemExit(main())
