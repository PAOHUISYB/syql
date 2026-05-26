#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三福小程序签到脚本 (WCS 适配版)
原始脚本作者：3iXi
WCS 适配 + 多账号支持

环境变量:
  sfwx          — 多账号 WCS userKey，用 # & 或 , 分隔
  wx_server_url — WCS 取码服务地址
  wx_auth       — WCS 认证 token
  PLUSPLUS_TOKEN — PushPlus 通知 token（可选）
"""

import os
import sys
import json
import time
import re
from datetime import datetime
from typing import Optional, List

try:
    import httpx
except ImportError:
    print("错误: 需要安装 httpx[http2] 依赖")
    sys.exit(1)

# ===================== WCS 配置 =====================
APPID = "wxfe13a2a5df88b058"
WX_SERVER_URL = os.getenv("wx_server_url", "")
WX_AUTH = os.getenv("wx_auth", "")
SFWX = os.getenv("sfwx", "")

# ===================== 通知配置 =====================
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# ===================== Token 缓存 =====================
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_sanfu.json")

def load_cache() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_userkeys() -> List[str]:
    """解析多账号 userKey，支持 & # , 分隔"""
    if not SFWX:
        return []
    return [x.strip() for x in re.split(r'[&#,]', SFWX) if x.strip()]


def get_code_from_wcs(user_key: str) -> Optional[str]:
    """从 WCS 服务获取 code"""
    if not WX_SERVER_URL or not WX_AUTH:
        print("❌ 未配置 wx_server_url 或 wx_auth")
        return None

    label = user_key[:10] + "..." if user_key else "单账号"
    body = {"appid": APPID}
    if user_key:
        body["openid"] = user_key

    try:
        resp = httpx.post(
            f"{WX_SERVER_URL}/wx/code",
            json=body,
            headers={"AUTH": WX_AUTH, "Content-Type": "application/json"},
            timeout=90.0,
        )
        data = resp.json()
        if data.get("status") and data.get("data", {}).get("code"):
            print(f"✅ [{label}] 获取code成功")
            return data["data"]["code"]
        print(f"❌ [{label}] 获取code失败: {data.get('message', '未知错误')}")
    except Exception as e:
        print(f"❌ [{label}] 获取code异常: {type(e).__name__} | {e}")
    return None


def send_pushplus(title: str, content: str) -> None:
    """PushPlus 通知"""
    if not PLUSPLUS_TOKEN:
        return
    try:
        httpx.post(
            "https://www.pushplus.plus/send",
            json={"token": PLUSPLUS_TOKEN, "title": title, "content": content, "template": "txt"},
            timeout=10.0,
        )
        print("✅ 通知推送成功")
    except Exception as e:
        print(f"❌ 通知推送失败: {e}")


class SanfuSignin:
    """三福小程序签到"""

    def __init__(self, user_key: str = ""):
        self.user_key = user_key
        self.base_url = "https://crm.sanfu.com"
        self.app_id = APPID
        self.client = httpx.Client(http2=True, timeout=30.0, verify=False)
        self.headers = {
            "host": "crm.sanfu.com",
            "connection": "keep-alive",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B)",
            "content-type": "application/json",
            "accept": "*/*",
            "referer": f"https://servicewechat.com/{APPID}/333/page-frame.html",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "zh-CN,zh;q=0.9",
        }
        self.sid = None

    @property
    def label(self) -> str:
        return self.user_key[:10] + "..." if self.user_key else "单账号"

    def login(self, code: str) -> bool:
        payload = {
            "code": code,
            "appid": self.app_id,
            "shoId": "",
            "userId": "",
            "sourceWxsceneid": 1145,
            "sourceUrl": "pages/ucenter_index/ucenter_index",
        }
        url = f"{self.base_url}/ms-sanfu-wechat-customer-core/customer/core/wxMiniAppLogin"

        try:
            response = self.client.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200 and data.get("success"):
                sid = data.get("data", {}).get("sid")
                if sid:
                    self.sid = sid
                    print("  登录成功")
                    return True
                print("  登录失败：未获取到sid")
            else:
                print(f"  登录失败：{data.get('msg', '未知错误')}")
        except Exception as e:
            print(f"  登录请求失败: {e}")
        return False

    def check_signin_status(self) -> Optional[bool]:
        if not self.sid:
            print("  未获取到sid，无法检查签到状态")
            return None

        url = f"{self.base_url}/ms-sanfu-wechat-customer/customer/index/equity?sid={self.sid}"
        try:
            response = self.client.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200:
                sign_in = data.get("data", {}).get("signIn", 1)
                is_signed = sign_in == 1
                print(f"  签到状态: {'已签到' if is_signed else '未签到'}")
                return is_signed
            print(f"  检查签到状态失败：{data.get('msg', '未知错误')}")
        except Exception as e:
            print(f"  检查签到状态请求失败: {e}")
        return None

    def submit_signin(self) -> Optional[dict]:
        if not self.sid:
            print("  未获取到sid，无法签到")
            return None

        payload = {"sid": self.sid, "signWay": 0}
        url = f"{self.base_url}/ms-sanfu-wechat-common/customer/onSign"

        try:
            response = self.client.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200:
                return data.get("data", {})
            print(f"  签到失败：{data.get('msg', '未知错误')}")
        except Exception as e:
            print(f"  签到请求失败: {e}")
        return None

    def get_account_info(self) -> Optional[dict]:
        if not self.sid:
            return None

        url = f"{self.base_url}/ms-sanfu-wechat-customer/customer/index/baseInfo?sid={self.sid}"
        try:
            response = self.client.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200:
                return data.get("data", {})
        except Exception as e:
            print(f"  获取账号信息请求失败: {e}")
        return None

    def validate_sid(self) -> bool:
        """快速验证缓存 sid 是否有效"""
        if not self.sid:
            return False
        url = f"{self.base_url}/ms-sanfu-wechat-customer/customer/index/equity?sid={self.sid}"
        try:
            response = self.client.get(url, headers=self.headers, timeout=15.0)
            return response.status_code == 200 and response.json().get("code") == 200
        except Exception:
            return False

    def process_account(self) -> str:
        """处理单个账号的签到流程，返回结果消息"""
        print(f"\n开始处理账号: {self.label}")

        # ─── Phase 1: 登录（缓存优先，WCS 兜底） ───
        cache = load_cache()
        cache_key = self.user_key or "default"
        cached = cache.get(cache_key, {})

        if cached.get("sid"):
            self.sid = cached["sid"]
            if self.validate_sid():
                print(f"  ✅ 缓存sid有效，跳过WCS取码")
            else:
                print(f"  ⚠️ 缓存sid已过期，重新获取")
                self.sid = None
                cache.pop(cache_key, None)
                save_cache(cache)

        if not self.sid:
            for attempt in range(2):
                if attempt > 0:
                    print(f"  🔁 登录失败，重新从WCS取code（第{attempt+1}/2次）...")
                code = get_code_from_wcs(self.user_key)
                if not code:
                    if attempt == 0: continue
                    return f"[{self.label}] 取码失败"
                if self.login(code):
                    break
            if not self.sid:
                return f"[{self.label}] 登录失败"
            cache[cache_key] = {"sid": self.sid, "cached_at": datetime.now().isoformat()}
            save_cache(cache)

        # ─── Phase 2: 业务逻辑 ───"

        msgs = []

        # 3. 检查签到状态
        sign_status = self.check_signin_status()
        if sign_status is None:
            return f"[{self.label}] 检查签到状态失败"

        if sign_status:
            msgs.append("今日已签")
        else:
            sign_result = self.submit_signin()
            if sign_result is None:
                return f"[{self.label}] 签到失败"

            on_sign_fubi = sign_result.get("fubi", 0)
            on_keep_day = sign_result.get("onKeepSignDay", 0)
            gift_daily = sign_result.get("giftMoneyDaily", 0)

            parts = [f"签到+{on_sign_fubi}福币", f"连续{on_keep_day}天"]
            if gift_daily > 0:
                parts.append(f"再签{gift_daily}天得礼物")
            msgs.append(" | ".join(parts))

        # 4. 获取账号信息
        account_info = self.get_account_info()
        if account_info:
            fubi = account_info.get("fubi", 0)
            msgs.append(f"当前{fubi}福币")

        return f"[{self.label}] " + " | ".join(msgs)


def main():
    print("===== 三福会员中心签到 (WCS版) =====\n")
    print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 WCS 服务器: {WX_SERVER_URL}")

    if not WX_SERVER_URL or not WX_AUTH:
        print("❌ 未配置 wx_server_url 或 wx_auth")
        sys.exit(1)

    user_keys = parse_userkeys()
    if not user_keys:
        print("ℹ️ 未配置 sfwx 环境变量 | 使用单账号模式")
        user_keys = [""]
    else:
        print(f"ℹ️ 多账号模式 | 共 {len(user_keys)} 个 | 分隔符: & # ,")

    results = []
    for i, uk in enumerate(user_keys):
        label = uk[:10] + "..." if uk else "单账号"
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(user_keys)}] 处理账号: {label}")
        print(f"{'='*50}")

        bot = SanfuSignin(uk)
        try:
            result = bot.process_account()
            results.append(result)
        except Exception as e:
            results.append(f"[{label}] 异常: {e}")
        finally:
            bot.client.close()

        if i < len(user_keys) - 1:
            print(f"\n⏳ 等待2秒...")
            time.sleep(2)

    print("\n" + "=" * 40)
    print("🎉 所有账号处理完成")
    summary = "\n".join(results)
    print(summary)

    if PLUSPLUS_TOKEN and results:
        send_pushplus("三福签到", summary)


if __name__ == "__main__":
    main()
