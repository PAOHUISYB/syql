# -*- coding: utf-8 -*-
import time
import random
import json
import os
import sys
import base64
import binascii
import requests
from Crypto.Cipher import AES
from pyncm import apis, GetCurrentSession, SetCurrentSession, Session
from pyncm.apis.login import LoginViaCellphone, LoginViaEmail

# --- 全域變數 ---
NETEASE_USER = os.environ.get("WYY_USER", "")
NETEASE_PWD = os.environ.get("WYY_PWD", "")
NETEASE_COOKIE = os.environ.get("NETEASE_COOKIE", "")
SONG_ID = os.environ.get("NETEASE_SONG_ID", "")  # 評論歌曲ID
SCROBBLE_SONG_ID = os.environ.get("NETEASE_SCROBBLE_SONG_ID", "")  # 刷播放量歌曲ID
SCROBBLE_COUNT = os.environ.get("SCROBBLE_COUNT", "1")  # 刷播放次數
BASE_URL = "https://music.163.com"
COOKIE_FILE = "netease_cookies.json"

# --- 通知功能 ---
def send_notification(title, content):
    """调用青龙面板内置的通知模块"""
    try:
        from notify import send
        send(title, content)
        print("🔔 通知已发送")
    except ImportError:
        print("⚠️ 未检测到 notify 模块，跳过发送通知")
    except Exception as e:
        print(f"❌ 发送通知失败: {e}")

# --- 加密函式 ---
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7"
)
NONCE = b"0CoJUm6Qyw8W8jud"
PUBKEY = "010001"

def aes_encrypt(text, key):
    pad = 16 - len(text) % 16
    text = text + bytearray([pad] * pad)
    encryptor = AES.new(key, 2, b"0102030405060708")
    ciphertext = encryptor.encrypt(text)
    return base64.b64encode(ciphertext)

def rsa_encrypt(text, pubkey, modulus):
    text = text[::-1]
    rs = pow(int(binascii.hexlify(text), 16), int(pubkey, 16), int(modulus, 16))
    return format(rs, "x").zfill(256)

def create_secret_key(size):
    return binascii.hexlify(os.urandom(size))[:16]

def weapi_encrypt(data):
    data = json.dumps(data)
    secret_key = create_secret_key(16)
    params = aes_encrypt(data.encode("utf-8"), NONCE)
    params = aes_encrypt(params, secret_key)
    enc_sec_key = rsa_encrypt(secret_key, PUBKEY, MODULUS)
    return {"params": params.decode("utf-8"), "encSecKey": enc_sec_key}

# --- 核心 API 類別 ---
class NeteaseMusic:
    def __init__(self, cookie):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": BASE_URL,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": cookie
        })
        self.csrf_token = self._get_csrf_from_cookie(cookie)
        self.nickname = "未知账号"

    def _get_csrf_from_cookie(self, cookie):
        for item in cookie.split(';'):
            if item.strip().startswith('__csrf='):
                return item.strip().split('=')[1]
        return ""

    def check_login_status(self):
        if not self.csrf_token:
            return False
        url = f"{BASE_URL}/weapi/w/nuser/account/get"
        data = {"csrf_token": self.csrf_token}
        encrypted_data = weapi_encrypt(data)
        try:
            response = self.session.post(url, data=encrypted_data)
            result = response.json()
            if result.get("code") == 200 and result.get("profile"):
                self.nickname = result.get('profile', {}).get('nickname', '未知')
                print(f"✅ 登入狀態正常！帳號：{self.nickname}")
                return True
            return False
        except:
            return False

    def get_track_detail(self, song_id):
        url = f"{BASE_URL}/weapi/v3/song/detail"
        data = {"c": json.dumps([{"id": song_id}]), "csrf_token": self.csrf_token}
        encrypted_data = weapi_encrypt(data)
        try:
            response = self.session.post(url, data=encrypted_data)
            result = response.json()
            if result.get("code") == 200 and result.get("songs"):
                song = result["songs"][0]
                return {
                    "name": song.get("name", "未知歌曲"),
                    "duration": song.get("dt", 180000),
                    "artists": [artist.get("name", "") for artist in song.get("ar", [])]
                }
            return None
        except:
            return None

    def scrobble(self, song_id, source_id=0, time_sec=180):
        url = f"{BASE_URL}/weapi/feedback/weblog"
        data = {
            "logs": json.dumps([{
                "action": "play",
                "json": {
                    "download": 0, "end": "playend", "id": song_id,
                    "sourceId": source_id, "time": time_sec, "type": "song", "wifi": 0
                }
            }]),
            "csrf_token": self.csrf_token
        }
        encrypted_data = weapi_encrypt(data)
        try:
            response = self.session.post(url, data=encrypted_data)
            result = response.json()
            return result.get("code") == 200, result.get('message', '未知錯誤')
        except Exception as e:
            return False, str(e)

    def scrobble_song(self, song_id, count=1, source_id=0):
        track_info = self.get_track_detail(song_id)
        if track_info:
            song_name = track_info["name"]
            duration_sec = track_info["duration"] // 1000
            artists = "、".join(track_info["artists"])
            print(f"🎵 歌曲：{song_name} - {artists} ({duration_sec}秒)")
        else:
            duration_sec = 180
            song_name = "未知歌曲"

        print(f"🚀 開始刷播放量，目標次數：{count}")
        success_count = 0
        for i in range(count):
            success, message = self.scrobble(song_id, source_id, duration_sec)
            if success:
                success_count += 1
                print(f"✅ [{i+1}/{count}] 打卡成功！")
            else:
                print(f"❌ [{i+1}/{count}] 打卡失敗：{message}")
            if i < count - 1:
                time.sleep(random.uniform(1, 3))
        print(f"🏁 完成！成功 {success_count}/{count} 次。")
        return success_count, song_name

    def comment(self, song_id, content):
        if not self.csrf_token: return False, "CSRF Token 為空"
        url = f"{BASE_URL}/weapi/resource/comments/add?csrf_token={self.csrf_token}"
        data = {"threadId": f"R_SO_4_{song_id}", "content": content, "csrf_token": self.csrf_token}
        encrypted_data = weapi_encrypt(data)
        try:
            response = self.session.post(url, data=encrypted_data)
            result = response.json()
            if result.get("code") == 200:
                print(f"✅ 評論成功！內容：{content}")
                return True, content
            return False, result.get('message', '未知錯誤')
        except Exception as e:
            return False, str(e)

# --- 智能 Cookie 管理函式 ---
def get_cookie_string(session):
    return "; ".join([f"{k}={v}" for k, v in session.cookies.get_dict().items()])

def save_cookies_to_file(session):
    try:
        with open(COOKIE_FILE, 'w') as f:
            json.dump(session.cookies.get_dict(), f)
        print(f"💾 Cookie 已保存到 {COOKIE_FILE}")
    except: pass

def load_cookies_from_file():
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, 'r') as f:
                cookies = json.load(f)
            session = Session()
            session.cookies.update(cookies)
            SetCurrentSession(session)
            return get_cookie_string(session)
        except: pass
    return None

def smart_login(user, pwd, env_cookie):
    if env_cookie:
        print("🔍 使用環境變數 Cookie...")
        nm = NeteaseMusic(env_cookie)
        if nm.check_login_status(): return env_cookie
    
    local_cookie = load_cookies_from_file()
    if local_cookie:
        print("🔍 使用本地文件 Cookie...")
        nm = NeteaseMusic(local_cookie)
        if nm.check_login_status(): return local_cookie

    if user and pwd:
        print("🔑 Cookie 失效，嘗試帳號密碼登錄...")
        try:
            res = LoginViaEmail(user, pwd) if "@" in user else LoginViaCellphone(user, pwd)
            if res.get('code') == 200:
                session = GetCurrentSession()
                new_cookie = get_cookie_string(session)
                save_cookies_to_file(session)
                return new_cookie
        except Exception as e:
            print(f"❌ 登錄異常: {e}")
    return None

# --- 主程序 ---
if __name__ == "__main__":
    user = NETEASE_USER or (sys.argv[1] if len(sys.argv) > 1 else "")
    pwd = NETEASE_PWD or (sys.argv[2] if len(sys.argv) > 2 else "")
    
    final_cookie = smart_login(user, pwd, NETEASE_COOKIE)
    
    report = []
    if final_cookie:
        nm = NeteaseMusic(final_cookie)
        report.append(f"👤 账号：{nm.nickname}")
        
        # 1. 評論任務 (主創說)
        if SONG_ID:
            today = time.strftime("%Y年%m月%d日", time.localtime())
            hour = time.strftime("%H:%M", time.localtime())
            content = f"主創說：今天是{today}的13:14分，希望你可以開心！" if hour == "13:14" else f"今天是{today} {hour}，希望你可以开心"
            success, msg = nm.comment(SONG_ID, content)
            report.append(f"💬 评论任务：{'✅ 成功' if success else '❌ 失败 (' + msg + ')'}")
            
        # 2. 刷播放量任務
        if SCROBBLE_SONG_ID:
            success_count, song_name = nm.scrobble_song(SCROBBLE_SONG_ID, int(SCROBBLE_COUNT))
            report.append(f"🎵 刷播放量：{success_count}/{SCROBBLE_COUNT} 次")
            report.append(f"🎼 目标歌曲：{song_name}")
        
        # 发送通知
        send_notification("网易云助手任务报告", "\n".join(report))
    else:
        error_msg = "❌ 登录失败，请检查凭据或 Cookie。"
        print(error_msg)
        send_notification("网易云助手运行失败", error_msg)
