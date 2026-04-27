#!/usr/bin/env node
/**
 * 雀巢会员签到脚本（优化独立版）
 *
 * 功能：
 *   - 获取用户信息
 *   - 自动完成所有日常任务（例如签到、浏览等）
 *   - 查询当前巢币余额
 *
 * 环境变量：
 *   NESTLE_TOKEN  – authorization 令牌（不带 "Bearer " 前缀），多个用 & 或换行分隔
 *
 * 抓包说明：
 *   Host: https://crm.nestlechinese.com
 *   从请求头中复制 authorization 字段的值，并去掉 "Bearer " 前缀（脚本会自动添加）
 *
 * 运行方式：
 *   node nestle.js
 */

// ==================== 配置 ====================
const BASE_URL = 'https://crm.nestlechinese.com';
const USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.60 NetType/WIFI Language/zh_CN miniProgram/wxc5db704249c9bb31';

// ==================== 工具函数 ====================
/**
 * 通用 HTTP 请求
 */
async function request(url, method = 'GET', headers = {}, body = null) {
    const options = {
        method: method.toUpperCase(),
        headers: {
            'User-Agent': USER_AGENT,
            'Content-Type': 'application/json',
            'Referer': 'https://servicewechat.com/wxc5db704249c9bb31/353/page-frame.html',
            ...headers,
        },
    };
    if (body) options.body = JSON.stringify(body);
    const res = await fetch(url, options);
    return await res.json();
}

/**
 * 随机延迟（秒）
 */
function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ==================== 主流程 ====================
async function main() {
    console.log('===== 雀巢会员脚本 =====');

    // 读取并解析令牌
    const raw = process.env.NESTLE_TOKEN || '';
    const tokens = raw.split(/[\n&]/).map(s => s.trim()).filter(Boolean);
    if (tokens.length === 0) {
        console.error('❌ 未设置 NESTLE_TOKEN 环境变量。');
        return;
    }
    console.log(`共检测到 ${tokens.length} 个账号\n`);

    // 推送消息收集
    let pushMessage = '';

    for (let i = 0; i < tokens.length; i++) {
        const token = tokens[i];
        console.log(`***** 处理第 [${i + 1}] 个账号 *****`);

        // 构建认证头（自动添加 Bearer 前缀）
        const headers = {
            'Authorization': `Bearer ${token}`,
        };

        // 账号信息块
        let accountMsg = `📋 账号[${i + 1}]\n`;

        try {
            // 1. 获取用户信息
            const userInfo = await request(`${BASE_URL}/openapi/member/api/User/GetUserInfo`, 'GET', headers);
            let nickname = '未知';
            let mobile = '未知';
            if (userInfo.errcode === 200) {
                nickname = userInfo.data.nickname || '未知';
                mobile = userInfo.data.mobile || '未知';
                console.log(`👤 用户：${nickname} (${mobile})`);
                accountMsg += `👤 ${nickname} (${mobile})\n`;
            } else {
                console.log(`❌ 获取用户信息失败：${userInfo.errmsg}`);
                accountMsg += `❌ 用户信息获取失败：${userInfo.errmsg}\n`;
                // 用户信息都拿不到，跳过后续任务
                pushMessage += accountMsg + '\n';
                continue;
            }

            // 2. 获取任务列表并执行
            await wait(1000);
            const taskList = await request(`${BASE_URL}/openapi/activityservice/api/task/getlist`, 'POST', headers);
            if (taskList.errcode === 200 && taskList.data.length > 0) {
                accountMsg += `📌 任务执行：\n`;
                for (const task of taskList.data) {
                    const taskTitle = task.task_title || '未知任务';
                    console.log(`  开始【${taskTitle}】任务`);
                    await wait(1000);

                    const doRes = await request(`${BASE_URL}/openapi/activityservice/api/task/add`, 'POST', headers, {
                        task_guid: task.task_guid,
                    });
                    if (doRes.errcode === 200) {
                        console.log(`  ✅ ${taskTitle} → 成功`);
                        accountMsg += `   ✅ ${taskTitle}\n`;
                    } else {
                        console.log(`  ⚠️ ${taskTitle} → ${doRes.errmsg}`);
                        accountMsg += `   ⚠️ ${taskTitle}：${doRes.errmsg}\n`;
                    }
                    await wait(1500);
                }
            } else {
                console.log('📭 没有可执行的任务或获取任务列表失败');
                accountMsg += `📭 无可执行任务\n`;
            }

            // 3. 查询巢币余额
            await wait(1000);
            const balance = await request(`${BASE_URL}/openapi/pointsservice/api/Points/getuserbalance`, 'POST', headers);
            if (balance.errcode === 200) {
                const coin = balance.data ?? '未知';
                console.log(`💰 当前巢币：${coin}`);
                accountMsg += `💰 巢币余额：${coin}\n`;
            } else {
                console.log(`❌ 积分查询失败：${balance.errmsg}`);
                accountMsg += `❌ 积分查询失败：${balance.errmsg}\n`;
            }

        } catch (e) {
            console.log(`🔥 网络异常：${e.message}`);
            accountMsg += `🔥 网络异常：${e.message}\n`;
        }

        pushMessage += accountMsg + '\n';
        console.log('');
        // 账号间等待 2~2.5 秒
        await wait(2000 + Math.random() * 500);
    }

    // 输出推送预览
    console.log('===== 推送消息预览 =====');
    console.log(pushMessage);
    console.log('===== 全部账号处理完成 =====');
    // 如需实际推送，可在这里调用你的通知函数（如 Bark、Server酱等）
}

main().catch(e => console.error(e));
