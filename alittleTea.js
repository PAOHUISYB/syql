/**
 * 一点点 (1点点alittleTea+) 每日签到
 * WCS + 动态签名版 — 不再依赖 HAR 固定 sign
 *
 * 签名算法来源：3iXi 脚本 + HAR 交叉验证
 *
 * 环境变量:
 *   yddwx        — 多账号 WCS userKey，用 # & 或换行分隔
 *   wx_server_url — WCS 取码服务地址
 *   wx_auth       — WCS 认证 token
 *
 * 青龙面板添加方式：
 *   环境变量名: yddwx
 *   值: ow#第二个userKey...
 */

let axios = null;
const crypto = require('crypto');

const APPID = 'wxe87f500c8cef4c8a';
const APP_ID = '202201129689';
const WCS_URL = process.env.wx_server_url || '';
const WCS_AUTH = process.env.wx_auth || '';
const YDDWX = process.env.yddwx || '';

const CACHE_FILE = require('path').join(__dirname, 'cache_alittle_tea.json');

function loadCache() {
  try {
    if (require('fs').existsSync(CACHE_FILE)) return JSON.parse(require('fs').readFileSync(CACHE_FILE, 'utf-8'));
  } catch (e) {}
  return {};
}

function saveCache(cache) {
  try { require('fs').writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), 'utf-8'); } catch (e) {}
}

// ══════════════════════════════════════
// 签名密钥 — 来自 3iXi 脚本，HAR 交叉验证通过
// ══════════════════════════════════════
const SIGN_KEY = '4645f747025858aa92bdf966eb3d3abc';

// ══════════════════════════════════════
// 账号标识（仅用于 WCS 取码和日志标签）
// ══════════════════════════════════════
const ACCOUNT_LABELS = {
  owNAX6jD_nZMrJaPZPrLIm3PjdQY: '账号1',
  // 在此处粘贴其他账号: userKey => '标签'
};

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19841';
const REFERER = `https://servicewechat.com/${APPID}/299/page-frame.html`;
const BASE_URL = 'https://crmapi.alittle-group.cn/open';

const REQ_HEADERS = {
  'User-Agent': UA,
  'xweb_xhr': '1',
  'Content-Type': 'application/json',
  Accept: '*/*',
  'Sec-Fetch-Site': 'cross-site',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Dest': 'empty',
  Referer: REFERER,
  'Accept-Encoding': 'gzip, deflate, br',
  'Accept-Language': 'zh-CN,zh;q=0.9',
};

// ══════════════════════════════════════
// 动态签名算法
// ══════════════════════════════════════
function generateSign(params) {
  const sorted = Object.keys(params)
    .filter(k => k !== 'sign' && params[k] !== undefined && params[k] !== null && params[k] !== '')
    .sort()
    .map(k => `${k}=${params[k]}`);
  sorted.push(`key=${SIGN_KEY}`);
  return crypto.createHash('md5').update(sorted.join('&')).digest('hex');
}

function buildSignedUrl(method, extraParams = {}) {
  const params = { method, app_id: APP_ID, sign_type: 'MD5', version: '1.0.0', ...extraParams };
  params.sign = generateSign(params);
  const search = new URLSearchParams(params);
  return `${BASE_URL}?${search.toString()}`;
}

// ══════════════════════════════════════
// 工具函数
// ══════════════════════════════════════
function log(msg) {
  console.log(`[${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}] ${msg}`);
}

function getOpenids() {
  return YDDWX.split(/[&#,\n]/).map(s => s.trim()).filter(Boolean);
}

function isTodayInActivity(signConfig) {
  const today = new Date().toLocaleDateString('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
  }).replace(/\//g, '-');
  const todayItem = signConfig?.data?.list?.find(d => d.day2 === today);
  return { today, todayItem, active: Boolean(todayItem) };
}

// ══════════════════════════════════════
// WCS 取码
// ══════════════════════════════════════
async function getCodeFromWCS(userKey) {
  axios ||= require('axios');
  try {
    const resp = await axios.post(`${WCS_URL}/wx/code`,
      { appid: APPID, openid: userKey || '' },
      { headers: { auth: WCS_AUTH, 'Content-Type': 'application/json' }, timeout: 90000 }
    );
    if (resp.data?.status && resp.data?.data?.code) return resp.data.data.code;
    log(`  WCS 取码失败 | ${JSON.stringify(resp.data)}`);
    return null;
  } catch (e) {
    log(`  WCS 取码异常 | ${e?.message || e}`);
    return null;
  }
}

async function httpGet(url) {
  axios ||= require('axios');
  const resp = await axios.get(url, { headers: REQ_HEADERS, timeout: 30000 });
  return resp.data;
}

async function validateToken(token, openid) {
  try {
    const url = buildSignedUrl('crm.activity.sign.in.config', { token, openid });
    const resp = await httpGet(url);
    return resp?.errCode === 10000;
  } catch (e) { return false; }
}

// ══════════════════════════════════════
// 单账号流程
// ══════════════════════════════════════
async function runAccount(userKey, index) {
  const label = ACCOUNT_LABELS[userKey] || `${userKey.slice(0, 10)}...`;
  const sn = `账号${index}(${label})`;
  log(`\n===== ${sn} =====`);

  const cache = loadCache();
  const cacheKey = userKey || 'default';
  const cached = cache[cacheKey] || {};

  // ─── Phase 1: 获取 token / openid（缓存优先，WCS 兜底） ───
  let token, realOpenid, realUnionid, memberId;

  if (cached.token && cached.realOpenid) {
    const valid = await validateToken(cached.token, cached.realOpenid);
    if (valid) {
      log(`  ✅ 缓存token有效，跳过WCS取码`);
      token = cached.token;
      realOpenid = cached.realOpenid;
      realUnionid = cached.realUnionid;
      memberId = cached.memberId;
    } else {
      log(`  ⚠️ 缓存token已过期，重新获取`);
      delete cache[cacheKey];
      saveCache(cache);
    }
  }

  if (!token) {
    for (let attempt = 0; attempt < 2; attempt++) {
      if (attempt > 0) log(`  🔁 重新从WCS取code（第${attempt + 1}/2次）...`);

      const code = await getCodeFromWCS(userKey);
      if (!code) { if (attempt === 0) continue; return `[${label}] 取码失败`; }

      const openidUrl = buildSignedUrl('crm.wechat.openid', { js_code: code });
      const openidResp = await httpGet(openidUrl);
      if (openidResp?.errCode !== 10000) {
        if (attempt === 0) continue;
        return `[${label}] openid 获取失败`;
      }
      realOpenid = openidResp.data.openid;
      realUnionid = openidResp.data.unionid;
      log(`  openid ✅`);

      const loginUrl = buildSignedUrl('crm.member.wechat.user.login', {
        openid: realOpenid,
        unionid: realUnionid,
      });
      const loginResp = await httpGet(loginUrl);
      token = loginResp?.data?.token;
      if (!token) {
        if (attempt === 0) continue;
        return `[${label}] 登录失败`;
      }
      memberId = loginResp?.data?.member_id;
      log(`  token ✅`);

      await httpGet(buildSignedUrl('crm.member.member.login', {
        member_id: String(memberId),
        openid: realOpenid,
      }));

      cache[cacheKey] = { token, memberId, realOpenid, realUnionid, cached_at: new Date().toISOString() };
      saveCache(cache);
      break;
    }
    if (!token) return `[${label}] token获取失败`;
  }

  // ─── Phase 2: 签到业务 ───
  const configUrl = buildSignedUrl('crm.activity.sign.in.config', {
    token,
    openid: realOpenid,
  });
  const signConfig = await httpGet(configUrl);

  const { today, todayItem, active } = isTodayInActivity(signConfig);
  if (!active) {
    log(`  ⚠️ 今天不在活动周期内`);
    return `[${label}] 活动周期未覆盖`;
  }

  const contDays = signConfig?.data?.sign_d || 0;
  if (todayItem?.is_sgin === 1) {
    log(`  ✅ 今日已签 · 连续 ${contDays} 天`);
    return `[${label}] 今日已签`;
  }

  // 6. 动态签名 → 提交签到
  const signUrl = buildSignedUrl('crm.activity.sign.in.sign', {
    token,
    openid: realOpenid,
  });
  const signSubmit = await httpGet(signUrl);
  if (signSubmit?.errCode === 10000) {
    const newSignD = signSubmit?.data?.sign_d || contDays + 1;
    log(`  ✅ 签到成功 · 连续 ${newSignD} 天`);
    return `[${label}] 签到成功`;
  }
  log(`  签到失败: ${signSubmit?.errMsg || JSON.stringify(signSubmit)}`);
  return `[${label}] 签到失败`;
}

// ══════════════════════════════════════
// 主流程
// ══════════════════════════════════════
async function main() {
  if (!WCS_URL || !WCS_AUTH) {
    console.error('缺少 wx_server_url 或 wx_auth');
    process.exit(1);
  }
  const keys = getOpenids();
  if (keys.length === 0) { console.error('缺少 yddwx'); process.exit(1); }
  log(`\n===== 一点点签到（动态签名版）=====`);
  log(`  共 ${keys.length} 个账号\n`);

  const msgs = [];
  for (let i = 0; i < keys.length; i++) {
    const res = await runAccount(keys[i], i + 1);
    msgs.push(res);
    if (i < keys.length - 1) await new Promise(r => setTimeout(r, 3000));
  }

  log('\n' + '═'.repeat(28));
  log(`  执行完毕\n${msgs.join('\n')}`);

  try {
    const { sendNotify } = require('./sendNotify');
    await sendNotify(`🍵 一点点签到`, msgs.join('\n'));
  } catch {}
}

if (require.main === module) {
  main().catch(err => {
    console.error('脚本异常:', err?.response?.data || err.message || err);
    process.exit(1);
  });
}

module.exports = { generateSign, buildSignedUrl, getOpenids };
