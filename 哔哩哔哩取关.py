#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import json
from typing import List, Dict

# ==================== 请修改以下配置 ====================
# 必填：你的B站Cookie
USER_COOKIE = "这里填写你的Cookie"

# 目标分组名称，留空""则清理整个关注列表
TARGET_GROUP = "默认分组"

# 一次最多清理多少个关注（设为0表示清理全部）
MAX_UNFOLLOW = 20

# 白名单：这些UP主的UID不会被取关
WHITELIST = []

# 取关间隔（秒），防止操作过快导致风控，建议设置5-10秒
SLEEP_INTERVAL = 5
# ===================================================

class BiliUnfollowTool:
    def __init__(self, cookie: str):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com'
        })
        self.session.cookies.update(self.parse_cookie(cookie))

    def parse_cookie(self, cookie_str: str) -> dict:
        """解析cookie字符串为字典"""
        cookie_dict = {}
        for item in cookie_str.split(';'):
            item = item.strip()
            if not item:
                continue
            key, value = item.split('=', 1)
            cookie_dict[key] = value
        return cookie_dict

    def verify_cookie(self) -> bool:
        """验证Cookie是否有效"""
        url = 'https://api.bilibili.com/x/web-interface/nav'
        try:
            resp = self.session.get(url, timeout=10)
            data = resp.json()
            if data.get('code') == 0:
                username = data.get('data', {}).get('name', '未知')
                print(f'[✓] Cookie验证成功，当前登录用户：{username}')
                return True
            else:
                print(f'[✗] Cookie验证失败，请检查！错误信息：{data.get("message")}')
                return False
        except Exception as e:
            print(f'[✗] 网络请求出错：{str(e)}')
            return False

    def get_followings(self, group_name: str = "") -> List[Dict]:
        """获取关注列表"""
        url = 'https://api.bilibili.com/x/relation/followings'
        params = {
            'vmid': self.get_my_mid(),
            'pn': 1,
            'ps': 50
        }

        if group_name:
            params['group_name'] = group_name

        all_followings = []

        while True:
            try:
                resp = self.session.get(url, params=params, timeout=10)
                data = resp.json()

                if data.get('code') != 0:
                    print(f'获取关注列表失败：{data.get("message")}')
                    break

                followings = data.get('data', {}).get('list', [])
                if not followings:
                    break

                for following in followings:
                    all_followings.append({
                        'mid': following.get('mid'),
                        'uname': following.get('uname'),
                        'mtime': following.get('mtime')
                    })

                if len(followings) < params['ps']:
                    break

                params['pn'] += 1
                time.sleep(1)  # 避免请求过快

            except Exception as e:
                print(f'获取关注列表时出错：{str(e)}')
                break

        print(f'[✓] 获取到 {len(all_followings)} 个关注')
        return all_followings

    def get_my_mid(self) -> int:
        """获取自己的UID"""
        url = 'https://api.bilibili.com/x/web-interface/nav'
        resp = self.session.get(url)
        data = resp.json()
        return data.get('data', {}).get('mid', 0)

    def unfollow(self, uid: int, uname: str) -> bool:
        """取关指定UP主"""
        url = 'https://api.bilibili.com/x/relation/modify'
        data = {
            'fid': uid,
            'act': 2,  # 2表示取消关注
            're_src': 11,
            'csrf': self.get_csrf()
        }

        try:
            resp = self.session.post(url, data=data, timeout=10)
            result = resp.json()

            if result.get('code') == 0:
                print(f'[✓] 取关成功：{uname} (UID: {uid})')
                return True
            else:
                print(f'[✗] 取关失败：{uname} - {result.get("message")}')
                return False
        except Exception as e:
            print(f'[✗] 取关失败：{uname} - {str(e)}')
            return False

    def get_csrf(self) -> str:
        """获取CSRF Token"""
        for cookie in self.session.cookies:
            if cookie.name == 'bili_jct':
                return cookie.value
        return ''

    def run(self, group_name: str = "", max_unfollow: int = 0, whitelist: List[int] = None):
        """执行批量取关"""
        if whitelist is None:
            whitelist = []

        print("="*50)
        print("B站关注批量清理工具")
        print("="*50)

        # 验证Cookie
        if not self.verify_cookie():
            return

        # 获取关注列表
        print(f"\n开始获取关注列表（分组：{group_name or '全部'}）...")
        followings = self.get_followings(group_name)

        if not followings:
            print("没有找到任何关注")
            return

        # 过滤白名单
        to_unfollow = [f for f in followings if f['mid'] not in whitelist]

        if whitelist:
            print(f"\n白名单保护：{len(whitelist)} 个UP主不会被取关")
            for uid in whitelist:
                protected = next((f for f in followings if f['mid'] == uid), None)
                if protected:
                    print(f"  - 保护：{protected['uname']}")

        # 限制取关数量
        if max_unfollow > 0 and len(to_unfollow) > max_unfollow:
            to_unfollow = to_unfollow[:max_unfollow]

        print(f"\n准备取关 {len(to_unfollow)} 个关注")

        if not to_unfollow:
            print("没有需要取关的关注")
            return

        # 执行取关
        print("\n开始执行取关...")
        success_count = 0

        for i, following in enumerate(to_unfollow, 1):
            print(f"\n[{i}/{len(to_unfollow)}] ", end="")
            if self.unfollow(following['mid'], following['uname']):
                success_count += 1

            # 避免操作过快
            if i < len(to_unfollow):
                time.sleep(SLEEP_INTERVAL)

        print("\n" + "="*50)
        print(f"清理完成！成功取关：{success_count}/{len(to_unfollow)}")
        print("="*50)

def main():
    tool = BiliUnfollowTool(USER_COOKIE)

    whitelist = WHITELIST if isinstance(WHITELIST, list) else []

    tool.run(
        group_name=TARGET_GROUP,
        max_unfollow=MAX_UNFOLLOW,
        whitelist=whitelist
    )

if __name__ == "__main__":
    main()
