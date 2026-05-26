/**
 * 茶百道签到 — WCS 自动获取 Token 版
 *
 * cron: 30 10 * * *
 *
 * 环境变量：
 *   wx_server_url  - WCS 服务端地址（必填，如 http://192.168.1.4:8787）
 *   wx_auth        - WCS API Key（必填）
 *   CBDWX         - 多账号 openid（可选，多账号用 & 或 # 分隔，单账号不填）
 *   CBD_BUSINESS_ID - 签到活动 businessId（可选，活动换期时更新此变量即可，无需改脚本）
 *   CBD_TOKEN      - 手动 CSESSION token（可选，多账号用 # 分隔）
 *   CBD_APPID      - 茶百道小程序 appid（可选，默认 wx2804355dbf8d15c3）
 *
 * QL 上传：直接上传本文件即可，所有逻辑已内联。
 */

const axios = require('axios');
const fs = require('fs');
const path = require('path');

// ════════════════════════════════════
// WCS 模块（内联，避免 QL 跨目录 require 问题）
// ════════════════════════════════════

const WX_SERVER_URL = (process.env.wx_server_url || '').replace(/\/+$/, '');
const WX_AUTH = process.env.wx_auth || '';

const CACHE_FILE = path.join(__dirname, 'chabaidao_cache.json');

function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) return JSON.parse(fs.readFileSync(CACHE_FILE, 'utf-8'));
  } catch (e) {}
  return {};
}

function saveCache(cache) {
  try { fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), 'utf-8'); } catch (e) {}
}

function clearCache(name) {
  const cache = loadCache();
  delete cache[name];
  saveCache(cache);
  log(`[缓存] 已清除 ${name}`);
}

function isTokenExpired(code, msg) {
  const s = String(code || '').toLowerCase() + (msg || '').toLowerCase();
  return ['10007', '501040048', '301040013', 'unauthorized', 'token_expired'].some(k => s.includes(k));
}

async function getCodeFromWCS(appid, openid) {
  if (!WX_SERVER_URL || !WX_AUTH) return null;

  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) {
      const wait = attempt * 5000;
      log(`[WCS] 第 ${attempt + 1}/3 次重试，等待 ${wait / 1000}s...`);
      await new Promise(r => setTimeout(r, wait));
    }

    try {
      log(`[WCS] POST ${WX_SERVER_URL}/wx/code (第 ${attempt + 1}/3 次)`);
      const resp = await axios.post(`${WX_SERVER_URL}/wx/code`,
        { appid, openid: openid || '' },
        {
          headers: { 'auth': WX_AUTH, 'Content-Type': 'application/json' },
          timeout: 90000,
        }
      );

      const data = resp.data;
      // WCS 返回: {status: true, data: {code: "xxx"}}
      if (data.status && data.data && data.data.code) {
        const code = data.data.code;
        log(`[WCS] ✅ code: ${code.substring(0, 20)}...`);

        const lr = data.data.loginResponse;
        if (lr && lr.cachedLoginFallback) {
          log(`[WCS] ⚠️ 使用了缓存回退(cachedLoginFallback=true)，登录态可能已过期`);
        }
        return code;
      }

      // 504 / WMPF 超时 → 可重试
      const msg = data.message || '';
      if (msg.includes('504') || msg.includes('502') || msg.includes('timeout')) {
        log(`[WCS] ⚠️ WMPF 超时(504)，准备重试...`);
        continue;
      }

      log(`[WCS] ⚠️ 获取 code 失败: ${JSON.stringify(data)}`);
      return null;

    } catch (e) {
      const errMsg = e.message || '';
      log(`[WCS] ⚠️ 请求失败: ${errMsg}`);
      // 超时类错误可重试
      if (errMsg.includes('timeout') || errMsg.includes('ETIMEDOUT') || errMsg.includes('ECONNRESET')) {
        continue;
      }
      return null;
    }
  }

  log(`[WCS] ❌ 3次尝试全部失败`);
  return null;
}

async function getEncryptKeyFromWCS(appid) {
  if (!WX_SERVER_URL || !WX_AUTH) return null;

  try {
    log(`[WCS] POST ${WX_SERVER_URL}/wx/encrypt`);
    const resp = await axios.post(`${WX_SERVER_URL}/wx/encrypt`,
      { appid },
      {
        headers: { 'auth': WX_AUTH, 'Content-Type': 'application/json' },
        timeout: 90000,
      }
    );

    const data = resp.data;
    if (data.status && data.data && data.data.encryptKey) {
      log(`[WCS] ✅ encryptKey: ${data.data.encryptKey.substring(0, 20)}... iv: ${data.data.iv}`);
      return data.data;
    }
    log(`[WCS] ⚠️ 获取 encryptKey 失败: ${JSON.stringify(data)}`);
    return null;
  } catch (e) {
    log(`[WCS] ⚠️ encryptKey 请求失败: ${e.message}`);
    return null;
  }
}


// ════════════════════════════════════
// 茶百道配置
// ════════════════════════════════════

const APPID = process.env.CBD_APPID || 'wx2804355dbf8d15c3';
const PAGE_FRAME_VERSION = '1146';

const APISIX_GATEWAY = 'https://apisix-gateway-pro.shuxinyc.com';
const MARKETING_GATEWAY = 'https://md-h5-gateway.shuxinyc.com';
const MEMBER_GATEWAY = 'https://chabaidao-gateway2.shuxinyc.com';

// 茶百道真正的登录接口（HAR index 121 证实：code 明文发送，无需加密）
const LOGIN_URL = `${MEMBER_GATEWAY}/hll-auth-client/oauth2/login/get/info`;
// 活动 businessId 优先从环境变量读取，活动换期只需更新 CBD_BUSINESS_ID 变量，不用改脚本
const DEFAULT_BUSINESS_ID = process.env.CBD_BUSINESS_ID || 'D1gIz6hDVa8U';

// 已知常用 businessId 备选（活动结束后自动尝试下一个）
const KNOWN_BUSINESS_IDS = [
  process.env.CBD_BUSINESS_ID,
  'D1gIz6hDVa8U',
  'vbXC51kPVeIP',
].filter(Boolean);

// 尝试用空 businessId 自动发现当前活动（无签名，依赖 CSESSION）
async function tryAutoDiscoverCurrentActivity(csession, shopId) {
  try {
    const resp = await axios.post(
      `${MARKETING_GATEWAY}/marketing/minip/activity/queryDetail`,
      { id: '', businessId: '', activityType: 3, month: '', year: '', shopId: shopId || -1 },
      { headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'), timeout: 15000 }
    );
    const data = resp.data;
    if (data.code === '000' && data.data?.signInDetail) {
      const detail = data.data.signInDetail;
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const start = (detail.startTime || '').slice(0, 8);
      const end = (detail.endTime || '').slice(0, 8);
      if (today >= start && today <= end) {
        log(`[查询] 🔍 自动发现当前活动: ${detail.name} (${detail.startTime}~${detail.endTime})`);
        return { detail, autoDiscovered: true };
      }
    }
  } catch (e) { /* 自发现失败，回退到已知 businessId */ }
  return null;
}

// ════════════════════════════════════
// 工具函数
// ════════════════════════════════════

function log(msg) {
  console.log(`[${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}] ${msg}`);
}

function getEnv(name) { return process.env[name] || ''; }

function getAccounts(envName) {
  const raw = getEnv(envName);
  if (!raw) return [];
  return raw.split(/[#&]/).map(s => s.trim()).filter(Boolean);
}

const delay = ms => new Promise(r => setTimeout(r, ms));

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0xf2541923) XWEB/19823';

// ════════════════════════════════════
// 茶百道 Session 获取
// ════════════════════════════════════

async function validateSession(csession) {
  try {
    const resp = await axios.post(
      `${MEMBER_GATEWAY}/member2c/applet/head/assets`, {},
      { headers: makeHeaders(csession, 'chabaidao-gateway2.shuxinyc.com'), timeout: 10000 }
    );
    return resp.data.code === '000';
  } catch (e) {
    return false;
  }
}

async function getChabaidaoSession(accountName, openid) {
  // 1. 检查缓存并验证
  const cache = loadCache();
  const cacheKey = openid ? `${accountName}_${openid.substring(0, 8)}` : accountName;
  if (cache[cacheKey] && cache[cacheKey].session) {
    log(`[${accountName}] 检查缓存 session...`);
    const valid = await validateSession(cache[cacheKey].session);
    if (valid) {
      log(`[${accountName}] ✅ 缓存session有效，跳过WCS取码`);
      return cache[cacheKey].session;
    }
    log(`[${accountName}] ⚠️ 缓存session已过期，重新获取`);
    delete cache[cacheKey];
    saveCache(cache);
  }

  // 2. 获取 wx.login code
  const code1 = await getCodeFromWCS(APPID, openid || '');
  if (!code1) {
    log(`[${accountName}] 获取 code 失败`);
    return null;
  }

  const loginHeaders = (csession) => ({
    'Host': 'chabaidao-gateway2.shuxinyc.com',
    'Content-Type': 'application/json',
    'User-Agent': UA,
    'Referer': `https://servicewechat.com/${APPID}/${PAGE_FRAME_VERSION}/page-frame.html`,
    'versionCode': '34592',
    'versionName': '3.4.592',
    'xweb_xhr': '1',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'CSESSION': csession || '',
  });

  try {
    // 3. 首次登录（pureSign=true，无 token）
    log(`[${accountName}] 步骤1/2: 首次登录（pureSign=true）...`);
    const resp1 = await axios.post(LOGIN_URL,
      { token: '', groupId: '317964', memberSystemId: '21', code: code1, appId: APPID, pureSign: true },
      { headers: loginHeaders(''), timeout: 20000 }
    );
    const data1 = resp1.data;
    if (data1.code !== '000' || !data1.data || !data1.data.token) {
      log(`[${accountName}] 首次登录失败: ${JSON.stringify(data1)}`);
      return null;
    }
    const session1 = data1.data.token;
    const shopId = data1.data.shopId || 0;
    log(`[${accountName}] ✅ 首次登录成功: ${session1.substring(0, 30)}...`);

    // 4. 获取新 code，二次登录（pureSign=false，带旧 token）
    log(`[${accountName}] 步骤2/2: 二次登录刷新（pureSign=false）...`);
    const code2 = await getCodeFromWCS(APPID, openid || '');
    if (!code2) {
      log(`[${accountName}] ⚠️ 获取第二次 code 失败，使用首次 session`);
      cache[cacheKey] = { session: session1, shopId, updateTime: new Date().toISOString() };
      saveCache(cache);
      return session1;
    }

    const resp2 = await axios.post(LOGIN_URL,
      { token: session1, groupId: '317964', memberSystemId: '21', code: code2, appId: APPID, pureSign: false },
      { headers: loginHeaders(session1), timeout: 20000 }
    );
    const data2 = resp2.data;
    if (data2.code === '000' && data2.data && data2.data.token) {
      const session2 = data2.data.token;
      const shopId2 = data2.data.shopId || shopId;
      log(`[${accountName}] ✅ 二次登录成功（pureSign=false）: ${session2.substring(0, 30)}...`);
      cache[cacheKey] = { session: session2, shopId: shopId2, updateTime: new Date().toISOString() };
      saveCache(cache);
      return session2;
    }

    // 二次登录失败，回退
    log(`[${accountName}] ⚠️ 二次登录失败: ${JSON.stringify(data2)}，使用首次 session`);
    cache[cacheKey] = { session: session1, shopId, updateTime: new Date().toISOString() };
    saveCache(cache);
    return session1;

  } catch (e) {
    log(`[${accountName}] 登录请求失败: ${e.message}, 响应: ${JSON.stringify(e.response?.data)}`);
    return null;
  }
}

// ════════════════════════════════════
// 通用请求头
// ════════════════════════════════════

function makeHeaders(csession, host) {
  return {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Content-Type': 'application/json',
    'CSESSION': csession,
    'User-Agent': UA,
    'Referer': `https://servicewechat.com/${APPID}/${PAGE_FRAME_VERSION}/page-frame.html`,
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'versionCode': '34592',
    'versionName': '3.4.592',
    'xweb_xhr': '1',
    'Host': host,
  };
}

// ════════════════════════════════════
// 业务 API
// ════════════════════════════════════

async function querySignInDetail(csession, shopId) {
  log(`[查询] 获取签到活动...`);
  const resp = await axios.post(
    `${MARKETING_GATEWAY}/marketing/minip/activity/queryDetail`,
    { id: '', businessId: DEFAULT_BUSINESS_ID, activityType: 3, month: '', year: '', shopId: shopId || -1 },
    { headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'), timeout: 30000 }
  );

  const data = resp.data;
  if (data.code !== '000') {
    if (isTokenExpired(data.code, data.msg)) throw new Error('TOKEN_EXPIRED');
    throw new Error(`查询活动失败: code=${data.code}, msg=${data.msg}`);
  }

  const detail = data.data?.signInDetail;
  if (!detail) throw new Error('签到活动详情为空');

  log(`[查询] 活动: ${detail.name}`);
  log(`[查询] 时间: ${detail.startTime} ~ ${detail.endTime}`);

  if (detail.signInRecordList) {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    if (detail.signInRecordList.some(r => r.signDate === today)) {
      log(`[查询] 今日已签到`);
      return { detail, alreadySigned: true };
    }
  }
  return { detail, alreadySigned: false };
}

async function doSignIn(csession, shopId, businessId) {
  log(`[签到] 执行签到...`);
  const resp = await axios.post(
    `${MARKETING_GATEWAY}/marketing/minip/activity/join/signIn`,
    { id: '', businessId: businessId || DEFAULT_BUSINESS_ID, activityJoinSource: 0, shopId: shopId || -1 },
    { headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'), timeout: 30000 }
  );

  const data = resp.data;
  if (data.code === '000') {
    log(`[签到] ✅ 成功！日期: ${data.data?.signDate}`);
    if (data.data?.marketingGiftConfCOList) {
      for (const gift of data.data.marketingGiftConfCOList) {
        if (gift.giftList) {
          for (const g of gift.giftList) {
            if (g.giftType === 3) log(`[签到] 获得 ${g.point} 熊猫币`);
            else if (g.giftType === 1) log(`[签到] 获得优惠券`);
          }
        }
      }
    }
    return { success: true, data };
  }

  // 301040013=今日已签到，不是 token 过期，先判断
  if (data.code === '301040013') { log(`[签到] 今日已签到过`); return { success: true, alreadySigned: true }; }
  // 301040011=活动已结束，无需重试
  if (data.code === '301040011') { log(`[签到] 活动已结束`); return { success: false, activityEnded: true }; }
  // 301040047=当前未开放领取（未到活动开放时间）
  if (data.code === '301040047') { log(`[签到] 当前未到活动开放时间`); return { success: false, notYetOpen: true }; }
  if (isTokenExpired(data.code, data.msg)) throw new Error('TOKEN_EXPIRED');
  throw new Error(`签到失败: code=${data.code}, msg=${data.msg}`);
}

async function queryAssets(csession) {
  try {
    const resp = await axios.post(
      `${MEMBER_GATEWAY}/member2c/applet/head/assets`, {},
      { headers: makeHeaders(csession, 'chabaidao-gateway2.shuxinyc.com'), timeout: 30000 }
    );
    const data = resp.data;
    if (data.code === '000') {
      log(`[查询] 熊猫币: ${data.data?.pointsVal}, 优惠券: ${data.data?.couponNum}张, 等级: ${data.data?.level}`);
      return data.data;
    }
  } catch (e) { log(`[查询] 积分查询失败（可忽略）: ${e.message}`); }
  return null;
}

async function bindMemberInfo(csession) {
  try {
    // 先调用轻量接口预热 session（HAR 中 login 与 selectMemberInfo 之间隔了大量请求）
    log(`[会员] 预热 session...`);
    await axios.post(
      `${MEMBER_GATEWAY}/coupon/applet/getMemberCouponTag`, {},
      { headers: makeHeaders(csession, 'chabaidao-gateway2.shuxinyc.com'), timeout: 10000 }
    );
    await delay(500);

    log(`[会员] 绑定会员身份...`);
    const resp = await axios.post(
      `${MEMBER_GATEWAY}/member2c/applet/v2/selectMemberInfo`,
      { appID: APPID, sourceType: 30 },
      { headers: makeHeaders(csession, 'chabaidao-gateway2.shuxinyc.com'), timeout: 15000 }
    );
    if (resp.data.code === '000') {
      log(`[会员] ✅ 已绑定: cardNo=${resp.data.data?.cardNo || 'N/A'}, memberId=${resp.data.data?.memberId || 'N/A'}`);
      return true;
    }
    log(`[会员] 绑定失败: ${JSON.stringify(resp.data)}`);
    return false;
  } catch (e) {
    log(`[会员] 绑定请求失败: ${e.message}`);
    return false;
  }
}

// ════════════════════════════════════
// 单账号流程
// ════════════════════════════════════

async function runAccount(accountName, openid) {
  const oid = openid || '';
  const label = oid ? `${accountName}(${oid.substring(0, 8)}...)` : accountName;
  log(`\n========== ${label} 开始 ==========`);

  let msg = `【${label}】`;
  let retry = 0;

  const cacheKey = oid ? `${accountName}_${oid.substring(0, 8)}` : accountName;

  while (retry < 2) {
    try {
      const csession = await getChabaidaoSession(accountName, oid);
      if (!csession) throw new Error('获取 session 失败');

      // 读取 shopId（登录时已缓存）
      const shopId = (loadCache()[cacheKey] || {}).shopId || -1;

      // 绑定会员身份（两步登录后通常能成功）
      await bindMemberInfo(csession);

      const { detail, alreadySigned } = await querySignInDetail(csession, shopId);
      msg += `\n活动: ${detail?.name || '未知'}`;

      if (alreadySigned) {
        msg += `\n签到: 今日已签到`;
      } else {
        let signResult = await doSignIn(csession, shopId);

        // 活动已结束 / 未开放 → 自动发现 → 备选 businessId
        if (signResult.activityEnded || signResult.notYetOpen) {
          let found = false;

          // ① 先用空 businessId 自动发现当前活动
          const discovered = await tryAutoDiscoverCurrentActivity(csession, shopId);
          if (discovered) {
            log(`[${label}] 🔍 自发现活动: ${discovered.detail.name}`);
            const tryResult = await doSignIn(csession, shopId);
            if (tryResult.success || tryResult.alreadySigned) {
              signResult = tryResult;
              found = true;
            }
          }

          // ② 自发现失败 → 遍历已知 businessId
          if (!found) {
            for (const bid of KNOWN_BUSINESS_IDS) {
              if (!bid || bid === DEFAULT_BUSINESS_ID) continue;
              log(`[${label}] 尝试备用 businessId: ${bid}`);
              const tryResult = await doSignIn(csession, shopId, bid);
              if (tryResult.success || tryResult.alreadySigned) {
                signResult = tryResult;
                found = true;
                log(`[${label}] ✅ 备用 businessId 签到成功: ${bid}`);
                break;
              }
            }
          }

          if (!found) {
            msg += signResult.activityEnded
              ? `\n签到: 活动已结束（自发现+备选均失败，请更新 CBD_BUSINESS_ID）`
              : `\n签到: 未到活动开放时间`;
            log(`========== ${label} 结束 ==========\n`);
            notifyMsg.push(msg);
            return;
          }
        }

        if (signResult.success || signResult.alreadySigned) {
          msg += `\n签到: 成功`;
          if (signResult.data?.data?.signDate) msg += ` (${signResult.data.data.signDate})`;
        } else {
          msg += `\n签到: ${signResult.activityEnded ? '活动已结束' : signResult.notYetOpen ? '未到开放时间' : '失败'}`;
        }
      }

      const assets = await queryAssets(csession);
      if (assets) msg += `\n熊猫币: ${assets.pointsVal} | 优惠券: ${assets.couponNum}张 | ${assets.level}`;

      log(`========== ${label} 结束 ==========\n`);
      notifyMsg.push(msg);
      return;

    } catch (e) {
      if (e.message === 'TOKEN_EXPIRED') {
        log(`[${label}] Token 过期，清除缓存并重试...`);
        clearCache(cacheKey);
        retry++;
        continue;
      }
      // 会员id为空说明 session 未正确绑定，清缓存重试
      if (e.message.includes('会员id不能为空')) {
        log(`[${label}] Session 未绑定会员，清除缓存重试...`);
        clearCache(cacheKey);
        retry++;
        continue;
      }
      log(`[${label}] 失败: ${e.message}`);
      msg += `\n失败: ${e.message}`;
      break;
    }
  }

  notifyMsg.push(msg);
  log(`========== ${label} 结束 ==========\n`);
}

// ════════════════════════════════════
// 主流程
// ════════════════════════════════════

async function main() {
  log('茶百道签到 — WCS 自动获取 Token 版');
  log('====================================');

  const useAutoMode = !!(WX_SERVER_URL && WX_AUTH);
  const tokens = getAccounts('CBD_TOKEN');

  if (!useAutoMode && tokens.length === 0) {
    console.error('缺少配置：wx_server_url + wx_auth（自动模式）或 CBD_TOKEN（手动模式）');
    process.exit(1);
  }

  if (useAutoMode) {
    // 读取多账号 openid（环境变量 CBDWX，用 & 或 # 分隔）
    const openids = getAccounts('CBDWX');
    if (openids.length > 0) {
      log(`自动模式 | WCS: ${WX_SERVER_URL} | ${openids.length} 个账号`);
      for (let i = 0; i < openids.length; i++) {
        await runAccount(`账号${i + 1}`, openids[i]);
        if (i < openids.length - 1) await delay(2000);
      }
    } else {
      log(`自动模式 | WCS: ${WX_SERVER_URL} | 单账号`);
      await runAccount('账号1');
    }
  } else {
    log(`手动模式 | ${tokens.length} 个账号`);
    for (let i = 0; i < tokens.length; i++) {
      await runAccount(`账号${i + 1}`);
      if (i < tokens.length - 1) await delay(2000);
    }
  }

  log('\n全部账号处理完毕');

  if (notifyMsg.length > 0) {
    try {
      const { sendNotify } = require('./sendNotify');
      await sendNotify('茶百道签到', notifyMsg.join('\n'));
    } catch (e) { log(`[通知] 发送失败: ${e.message}`); }
  }
}

const notifyMsg = [];

main().catch(e => {
  console.error('脚本异常退出:', e);
  process.exit(1);
});
