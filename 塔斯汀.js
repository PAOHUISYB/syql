#!/usr/bin/env node
/**
 * 塔斯汀签到脚本（最终稳定版 - 不含积分查询）
 * 
 * 环境变量：
 *   TASTI_TOKEN      - 登录 token，多个用 & 或换行分隔
 *   TASTI_PHONE_ENC  - 加密手机号，与 token 顺序一一对应
 */

const BASE_URL = 'https://sss-web.tastientech.com';
const ACTIVITY_ID = 70;
const USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.60 NetType/WIFI Language/zh_CN miniProgram/wx557473f23153a429';

async function request(url, method = 'GET', headers = {}, body = null) {
    const options = {
        method: method.toUpperCase(),
        headers: {
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
            'version': '3.2.3',
            'channel': '1',
            'xweb_xhr': '1',
            'Referer': 'https://servicewechat.com/wx557473f23153a429/378/page-frame.html',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            ...headers,
        },
    };
    if (body) options.body = JSON.stringify(body);
    const res = await fetch(url, options);
    return await res.json();
}

function maskPhone(enc) {
    if (!enc || enc.length < 8) return '********';
    return enc.slice(0, 4) + '****' + enc.slice(-4);
}

async function main() {
    console.log('===== 塔斯汀签到脚本 ====');
    const rawTokens = process.env.TASTI_TOKEN || '';
    const rawPhones = process.env.TASTI_PHONE_ENC || '';
    const tokens = rawTokens.split(/[\n&]/).map(s => s.trim()).filter(Boolean);
    const encPhones = rawPhones.split(/[\n&]/).map(s => s.trim()).filter(Boolean);

    if (!tokens.length) return console.error('❌ 未设置 TASTI_TOKEN');
    if (tokens.length !== encPhones.length) return console.error('❌ TASTI_TOKEN 与 TASTI_PHONE_ENC 数量不一致');

    console.log(`共 ${tokens.length} 个账号\n`);

    for (let i = 0; i < tokens.length; i++) {
        const token = tokens[i], encPhone = encPhones[i];
        console.log(`***** 第 [${i + 1}] 个账号 *****`);
        const headers = { 'user-token': token };

        try {
            // 获取用户昵称（非必须，用于展示）
            const info = await request(`${BASE_URL}/api/intelligence/member/getMemberDetail`, 'GET', headers);
            const nick = info.code === 200 ? (info.result.nickName || '未设置昵称') : '获取失败';
            console.log(`👤 用户：${nick}（手机 ${maskPhone(encPhone)}）`);

            // 签到
            const sign = await request(`${BASE_URL}/api/sign/member/signV2`, 'POST', headers, {
                activityId: ACTIVITY_ID,
                memberName: nick === '获取失败' ? '' : nick,
                memberPhone: encPhone,
            });

            if (sign.code === 200) {
                const reward = sign.result.rewardInfoList[0];
                console.log(`✅ 签到成功，获得：${reward.rewardName || `积分+${reward.point}`}`);
            } else {
                console.log(`⚠️ 签到结果：${sign.msg}`);
            }

            // ⬇️ 积分查询预留位（等你抓包后补全）⬇️
            // const pointRes = await request(...);  // 填入抓包到的接口
            // if (pointRes.code === 200) {
            //     console.log(`💰 当前积分：${pointRes.result.point ?? pointRes.result.currentPoint}`);
            // } else {
            //     console.log(`❌ 积分查询失败：${pointRes.msg}`);
            // }
            // ⬆️ 预留位结束 ⬆️

        } catch (e) {
            console.log(`🔥 网络异常：${e.message}`);
        }
        console.log('');
    }
    console.log('===== 全部处理完毕 =====');
}

main().catch(e => console.error(e));
