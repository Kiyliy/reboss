# reboss：BOSS 网页接口与登录适配器

参照 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 的编排、API、认证、请求构建和 HTTP 客户端分层，独立实现 BOSS 网页端适配。本人正常 App 扫码、客户端凭据交接、账号核验和跨进程复核已在一次真实流程中通过；这不代表手机号、微信、全部业务接口或完整浏览器环境已经跑通。

## 动态校验尚未通过

一次已登录职位搜索仍返回 HTTP 200、业务码 **37**，没有取得职位结果；客户端当场停止，没有重试。`traceId` 已按源码补入并通过离线输入对照，但 `__zp_stoken__` 的有效生成及服务端接受仍未完成，不能把接口数量、登录成功或离线测试称为核心算法已解决。

本次已取得官方安全页和响应指定的动态脚本，确认当前 code 37 是安全页流程，而不是简单的请求头重新赋值。[安全控制器](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)、[官方安全页](https://www.zhipin.com/web/passport/zp/security.html) 详细来源、实际脚本哈希、分析限制和验收缺口见 `docs/SECURITY_PROTOCOL.md` 与 `reports/security-current.json`。

## 当前交付

| 项目 | 实际范围 |
| --- | --- |
| 接口目录 | 387 个去重路径，全部提供分组命名入口；306 个有方法证据，81 个方法未知 |
| 浏览器观察 | 18 个 API 路径曾在匿名浏览器发出请求，不等于业务成功 |
| 请求构建 | 253 个路径有主站来源依据；动态路径、未知方法、未知来源和未知编码默认阻止执行 |
| 登录 | App 扫码、微信小程序扫码、手机号四组验证类型的分版本请求构建、凭据交接及账号复核 |
| 业务接口 | 职位搜索、详情、筛选条件、账号状态与显式退出；其他目录条目通过通用分组适配器访问 |
| 离线测试 | 216 项 Python 测试、10 项 JavaScript AST/作用域测试、3 项 traceId 与 4 项局部编码测试通过；不证明业务接口已成功 |
| 核心入口分析 | `ABC.z` 静态绑定到本次脚本分派状态 6375；bootstrap 分析器 19 项合成测试和 1 项本地原文件检查通过，未执行或还原完整动态算法 |
| 局部计算 | 五段独立纯值模型：UTF-16 单元、加 3 后异或、偏移变换、数值编码、字节数组 Base64；不含完整输入包和有效令牌生成 |
| 真实 App 扫码 | 本人手机确认后，`dispatcher` 和 `getUserInfo` 均为 HTTP 200、业务码 0，账号标识有效 |
| 登录态复用 | 私有状态保存后，新进程重新查询账号，状态为 `VERIFIED`；不表示已测出有效期 |
| 真实 cURL 对照 | 匿名浏览器账号响应为 62 字节、code 7；已登录 HTTP 适配器响应为 615 字节、code 0，两次各自的状态、JSON、UTF-8 正文均匹配 |
| 职位实测 | 账号查询 code 0 后，一次搜索 code 37；未取得职位结果，未请求详情，未重试 |
| 尚未验收 | 动态 stoken、真实手机号与微信登录、成功职位查询、退出的服务端撤销、全部接口运行结果及浏览器完整等价 |

接口范围仅来自本次取得的公开发布脚本与匿名抓包，核心映射依据为[职位 SPA 业务模块](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)、[独立登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)和[职位 SPA 登录组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js)。完整条目、来源 URL、方法依据和未知项分别记录在 `docs/API_COVERAGE.md`、`catalog/api_registry.json` 与 `docs/EVIDENCE.md`。

## 安装与默认离线使用

以 Python 3.12、Node 22 为本次验证环境，依赖版本固定在仓库中。日常 Python 调用不需要安装 Node；Node 依赖只用于可选的公开 JavaScript 静态分析。

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python main.py
python main.py catalog
python main.py catalog --endpoint /wapi/zpgeek/search/joblist.json
python main.py job-preview --query Python
python -m unittest discover -s tests -v
python tools/check_framework.py --report reports/expanded-checks.json

# 可选的 AST 分析依赖和离线测试
npm install --ignore-scripts
npm run test:ast
npm run test:trace-id
npm run test:security-static
npm run test:security-codec
```

`status`、`catalog`、`job-preview` 都不联网。请求预览仅显示路径、方法、字段名称、正文长度和审批要求，不打印手机号、验证码、查询值或会话材料。

## 目录与接口调用

```text
main.py                         Data_Spider 编排和默认离线 CLI
boss_apis/surface_api.py         387 条路径的分组命名入口，默认只构建请求
boss_apis/phone_login_api.py     分版本 SMS 流程与显式身份确认
boss_apis/login_api.py           App 扫码观察器
boss_apis/qr_login_api.py        App / 小程序交接与登录后复核
boss_apis/jobs_api.py            职位搜索、详情、筛选条件
boss_apis/account_api.py         显式退出与当前客户端复核
builder/                        CookieJar、头、参数、表单、加密、请求审批
builder/trace_id.py              SPA 请求标识的源码辅助实现，不是 stoken
builder/security_codec.py        五段局部计算模型，不是完整安全 Cookie 生成器
utils/                          有限 HTTP 传输、操作策略、私有状态持久化
tools/                          被动 CDP 捕获、目录发现、AST 提取、cURL 对照
tools/analyze_security_bootstrap.mjs  固定哈希动态脚本的初始化绑定检查，不执行脚本
catalog/                        候选路径、静态调用契约和最终注册表
tests/                          全部为离线夹具，不发送真实短信
docs/                           协议、用法、架构、覆盖表和验证台账
reports/                        不含会话值的实际检查记录
```

下面的示例只生成请求，不访问 BOSS。获取真实响应需要显式启用网络，并且会改变状态的操作还需要对具体请求的独立确认。

```python
from builder.auth import BossAuth
from boss_apis.surface_api import BossSurface
from boss_apis.jobs_api import JobsAPI

with BossAuth() as auth:
    api = BossSurface(auth)
    print(api.summary())
    print(api.geek.search_joblist.describe())
    plan = JobsAPI(auth).search("Python", page=1, page_size=15)
    print(plan.preview())
```

分组入口不代表完整参数 schema 已恢复。`ContractIncomplete` 是有意保留的边界，不能通过猜测 HTTP 方法、补造安全字段或把所有 GET 当作只读来绕开。

## 登录流程

登录协议与库调用示例见 `docs/LOGIN_PROTOCOL.md` 和 `docs/USAGE.md`。当前已有一次本人正常 App 扫码的成功记录，每次新的登录仍需本人完成官方确认及新的账号复核，不能复用报告中的成功状态代替验证。

- **App 扫码**：创建官方挑战，观察扫描与手机确认，显式执行 `dispatcher`，再调用账号接口；原始 `qrId` 与第二阶段标识不可互换。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)
- **微信小程序**：使用 `shortRandKey` 获取小程序码、观察扫描、执行 `loginConfirm`，不是通用微信 OAuth 的重建。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)
- **手机号**：明确选择 `sign_v5333` 或 `geek_spa_v6763`，使用官方 SDK 的真实验证结果；两个构建版本的短信 token、`version` 和登录建议流程不同。[独立登录版本](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)、[SPA 登录版本](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js)
- **Type 2**：隐式凭据传递方式尚未核验，允许查看请求契约，但专用手机号执行器阻止该分支联网；不补造 `sig`、`nc_token` 等值。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)

扫码观察 CLI 如下，只创建挑战和观察状态，不自动兑换登录凭据。二维码与状态文件必须是新路径，不能覆盖正在使用的挑战。

```bash
python main.py qr-create --live \
  --state evidence/private/qr-new.json \
  --image evidence/private/qr-new.png
python main.py qr-watch --live \
  --state evidence/private/qr-new.json --seconds 90
```

初始扫码观察采用发布组件的 30 秒前端等待窗口，不是实测服务端 TTL；超过窗口后应由用户明确决定是否重新创建挑战。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) `qr-watch` 的总观察上限为 90 秒，扫码确认之后的交接需要另外调用 `QRLoginAPI.exchange`。

本次实际观察器先发生读取超时，用户随后报告已确认，于是显式补查一次 `scanLogin`，取得真实服务端确认后才兑换凭据。这不是自动重试或把用户回复当作服务端成功，恢复方法也不允许对风控停止继续尝试。

```bash
# 仅在本人已确认登录这台客户端之后运行。
python tools/complete_qr_login.py \
  --state evidence/private/qr-new.json \
  --private-dir evidence/private/qr-exchange-new \
  --auth-output evidence/private/auth-new.json \
  --report reports/qr-login-new.json \
  --approve-exchange
# 若观察器仅因读取超时/等待窗口结束停下，且本人已确认，可额外显式加：
# --recheck-confirmation
```

工具从当前正常入口 HTML 提取页面 key，最多做一次正常交接，再核验账号。它不会生成假指纹或安全 Cookie，完整响应与 Cookie 只保存在私有捕获目录。

## 有限职位诊断

`tools/probe_jobs.py` 先核验当前账号，再请求一页搜索；仅在显式开启详情且真实结果带有所需标识时，才请求一个详情。遇验证、业务失败或未认识的响应结构立即停止；目前 `reports/jobs-current.json` 记录的是 code 37 失败路径，不是可用的职位采集器。

```bash
# 仅在正常浏览器流程已完成、当前会话适合继续验证时使用。
# 不要为了尝试绕过本次 code 37 而循环运行。
python tools/probe_jobs.py --live \
  --state evidence/private/auth-new.json \
  --private-dir evidence/private/jobs-new \
  --report reports/jobs-new.json --query Python
# 可选 --include-detail，最多使用真实首条结果查询一个详情。
```

当前职位请求规划会使用已审阅的 `geek_spa_v6763` traceId profile，仍使用诊断 UA，不宣称完整浏览器等价。新增 traceId 后没有重试本次风险请求，不能由此声称已经消除 code 37。

## 抓包与 cURL 对照

`tools/capture_cdp.mjs` 对已授权、已打开的 BOSS 浏览器页面进行被动网络记录，不替用户点击、导航或登录。原始请求、响应、Cookie 和 QR 标识只能保留在私有目录，不能提交到仓库。

```bash
python tools/replay_capture.py evidence/private/request.json \
  --private-dir evidence/private/replay-new \
  --report reports/replay-current.json
# 确认目标是允许重放的只读请求后，增加 --execute 才会实际重放一次。
```

重放工具保留捕获到的原始 query、普通头与空头，不把字典化的请求头说成完整线序捕获。目前主站允许重放的 API 仅为已确认的 `getUserInfo.json`；`dispatcher` 等改变状态的 GET 不进入这条只读重放路径。

匿名对照见 `reports/replay-jobs-user-info.json`：HTTP 200、业务码 7，JSON 与 62 字节 UTF-8 正文一致。已登录对照见 `reports/replay-authenticated-user-info.json`：HTTP 200、业务码 0，JSON 与 615 字节 UTF-8 正文一致，原请求来自 HTTP 适配器而非浏览器。

`verified_equivalent` 仅表示该次 HTTP 状态与解码正文比较通过，不表示 TLS 指纹、HTTP/2 帧、压缩字节、全部请求或登录生命周期相同。`main.py` 展示的历史成功也不代表运行它的当前客户端已经登录。

## 隐私、确认和限制

- **环境**：本次代码和验证在云端 Linux 完成，没有修改用户本地 Windows。
- **默认离线**：`BossAuth()` 不允许网络；需显式 `live=True` 或注入本地 MockTransport。
- **精确确认**：发送短信、最终登录、退出、资料修改等必须有绑定该请求的 `ActionApproval`；它只是防误操作机制，不是用户授权或身份核验的替代品。
- **凭据保护**：Cookie 保留 domain、path、secure、expires 等属性；加载历史状态不会直接认定账号仍有效，必须重新查询账号。
- **发布范围**：不提交 PAT、密码、手机号、验证码、原始抓包、QR 图片、浏览器资料、BOSS 发布脚本或参考仓库源码。
- **停止条件**：验证、风控、未知身份、额外安全确认或异常响应均停止，不自动破解、轮换账号、重试或提交申请。

本项目只用于本人账号和获准访问范围内的协议兼容研究。目录中的消息、简历或资料类路径不代表已经执行过这些操作，也不是默认授权批量调用。
