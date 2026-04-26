"""
海底捞签到

打开微信海底捞小程序登录后随便抓-然后搜索_haidilao_app_token(一般在请求头里)把里面的TOKEN_APP开头的填到变量hdlck里面即可

支持多用户运行

多用户用&或者@隔开
例如
账号1：TOKEN_APP...123
账号2： TOKEN_APP...000
则变量为TOKEN_APP...123&TOKEN_APP...000
export hdlck=""

cron: 0 7,12 * * *
const $ = new Env("海底捞签到");
"""
import requests
import re
import os
import time

# ========== 替代原来的混淆代码 ==========
all_print_list = []

def myprint(msg):
    msg = str(msg)
    print(msg)
    all_print_list.append(msg)
# =======================================

# 分割变量
if 'hdlck' in os.environ:
    hdlck = re.split("@|&", os.environ.get("hdlck"))
    print(f'查找到{len(hdlck)}个账号')
else:
    hdlck = []
    print('无hdlck变量')

# 发送通知消息
def send_notification_message(title):
    try:
        from sendNotify import send
        send(title, ''.join(all_print_list))
    except Exception as e:
        if e:
            print('发送通知消息失败！')

# 登录信息查询
def denlu(ck):
    headers = {
        '_haidilao_app_token': ck,
        'user-agent': 'Mozilla/5.0 (Linux; Android 14; 2201122C Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.188 Mobile Safari/537.36 XWEB/1260097 MMWEBSDK/20240501 MMWEBID/2247 MicroMessenger/8.0.50.2701(0x2800323C) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64'
    }
    data = {"type": 1}
    qd = requests.post(url='https://superapp-public.kiwa-tech.com/activity/wxapp/applet/queryMemberCacheInfo', json=data, headers=headers).json()
    if qd['success'] == True:
        myprint(f"账号：{qd['data']['customerName']} 登录成功")
        return qd['success']
    elif qd['success'] == False:
        myprint(f"登录失败")
        return qd['success']

# 签到
def sign(ck):
    headers = {
        '_haidilao_app_token': ck,
        'user-agent': 'Mozilla/5.0 (Linux; Android 14; 2201122C Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.188 Mobile Safari/537.36 XWEB/1260097 MMWEBSDK/20240501 MMWEBID/2247 MicroMessenger/8.0.50.2701(0x2800323C) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64'
    }
    data = {"signinSource": "MiniApp"}
    qd = requests.post(url='https://superapp-public.kiwa-tech.com/activity/wxapp/signin/signin', json=data, headers=headers).json()
    if qd['success'] == True:
        myprint(f"签到状态：{qd['data']['signinQueryDetailList'][0]['activityName']}-{qd['data']['signinQueryDetailList'][0]['dailyDate']}获得碎片：{qd['data']['signinQueryDetailList'][0]['fragment']}")
    elif qd['success'] == False:
        myprint(f"签到状态：{qd['msg']}")

# 积分查询
def jfcx(ck):
    headers = {
        '_haidilao_app_token': ck,
        'user-agent': 'Mozilla/5.0 (Linux; Android 14; 2201122C Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.188 Mobile Safari/537.36 XWEB/1260097 MMWEBSDK/20240501 MMWEBID/2247 MicroMessenger/8.0.50.2701(0x2800323C) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64'
    }
    qd = requests.post(url='https://superapp-public.kiwa-tech.com/activity/wxapp/signin/queryFragment', headers=headers).json()
    if qd['success'] == True:
        myprint(f"目前碎片：{qd['data']['total']}\n本期碎片将于{qd['data']['expireDate']}过期")
    elif qd['success'] == False:
        myprint(f"碎片查询失败")

def main():
    z = 1
    for ck in hdlck:
        try:
            myprint(f'登录第{z}个账号')
            myprint('----------------------')
            zt = denlu(ck)
            if zt == True:
                try:
                    print('-------------')
                    sign(ck)
                except Exception as e:
                    print('签到异常')
                try:
                    print('-------------')
                    jfcx(ck)
                except Exception as e:
                    print('签到异常')
            else:
                print('登录异常')
            
            myprint('----------------------')
            z = z + 1
        except Exception as e:
            print('未知错误')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('未知错误')
    try:
        send_notification_message(title='海底捞')  # 发送通知
    except Exception as e:
        print('小错误')
