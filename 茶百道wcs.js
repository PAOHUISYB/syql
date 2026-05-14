/**
 * 茶百道签到 - WCS 版（通过 WeChatCodeServer 获取 code 换 token 签到）
 * 青龙面板定时任务脚本
 * 
 * ━━━━━━━━━━━━ WCS 获取 Code 流程 ━━━━━━━━━━━━
 * 
 * WCS (WeChatCodeServer) 通过 WMPF 在模拟器内控制微信小程序，
 * 对外暴露 REST API 让脚本远程获取 wx.login 的 code。
 * 
 * 核心接口：POST {WCS_URL}/wx/code
 *   请求: { appid: "wx2804355dbf8d15c3", openid: "用户openid" }
 *   返回: { data: { code: "0d382VGa1...", openid: "6b9112d0", ... } }
 * 
 * code → token 流程：
 *   1. WCS 获取 code（有效期~5分钟，一次性）
 *   2. POST apisix-gateway-pro.shuxinyc.com/applet/v2/decrypt 用 code 换 CSESSION
 *   3. CSESSION 即为业务 token（有效期几小时~几天）
 * 
 * ━━━━━━━━━━━━ openid 获取方法 ━━━━━━━━━━━━
 * 
 * openid 在 WCS 的 /api/accounts 接口中查看，
 * 或者从抓包工具中搜索 shuxinyc 请求的 CSESSION 前半部分（竖线前的数字即时间戳，非 openid）
 * openid 通常在 WCS 配置时已经设好，直接复制到环境变量 CBD 即可
 * 
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 
 * 环境变量：
 *   wx_server_url  - WCS 服务地址，如 http://192.168.1.4:8787（必填）
 *   wx_auth        - WCS API Key（必填）
 *   CBD            - 茶百道 openid，多账号用 # 或 , 分隔（必填）
 * 
 * 定时规则建议：30 10 * * *（每天 10:30，签到活动 10:00 开始）
 * 
 * 流程：
 *   1. POST /wx/code → 获取 wx.login code
 *   2. POST /applet/v2/decrypt → 用 code 换 CSESSION token
 *   3. POST /marketing/minip/activity/queryDetail → 查询签到活动信息
 *   4. POST /marketing/minip/activity/join/signIn → 执行签到
 *   5. POST /close → 关闭 WCS 会话
 */

const got = require('got');

// ============ 配置 ============
const APPID = 'wx2804355dbf8d15c3';          // 茶百道饮品点单小程序 APPID
const PAGE_FRAME_VERSION = '1143';

// 业务 API 域名
const API_GATEWAY = 'https://apisix-gateway-pro.shuxinyc.com';
const MARKETING_GATEWAY = 'https://md-h5-gateway.shuxinyc.com';

// 默认签到活动 businessId（每周可能变化，脚本会自动查询当前有效的）
const DEFAULT_BUSINESS_ID = 'vbXC51kPVeIP';

// ============ 工具函数 ============

function log(msg) {
  const now = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  console.log(`[${now}] ${msg}`);
}

function getEnv(name) {
  return process.env[name] || '';
}

function getAccounts(envName) {
  const raw = getEnv(envName);
  if (!raw) return [];
  return raw.split(/[#,]/).map(s => s.trim()).filter(Boolean);
}

// 延时
const delay = ms => new Promise(r => setTimeout(r, ms));

// ============ WCS 客户端 ============

async function wxCode(openid) {
  const url = getEnv('wx_server_url').replace(/\/+$/, '');
  const auth = getEnv('wx_auth');

  log(`[WCS] 请求 code, openid=${openid}`);
  const resp = await got.post(`${url}/wx/code`, {
    headers: { auth, 'Content-Type': 'application/json' },
    json: { appid: APPID, openid },
    timeout: { request: 90000 },
    retry: { limit: 1 },
  });

  const data = JSON.parse(resp.body);
  if (!data.status || !data.data?.code) {
    throw new Error(`WCS 获取 code 失败: ${JSON.stringify(data)}`);
  }

  log(`[WCS] code 获取成功: ${data.data.code.substring(0, 10)}...`);
  return data.data.code;
}

async function wxClose(openid) {
  const url = getEnv('wx_server_url').replace(/\/+$/, '');
  const auth = getEnv('wx_auth');

  try {
    await got.post(`${url}/close`, {
      headers: { auth, 'Content-Type': 'application/json' },
      json: { appid: APPID, openid },
      timeout: { request: 30000 },
    });
    log(`[WCS] 会话已关闭, openid=${openid}`);
  } catch (e) {
    log(`[WCS] 关闭会话失败（可忽略）: ${e.message}`);
  }
}

// ============ 业务 API ============

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823';

const COMMON_HEADERS = {
  'Accept': '*/*',
  'Accept-Encoding': 'gzip, deflate, br',
  'Accept-Language': 'zh-CN,zh;q=0.9',
  'Content-Type': 'application/json',
  'User-Agent': UA,
  'Referer': `https://servicewechat.com/${APPID}/${PAGE_FRAME_VERSION}/page-frame.html`,
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'cross-site',
  'versionCode': '34580',
  'versionName': '3.4.580',
  'xweb_xhr': '1',
};

/**
 * 用 code 换 CSESSION token
 * 调用 decrypt 接口，把 code 传过去换取会话 token
 */
async function decryptCode(code) {
  log(`[业务] 用 code 换 CSESSION token...`);
  const resp = await got.post(`${API_GATEWAY}/applet/v2/decrypt`, {
    headers: {
      ...COMMON_HEADERS,
      'Host': 'apisix-gateway-pro.shuxinyc.com',
    },
    json: { code },
    timeout: { request: 30000 },
  });

  const data = JSON.parse(resp.body);
  // 尝试从响应中提取 CSESSION
  const setCookie = resp.headers['set-cookie'];
  let csession = '';

  if (setCookie) {
    const cookies = Array.isArray(setCookie) ? setCookie : [setCookie];
    for (const c of cookies) {
      const match = c.match(/CSESSION=([^;]+)/);
      if (match) {
        csession = match[1];
        break;
      }
    }
  }

  // 也可能从响应 body 中拿
  if (!csession && data.data) {
    csession = data.data.csession || data.data.token || data.data.sessionKey || '';
  }

  if (!csession) {
    // 检查返回的 data 是否就是 token
    if (data.code === 0 || data.code === '000') {
      log(`[业务] decrypt 成功但未找到 CSESSION，可能需要从 cookie 提取`);
      log(`[业务] decrypt 响应: ${JSON.stringify(data).substring(0, 500)}`);
    }
    throw new Error(`无法获取 CSESSION token，decrypt 响应: ${JSON.stringify(data).substring(0, 300)}`);
  }

  log(`[业务] CSESSION 获取成功: ${csession.substring(0, 20)}...`);
  return csession;
}

/**
 * 查询签到活动详情
 */
async function querySignInDetail(csession) {
  log(`[业务] 查询签到活动详情...`);
  const resp = await got.post(`${MARKETING_GATEWAY}/marketing/minip/activity/queryDetail`, {
    headers: {
      ...COMMON_HEADERS,
      'Host': 'md-h5-gateway.shuxinyc.com',
      'CSESSION': csession,
    },
    json: {
      id: '',
      businessId: DEFAULT_BUSINESS_ID,
      activityType: 3,
      month: '',
      year: '',
      shopId: -1,
    },
    timeout: { request: 30000 },
  });

  const data = JSON.parse(resp.body);
  if (data.code !== '000') {
    throw new Error(`查询签到活动失败: ${data.msg}`);
  }

  const detail = data.data?.signInDetail;
  if (!detail) {
    throw new Error('签到活动详情为空');
  }

  log(`[业务] 当前活动: ${detail.name}`);
  log(`[业务] 活动时间: ${detail.startTime} ~ ${detail.endTime}`);

  // 检查当前是否在活动时间内
  const now = new Date();
  const start = parseDateTime(detail.startTime);
  const end = parseDateTime(detail.endTime);
  if (now < start || now > end) {
    log(`[业务] ⚠️ 当前不在活动时间范围内`);
  }

  return detail;
}

/**
 * 执行签到
 */
async function doSignIn(csession, businessId) {
  log(`[业务] 执行签到...`);
  const resp = await got.post(`${MARKETING_GATEWAY}/marketing/minip/activity/join/signIn`, {
    headers: {
      ...COMMON_HEADERS,
      'Host': 'md-h5-gateway.shuxinyc.com',
      'CSESSION': csession,
    },
    json: {
      id: '',
      businessId: businessId || DEFAULT_BUSINESS_ID,
      activityJoinSource: 0,
      shopId: -1,
    },
    timeout: { request: 30000 },
  });

  const data = JSON.parse(resp.body);
  if (data.code === '000') {
    log(`[业务] ✅ 签到成功！日期: ${data.data?.signDate}`);
    
    // 打印奖励
    if (data.data?.marketingGiftConfCOList) {
      for (const gift of data.data.marketingGiftConfCOList) {
        if (gift.giftList) {
          for (const g of gift.giftList) {
            if (g.giftType === 3) {
              log(`[业务] 🪙 获得 ${g.point} 熊猫币`);
            }
          }
        }
      }
    }
    return data;
  } else if (data.code === '501040048') {
    log(`[业务] ⚠️ 已签到过或操作频繁: ${data.msg}`);
    return data;
  } else {
    throw new Error(`签到失败: code=${data.code}, msg=${data.msg}`);
  }
}

/**
 * 查询积分余额
 */
async function queryAssets(csession) {
  try {
    const resp = await got.post('https://chabaidao-gateway2.shuxinyc.com/member2c/applet/head/assets', {
      headers: {
        ...COMMON_HEADERS,
        'Host': 'chabaidao-gateway2.shuxinyc.com',
        'CSESSION': csession,
      },
      json: {},
      timeout: { request: 30000 },
    });
    const data = JSON.parse(resp.body);
    if (data.code === '000') {
      log(`[业务] 💰 熊猫币: ${data.data?.pointsVal}, 优惠券: ${data.data?.couponNum}张, 等级: ${data.data?.level}`);
      return data.data;
    }
  } catch (e) {
    log(`[业务] 查询积分失败（可忽略）: ${e.message}`);
  }
  return null;
}

// 日期解析
function parseDateTime(str) {
  // 格式: 20260511000000
  const s = str.replace(/(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/, '$1-$2-$3 $4:$5:$6');
  return new Date(s);
}

// ============ 主流程 ============

async function runAccount(openid) {
  log(`\n========== 账号 ${openid} 开始 ==========`);

  let code;
  try {
    // Step 1: 通过 WCS 获取 code
    code = await wxCode(openid);
  } catch (e) {
    log(`❌ WCS 获取 code 失败: ${e.message}`);
    return;
  }

  let csession;
  try {
    // Step 2: 用 code 换 CSESSION token
    csession = await decryptCode(code);
  } catch (e) {
    log(`❌ 获取 CSESSION 失败: ${e.message}`);
    await wxClose(openid);
    return;
  }

  try {
    // Step 3: 查询签到活动
    await querySignInDetail(csession);

    // Step 4: 执行签到
    await doSignIn(csession);

    // Step 5: 查询积分
    await queryAssets(csession);

  } catch (e) {
    log(`❌ 业务操作失败: ${e.message}`);
  } finally {
    // Step 6: 关闭 WCS 会话
    await wxClose(openid);
  }

  log(`========== 账号 ${openid} 结束 ==========\n`);
}

async function main() {
  log('🧋 茶百道签到 - WCS 版');
  log('====================================');

  // 检查环境变量
  if (!getEnv('wx_server_url') || !getEnv('wx_auth')) {
    console.error('❌ 缺少必要环境变量: wx_server_url, wx_auth');
    process.exit(1);
  }

  const accounts = getAccounts('CBD');
  if (accounts.length === 0) {
    console.error('❌ 缺少环境变量: CBD（茶百道 openid）');
    process.exit(1);
  }

  log(`共 ${accounts.length} 个账号`);

  for (const openid of accounts) {
    await runAccount(openid);
    if (accounts.length > 1) {
      await delay(3000); // 多账号间隔3秒
    }
  }

  log('🧋 全部账号处理完毕');
}

main().catch(e => {
  console.error('脚本异常退出:', e);
  process.exit(1);
});
