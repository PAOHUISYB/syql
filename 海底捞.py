# -*- coding: utf-8 -*-
"""
cron: 20 8 * * *
new Env('海底捞会员签到');
"""

import random
import time

import requests

from notify_mtr import send
from utils import get_data

API_BASE = "https://superapp-public.kiwa-tech.com"

UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile MicroMessenger NetType/4G Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile MicroMessenger NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 12; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.5304.105 Mobile Safari/537.36 MicroMessenger NetType/4G Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile MicroMessenger NetType/5G Language/zh_CN",
]


def api_post(path, json_data=None, token=None, ua=None):
    url = f"{API_BASE}{path}"
    headers = {
        "Host": "superapp-public.kiwa-tech.com",
        "appId": "15",
        "content-type": "application/json",
        "Accept-Encoding": "gzip,compress,br,deflate",
        "User-Agent": ua,
        "Referer": "https://servicewechat.com/wx1ddeb67115f30d1a/14/page-frame.html",
    }
    if token:
        headers["_HAIDILAO_APP_TOKEN"] = token
        headers["ReqType"] = "APPH5"
        headers["Referer"] = f"{API_BASE}app-sign-in/?SignInToken={token}&source=MiniApp"

    try:
        resp = requests.post(url, headers=headers, json=json_data, timeout=15)
        return resp.json()
    except Exception as e:
        return {"success": False, "msg": str(e)}


class Haidilao:
    def checkin(self, openid, uid, ua):
        login_res = api_post(
            "login/thirdCommLogin",
            {"openId": openid, "country": "CN", "uid": uid, "type": 1, "codeType": 1},
            ua=ua
        )

        if not login_res.get("success"):
            msg = login_res.get("msg", "")
            if any(k in msg for k in ["失效", "过期", "无效", "token", "登录"]):
                return "❌ Cookie 失效，请重新抓取 openid/uid"
            return f"❌ 登录失败: {msg}"

        token = login_res["data"]["token"]
        name = login_res["data"].get("name", "未知")

        sign_res = api_post(
            "activity/wxapp/signin/signin",
            {"signinSource": "MiniApp"},
            token=token,
            ua=ua
        )

        if "重复" in sign_res.get("msg", ""):
            frag = self._query_fragment(token, ua)
            return f"🔄 {name} 今日已签到 | 碎片: {frag}"

        if not sign_res.get("success"):
            return "❌ Cookie 失效，请重新抓取 openid/uid"

        frag = self._query_fragment(token, ua)
        return f"✅ {name} 签到成功 | 碎片: {frag}"

    def _query_fragment(self, token, ua):
        frag_res = api_post("activity/wxapp/signin/queryFragment", None, token=token, ua=ua)
        if frag_res.get("success"):
            return frag_res.get("data", {}).get("total", "?")
        return "?"


if __name__ == "__main__":
    data = get_data()
    items = data.get("HAIDILAO", [])

    if not items:
        print("[海底捞] 未配置账号，请设置 HAIDILAO 环境变量")
        exit(0)

    results = []
    for i, item in enumerate(items, 1):
        ua = UA_POOL[i % len(UA_POOL)]
        print(f"[海底捞] ---- 账号 {i}/{len(items)} ----")
        msg = Haidilao().checkin(
            openid=str(item.get("openid")),
            uid=str(item.get("uid")),
            ua=ua
        )
        print(f"[海底捞] {msg}")
        results.append(msg)
        if i < len(items):
            time.sleep(3)

    send("海底捞会员签到", "\n".join(results))
