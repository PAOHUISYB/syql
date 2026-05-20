/**
 * 茶百道签到 — WCS 自动获取 Token 版
 *
 * cron: 30 10 * * *
 *
 * 环境变量：
 *   wx_server_url  - WCS 服务端地址（必填，如 http://192.168.1.4:8787）
 *   wx_auth        - WCS API Key（必填）
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

async function checkWcsHealth() {
  try {
    const resp = await axios.get(`${WX_SERVER_URL}/api/status`, {
      headers: { 'auth': WX_AUTH },
      timeout: 10000,
    });
    if (resp.data && resp.data.status) {
      log(`[WCS] 服务状态正常`);
      return true;
    }
    log(`[WCS] ⚠️ 服务状态异常: ${JSON.stringify(resp.data)}`);
    return false;
  } catch (e) {
    log(`[WCS] ⚠️ 服务不可达: ${e.message}`);
    return false;
  }
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

async function codeToSession(code, exchangeUrl, extraData, extraHeaders) {
  if (!code) return null;
  try {
    const resp = await axios.post(exchangeUrl,
      { code, ...(extraData || {}) },
      {
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
          ...(extraHeaders || {}),
        },
        timeout: 20000,
      }
    );
    return resp.data;
  } catch (e) {
    log(`[WCS] ⚠️ 换 token 失败: ${e.message}`);
    return null;
  }
}

/**
 * 获取 session（缓存 → WCS获取code → 换token → 缓存）
 */
async function getSession(appid, accountName, exchangeUrl, extractFn, extraData, extraHeaders) {
  const cache = loadCache();
  if (cache[accountName] && cache[accountName].session) {
    log(`[${accountName}] 使用缓存的 session`);
    return cache[accountName].session;
  }

  // 健康检查（仅警告，不阻塞 — /api/status 可能误报但 /wx/code 实际可用）
  const healthy = await checkWcsHealth();
  if (!healthy) {
    log(`[WCS] ⚠️ /api/status 返回异常，但继续尝试获取 code（可能只是 status 端点问题）`);
  }

  const code = await getCodeFromWCS(appid, '');
  if (!code) return null;

  const result = await codeToSession(code, exchangeUrl, extraData, extraHeaders);
  if (!result) return null;

  let session;
  try { session = extractFn(result); } catch (e) {
    log(`[${accountName}] 解析 session 异常: ${e.message}, 原始响应: ${JSON.stringify(result)}`);
    return null;
  }
  if (!session) {
    log(`[${accountName}] 未获取到有效 session, 原始响应: ${JSON.stringify(result)}`);
    return null;
  }

  cache[accountName] = { session, updateTime: new Date().toISOString() };
  saveCache(cache);
  log(`[${accountName}] ✅ session 已缓存`);
  return session;
}

// ════════════════════════════════════
// 茶百道配置
// ════════════════════════════════════

const APPID = process.env.CBD_APPID || 'wx2804355dbf8d15c3';
const PAGE_FRAME_VERSION = '1143';

const APISIX_GATEWAY = 'https://apisix-gateway-pro.shuxinyc.com';
const MARKETING_GATEWAY = 'https://md-h5-gateway.shuxinyc.com';
const MEMBER_GATEWAY = 'https://chabaidao-gateway2.shuxinyc.com';

const CODE_EXCHANGE_URL = `${APISIX_GATEWAY}/applet/v2/decrypt`;
const DEFAULT_BUSINESS_ID = 'vbXC51kPVeIP';

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
  return raw.split(/[#]/).map(s => s.trim()).filter(Boolean);
}

const delay = ms => new Promise(r => setTimeout(r, ms));

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0xf2541923) XWEB/19823';

// ════════════════════════════════════
// 茶百道 Session 获取
// ════════════════════════════════════

async function getChabaidaoSession(accountName) {
  // code 换 session 时需要带小程序请求头（与业务接口一致），否则 apisix 网关拒绝
  const exchangeHeaders = {
    'Host': 'apisix-gateway-pro.shuxinyc.com',
    'User-Agent': UA,
    'Referer': `https://servicewechat.com/${APPID}/${PAGE_FRAME_VERSION}/page-frame.html`,
    'versionCode': '34580',
    'versionName': '3.4.580',
    'xweb_xhr': '1',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9',
  };

  return await getSession(APPID, accountName, CODE_EXCHANGE_URL,
    (data) => {
      if (data.code === 0 && data.data && data.data.session) {
        return data.data.session;
      }
      log(`[${accountName}] 换 session 响应异常: code=${data.code}, msg=${data.msg}, data=${JSON.stringify(data.data)}`);
      return null;
    },
    null,            // extraData
    exchangeHeaders  // extraHeaders
  );
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
    'versionCode': '34580',
    'versionName': '3.4.580',
    'xweb_xhr': '1',
    'Host': host,
  };
}

// ════════════════════════════════════
// 业务 API
// ════════════════════════════════════

async function querySignInDetail(csession) {
  log(`[查询] 获取签到活动...`);
  const resp = await axios.post(
    `${MARKETING_GATEWAY}/marketing/minip/activity/queryDetail`,
    { id: '', businessId: DEFAULT_BUSINESS_ID, activityType: 3, month: '', year: '', shopId: -1 },
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

async function doSignIn(csession, businessId) {
  log(`[签到] 执行签到...`);
  const resp = await axios.post(
    `${MARKETING_GATEWAY}/marketing/minip/activity/join/signIn`,
    { id: '', businessId: businessId || DEFAULT_BUSINESS_ID, activityJoinSource: 0, shopId: -1 },
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

  if (isTokenExpired(data.code, data.msg)) throw new Error('TOKEN_EXPIRED');
  if (data.code === '301040013') { log(`[签到] 今日已签到过`); return { success: true, alreadySigned: true }; }
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

// ════════════════════════════════════
// 单账号流程
// ════════════════════════════════════

async function runAccount(accountName) {
  log(`\n========== ${accountName} 开始 ==========`);

  let msg = `【${accountName}】`;
  let retry = 0;

  while (retry < 2) {
    try {
      const csession = await getChabaidaoSession(accountName);
      if (!csession) throw new Error('获取 session 失败');

      const { detail, alreadySigned } = await querySignInDetail(csession);
      msg += `\n活动: ${detail?.name || '未知'}`;

      if (alreadySigned) {
        msg += `\n签到: 今日已签到`;
      } else {
        const result = await doSignIn(csession);
        msg += `\n签到: 成功`;
        if (result.data?.data?.signDate) msg += ` (${result.data.data.signDate})`;
      }

      const assets = await queryAssets(csession);
      if (assets) msg += `\n熊猫币: ${assets.pointsVal} | 优惠券: ${assets.couponNum}张 | ${assets.level}`;

      log(`========== ${accountName} 结束 ==========\n`);
      notifyMsg.push(msg);
      return;

    } catch (e) {
      if (e.message === 'TOKEN_EXPIRED') {
        log(`[${accountName}] Token 过期，清除缓存并重试...`);
        clearCache(accountName);
        retry++;
        continue;
      }
      log(`[${accountName}] 失败: ${e.message}`);
      msg += `\n失败: ${e.message}`;
      break;
    }
  }

  notifyMsg.push(msg);
  log(`========== ${accountName} 结束 ==========\n`);
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
    log(`自动模式 | WCS: ${WX_SERVER_URL}`);
    await runAccount('账号1');
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
