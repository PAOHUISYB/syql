/**
 * 百度贴吧 综合签到 (合并版)
 * ============================
 * 合并 tieba1.js（贴吧批量签到） + 贴吧2.js（成长任务签到）
 *
 * 环境变量:
 *   TIE_BA_COOKIE — 贴吧 Cookie，多账号用 & 或换行分隔
 *      格式1（仅贴吧签到）: BDUSS=xxxx
 *      格式2（贴吧签到+成长任务）: CUID=xxxx; BDUSS=xxxx
 *
 * cron 建议: 33 13 * * *
 */

const axios = require('axios');
const crypto = require('crypto');

const COOKIES = process.env.TIE_BA_COOKIE || '';
const UA = 'Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36';

function log(msg) {
  console.log(`[${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}] ${msg}`);
}

function rand(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const delay = ms => new Promise(r => setTimeout(r, ms));

function getAccounts() {
  if (!COOKIES) return [];
  return COOKIES.split(/[&\n]/).map(s => s.trim()).filter(Boolean);
}

function parseCookie(raw) {
  const bduss = (raw.match(/BDUSS=([^;]+)/) || [])[1] || raw;
  const cuid = (raw.match(/CUID=([^;]+)/) || [])[1] || '';
  return { bduss, cuid, raw };
}

// ════════════════════════════════════
// HTTP 请求
// ════════════════════════════════════
async function httpGet(url, cookie) {
  const resp = await axios.get(url, {
    headers: {
      Cookie: cookie,
      'User-Agent': UA,
      'Accept': 'application/json, text/plain, */*',
      'Host': 'tieba.baidu.com',
    },
    timeout: 15000,
  });
  return resp.data;
}

async function httpPost(url, cookie, body) {
  const resp = await axios.post(url, body, {
    headers: {
      Cookie: cookie,
      'User-Agent': UA,
      'Content-Type': 'application/x-www-form-urlencoded',
      'Host': 'tieba.baidu.com',
    },
    timeout: 15000,
  });
  return resp.data;
}

// ════════════════════════════════════
// Part 1: 成长任务签到 (原贴吧2.js)
// ════════════════════════════════════

async function getUserInfo(cookie, cuid) {
  try {
    const data = await httpGet(
      'https://tieba.baidu.com/mo/q/usergrowth/showUserGrowth?client_type=2&client_version=12.60.1.2',
      cookie
    );
    if (data?.no !== 0) {
      log(`  获取用户信息失败: ${data?.error || '未知'}`);
      return null;
    }
    return {
      uname: data.data.user.uname,
      tbs: data.data.tbs,
      growthValue: data.data.growth_info.value,
      tmoney: data.data.tmoney.current,
      levelInfo: data.data.level_info,
    };
  } catch (e) {
    log(`  获取用户信息异常: ${e.message}`);
    return null;
  }
}

async function growthSign(cookie, tbs, cuid) {
  if (!cuid) {
    log(`  ⚠️ 未提供 CUID，跳过成长任务签到`);
    return { skipped: true, msg: '缺少CUID' };
  }
  try {
    const params = `tbs=${tbs}&act_type=page_sign&cuid=${cuid}&client_type=2&brand=OPPO&model=OPPO%20R9s&zid=&clientVersion=12.60.1.2&clientType=2`;
    const data = await httpPost(
      'https://tieba.baidu.com/mo/q/usergrowth/commitUGTaskInfo',
      cookie,
      params
    );
    if (data?.no === 0) return { success: true };
    if (data?.no === 110101) return { success: true, msg: '今日已签' };
    return { success: false, msg: data?.error || JSON.stringify(data).substring(0, 80) };
  } catch (e) {
    return { success: false, msg: e.message };
  }
}

// ════════════════════════════════════
// Part 2: 贴吧批量签到 (原tieba1.js)
// ════════════════════════════════════

async function getTBS(cookie) {
  try {
    const data = await httpGet('http://tieba.baidu.com/dc/common/tbs', cookie);
    return data?.tbs || null;
  } catch (e) {
    log(`  获取TBS异常: ${e.message}`);
    return null;
  }
}

async function getFollowedForums(cookie) {
  try {
    const data = await httpGet('https://tieba.baidu.com/mo/q/newmoindex', cookie);
    const forums = data?.data?.like_forum || [];
    return {
      total: forums.length,
      unsigned: forums.filter(f => f.is_sign === 0).map(f => f.forum_name),
      signed: forums.filter(f => f.is_sign === 1).map(f => f.forum_name),
    };
  } catch (e) {
    log(`  获取贴吧列表异常: ${e.message}`);
    return { total: 0, unsigned: [], signed: [] };
  }
}

async function isForumInvalid(cookie, forumName) {
  try {
    const data = await httpGet(
      `https://tieba.baidu.com/f?ie=utf-8&kw=${forumName}&fr=search`,
      cookie
    );
    const str = typeof data === 'string' ? data : JSON.stringify(data);
    return str.includes('很抱歉，没有找到相关内容');
  } catch (e) {
    return false;
  }
}

async function signOneForum(cookie, forumName, tbs) {
  const kw = forumName.replace('+', '%2B');
  const signStr = `kw=${kw}tbs=${tbs}tiebaclient!!!`;
  const signMd5 = crypto.createHash('md5').update(signStr).digest('hex');

  try {
    const data = await httpPost('http://c.tieba.baidu.com/c/c/forum/sign', cookie, {
      kw,
      tbs,
      sign: signMd5,
    });
    return data?.error_code === '0' ? { success: true } : { success: false, code: data?.error_code };
  } catch (e) {
    return { success: false, code: e.message };
  }
}

// ════════════════════════════════════
// 单账号流程
// ════════════════════════════════════
async function runAccount(rawCookie, index) {
  const { bduss, cuid, raw } = parseCookie(rawCookie);
  const cookie = raw.includes('BDUSS=') ? raw : `BDUSS=${raw}`;
  log(`\n===== 账号[${index}] =====`);

  const parts = [];

  // ── 成长任务签到 ──
  log('  --- 成长任务 ---');
  const gTbs = await getTBS(cookie);
  if (!gTbs) {
    log('  ❌ Cookie失效，跳过本账号');
    return `[账号${index}] Cookie失效`;
  }

  if (cuid) {
    const gr = await growthSign(cookie, gTbs, cuid);
    if (gr.skipped) {
      parts.push('成长任务: 缺少CUID');
    } else if (gr.success) {
      log(`  ✅ 成长任务 ${gr.msg || '签到成功'}`);
      parts.push('成长任务: ✅');
    } else {
      log(`  ❌ 成长任务失败: ${gr.msg}`);
      parts.push(`成长任务: ${gr.msg}`);
    }
  } else {
    log('  ⚠️ 无CUID，跳过成长任务');
    parts.push('成长任务: 无CUID');
  }

  await delay(rand(1000, 2000));

  // ── 用户信息 ──
  if (cuid) {
    const info = await getUserInfo(cookie, cuid);
    if (info) {
      log(`  👤 ${info.uname} | Lv.${info.levelInfo?.find(l => l.is_current === 1)?.level || '?'} | 成长值${info.growthValue} | 贴贝${info.tmoney}`);
      parts.push(`${info.uname} Lv${info.levelInfo?.find(l => l.is_current === 1)?.level || '?'}`);
    }
  }

  await delay(rand(1000, 1500));

  // ── 贴吧批量签到 ──
  log('  --- 贴吧签到 ---');
  const forums = await getFollowedForums(cookie);
  log(`  关注${forums.total}个吧 | 已签${forums.signed.length}个 | 待签${forums.unsigned.length}个`);

  const successList = [...forums.signed];
  const failedList = [];
  const invalidList = [];

  if (forums.unsigned.length > 0) {
    const signTbs = await getTBS(cookie);
    if (!signTbs) {
      parts.push(`贴吧签到: TBS获取失败`);
    } else {
      let retries = 3;
      while (forums.unsigned.length > 0 && retries > 0) {
        for (const fname of [...forums.unsigned]) {
          // 检查贴吧是否失效
          const invalid = await isForumInvalid(cookie, fname);
          if (invalid) {
            forums.unsigned = forums.unsigned.filter(f => f !== fname);
            invalidList.push(fname);
            log(`  ⚠️ [${fname}] 贴吧已失效，跳过`);
            await delay(rand(500, 1000));
            continue;
          }

          const result = await signOneForum(cookie, fname, signTbs);
          if (result.success) {
            forums.unsigned = forums.unsigned.filter(f => f !== fname);
            successList.push(fname);
            log(`  ✅ [${fname}] 签到成功`);
          } else {
            failedList.push(fname);
            log(`  ❌ [${fname}] 失败 code=${result.code}`);
          }
          await delay(rand(1000, 2000));
        }
        retries--;
        if (forums.unsigned.length > 0 && retries > 0) {
          log(`  🔁 剩余${forums.unsigned.length}个未签，重试(${3 - retries}/3)...`);
          await delay(rand(5000, 10000));
        }
      }
    }
  }

  parts.push(`贴吧签到: ${successList.length}/${forums.total} 成功${invalidList.length > 0 ? ` 过滤${invalidList.length}个失效吧` : ''}`);

  return `[账号${index}] ` + parts.join(' | ');
}

// ════════════════════════════════════
// 主流程
// ════════════════════════════════════
async function main() {
  log('===== 百度贴吧 综合签到 =====');

  const accounts = getAccounts();
  if (accounts.length === 0) {
    console.error('未配置 TIE_BA_COOKIE 环境变量');
    process.exit(1);
  }

  log(`共 ${accounts.length} 个账号\n`);

  const msgs = [];
  for (let i = 0; i < accounts.length; i++) {
    msgs.push(await runAccount(accounts[i], i + 1));
    if (i < accounts.length - 1) await delay(rand(2000, 3000));
  }

  log('\n' + '='.repeat(40));
  log('执行完毕\n' + msgs.join('\n'));

  try {
    const { sendNotify } = require('./sendNotify');
    await sendNotify('贴吧综合签到', msgs.join('\n'));
  } catch {}
}

main().catch(e => {
  console.error('脚本异常:', e?.response?.data || e.message || e);
  process.exit(1);
});
