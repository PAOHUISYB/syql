/**
 * 茶百道签到 - Token 版（手动提供 CSESSION token 签到）
 * 青龙面板定时任务脚本
 * 
 * ━━━━━━━━━━━━ Token 获取方法 ━━━━━━━━━━━━
 * 
 * 1. 打开 Fatbeans/Charles/Fiddler 等抓包工具
 * 2. 在微信中打开「茶百道饮品点单」小程序，随便浏览一下
 * 3. 在抓包工具中搜索 shuxinyc，找到任意 API 请求（非图片/CDN），
 *    推荐抓这几个（返回数据小，好找）：
 *    - apisix-gateway-pro.shuxinyc.com/applet/v2/decrypt  ← code换token的接口
 *    - chabaidao-gateway2.shuxinyc.com/member2c/applet/head/assets
 *    - md-h5-gateway.shuxinyc.com/marketing/minip/activity/queryDetail
 * 4. 点进请求详情 → 查看请求头(Request Headers)
 * 5. 找到 CSESSION 字段，复制完整值，格式如下：
 *    1778734046|f8VbnmhQYwrMRMTH.1CPjraBqOzAJWJYlwRPUX7lY/Aji/674rXg0iQLsu45p2m8IWvZwTvd8ECyzxaJClD6lQH7ehmrEqHR27j4jTw==.6b8b9f894dc99def
 * 6. 填入青龙面板环境变量 CBD_TOKEN
 * 
 * ⚠️ CSESSION 有效期几小时~几天不等，过期后需重新抓取
 * ⚠️ 过期标志：接口返回 401/unauthorized 或 code=501040048 频繁操作
 * 
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 
 * 环境变量：
 *   CBD_TOKEN  - 茶百道 CSESSION token，多账号用 # 或 , 分隔（必填）
 * 
 * 定时规则建议：30 10 * * *（每天 10:30，签到活动 10:00 开始）
 * 
 * 流程：
 *   1. POST /marketing/minip/activity/queryDetail → 查询签到活动信息
 *   2. POST /marketing/minip/activity/join/signIn → 执行签到
 *   3. POST /member2c/applet/head/assets → 查询积分余额
 */

const got = require('got');

// ============ 配置 ============
const APPID = 'wx2804355dbf8d15c3';
const PAGE_FRAME_VERSION = '1143';

// 业务 API 域名
const MARKETING_GATEWAY = 'https://md-h5-gateway.shuxinyc.com';
const MEMBER_GATEWAY = 'https://chabaidao-gateway2.shuxinyc.com';

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

const delay = ms => new Promise(r => setTimeout(r, ms));

// ============ 通用请求头 ============

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823';

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

// ============ 业务 API ============

/**
 * 查询签到活动详情
 */
async function querySignInDetail(csession) {
  log(`[查询] 获取签到活动信息...`);
  const resp = await got.post(`${MARKETING_GATEWAY}/marketing/minip/activity/queryDetail`, {
    headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'),
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
    if (data.code === '501040048') {
      throw new Error('TOKEN_EXPIRED: 请勿频繁操作（可能 token 过期）');
    }
    throw new Error(`查询签到活动失败: code=${data.code}, msg=${data.msg}`);
  }

  const detail = data.data?.signInDetail;
  if (!detail) {
    throw new Error('签到活动详情为空');
  }

  log(`[查询] 当前活动: ${detail.name}`);
  log(`[查询] 活动时间: ${detail.startTime} ~ ${detail.endTime}`);

  // 提取签到状态
  if (detail.signInRecordList) {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const signed = detail.signInRecordList.some(r => r.signDate === today);
    if (signed) {
      log(`[查询] 今日已签到 ✓`);
      return { detail, alreadySigned: true };
    }
  }

  return { detail, alreadySigned: false };
}

/**
 * 执行签到
 */
async function doSignIn(csession, businessId) {
  log(`[签到] 执行签到...`);
  const resp = await got.post(`${MARKETING_GATEWAY}/marketing/minip/activity/join/signIn`, {
    headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'),
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
    log(`[签到] ✅ 签到成功！日期: ${data.data?.signDate}`);

    // 打印奖励详情
    if (data.data?.marketingGiftConfCOList) {
      for (const gift of data.data.marketingGiftConfCOList) {
        if (gift.giftList) {
          for (const g of gift.giftList) {
            if (g.giftType === 3) {
              log(`[签到] 🪙 获得 ${g.point} 熊猫币`);
            } else if (g.giftType === 1) {
              log(`[签到] 🎟️ 获得优惠券 (batchId: ${g.couponBatchId})`);
            }
          }
        }
      }
    }
    return { success: true, data };
  } else if (data.code === '501040048') {
    log(`[签到] ⚠️ 已签到过或操作频繁: ${data.msg}`);
    return { success: false, alreadySigned: true, data };
  } else {
    throw new Error(`签到失败: code=${data.code}, msg=${data.msg}`);
  }
}

/**
 * 查询签到奖励记录
 */
async function queryPrizeRecord(csession, businessId) {
  try {
    log(`[查询] 获取签到奖励记录...`);
    const resp = await got.post(`${MARKETING_GATEWAY}/marketing/minip/activity/member/prize/record`, {
      headers: makeHeaders(csession, 'md-h5-gateway.shuxinyc.com'),
      json: {
        activityId: '',
        businessId: businessId || DEFAULT_BUSINESS_ID,
        queryCurrentNew: true,
      },
      timeout: { request: 30000 },
    });
    const data = JSON.parse(resp.body);
    if (data.code === 200 || data.code === '000') {
      const name = data.data?.name || '';
      const gifts = data.data?.receiveGiftList || [];
      if (gifts.length > 0) {
        log(`[查询] 📋 活动名: ${name}`);
        for (const g of gifts) {
          if (g.couponData) {
            for (const c of g.couponData) {
              log(`[查询]   - ${c.couponName} (${c.effectTimeStart} ~ ${c.effectTimeEnd})`);
            }
          }
        }
      }
    }
  } catch (e) {
    log(`[查询] 奖励记录查询失败（可忽略）: ${e.message}`);
  }
}

/**
 * 查询积分余额
 */
async function queryAssets(csession) {
  try {
    const resp = await got.post(`${MEMBER_GATEWAY}/member2c/applet/head/assets`, {
      headers: makeHeaders(csession, 'chabaidao-gateway2.shuxinyc.com'),
      json: {},
      timeout: { request: 30000 },
    });
    const data = JSON.parse(resp.body);
    if (data.code === '000') {
      log(`[查询] 💰 熊猫币: ${data.data?.pointsVal}, 优惠券: ${data.data?.couponNum}张, 等级: ${data.data?.level}`);
      return data.data;
    }
  } catch (e) {
    log(`[查询] 积分查询失败（可忽略）: ${e.message}`);
  }
  return null;
}

// ============ 主流程 ============

async function runAccount(token, index) {
  const tokenPreview = token.substring(0, 20) + '...';
  log(`\n========== 账号 ${index + 1} (${tokenPreview}) 开始 ==========`);

  try {
    // Step 1: 查询签到活动
    const { detail, alreadySigned } = await querySignInDetail(token);

    // Step 2: 执行签到
    if (alreadySigned) {
      log(`今日已签到，跳过`);
    } else {
      await doSignIn(token, detail?.groupId ? undefined : DEFAULT_BUSINESS_ID);
    }

    // Step 3: 查询奖励记录
    await queryPrizeRecord(token);

    // Step 4: 查询积分
    await queryAssets(token);

  } catch (e) {
    if (e.message.includes('TOKEN_EXPIRED') || e.message.includes('401') || e.message.includes('unauthorized')) {
      log(`❌ Token 已过期！请重新抓包获取 CSESSION，更新 CBD_TOKEN 环境变量`);
    } else {
      log(`❌ 操作失败: ${e.message}`);
    }
  }

  log(`========== 账号 ${index + 1} 结束 ==========\n`);
}

async function main() {
  log('🧋 茶百道签到 - Token 版');
  log('====================================');

  const tokens = getAccounts('CBD_TOKEN');
  if (tokens.length === 0) {
    console.error('❌ 缺少环境变量: CBD_TOKEN（茶百道 CSESSION token）');
    console.error('   获取方式：用抓包工具抓取茶百道小程序请求，从 Header 中复制 CSESSION 值');
    console.error('   示例格式：1778734046|f8VbnmhQYwrMRMTH.xxx.6b8b9f894dc99def');
    process.exit(1);
  }

  log(`共 ${tokens.length} 个账号`);

  for (let i = 0; i < tokens.length; i++) {
    await runAccount(tokens[i], i);
    if (tokens.length > 1) {
      await delay(2000); // 多账号间隔2秒
    }
  }

  log('🧋 全部账号处理完毕');
}

main().catch(e => {
  console.error('脚本异常退出:', e);
  process.exit(1);
});
