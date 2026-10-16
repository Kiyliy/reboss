# reboss：BOSS 网页接口与登录适配器

参照 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 的编排、API、认证、请求构建和 HTTP 客户端分层，独立实现 BOSS 网页端适配。当前交付包含可运行代码、证据化接口目录、正常登录状态机和脱敏验证记录；不宣称全站接口或真实账号全流程已经跑通。

## 当前交付

| 项目 | 实际范围 |
| --- | --- |
| 接口目录 | 387 个去重路径，全部提供分组命名入口；306 个有方法证据，81 个方法未知 |
| 浏览器观察 | 18 个 API 路径曾在匿名浏览器发出请求，不等于业务成功 |
| 请求构建 | 253 个路径有主站来源依据；动态路径、未知方法、未知来源和未知编码默认阻止执行 |
| 登录 | App 扫码、微信小程序扫码、手机号四组验证类型的分版本请求构建、凭据交接及账号复核 |
| 业务接口 | 职位搜索、详情、筛选条件、账号状态与显式退出；其他目录条目通过通用分组适配器访问 |
| 离线测试 | 169 项 Python 测试、10 项 JavaScript AST/作用域测试通过 |
| 真实 cURL 对照 | 一次匿名账号接口：HTTP 状态、JSON、解码后 UTF-8 正文相同；返回业务码 7，仍未登录 |
| 尚未验收 | 真实手机号登录、扫码后账号登录、登录后职位查询、退出的服务端撤销、全部接口运行结果 |

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
utils/                          有限 HTTP 传输、操作策略、私有状态持久化
tools/                          被动 CDP 捕获、目录发现、AST 提取、cURL 对照
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

登录协议与完整库调用示例见 `docs/LOGIN_PROTOCOL.md` 和 `docs/USAGE.md`。当前代码已包含正常凭据交接，但真实成功仍需要本人完成官方验证、手机确认和后续账号接口复核。

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

## 抓包与 cURL 对照

`tools/capture_cdp.mjs` 对已授权、已打开的 BOSS 浏览器页面进行被动网络记录，不替用户点击、导航或登录。原始请求、响应、Cookie 和 QR 标识只能保留在私有目录，不能提交到仓库。

```bash
python tools/replay_capture.py evidence/private/request.json \
  --private-dir evidence/private/replay-new \
  --report reports/replay-current.json
# 确认目标是允许重放的只读请求后，增加 --execute 才会实际重放一次。
```

重放工具保留捕获到的原始 query、普通头与空头，不把字典化的请求头说成完整线序捕获。目前主站允许重放的 API 仅为已确认的 `getUserInfo.json`；`dispatcher` 等改变状态的 GET 不进入这条只读重放路径。

最新匿名对照见 `reports/replay-jobs-user-info.json`：响应正文可用，HTTP 200、JSON 与 62 字节 UTF-8 正文一致，但业务码为 7。这里的 `verified_equivalent` 仅表示该次 HTTP 状态与解码正文比较通过，不表示 TLS 指纹、HTTP/2 帧、压缩字节、全部请求或登录生命周期相同。

## 隐私、确认和限制

- **环境**：本次代码和验证在云端 Linux 完成，没有修改用户本地 Windows。
- **默认离线**：`BossAuth()` 不允许网络；需显式 `live=True` 或注入本地 MockTransport。
- **精确确认**：发送短信、最终登录、退出、资料修改等必须有绑定该请求的 `ActionApproval`；它只是防误操作机制，不是用户授权或身份核验的替代品。
- **凭据保护**：Cookie 保留 domain、path、secure、expires 等属性；加载历史状态不会直接认定账号仍有效，必须重新查询账号。
- **发布范围**：不提交 PAT、密码、手机号、验证码、原始抓包、QR 图片、浏览器资料、BOSS 发布脚本或参考仓库源码。
- **停止条件**：验证、风控、未知身份、额外安全确认或异常响应均停止，不自动破解、轮换账号、重试或提交申请。

本项目只用于本人账号和获准访问范围内的协议兼容研究。目录中的消息、简历或资料类路径不代表已经执行过这些操作，也不是默认授权批量调用。
