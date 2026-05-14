#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信支付提现笔笔省 + 日常赠金 领取脚本（WCS版）

通过 WCS (WeChatCodeServer) 获取 wx.login code，
支持：领每日赠金、领笔笔省优惠券、查询余额

功能：
  1. 每日赠金（daily gift）领取
  2. 笔笔省优惠券（gift）领取
  3. 余额查询
  4. Token 本地缓存（下次先读缓存，无效再授权）
  5. 多账号代理轮流（PROXY_API_URL）

cron: "20 9 * * *" 每天 9:20 执行
cron: "10 11,12 * * *" 笔笔省每天 11:10 和 12:10 执行

环境变量：
  wx_server_url   WCS 服务端地址（必填，如 http://192.168.1.4:8787）
  wx_auth         WCS API Key（必填）
  wxpay           微信 openid（多账号用 # 分隔）
  WX_OPENIDS      备选 openid 环境变量
  PROXY_API_URL   代理 API，返回 txt 文本（ip:port），不填则不使用代理
"""

from __future__ import annotations

import os
import random
import secrets
import string
import sys
import time
import json
import traceback
from typing import Any

import requests

# ══════════════════════════════════════
# 通知模块
# ══════════════════════════════════════

def send_notify(title: str, content: str) -> None:
    """调用青龙内置 sendNotify（兼容多种导出名）"""
    # 方式1：青龙的 sendNotify
    try:
        sys.path.append('/ql')
        from sendNotify import sendNotify as _sn
        _sn(title, content)
        print(f"\n[通知] ✅ 已发送：{title}", file=sys.stderr)
        return
    except Exception:
        pass
    # 方式2：直接 import notify
    try:
        import notify
        if hasattr(notify, 'send'):
            notify.send(title, content)
            print(f"\n[通知] ✅ 已发送（notify.send）：{title}", file=sys.stderr)
            return
        if hasattr(notify, 'sendNotify'):
            notify.sendNotify(title, content)
            print(f"\n[通知] ✅ 已发送（notify.sendNotify）：{title}", file=sys.stderr)
            return
    except Exception:
        pass
    # 方式3：尝试下载青龙官方 notify.py
    try:
        import urllib.request
        url = "https://raw.githubusercontent.com/whyour/qinglong/refs/heads/develop/sample/notify.py"
        urllib.request.urlretrieve(url, "notify.py")
        import notify as nm
        if hasattr(nm, 'send'):
            nm.send(title, content)
            print(f"\n[通知] ✅ 已发送（下载 notify）：{title}", file=sys.stderr)
            return
    except Exception:
        pass
    print(f"\n[通知] ⚠️ 无法发送：未找到 notify 模块", file=sys.stderr)


_notify_lines: list[str] = []


def _notify(msg: str) -> None:
    _notify_lines.append(msg)


# ══════════════════════════════════════
# WCS 配置
# ══════════════════════════════════════

WCS_URL = os.environ.get("wx_server_url", "").rstrip("/")
WCS_AUTH = os.environ.get("wx_auth", "")

# 代理配置
PROXY_API_URL = os.environ.get("PROXY_API_URL", "").strip()


def _wcs_base_urls() -> list[str]:
    return [WCS_URL] if WCS_URL else []


def _wcs_debug(action: str, response: requests.Response) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        body = response.text[:300] if response.text else "(empty)"
    except Exception:
        body = "(unreadable)"
    print(f" [{ts}] {action} ← HTTP {response.status_code} | {body}", file=sys.stderr)


def resolve_openids() -> list[str]:
    """读取 wxpay / WX_OPENIDS 环境变量"""
    for env_key in ("wxpay", "WX_OPENIDS"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            ids = [s.strip() for s in raw.replace(",", "#").split("#") if s.strip()]
            if ids:
                return ids
    return []


def get_login_codes(
    appid: str,
    openid: str,
    *,
    code_count: int = 1,
    timeout: int = 90,
    init_retries: int = 2,
) -> list[str]:
    """通过 WCS 获取 wx.login code"""
    urls = _wcs_base_urls()
    if not urls:
        raise RuntimeError("未配置 WCS 服务端地址（wx_server_url）")

    codes: list[str] = []
    for url in urls:
        for attempt in range(init_retries + 1):
            try:
                endpoint = f"{url.rstrip('/')}/wx/code"
                print(
                    f" 📡 POST {endpoint} appid={appid} openid={_mask(openid)}"
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
                data = payload.get("data")
                if not status or not data:
                    raise RuntimeError(f"WCS 返回失败：status={status}, message={payload.get('message')}")

                code = data.get("code", "")
                if not code:
                    lr = data.get("loginResponse") or {}
                    cached = lr.get("cachedLoginFallback", False)
                    raise RuntimeError(f"code为空 (cachedFallback={cached})")

                codes.append(code)
                print(f" ✅ code 获取成功：{code[:20]}...", file=sys.stderr)
                if len(codes) >= code_count:
                    return codes
                break

            except requests.exceptions.Timeout:
                print(f" ⏰ 超时 ({timeout}s)" + (f"，重试..." if attempt < init_retries else "，放弃"), file=sys.stderr)
            except Exception as e:
                print(f" ❌ {e}" + (f"，重试..." if attempt < init_retries else "，放弃"), file=sys.stderr)

    if not codes:
        raise RuntimeError(f"未能获取到任何 code（已尝试 {len(urls)} 个节点）")
    return codes


def _mask(openid: str) -> str:
    return openid if len(openid) <= 12 else f"{openid[:6]}...{openid[-4:]}"


# ══════════════════════════════════════
# 代理模块
# ══════════════════════════════════════

_proxy_index = 0


def get_proxy() -> str | None:
    """从 PROXY_API_URL 获取一个代理 ip:port"""
    global _proxy_index
    if not PROXY_API_URL:
        return None
    try:
        resp = requests.get(PROXY_API_URL, timeout=10)
        resp.raise_for_status()
        proxy = resp.text.strip()
        print(f" 🌐 代理: {proxy}", file=sys.stderr)
        return proxy
    except Exception as e:
        print(f" ⚠️ 获取代理失败：{e}，跳过使用代理", file=sys.stderr)
        return None


def apply_proxy(session: requests.Session, proxy: str | None) -> None:
    """为 session 应用代理"""
    if not proxy:
        session.proxies.clear()
        return
    session.proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}",
    }


# ══════════════════════════════════════
# Token 本地缓存（account_info.json）
# ══════════════════════════════════════

ACCOUNT_FILE = "wxpay_account_info.json"


def load_account_info() -> dict[str, dict]:
    """加载本地缓存的账号 token"""
    if not os.path.exists(ACCOUNT_FILE):
        return {}
    try:
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_account_info(info: dict[str, dict]) -> None:
    """保存账号 token 到本地缓存"""
    try:
        with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        print(f" 💾 本地缓存已更新（{len(info)} 个账号）", file=sys.stderr)
    except Exception as e:
        print(f" ⚠️ 保存缓存失败：{e}", file=sys.stderr)


# ══════════════════════════════════════
# 微信支付领券业务逻辑
# ══════════════════════════════════════

APPID = "wxdb3c0e388702f785"
API_TIMEOUT = 15
BRIDGE_TIMEOUT = 90
BRIDGE_INIT_RETRIES = 2

DOMAIN = "https://discount.wxpapp.wechatpay.cn"
PAGE = "pages/gift/index"
MODULE_NAME = "mmpaytxbbsmp"
PAGE_FRAME_VERSION = "180"

# 是否领取每日赠金（daily gift）
ENABLE_DAILY_GIFT = True
# 是否领取笔笔省优惠券（gift）
ENABLE_GIFT_REDEEM = True

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


# ── HTTP 工具 ──

def api_get(session: requests.Session, path: str, headers: dict, ua: str) -> dict[str, Any]:
    resp = session.get(f"{DOMAIN}{path}", headers=headers, timeout=API_TIMEOUT)
    return _unwrap(resp, path)


def api_post(session: requests.Session, path: str, headers: dict, json_data: dict, ua: str) -> dict[str, Any]:
    resp = session.post(f"{DOMAIN}{path}", headers=headers, json=json_data, timeout=API_TIMEOUT)
    return _unwrap(resp, path)


def _unwrap(resp: requests.Response, action: str) -> dict[str, Any]:
    _wcs_debug(action, resp)
    try:
        resp.raise_for_status()
        payload = resp.json()
    except Exception as err:
        raise ClaimError(f"{action} 请求失败：{err}，响应：{resp.text[:200]}") from err
    if not isinstance(payload, dict):
        raise ClaimError(f"{action} 返回格式异常：{payload!r}")
    if payload.get("errcode", -1) not in (0, None):
        msg = payload.get("msg") or payload.get("errmsg") or ""
        raise ClaimError(f"{action} 失败：errcode={payload.get('errcode')}，{msg}")
    return payload.get("data", {}) if isinstance(payload, dict) else {}


# ── Header 构造 ──

def make_headers(track_id: str, *, jscode: str | None = None,
                 session_token: str | None = None, session_id: str | None = None,
                 ua: str | None = None) -> dict[str, str]:
    h = {
        "User-Agent": ua or get_ua(),
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
    # 注意：微信支付 API 要求 Session-Token 首字母大写！
    if session_token:
        h["Session-Token"] = session_token
    if session_id:
        h["session-id"] = session_id
    return h


def make_track_id() -> str:
    return "T" + "".join(secrets.choice("0123456789ABCDEF") for _ in range(31))


def make_session_id() -> str:
    rp = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    return f"daily_reward-{int(time.time() * 1000)}-{rp}"


# ── 业务接口 ──

def login_with_codes(session: requests.Session, codes: list[str], track_id: str, ua: str) -> tuple[str, int]:
    """用 code 列表尝试登录，返回 (session_token, used_index)"""
    errors: list[str] = []
    for index, code in enumerate(codes, start=1):
        try:
            data = api_get(session, "/txbbs-user/user/login",
                           headers=make_headers(track_id, jscode=code, ua=ua), ua=ua)
            token = data.get("session_token")
            if not isinstance(token, str) or not token:
                raise ClaimError(f"login 返回缺少 session_token：{data}")
            print(f"  ✅ 登录成功（code #{index}）", file=sys.stderr)
            return token, index
        except Exception as err:
            errors.append(f"第{index}个code失败：{err}")
    raise ClaimError("全部 code 登录失败：" + "；".join(errors))


def get_balance(session: requests.Session, track_id: str, token: str, ua: str) -> dict[str, Any]:
    """
    查询余额、提现免费券、提现额度
    返回完整余额信息字典
    API 返回示例：{"balance":"887104","pending_balance":"0","total_deduct_face_value":"8.87"}
    """
    try:
        data = api_get(session, "/txbbs-mall/cashoutfree/getbalance",
                       headers=make_headers(track_id, session_token=token, ua=ua), ua=ua)
        balance = data.get("balance", 0)
        free_count = data.get("free_coupon_count", 0)
        # 提现额度相关字段
        withdrawable = data.get("withdrawable_balance", balance)  # 可提现金额
        total_earned = data.get("total_earned", 0)  # 累计获得
        total_withdrawn = data.get("total_withdrawn", 0)  # 累计提现
        return {
            "balance": balance,
            "free_count": free_count,
            "withdrawable": withdrawable,
            "total_earned": total_earned,
            "total_withdrawn": total_withdrawn,
            "raw": data,
        }
    except Exception as e:
        print(f"  ⚠️ 查余额失败：{e}", file=sys.stderr)
        return {"balance": 0, "free_count": 0, "withdrawable": 0, "total_earned": 0, "total_withdrawn": 0, "raw": {}}


def get_gifts_list(session: requests.Session, track_id: str, token: str, ua: str) -> list[dict]:
    """获取笔笔省优惠券列表"""
    try:
        data = api_get(session, "/txbbs-mall/gift/listgifts?longitude=0&latitude=0",
                       headers=make_headers(track_id, session_token=token, ua=ua), ua=ua)
        items = data.get("gift_info_list", [])
        return [item for item in items if isinstance(item, dict)]
    except Exception as e:
        print(f"  ⚠️ 查优惠券列表失败：{e}", file=sys.stderr)
        return []


def redeem_gift(session: requests.Session, track_id: str, token: str, gift: dict, ua: str) -> bool:
    """领取笔笔省优惠券"""
    gift_id = gift.get("gift_id")
    gift_name = (gift.get("coupon_info") or {}).get("name", f"gift_id={gift_id}")
    try:
        api_post(session, "/txbbs-mall/gift/redeemgift",
                 headers=make_headers(track_id, session_token=token, session_id=make_session_id(), ua=ua),
                 json_data={"gift_id": gift_id}, ua=ua)
        print(f"  ✅ 领取成功：{gift_name}", file=sys.stderr)
        return True
    except ClaimError as e:
        print(f"  ❌ 领取失败：{gift_name} | {e}", file=sys.stderr)
        return False


def query_daily_gift_coupons(session: requests.Session, track_id: str, token: str, ua: str) -> list[dict]:
    """查询每日赠金券列表"""
    try:
        data = api_get(session, "/txbbs-mall/coupon/querydailygiftcoupons",
                       headers=make_headers(track_id, session_token=token, ua=ua), ua=ua)
        items = data.get("coupon_items", [])
        return [item for item in items if isinstance(item, dict)]
    except Exception as e:
        print(f"  ⚠️ 查每日赠金失败：{e}", file=sys.stderr)
        return []


def claim_daily_gift(session: requests.Session, track_id: str, token: str, coupon: dict, ua: str) -> bool:
    """领取每日赠金"""
    ci = coupon.get("coupon_info", {}) or {}
    cid = ci.get("coupon_id")
    gift_type = coupon.get("daily_gift_type")
    amount = ci.get("face_value")
    name = ci.get("name", f"coupon_id={cid}")
    if not all([cid, gift_type, amount]):
        return False
    try:
        api_post(session, "/txbbs-mall/coupon/claimdailygiftcoupon",
                 headers=make_headers(track_id, session_token=token, session_id=make_session_id(), ua=ua),
                 json_data={"daily_gift_type": gift_type, "coupon_id": cid,
                            "expected_send_amount": amount}, ua=ua)
        amount_str = f"{amount // 100}元" if amount % 100 == 0 else f"{amount / 100:.2f}元"
        print(f"  ✅ 领取成功：{name} {amount_str}", file=sys.stderr)
        return True
    except ClaimError as e:
        print(f"  ❌ 领取失败：{name} | {e}", file=sys.stderr)
        return False


# ── 主逻辑 ──

def run_account(openid: str, cached_token: str | None) -> dict[str, Any]:
    track_id = make_track_id()
    session = requests.Session()

    # 应用代理（多账号轮流）
    proxy = get_proxy()
    apply_proxy(session, proxy)

    ua = get_ua()
    token = None
    used_cached = False

    # 缓存策略：先尝试缓存的 token
    if cached_token:
        try:
            test_resp = session.get(
                f"{DOMAIN}/txbbs-mall/cashoutfree/getbalance",
                headers=make_headers(track_id, session_token=cached_token, ua=ua),
                timeout=API_TIMEOUT
            )
            if test_resp.status_code == 200:
                payload = test_resp.json()
                if payload.get("errcode") == 0:
                    token = cached_token
                    used_cached = True
                    print(f"  ✅ 缓存 token 有效，直接使用", file=sys.stderr)
        except Exception:
            pass

    # 缓存无效 → WCS 获取新 code
    if not token:
        codes = get_login_codes(APPID, openid, code_count=1,
                                timeout=BRIDGE_TIMEOUT, init_retries=BRIDGE_INIT_RETRIES)
        token, _ = login_with_codes(session, codes, track_id, ua)

    # 把 token 写入 session headers，确保后续所有请求都带上
    session.headers["Session-Token"] = token

    # ── 1. 查余额（登录后先查一次） ──
    bal = get_balance(session, track_id, token, ua)

    def _yuan(fen) -> str:
        """分转元，兼容字符串/整数/None"""
        try:
            v = int(fen)
        except (TypeError, ValueError):
            return "0元"
        if v == 0:
            return "0元"
        return f"{v // 100}元" if v % 100 == 0 else f"{v / 100:.2f}元"

    balance = bal["balance"]
    free_count = bal["free_count"]
    withdrawable = bal["withdrawable"]
    total_earned = bal["total_earned"]
    total_withdrawn = bal["total_withdrawn"]
    pending = bal.get("raw", {}).get("pending_balance", 0)
    deduct = bal.get("raw", {}).get("total_deduct_face_value", "")

    print(f"  💰 可提现额度：{_yuan(withdrawable)}", file=sys.stderr)
    print(f"  💰 账户余额：{_yuan(balance)}", file=sys.stderr)
    print(f"  ⏳ 待入账：{_yuan(pending)}", file=sys.stderr)
    print(f"  🎫 提现免费券：{free_count}张", file=sys.stderr)
    print(f"  📊 累计获得：{_yuan(total_earned)} | 累计提现：{_yuan(total_withdrawn)}", file=sys.stderr)
    if deduct:
        print(f"  📊 累计抵扣面值：{deduct}元", file=sys.stderr)

    results = {
        "openid": _mask(openid),
        "cached": used_cached,
        "latest_token": token,
        "balance": _yuan(balance),
        "withdrawable": _yuan(withdrawable),
        "free_coupons": free_count,
        "total_earned": _yuan(total_earned),
        "total_withdrawn": _yuan(total_withdrawn),
        "daily_gift_status": None,
        "daily_gift_coupon": None,
        "gift_redeemed": [],
        "gift_skipped": [],
        "errors": [],
    }

    # ── 2. 领每日赠金 ──
    if ENABLE_DAILY_GIFT:
        coupons = query_daily_gift_coupons(session, track_id, token, ua)
        for coupon in coupons:
            ci = coupon.get("coupon_info") or {}
            name = ci.get("name", "每日赠金")
            amount = ci.get("face_value")
            if not amount:
                continue
            amount_str = _yuan(amount)

            if coupon.get("is_claimed"):
                results["daily_gift_status"] = "already_claimed"
                results["daily_gift_coupon"] = f"{name} {amount_str}"
                print(f"  📋 今日已领取：{name} {amount_str}", file=sys.stderr)
            else:
                ok = claim_daily_gift(session, track_id, token, coupon, ua)
                results["daily_gift_status"] = "claimed" if ok else "failed"
                results["daily_gift_coupon"] = f"{name} {amount_str}"
                if ok:
                    _notify(f"✅ 每日赠金：{name} {amount_str}")

    # ── 3. 领笔笔省优惠券 ──
    if ENABLE_GIFT_REDEEM:
        gifts = get_gifts_list(session, track_id, token, ua)
        for gift in gifts:
            if gift.get("gift_type") != "GT_COUPON":
                continue
            if gift.get("gift_status") != "GS_AVAILABLE":
                continue
            ci = gift.get("coupon_info") or {}
            name = ci.get("name", f"gift_id={gift.get('gift_id')}")
            ok = redeem_gift(session, track_id, token, gift, ua)
            if ok:
                results["gift_redeemed"].append(name)
                _notify(f"✅ 笔笔省优惠券：{name}")
            else:
                results["gift_skipped"].append(name)

    # ── 4. 再次查询余额（领券后刷新） ──
    bal_after = get_balance(session, track_id, token, ua)
    balance_after = bal_after["balance"]
    free_count_after = bal_after["free_count"]
    withdrawable_after = bal_after["withdrawable"]

    print(f"\n  💰 可提现额度：{_yuan(withdrawable_after)}", file=sys.stderr)
    print(f"  💰 账户余额：{_yuan(balance_after)}", file=sys.stderr)
    print(f"  🎫 提现免费券：{free_count_after}张", file=sys.stderr)

    # 更新 results
    results["balance"] = _yuan(balance_after)
    results["withdrawable"] = _yuan(withdrawable_after)
    results["free_coupons"] = free_count_after

    _notify(f"账号 {_mask(openid)} | 可提现 {_yuan(withdrawable_after)} | 余额 {_yuan(balance_after)} | 免单券 {free_count_after}张")

    # 保留 _yuan 供后续 print_success 使用
    results["_yuan"] = _yuan

    session.close()
    return results


# ── 入口 ──

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    print("=" * 55)
    print(" 🌸 微信支付提现笔笔省 + 日常赠金 (WCS版)")
    print(f" ⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    if not os.environ.get("wx_server_url") or not os.environ.get("wx_auth"):
        print("\n❌ 未配置 WCS 环境变量（wx_server_url / wx_auth）")
        return 1

    openids = resolve_openids()
    if not openids:
        print("\n❌ 未获取到账号：请配置 wxpay 或 WX_OPENIDS 环境变量")
        return 1

    print(f"\n📋 共 {len(openids)} 个账号" + (f"，代理开启" if PROXY_API_URL else "，无代理"))
    print(f"✅ 每日赠金 {'开启' if ENABLE_DAILY_GIFT else '关闭'} | ✅ 笔笔省领券 {'开启' if ENABLE_GIFT_REDEEM else '关闭'}")
    print()

    # 加载本地缓存
    cached_accounts = load_account_info()
    new_accounts: dict[str, dict] = {}

    ok_count = 0
    fail_count = 0

    for index, openid in enumerate(openids, start=1):
        prefix = f"🌸 账号[{index}]"
        print(f"\n{prefix} {'─' * 40}")

        # 取出缓存的 token
        cached_info = cached_accounts.get(openid, {})
        cached_token = cached_info.get("token") if isinstance(cached_info, dict) else None

        try:
            result = run_account(openid, cached_token)

            # 保存新 token 到缓存
            new_accounts[openid] = {"token": result.get("latest_token", "")}

            print_success(prefix, result)
            ok_count += 1

        except Exception as err:
            print(f"{prefix} ❌ 处理失败（{_mask(openid)}）")
            print(f"{prefix} 错误：{err}")
            fail_count += 1
            _notify(f"【账号{index} {openid[:8]}...】❌ 失败：{err}")

    # 保存缓存
    if new_accounts:
        save_account_info(new_accounts)

    # 汇总通知
    print(f"\n{'=' * 55}")
    print(f" 结果：✅ {ok_count}/{len(openids)} 成功" + (f" | ❌ {fail_count} 失败" if fail_count else ""))
    print(f"{'=' * 55}")

    if _notify_lines:
        title = f"🌸 微信支付 ({ok_count}/{len(openids)})"
        content = "\n".join(_notify_lines)
        send_notify(title, content)

    return 0 if ok_count == len(openids) else 1


def print_success(prefix: str, result: dict) -> None:
    print(f"\n{prefix} ✅ 完成（{result['openid']}）")
    print(f"{prefix} 💰 可提现额度：{result['withdrawable']}")
    print(f"{prefix} 💰 账户余额：{result['balance']}")
    print(f"{prefix} 🎫 提现免费券：{result['free_coupons']}张")
    print(f"{prefix} 📊 累计获得：{result['total_earned']} | 累计提现：{result['total_withdrawn']}")

    dg = result.get("daily_gift_coupon")
    if dg:
        status = result.get("daily_gift_status")
        if status == "claimed":
            print(f"{prefix} 🎁 每日赠金：{dg}")
        elif status == "already_claimed":
            print(f"{prefix} 📋 今日已领：{dg}")

    redeemed = result.get("gift_redeemed", [])
    if redeemed:
        print(f"{prefix} 🎫 笔笔省领券：{len(redeemed)}个")
        for name in redeemed:
            print(f"{prefix}   ✅ {name}")
    else:
        print(f"{prefix} 🎫 笔笔省领券：无新券可领")


if __name__ == "__main__":
    raise SystemExit(main())
