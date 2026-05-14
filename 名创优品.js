/**
 * 名创优品小程序签到及任务自动化脚本
 * 用于青龙面板定时执行
 * 
 * ━━━━━━━━━━━━ Token 获取方法 ━━━━━━━━━━━━
 * 
 * 1. 打开 Fatbeans/Charles/Fiddler 等抓包工具
 * 2. 在微信中打开「名创优品」小程序，进入潮玩签到页面
 * 3. 在抓包工具中搜索 miniso，找到任意 API 请求，推荐抓：
 *    - api-saas.miniso.com/task-manage-platform/api/virtualCoin/member
 *    - api-saas.miniso.com/task-manage-platform/api/activity/signInTask/taskDetail
 * 4. 点进请求详情 → 查看请求头(Request Headers)
 * 5. 找到以下字段，按格式拼接：
 *    content-openid → openid
 *    content-unionid → unionid
 *    content-skey → skey
 *    content-uid → uid
 * 6. 格式: openid#unionid#skey@uid@phone@storeid
 *    多账号用 | 分隔
 * 
 * ⚠️ skey 会过期，过期标志：接口返回"暂未登录或token认证不通过"
 * ⚠️ 过期后需重新抓包获取
 * 
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 
 * 环境变量：
 *   MINISO_TOKENS - 多账号配置，格式: openid#unionid#skey@uid@phone@storeid
 *                   多账号用 | 分隔
 */

const axios = require('axios');
const CryptoJS = require('crypto-js');
const { sendNotify } = require('./sendNotify');

// ============ 通知消息收集 ============
const notifyMsg = [];

class MinisoBot {
  constructor(config) {
    this.headers = {
      'host': 'api-saas.miniso.com',
      'content-pagetype': '%E6%BD%AC%E7%8E%A9%E7%AD%BE%E5%88%B0%E9%A1%B5%E9%9D%A2',
      'x-mi-store-id': config.storeId || 'Z6XV',
      'xweb_xhr': '1',
      'content-sceneid': '1256',
      'content-type': 'application/json',
      'content-weappcode': '52',
      'tenant-code': 'MINISO',
      'content-appcode': '51',
      'content-pagename': '%E6%BD%AC%E7%8E%A9%E7%AD%BE%E5%88%B0%E9%A1%B5%E9%9D%A2',
      'tenant': 'MINISO',
      'x-mi-version': '5.1.64',
      'x-client-source': 'MINISO_WX_MINI',
      'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254181d) XWEB/19339',
      'version': 'storeexpress1.0',
      'accept': '*/*',
      'sec-fetch-site': 'cross-site',
      'sec-fetch-mode': 'cors',
      'sec-fetch-dest': 'empty',
      'referer': 'https://servicewechat.com/wx2a212470bade49bf/1084/page-frame.html',
      'accept-encoding': 'gzip, deflate, br',
      'accept-language': 'zh-CN,zh;q=0.9',
      'priority': 'u=1, i',
      'can-flash-send': 'true'
    };

    this.skey = config.skey;
    this.openid = config.openid;
    this.unionid = config.unionid;
    this.uid = config.uid;
    this.phone = config.phone;
    this.storeId = config.storeId || 'Z6XV';

    // 结果统计
    this.result = {
      signIn: null,        // null=未执行, true=成功, false=失败
      signInDays: 0,
      tasksDone: 0,
      tasksFailed: 0,
      tasksSkipped: 0,
      coinBefore: null,
      coinAfter: null,
      coinGain: 0,
      errors: [],
      tokenExpired: false,
    };

    this.updateHeaders();
  }

  updateHeaders() {
    this.headers['content-skey'] = this.skey;
    this.headers['content-openid'] = this.openid;
    this.headers['content-unionid'] = this.unionid;
    this.headers['content-uid'] = this.uid;
    this.headers['content-latitude'] = '[object Undefined]';
    this.headers['content-longitude'] = '[object Undefined]';
    this.headers['x-mi-city'] = '';
    this.headers['x-mi-store-id'] = this.storeId;
  }

  generateSignature(dataStr) {
    return this.md5(dataStr);
  }

  md5(str) {
    return CryptoJS.MD5(str).toString().toUpperCase();
  }

  getTimestamp() {
    return Date.now();
  }

  generateNonce() {
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    let result = '';
    for (let i = 0; i < 32; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
  }

  updateRequestHeaders(headers) {
    const timestamp = this.getTimestamp();
    const nonce = this.generateNonce();
    headers['time'] = timestamp;
    headers['nonce'] = nonce;
    return { headers, timestamp, nonce };
  }

  // 检测 token 过期
  checkTokenExpired(response) {
    const msg = response.data?.message || response.data?.msg || '';
    if (msg.includes('暂未登录') || msg.includes('token认证不通过') || msg.includes('登录过期')) {
      this.result.tokenExpired = true;
      return true;
    }
    return false;
  }

  async getVirtualCoinInfo() {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      reqData.headers['signature'] = this.md5('virtualCoinMember' + reqData.timestamp + reqData.nonce);
      const response = await axios.get(
        'https://api-saas.miniso.com/task-manage-platform/api/virtualCoin/member',
        { headers: reqData.headers }
      );
      if (response.data.code === 200) {
        console.log(`  mini币余额: ${response.data.data.quantity}`);
        return response.data.data;
      } else {
        console.log(`  ✗ 获取虚拟币失败: ${response.data.message}`);
        this.checkTokenExpired(response);
        return null;
      }
    } catch (error) {
      console.log(`  ✗ 获取虚拟币出错: ${error.message}`);
      return null;
    }
  }

  async getSignInTaskDetail(activityId = 18) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      reqData.headers['signature'] = this.md5('signInTaskDetail' + activityId + reqData.timestamp + reqData.nonce);
      const response = await axios.get(
        `https://api-saas.miniso.com/task-manage-platform/api/activity/signInTask/taskDetail?activityId=${activityId}`,
        { headers: reqData.headers }
      );
      if (response.data.code === 200) {
        const taskData = response.data.data;
        console.log(`  连续签到 ${taskData.signInFinishDays} 天，今日: ${taskData.todaySignInFinishFlag ? '✅已签' : '❌未签'}`);
        return taskData;
      } else {
        console.log(`  ✗ 获取签到详情失败: ${response.data.message}`);
        this.checkTokenExpired(response);
        return null;
      }
    } catch (error) {
      console.log(`  ✗ 获取签到详情出错: ${error.message}`);
      return null;
    }
  }

  async completeSignIn(taskId, activityId = 18) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      const body = { activityId: String(activityId), taskId: taskId };
      reqData.headers['signature'] = this.md5(JSON.stringify(body) + reqData.timestamp + reqData.nonce);

      const response = await axios.post(
        'https://api-saas.miniso.com/task-manage-platform/api/activity/signInTask/award/receive',
        body,
        { headers: reqData.headers }
      );

      if (response.data.code === 200) {
        return true;
      } else {
        console.log(`  ✗ 签到失败: ${response.data.message}`);
        this.checkTokenExpired(response);
        return false;
      }
    } catch (error) {
      console.log(`  ✗ 签到出错: ${error.message}`);
      return false;
    }
  }

  async getPeriodTaskList(activityId = 18) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      const url = `https://api-saas.miniso.com/task-manage-platform/api/activity/periodTask/taskDetail?activityId=${activityId}&unionId=${this.unionid}`;
      reqData.headers['signature'] = this.md5('periodTaskList' + activityId + this.unionid + reqData.timestamp + reqData.nonce);
      const response = await axios.get(url, { headers: reqData.headers });
      if (response.data.code === 200 && response.data.success) {
        const periods = response.data.data;
        let allTasks = [];
        for (const period of periods) {
          if (period.periodTasks && Array.isArray(period.periodTasks)) {
            allTasks = allTasks.concat(period.periodTasks);
          }
        }
        console.log(`  发现 ${allTasks.length} 个每日任务`);
        return { periods, periodTasks: allTasks };
      } else {
        console.log(`  ✗ 获取任务列表失败: ${response.data.message || response.data.msg || '未知错误'}`);
        this.checkTokenExpired(response);
        return null;
      }
    } catch (error) {
      console.log(`  ✗ 获取任务列表出错: ${error.message}`);
      return null;
    }
  }

  async completeTask(taskId, taskType, activityId = 18) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      const dataStr = JSON.stringify({ activityId, taskId, taskType });
      reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
      const response = await axios.post(
        'https://api-saas.miniso.com/task-manage-platform/api/activity/task/finish',
        { activityId, taskId, taskType },
        { headers: reqData.headers }
      );
      if (response.data.code === 200) {
        return true;
      } else {
        this.checkTokenExpired(response);
        return false;
      }
    } catch (error) {
      return false;
    }
  }

  async completeBrowseTask(taskId, activityId = 18) {
    try {
      const browseHeaders = {
        'host': 'api.multibrands.miniso.com',
        'content-pagetype': '%E8%90%BD%E5%9C%B0%E9%A1%B5',
        'can-flash-send': 'true',
        'x-mi-store-id': this.headers['x-mi-store-id'],
        'xweb_xhr': '1',
        'content-sceneid': '1256',
        'content-type': 'application/json',
        'content-weappcode': '52',
        'tenant-code': 'MINISO',
        'content-openid': this.headers['content-openid'],
        'content-latitude': '[object Undefined]',
        'content-appcode': '51',
        'x-mi-city': '',
        'content-pagename': '%E8%90%BD%E5%9C%B0%E9%A1%B5',
        'content-unionid': this.headers['content-unionid'],
        'tenant': 'MINISO',
        'x-mi-version': '5.1.64',
        'x-client-source': 'MINISO_WX_MINI',
        'content-longitude': '[object Undefined]',
        'content-uid': this.headers['content-uid'],
        'user-agent': this.headers['user-agent'],
        'content-skey': this.headers['content-skey'],
        'version': 'storeexpress1.0',
        'accept': '*/*',
        'sec-fetch-site': 'cross-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://servicewechat.com/wx2a212470bade49bf/1084/page-frame.html',
        'accept-encoding': 'gzip, deflate, br',
        'accept-language': 'zh-CN,zh;q=0.9',
        'priority': 'u=1, i'
      };
      const timestamp = this.getTimestamp();
      const nonce = this.generateNonce();
      browseHeaders['time'] = timestamp;
      browseHeaders['nonce'] = nonce;
      browseHeaders['content-nonce'] = timestamp + 1;
      browseHeaders['signature'] = this.md5('browseTask' + taskId + timestamp + nonce);
      browseHeaders['content-sign'] = this.md5('browseTask' + taskId + (timestamp + 1) + nonce);

      const response = await axios.post(
        'https://api.multibrands.miniso.com/multi-configure-platform/api/activity/task/browse/finish',
        { activityId, taskId },
        { headers: browseHeaders }
      );
      if (response.data.code === 200) {
        return true;
      } else {
        this.checkTokenExpired(response);
        return false;
      }
    } catch (error) {
      return false;
    }
  }

  async recordTaskUV(activityId, taskId, taskType = 1) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      const dataStr = JSON.stringify({ activityId, taskId, taskType });
      reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
      const response = await axios.post(
        'https://api-saas.miniso.com/task-manage-platform/api/activity/task/uvClick',
        { activityId, taskId, taskType },
        { headers: reqData.headers }
      );
      return response.data.code === 200;
    } catch (error) {
      return false;
    }
  }

  async receiveAward(taskId, activityId = 18) {
    try {
      let reqData = this.updateRequestHeaders({ ...this.headers });
      const dataStr = JSON.stringify({ activityId, taskId });
      reqData.headers['signature'] = this.md5(dataStr + reqData.timestamp + reqData.nonce);
      const response = await axios.post(
        'https://api-saas.miniso.com/task-manage-platform/api/activity/periodTask/award/receive',
        { activityId, taskId },
        { headers: reqData.headers }
      );
      if (response.data.code === 200) {
        const awardData = response.data.data;
        console.log(`    🎁 领取奖励: ${awardData.awardName}, ${awardData.awardDesc}`);
        return true;
      } else {
        this.checkTokenExpired(response);
        return false;
      }
    } catch (error) {
      return false;
    }
  }

  async performSignInTask() {
    console.log('→ 签到任务');

    const taskDetail = await this.getSignInTaskDetail();
    if (!taskDetail) {
      this.result.signIn = false;
      this.result.errors.push('签到: 获取详情失败');
      return;
    }

    if (taskDetail.todaySignInFinishFlag === 1) {
      console.log('  ✅ 今日已签到');
      this.result.signIn = true;
      this.result.signInDays = taskDetail.signInFinishDays;
      await this.recordTaskUV(18, taskDetail.taskId);
      return;
    }

    const nextDay = (taskDetail.signInFinishDays || 0) + 1;
    const result = await this.completeSignIn(taskDetail.taskId, 18);
    if (result) {
      console.log(`  ✅ 第 ${nextDay} 天签到成功`);
      this.result.signIn = true;
      this.result.signInDays = nextDay;
      await this.recordTaskUV(18, taskDetail.taskId);
    } else {
      this.result.signIn = false;
      this.result.errors.push(`签到: 第${nextDay}天失败`);
    }
  }

  async performDailyTasks() {
    console.log('→ 每日任务');

    // token 已过期则跳过，不浪费等待时间
    if (this.result.tokenExpired) {
      console.log('  ⏭️ Token已过期，跳过任务执行');
      return;
    }

    const periodTaskData = await this.getPeriodTaskList();
    if (!periodTaskData) {
      this.result.errors.push('任务: 获取列表失败');
      return;
    }

    const tasks = periodTaskData.periodTasks || [];

    for (const task of tasks) {
      // token 过期则提前退出
      if (this.result.tokenExpired) {
        this.result.tasksSkipped += tasks.length - tasks.indexOf(task);
        console.log('  ⏭️ Token已过期，跳过剩余任务');
        break;
      }

      if (task.periodFinishTimes >= task.periodAllowTimes) {
        // 已完成的任务尝试领奖
        if (task.buttonStatus !== 3) {
          console.log(`  🔄 ${task.taskName} (已完成，领奖)`);
          const received = await this.receiveAward(task.taskId, 18);
          if (received) this.result.tasksDone++;
        } else {
          console.log(`  ⏭️ ${task.taskName} (已完成)`);
          this.result.tasksSkipped++;
        }
        continue;
      }

      switch (task.taskType) {
        case 5:
          console.log(`  👀 ${task.taskName} (浏览${task.browseSeconds || 0}s)`);
          if (task.browseSeconds > 0) {
            await new Promise(resolve => setTimeout(resolve, task.browseSeconds * 1000));
          }
          await this.recordTaskUV(18, task.taskId, 5);
          const browseOk = await this.completeBrowseTask(task.taskId, 18);
          if (browseOk) {
            console.log(`    ✅ 浏览完成`);
            this.result.tasksDone++;
            await new Promise(resolve => setTimeout(resolve, 1000));
            await this.receiveAward(task.taskId, 18);
          } else {
            console.log(`    ❌ 浏览失败`);
            this.result.tasksFailed++;
            this.result.errors.push(`${task.taskName}: 浏览失败`);
          }
          break;
        case 2:
          console.log(`  📤 ${task.taskName} (分享，需手动)`);
          this.result.tasksSkipped++;
          break;
        case 3:
          console.log(`  👥 ${task.taskName} (加微信，需手动)`);
          this.result.tasksSkipped++;
          break;
        default:
          console.log(`  ⚙️ ${task.taskName} (类型${task.taskType})`);
          const genericOk = await this.completeTask(task.taskId, task.taskType);
          if (genericOk) {
            console.log(`    ✅ 完成`);
            this.result.tasksDone++;
            await new Promise(resolve => setTimeout(resolve, 1000));
            await this.receiveAward(task.taskId, 18);
          } else {
            console.log(`    ❌ 失败`);
            this.result.tasksFailed++;
            this.result.errors.push(`${task.taskName}: 执行失败`);
          }
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }

  async executeAllTasks() {
    console.log('→ 查询mini币余额');
    this.result.coinBefore = await this.getVirtualCoinInfo();

    await this.performSignInTask();
    await this.performDailyTasks();

    console.log('→ 查询mini币余额');
    this.result.coinAfter = await this.getVirtualCoinInfo();

    if (this.result.coinAfter && this.result.coinBefore) {
      this.result.coinGain = this.result.coinAfter.quantity - this.result.coinBefore.quantity;
    }
  }

  // 生成通知文本
  getNotifyText() {
    let lines = [];

    // 签到结果
    if (this.result.signIn === true) {
      lines.push(`签到: ✅ 已签到（连续${this.result.signInDays}天）`);
    } else if (this.result.signIn === false) {
      lines.push(`签到: ❌ 失败`);
    }

    // 任务结果
    if (this.result.tasksDone > 0 || this.result.tasksFailed > 0) {
      const parts = [];
      if (this.result.tasksDone > 0) parts.push(`✅${this.result.tasksDone}个`);
      if (this.result.tasksFailed > 0) parts.push(`❌${this.result.tasksFailed}个`);
      if (this.result.tasksSkipped > 0) parts.push(`⏭️${this.result.tasksSkipped}个跳过`);
      lines.push(`任务: ${parts.join(' ')}`);
    }

    // mini币
    if (this.result.coinAfter) {
      lines.push(`mini币: ${this.result.coinAfter.quantity}${this.result.coinGain > 0 ? ` (+${this.result.coinGain})` : ''}`);
    }

    // token 过期
    if (this.result.tokenExpired) {
      lines.push(`⚠️ TOKEN已过期，需重新抓取！`);
    }

    // 错误详情（最多5条）
    if (this.result.errors.length > 0) {
      const showErrors = this.result.errors.slice(0, 5);
      lines.push(`失败详情: ${showErrors.join('; ')}`);
      if (this.result.errors.length > 5) {
        lines.push(`  ...还有${this.result.errors.length - 5}条`);
      }
    }

    return lines.join('\n');
  }
}

function parseConfig(tokenString) {
  if (!tokenString) return [];
  const accounts = [];
  const tokens = tokenString.split('|');
  for (const token of tokens) {
    if (token.trim()) {
      const parts = token.split('@');
      const identifiers = parts[0].split('#');
      if (identifiers.length >= 3) {
        const account = {
          openid: identifiers[0],
          unionid: identifiers[1],
          skey: identifiers[2],
          uid: parts[1] || '',
          phone: parts[2] || '',
          storeId: parts[3] || 'Z6XV'
        };
        if (account.skey && account.openid && account.unionid) {
          accounts.push(account);
        }
      }
    }
  }
  return accounts;
}

async function main() {
  console.log('🛍️ 名创优品自动化脚本');

  const tokenString = process.env.MINISO_TOKENS;
  const accounts = parseConfig(tokenString);

  if (accounts.length === 0) {
    console.error('❌ 未配置有效的账户信息');
    console.error('   格式: openid#unionid#skey@uid@phone@storeid');
    await sendNotify('🛍️ 名创优品', '❌ 未配置账户信息');
    return;
  }

  console.log(`共 ${accounts.length} 个账户\n`);

  for (let i = 0; i < accounts.length; i++) {
    console.log(`═══ 账户 ${i + 1} ═══`);
    const bot = new MinisoBot(accounts[i]);
    await bot.executeAllTasks();
    
    // 收集通知
    const notifyText = bot.getNotifyText();
    notifyMsg.push(`【账户${i + 1}】\n${notifyText}`);
    
    console.log(`\n${notifyText}\n`);

    if (i < accounts.length - 1) {
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }

  // 发送汇总通知
  const title = '🛍️ 名创优品';
  const content = notifyMsg.join('\n\n');
  console.log('[通知] 发送通知...');
  await sendNotify(title, content);
}

module.exports = main;

if (require.main === module) {
  main().catch(err => {
    console.error('❌ 脚本异常:', err);
  });
}
