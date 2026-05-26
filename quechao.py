#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================
# 雀巢会员俱乐部自动任务脚本(WCS 版本)
# 版本: v2.2.0
# 更新日期: 2026-05-18
# 功能: 自动完成每日签到、浏览官网、浏览视频号任务
# 适配: 雀巢小程序 | WCS code 服务 | 品赞代理 | PushPlus推送
# ==============================================

import os
import sys
import asyncio
import json
import random
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# 强制全局禁用所有系统代理环境变量
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
                'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']:
    os.environ.pop(env_var, None)

try:
    import httpx
    from httpx import AsyncHTTPTransport
    from httpx_socks import AsyncProxyTransport
except ImportError:
    print("❌ 缺少依赖库,请执行:pip install httpx[http2] httpx-socks python-dotenv")
    sys.exit(1)

# ===================== WCS 配置 =====================
# WCS 服务器地址(环境变量)
WX_SERVER_URL = os.getenv("wx_server_url", "http://127.0.0.1:8787")

# WCS API Key(环境变量)
WX_AUTH = os.getenv("wx_auth", "")

# 多账号 openid（环境变量 qcwx，用 &, # 或 , 分隔，单账号时可不配置）
QCWX = os.getenv("qcwx", "")

# ===================== Token 缓存 =====================
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_quechao.json")

def load_cache() -> Dict[str, Any]:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ===================== 其他配置 =====================
# PushPlus 通知Token(环境变量,可选)
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# 品赞代理配置(环境变量,可选)
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http")
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"

# 代理开关
ENABLE_PER_ACCOUNT_PROXY = True
PROXY_FETCH_INTERVAL = 3000
ENABLE_DIRECT_FALLBACK = True

# 固定配置
APPID = "wxc5db704249c9bb31"
APP_VERSION = "491"
XWEB_VERSION = "19823"
TOKEN_CLIENT_ID = "wechatMini"
TOKEN_CLIENT_SECRET = "secret"
TOKEN_GRANT_TYPE = "wechat_auth_code"
TOKEN_URL = "https://crm.nestlechinese.com/openapi/identityservice/connect/token"

# UA池
USER_AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    f"Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/{XWEB_VERSION} MMWEBSDK/20251006 MiniProgramEnv/android"
]

# 跳过的任务GUID
SKIP_TASK_GUIDS = {"38C8BBDA3DAE4CD685B270D939E5063D", "36EFECD2AD8C44278317ED567EB24DD9"}

# ===================== 工具函数 =====================
def sleep(ms: int) -> asyncio.Future:
    return asyncio.sleep(ms / 1000)

def random_int(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)

def get_ua() -> str:
    return random.choice(USER_AGENT_LIST)

def build_direct_transport() -> AsyncHTTPTransport:
    return AsyncHTTPTransport()

def parse_openids() -> List[str]:
    """解析多账号 openid，支持 &, #, , 分隔"""
    if not QCWX:
        return []

    return [x.strip() for x in re.split(r'[&#,]', QCWX) if x.strip()]

# ===================== 品赞代理系统 =====================
def parse_proxy_response(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        proxy_obj = None
        if data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
            proxy_obj = data["data"][0]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif data.get("result") and data["result"].get("ip") and data["result"].get("port"):
            proxy_obj = data["result"]

        if proxy_obj:
            return {
                "host": proxy_obj["ip"],
                "port": int(proxy_obj["port"]),
                "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                "password": proxy_obj.get("pass") or proxy_obj.get("password") or ""
            }
    except json.JSONDecodeError:
        if ":" in text:
            parts = text.split(":")
            if len(parts) >= 2:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2] if len(parts) >= 3 else "",
                    "password": parts[3] if len(parts) >= 4 else ""
                }
    return None

async def validate_proxy(proxy_info: Dict[str, Any]) -> bool:
    if not proxy_info:
        return False

    try:
        transport = build_proxy_transport(proxy_info)
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            response = await client.get(PROXY_VALIDATE_URL)
            if response.status_code == 200:
                ip = response.json().get("origin", "未知")
                print(f"✅ 代理验证通过 | 出口IP: {ip}")
                return True
    except Exception as e:
        print(f"⚠️ 代理验证失败 | 原因: {str(e)}")
    return False

def build_proxy_transport(proxy_info: Dict[str, Any]) -> Optional[AsyncProxyTransport]:
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info["username"]
    password = proxy_info["password"]

    try:
        if PROXY_TYPE == "socks5":
            proxy_url = f"socks5://{username}:{password}@{host}:{port}" if username and password else f"socks5://{host}:{port}"
        else:
            proxy_url = f"http://{username}:{password}@{host}:{port}" if username and password else f"http://{host}:{port}"

        return AsyncProxyTransport.from_url(proxy_url)
    except Exception as e:
        print(f"❌ 代理生成失败 | 原因: {str(e)}")
        return None

async def get_valid_proxy(account_name: str) -> Optional[Dict[str, Any]]:
    if not PROXY_API:
        print(f"i️ [{account_name}] 未配置代理 | 使用直连模式")
        return None

    print(f"🔌 [{account_name}] 正在获取专属代理...")

    for i in range(PROXY_RETRY_TIMES):
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport()) as client:
                response = await client.get(PROXY_API)
                proxy_info = parse_proxy_response(response.text)

                if not proxy_info:
                    print(f"⚠️ [{account_name}] 第{i+1}次获取代理失败 | 响应格式错误")
                    continue

                if await validate_proxy(proxy_info):
                    return proxy_info
                else:
                    print(f"⚠️ [{account_name}] 第{i+1}次代理不可用 | 重试中...")

        except Exception as e:
            print(f"⚠️ [{account_name}] 第{i+1}次获取代理异常 | 原因: {str(e)}")

        if i < PROXY_RETRY_TIMES - 1:
            await sleep(2000)

    print(f"❌ [{account_name}] 代理获取失败 | 切换直连模式")
    return None

# ===================== PushPlus推送函数 =====================
async def send_plusplus_notification(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0, transport=build_direct_transport()) as client:
            response = await client.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": PLUSPLUS_TOKEN,
                    "title": title,
                    "content": content,
                    "template": "txt"
                }
            )
            if response.status_code == 200:
                print("✅ 通知推送成功")
    except Exception as e:
        print(f"❌ 通知推送失败 | 原因: {str(e)}")

# ===================== 核心业务类 =====================
class QueChaoBot:
    def __init__(self, openid: str, proxy_info: Optional[Dict[str, Any]] = None):
        self.openid = openid
        self.proxy_info = proxy_info
        self.base_url = "https://crm.nestlechinese.com"
        self.token = None
        self.ua = get_ua()
        self.client = None

    @property
    def account_label(self) -> str:
        return f"{self.openid[:8]}..." if self.openid else "单账号"

    async def get_code(self) -> Optional[str]:
        """从 WCS 服务获取 code(POST + AUTH Header)"""
        request_url = f"{WX_SERVER_URL}/wx/code"
        print(f"📡 [{self.account_label}] 请求 WCS 接口 | URL: {request_url}")

        headers = {
            "AUTH": WX_AUTH,
            "Content-Type": "application/json"
        }

        # 单账号模式只传 appid；多账号模式必须传 openid
        body = {"appid": APPID}
        if self.openid:
            body["openid"] = self.openid

        body_preview = {"appid": body.get("appid"), "openid": (self.openid[:8] + "...") if self.openid else "<omitted>"}
        print(f"🧪 [{self.account_label}] 请求体预览 | {body_preview}")

        for attempt in range(1, 3):
            try:
                if attempt > 1:
                    print(f"🔁 [{self.account_label}] 第 {attempt}/2 次获取 code 重试...")
                async with httpx.AsyncClient(timeout=30.0, transport=build_direct_transport()) as client:
                    response = await client.post(request_url, headers=headers, json=body)

                    print(f"📝 [{self.account_label}] 接口响应 | 状态码: {response.status_code}")

                    if response.status_code != 200:
                        resp_text = response.text[:300] if response.text else "<empty>"
                        print(f"❌ [{self.account_label}] 获取code失败 | HTTP错误: {response.status_code} | 响应: {resp_text}")
                        return None

                    try:
                        res = response.json()
                    except json.JSONDecodeError:
                        resp_text = response.text[:300] if response.text else "<empty>"
                        print(f"❌ [{self.account_label}] 获取code失败 | 响应不是JSON格式 | 响应片段: {resp_text}")
                        return None

                    # WCS 返回格式: {"status": true, "message": "success", "data": {"code": "..."}}
                    if not res.get("status") or not res.get("data") or not res.get("data").get("code"):
                        print(f"❌ [{self.account_label}] 获取code失败 | 业务错误: {res.get('message', '未知错误')} | 完整响应: {json.dumps(res, ensure_ascii=False)}")
                        return None

                    code = res["data"]["code"]
                    code_preview = code[:8] + "..."
                    print(f"✅ [{self.account_label}] 获取code成功 | 预览: {code_preview}")
                    return code

            except httpx.ReadTimeout as e:
                print(f"❌ [{self.account_label}] 获取code超时 | 第 {attempt}/2 次 | 类型: {type(e).__name__} | repr: {repr(e)}")
                if attempt < 2:
                    await sleep(2000)
                    continue
                return None
            except Exception as e:
                print(f"❌ [{self.account_label}] 获取code异常 | 类型: {type(e).__name__} | repr: {repr(e)} | 原因: {str(e)}")
                return None

        return None

    async def get_token_by_code(self, code: str) -> Optional[str]:
        """通过code换取token"""
        print(f"🔑 [{self.account_label}] 正在换取token...")

        headers = {
            "Host": "crm.nestlechinese.com",
            "Connection": "keep-alive",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        form_data = {
            "client_id": TOKEN_CLIENT_ID,
            "client_secret": TOKEN_CLIENT_SECRET,
            "grant_type": TOKEN_GRANT_TYPE,
            "auth_code": code
        }

        try:
            transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
            mode = "代理" if self.proxy_info else "直连"

            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                timeout=20.0,
                http2=True
            ) as client:
                response = await client.post(TOKEN_URL, data=form_data)

                if response.status_code != 200:
                    raise Exception(f"HTTP错误: {response.status_code}")

                res = response.json()
                if res.get("access_token") and res.get("token_type", "Bearer").lower() == "bearer":
                    self.token = res["access_token"]
                    print(f"✅ [{self.account_label}] 获取token成功 | 模式: {mode}")
                    return self.token
                else:
                    raise Exception(f"业务错误: {res.get('error', '未知错误')}")
        except Exception as e:
            print(f"⚠️ [{self.account_label}] {mode}获取token失败 | 原因: {str(e)}")

            if self.proxy_info and ENABLE_DIRECT_FALLBACK:
                print(f"🌐 [{self.account_label}] 切换直连重试...")
                try:
                    async with httpx.AsyncClient(
                        headers=headers,
                        timeout=20.0,
                        http2=True,
                        transport=build_direct_transport()
                    ) as client:
                        response = await client.post(TOKEN_URL, data=form_data)

                        res = response.json()
                        if res.get("access_token"):
                            self.token = res["access_token"]
                            print(f"✅ [{self.account_label}] 直连获取token成功")
                            return self.token
                        else:
                            raise Exception(f"直连业务错误: {res.get('error', '未知错误')}")
                except Exception as e2:
                    print(f"❌ [{self.account_label}] 直连获取token失败 | 原因: {str(e2)}")

        return None

    async def validate_token(self) -> bool:
        """快速验证缓存 token 是否有效"""
        if not self.token:
            return False
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_base_headers(),
                transport=build_direct_transport(),
                http2=True,
                timeout=15.0,
            ) as client:
                response = await client.post(
                    "/openapi/pointsservice/api/Points/getuserbalance",
                    content="{}",
                )
                data = response.json()
                return data.get("errcode") == 200
        except Exception:
            return False

    async def __aenter__(self):
        transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_base_headers(),
            transport=transport,
            http2=True,
            timeout=30.0
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    def _get_base_headers(self) -> Dict[str, str]:
        headers = {
            "Host": "crm.nestlechinese.com",
            "displayVersion": "0",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    def check_response(self, response_data: Dict[str, Any]) -> bool:
        if response_data.get("errcode") != 200:
            print(f"❌ [{self.account_label}] 请求失败 | 原因: {response_data.get('errmsg', '未知错误')}")
            return False
        return True

    async def get_user_balance(self) -> Optional[int]:
        try:
            response = await self.client.post(
                "/openapi/pointsservice/api/Points/getuserbalance",
                content="{}"
            )
            response_data = response.json()

            if self.check_response(response_data):
                return response_data.get("data")
            return None
        except Exception as e:
            print(f"❌ [{self.account_label}] 获取积分失败 | 原因: {str(e)}")
            return None

    async def daily_sign(self) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/sign2025/sign",
                content='{"rule_id":1,"goods_rule_id":1}'
            )
            response_data = response.json()

            if response_data.get("errcode") == 201:
                sign_msg = "今日已签到"
                print(f"i️ [{self.account_label}] {sign_msg}")
                return True, sign_msg

            if self.check_response(response_data):
                data = response_data.get("data", {})
                sign_day = data.get("sign_day", 0)
                sign_points = data.get("sign_points", 0)
                sign_msg = f"签到成功 | 连续{sign_day}天 | +{sign_points}积分"
                print(f"✅ [{self.account_label}] {sign_msg}")
                return True, sign_msg
            else:
                sign_msg = f"签到失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [{self.account_label}] {sign_msg}")
                return False, sign_msg

        except Exception as e:
            sign_msg = f"签到异常: {str(e)}"
            print(f"❌ [{self.account_label}] {sign_msg}")
            return False, sign_msg

    async def get_task_list(self) -> List[Dict[str, Any]]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/getlist",
                content="{}"
            )
            response_data = response.json()

            if self.check_response(response_data):
                tasks = response_data.get("data", [])
                uncompleted_tasks = [
                    task for task in tasks
                    if task.get("task_status") == 0
                    and task.get("task_guid") not in SKIP_TASK_GUIDS
                ]
                print(f"📋 [{self.account_label}] 待完成任务: {len(uncompleted_tasks)}个")
                return uncompleted_tasks
            return []
        except Exception as e:
            print(f"❌ [{self.account_label}] 获取任务列表失败 | 原因: {str(e)}")
            return []

    async def complete_task(self, task_guid: str, task_desc: str) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/add",
                content=f'{{"task_guid":"{task_guid}"}}'
            )
            response_data = response.json()

            if self.check_response(response_data):
                msg = f"完成【{task_desc}】 | +2积分"
                print(f"✅ [{self.account_label}] {msg}")
                return True, msg
            else:
                msg = f"【{task_desc}】失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [{self.account_label}] {msg}")
                return False, msg

        except Exception as e:
            msg = f"【{task_desc}】异常: {str(e)}"
            print(f"❌ [{self.account_label}] {msg}")
            return False, msg

    async def run(self) -> Dict[str, Any]:
        result = {
            "openid": self.openid,
            "success": False,
            "proxy_status": "直连" if not self.proxy_info else "专属代理",
            "sign_msg": "",
            "task_msgs": [],
            "initial_score": 0,
            "final_score": 0,
            "gained_score": 0,
            "error": ""
        }

        print(f"\n{'='*40}")
        print(f"[{self.account_label}] 开始执行任务")
        print(f"{'='*40}")

        try:
            await sleep(random_int(2000, 5000))

            # ─── Phase 1: 获取 token（缓存优先，WCS 兜底） ───
            cache = load_cache()
            cache_key = self.openid or "default"
            cached = cache.get(cache_key, {})

            if cached.get("token"):
                self.token = cached["token"]
                if await self.validate_token():
                    print(f"✅ [{self.account_label}] 缓存token有效，跳过WCS取码")
                else:
                    print(f"⚠️ [{self.account_label}] 缓存token已过期，重新获取")
                    self.token = None
                    cache.pop(cache_key, None)
                    save_cache(cache)

            if not self.token:
                for attempt in range(2):
                    if attempt > 0:
                        print(f"  🔁 token换取失败，重新从WCS取code（第{attempt+1}/2次）...")
                    code = await self.get_code()
                    if not code:
                        if attempt == 0: continue
                        result["error"] = "获取code失败"
                        return result
                    token = await self.get_token_by_code(code)
                    if token: break
                if not token:
                    result["error"] = "获取token失败"
                    return result

                cache[cache_key] = {"token": self.token, "cached_at": datetime.now().isoformat()}
                save_cache(cache)

            # ─── Phase 2: 执行业务 ───
            async with self:
                initial_balance = await self.get_user_balance()
                if initial_balance is None:
                    result["error"] = "获取初始积分失败"
                    return result

                result["initial_score"] = initial_balance
                print(f"💰 [{self.account_label}] 初始积分: {initial_balance}")

                # 每日签到
                sign_success, sign_msg = await self.daily_sign()
                result["sign_msg"] = sign_msg
                await sleep(1000)

                # 完成日常任务
                tasks = await self.get_task_list()
                task_msgs = []
                for task in tasks:
                    task_guid = task.get("task_guid", "")
                    task_desc = task.get("task_sub_desc", task.get("task_title", "未知任务"))
                    if task_guid:
                        success, msg = await self.complete_task(task_guid, task_desc)
                        task_msgs.append(msg)
                        await sleep(1000)
                result["task_msgs"] = task_msgs

                # 获取最终积分
                final_balance = await self.get_user_balance()
                if final_balance is not None:
                    result["final_score"] = final_balance
                    result["gained_score"] = final_balance - initial_balance
                    print(f"📊 [{self.account_label}] 今日新增: {result['gained_score']}积分 | 当前: {final_balance}")

                result["success"] = True
                print(f"✅ [{self.account_label}] 任务执行完成")

        except Exception as e:
            result["error"] = str(e)
            print(f"❌ [{self.account_label}] 执行异常 | 原因: {str(e)}")

        return result

# ===================== 主程序 =====================
async def main():
    print('===== 雀巢会员俱乐部每日任务(WCS版) =====\n')
    print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 WCS 服务器: {WX_SERVER_URL}")

    # 检查环境变量
    if not WX_AUTH:
        print("❌ 未配置 wx_auth 环境变量 | 请在青龙面板添加 WCS API Key")
        sys.exit(1)

    openids = parse_openids()
    # 单账号模式：如果没有配置 qcwx，使用默认空 openid
    # WCS 只有一个绑定账号时，不需要传 openid，会自动用唯一账号
    if not openids:
        print("ℹ️ 未配置 qcwx 环境变量 | 使用单账号模式（WCS 自动选择唯一账号）")
        openids = [""]  # 空字符串表示不传 openid
    else:
        print(f"ℹ️ 检测到多账号 openid 配置 | 共 {len(openids)} 个 | 支持分隔符: &, #, ,")

    print(f"🔌 待执行账号: {len(openids)} 个")
    print(f"🌐 代理模式: {'单账号独立代理' if ENABLE_PER_ACCOUNT_PROXY else '全局共用代理'}\n")

    global_proxy_info = None
    if not ENABLE_PER_ACCOUNT_PROXY and PROXY_API:
        global_proxy_info = await get_valid_proxy("全局共用")

    results = []
    for index, openid in enumerate(openids):
        proxy_info = global_proxy_info
        if ENABLE_PER_ACCOUNT_PROXY:
            proxy_info = await get_valid_proxy(openid[:8] if openid else "单账号")
            await sleep(PROXY_FETCH_INTERVAL)

        bot = QueChaoBot(openid, proxy_info)
        result = await bot.run()
        results.append(result)

        if index < len(openids) - 1:
            print(f"\n⏳ 等待2秒后执行下一个账号...")
            await sleep(2000)

    # 汇总结果
    notify_content = "### 雀巢每日任务执行结果\n"
    for res in results:
        notify_content += f"\n#### {res['openid'][:8]}...\n"
        notify_content += f"- 代理状态:{res['proxy_status']}\n"
        notify_content += f"- 执行状态:{'成功' if res['success'] else '失败'}\n"
        if res['success']:
            notify_content += f"- 签到结果:{res['sign_msg']}\n"
            notify_content += f"- 任务完成:{'; '.join(res['task_msgs']) if res['task_msgs'] else '无未完成任务'}\n"
            notify_content += f"- 初始积分:{res['initial_score']}\n"
            notify_content += f"- 最终积分:{res['final_score']}\n"
            notify_content += f"- 今日新增:{res['gained_score']} 积分\n"
        else:
            notify_content += f"- 失败原因:{res['error']}\n"

    await send_plusplus_notification("雀巢每日任务完成", notify_content)

    print('\n' + '='*40)
    print('🎉 所有账号执行完成')
    print(f"📊 成功: {sum(1 for r in results if r['success'])}/{len(results)} 个")
    print(f"💰 今日总新增: {sum(r['gained_score'] for r in results if r['success'])} 积分")
    print('='*40)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 程序异常: {str(e)}")
