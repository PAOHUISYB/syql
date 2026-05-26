#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杰士邦会员中心小程序签到脚本 (WCS 适配版)
原始脚本作者：3iXi
WCS 适配 + 多账号支持

环境变量:
  jsbwx         — 多账号 WCS userKey，用 # & 或 , 分隔
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
from typing import Dict, Optional, List

try:
    import httpx
except ImportError:
    print("错误: 需要安装 httpx[http2] 依赖")
    sys.exit(1)

# ===================== WCS 配置 =====================
APPID = "wx5966681b4a895dee"
WX_SERVER_URL = os.getenv("wx_server_url", "")
WX_AUTH = os.getenv("wx_auth", "")
JSBWX = os.getenv("jsbwx", "")

# ===================== 通知配置 =====================
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")


def parse_userkeys() -> List[str]:
    """解析多账号 userKey，支持 & # , 分隔"""
    if not JSBWX:
        return []
    return [x.strip() for x in re.split(r'[&#,]', JSBWX) if x.strip()]


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
            code = data["data"]["code"]
            print(f"✅ [{label}] 获取code成功")
            return code
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


class JieshibangSignin:
    """杰士邦小程序签到"""

    def __init__(self, user_key: str = ""):
        self.user_key = user_key
        self.base_url = "https://api.vshop.hchiv.cn"
        self.app_id = APPID
        self.base_headers = {
            "host": "api.vshop.hchiv.cn",
            "xweb_xhr": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF",
            "appenv": "test",
            "content-type": "application/json",
            "accept": "*/*",
            "referer": f"https://servicewechat.com/{APPID}/47/page-frame.html",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "zh-CN,zh;q=0.9",
        }
        self.headers = self.base_headers.copy()
        self.client = httpx.Client(http2=True, verify=False)

    @property
    def label(self) -> str:
        return self.user_key[:10] + "..." if self.user_key else "单账号"

    def get_timestamp(self) -> int:
        return int(time.time() * 1000)

    def clear_session(self):
        self.headers = self.base_headers.copy()
        self.client.cookies.clear()

    def login(self, wx_info: str) -> Optional[str]:
        """登录获取 token"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/member/wechatlogin/authLoginApplet"
        params = {
            "sideType": "3", "mob": "", "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "wxInfo": wx_info,
            "extend": '{"sourcePage":"/packageA/pages/integral-index/integral-index","activityId":"","sourceShopId":"","guideNo":"","way":"member","linkType":"2001"}',
            "sessionIdForWxShop": "",
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("data", {}).get("success"):
                client_token = data["data"]["data"].get("clientToken")
                if client_token:
                    self.headers["authorization"] = f"Bearer {client_token}"
                    return client_token
            elif data.get("data", {}).get("code") == 1012:
                return "CODE_EXPIRED"
        except Exception as e:
            print(f"  登录请求失败: {e}")
        return None

    def get_client_info(self) -> Optional[Dict]:
        """获取客户信息"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/member/tblogin/getClientInfo"
        params = {
            "sideType": "3", "mob": "", "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("data", {}).get("success"):
                return data["data"]["data"]
        except Exception as e:
            print(f"  获取客户信息失败: {e}")
        return None

    def get_signin_activity_id(self, mob: str) -> Optional[str]:
        """获取签到活动ID"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/common/common/get-customer-page"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "pageId": 102999, "pageType": 2,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                page_json_str = data.get("data", {}).get("result", {}).get("pageJson", "")
                if page_json_str:
                    try:
                        page_json = json.loads(page_json_str)
                        for module in page_json.get("moduleList", []):
                            if module.get("type") == "iconNav":
                                for link in module.get("detail", {}).get("linkList", []):
                                    if link.get("text") == "签到":
                                        return link.get("id")
                    except json.JSONDecodeError:
                        print("  解析pageJson失败")
        except Exception as e:
            print(f"  获取签到活动ID失败: {e}")
        return None

    def signin(self, mob: str, activity_id: str) -> bool:
        """提交签到"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/api/play-default/sign/add-sign-new.do"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                integral = data.get("data", {}).get("integral", 0)
                integral_alias = data.get("data", {}).get("integralAlias", "积分")
                print(f"  签到成功，获得{integral}{integral_alias}")
                return True
            else:
                print(f"  签到失败: {data.get('errorMessage', '未知错误')}")
        except Exception as e:
            print(f"  签到请求失败: {e}")
        return False

    def get_lottery_activity_id(self, mob: str):
        """获取抽奖活动ID和名称"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/common/common/get-customer-page"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "pageId": 111079, "pageType": 2,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                page_json_str = data.get("data", {}).get("result", {}).get("pageJson", "")
                if page_json_str:
                    try:
                        page_json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', page_json_str)
                        page_json = json.loads(page_json_str)
                        for module in page_json.get("moduleList", []):
                            if module.get("type") == "imgAd":
                                for link in module.get("detail", {}).get("linkList", []):
                                    for zone in link.get("zones", []):
                                        link_url = zone.get("linkUrl", "")
                                        if "抽奖" in link_url:
                                            return zone.get("id"), link_url
                    except json.JSONDecodeError as e:
                        print(f"  解析抽奖pageJson失败: {e}")
        except Exception as e:
            print(f"  获取抽奖活动ID失败: {e}")
        return None, None

    def get_lottery_times(self, mob: str, activity_id: str) -> int:
        """获取抽奖次数"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/activity/draw/child/receiveFreeTimes"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("data", {}).get("success"):
                return data["data"]["data"].get("totalTimes", 0)
        except Exception as e:
            print(f"  获取抽奖次数失败: {e}")
        return 0

    def lottery(self, mob: str, activity_id: str) -> bool:
        """提交抽奖"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/activity/draw/startTurntable"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("data", {}).get("success"):
                prize_name = data["data"]["data"].get("prizeResult", {}).get("prizeName", "未知奖品")
                print(f"  抽奖成功，获得{prize_name}")
                return True
            else:
                print(f"  抽奖失败: {data.get('errorMessage', '未知错误')}")
        except Exception as e:
            print(f"  抽奖请求失败: {e}")
        return False

    def get_activity_list(self, mob: str) -> Optional[str]:
        """获取活动列表，查找包含"签到"的活动"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/activity/activity/activityList"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "pageNumber": 1, "pageSize": 20, "decoActStatus": ["1"],
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("data", {}).get("success"):
                for activity in data["data"]["data"].get("dataList", []):
                    if "签到" in activity.get("name", ""):
                        activity_id = str(activity.get("id", ""))
                        print(f"  获取到{activity['name']}")
                        return activity_id
        except Exception as e:
            print(f"  获取活动列表失败: {e}")
        return None

    def get_sign_prize(self, mob: str, activity_id: str) -> Optional[str]:
        """获取签到活动奖励详情"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/cloud/activity/sign/getSignPrize"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                response_list = data.get("data", {}).get("responseList", [])
                if response_list:
                    return response_list[0].get("prizeName", "未知奖品")
        except Exception as e:
            print(f"  获取签到奖励详情失败: {e}")
        return None

    def add_sign_new(self, mob: str, activity_id: str) -> Optional[Dict]:
        """提交签到活动"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/api/play-default/sign/add-sign-new.do"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                result_data = data.get("data", {})
                return {
                    "integral": result_data.get("integral", 0),
                    "integralAlias": result_data.get("integralAlias", "积分"),
                }
        except Exception as e:
            print(f"  提交签到活动失败: {e}")
        return None

    def get_continuous_sign_days(self, mob: str, activity_id: str) -> Optional[int]:
        """获取连续签到天数"""
        timestamp = self.get_timestamp()
        url = f"{self.base_url}/jfmb/api/play-default/sign/current-month-signdays-new.do"
        params = {
            "sideType": "3", "mob": mob, "appId": self.app_id,
            "shopNick": self.app_id, "timestamp": timestamp,
        }
        current_time = datetime.now().strftime("%Y-%m")
        payload = {
            "appId": self.app_id, "openId": True, "shopNick": "",
            "timestamp": timestamp, "interfaceSource": 0,
            "activityId": activity_id, "time": current_time,
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        self.headers["content-length"] = str(len(payload_str.encode('utf-8')))

        try:
            response = self.client.post(url, params=params, json=payload, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                return data.get("data", {}).get("continuousSignDay", 0)
        except Exception as e:
            print(f"  获取连续签到天数失败: {e}")
        return None

    def process_account(self) -> str:
        """处理单个账号的签到和抽奖，返回结果消息"""
        msgs = []

        # 1. WCS 取码
        code = get_code_from_wcs(self.user_key)
        if not code:
            return f"[{self.label}] 取码失败"

        # 2. 登录
        token = self.login(code)
        if token == "CODE_EXPIRED":
            print(f"  Code已过期，重新获取...")
            self.clear_session()
            code = get_code_from_wcs(self.user_key)
            if code:
                token = self.login(code)
        if not token or token == "CODE_EXPIRED":
            self.clear_session()
            return f"[{self.label}] 登录失败"

        # 3. 客户信息
        client_info = self.get_client_info()
        if not client_info:
            self.clear_session()
            return f"[{self.label}] 获取客户信息失败"

        client_name = client_info.get("client_name", self.label)
        residual_integral = client_info.get("residualIntegral", 0)
        user_mob = client_info.get("user_mob", "")
        print(f"  {client_name} 登录成功，当前积分 {residual_integral}")

        # 4. 每日签到（iconNav 方式）
        print("  --- 每日签到 ---")
        signin_id = self.get_signin_activity_id(user_mob)
        if signin_id:
            self.signin(user_mob, signin_id)
        else:
            msgs.append("每日签到活动ID获取失败")

        # 5. 签到活动（activityList 方式）
        print("  --- 签到活动 ---")
        try:
            activity_id = self.get_activity_list(user_mob)
            if activity_id:
                prize_name = self.get_sign_prize(user_mob, activity_id)
                if prize_name:
                    print(f"  签到奖励：{prize_name}")
                sign_result = self.add_sign_new(user_mob, activity_id)
                if sign_result:
                    integral = sign_result.get("integral", 0)
                    integral_alias = sign_result.get("integralAlias", "积分")
                    print(f"  签到成功，获得{integral}{integral_alias}")
                    continuous_days = self.get_continuous_sign_days(user_mob, activity_id)
                    if continuous_days is not None:
                        print(f"  已连续签到{continuous_days}天")
                        msgs.append(f"{client_name}: 签到+{integral}{integral_alias} | 连续{continuous_days}天")
                    else:
                        msgs.append(f"{client_name}: 签到+{integral}{integral_alias}")
                else:
                    msgs.append(f"{client_name}: 签到活动提交失败")
            else:
                msgs.append(f"{client_name}: 未找到签到活动")
        except Exception as e:
            print(f"  签到活动处理异常: {e}")
            msgs.append(f"{client_name}: 签到活动异常")

        # 6. 抽奖
        print("  --- 抽奖活动 ---")
        lottery_id, lottery_name = self.get_lottery_activity_id(user_mob)
        if lottery_id:
            lottery_times = self.get_lottery_times(user_mob, lottery_id)
            print(f"  抽奖活动「{lottery_name}」可免费抽奖 {lottery_times} 次")
            if lottery_times > 0:
                self.lottery(user_mob, lottery_id)
                msgs.append(f"{client_name}: 抽奖×{lottery_times}")
            else:
                msgs.append(f"{client_name}: 无免费抽奖次数")
        else:
            msgs.append(f"{client_name}: 抽奖活动ID获取失败")

        self.clear_session()
        return f"[{client_name}] " + " | ".join(msgs) if msgs else f"[{client_name}] 完成"


def main():
    print("===== 杰士邦会员中心签到 (WCS版) =====\n")
    print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 WCS 服务器: {WX_SERVER_URL}")

    if not WX_SERVER_URL or not WX_AUTH:
        print("❌ 未配置 wx_server_url 或 wx_auth")
        sys.exit(1)

    user_keys = parse_userkeys()
    if not user_keys:
        print("ℹ️ 未配置 jsbwx 环境变量 | 使用单账号模式")
        user_keys = [""]
    else:
        print(f"ℹ️ 多账号模式 | 共 {len(user_keys)} 个 | 分隔符: & # ,")

    results = []
    for i, uk in enumerate(user_keys):
        label = uk[:10] + "..." if uk else "单账号"
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(user_keys)}] 处理账号: {label}")
        print(f"{'='*50}")

        bot = JieshibangSignin(uk)
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
        send_pushplus("杰士邦签到", summary)


if __name__ == "__main__":
    main()
