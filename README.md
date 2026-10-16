# BOSS Web Adapter

这是参考 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 分层方式编写的 BOSS 网页端诊断项目，包含独立登录模块、会话管理、请求构建器和 cURL 复现工具。当前是可运行、可测试的阶段版本，不是已经跑通真实账号和职位采集的完整爬虫。

## 当前状态

- **架构**：参考仓库固定到 `fc8b9c2490a9561265425c26058290f01c064eda`，只参考组织方式，未导入其抖音签名、设备伪装、私信或发布代码。
- **登录流程**：实现匿名初始化、获取官方 QR 挑战、等待扫描、第二阶段标识、手机确认与取消观察；确认后停在 `CONFIRMED_AWAITING_EXCHANGE`。
- **账号判断**：账号信息接口的业务码和 `userId` 一起判断；Cookie 存在、HTTP 200、手机确认都不能单独证明已经登录。
- **验证边界**：离线测试与实际接口验证分开记录，见 `reports/framework-checks.json` 和 `docs/EVIDENCE.md`。
- **未完成**：真实账号凭据兑换、登录生命周期、职位搜索/详情接口、浏览器与 cURL 的完整一致性验证。

所有实现与测试均在本次云端 Linux 工作区完成，没有修改用户本地 Windows。源码包不包括参考仓库源码、BOSS 发布脚本、原始抓包、Cookie、二维码或其他私有会话材料。

## 目录与参考架构

参考项目将业务编排、API、登录、认证状态、请求头、参数和 HTTP 客户端分层组织，本项目按对应职责编写 BOSS 适配器。[参考仓库](https://github.com/cv-cat/DouYin_Spider)

```text
main.py                      Data_Spider 编排与默认离线 CLI
boss_apis/boss_api.py         BossAPI：已观察的账号信息接口
boss_apis/login_api.py        LoginAPI：正常扫码状态观察
builder/auth.py              BossAuth：CookieJar、私有持久化、状态判定
builder/header.py            Header / HeaderBuilder
builder/params.py            重复参数、空值和原始 query 保留
utils/http_client.py         允许列表、超时、请求上限、遇验证停止
utils/private_state.py       原子私有 JSON 写入
tools/replay_capture.py      已抓取 GET 的 cURL 配置与响应比较
tools/check_framework.py     离线测试和可选单次匿名实测
tests/                      离线 MockTransport 与转换测试
docs/                       架构映射、证据与限制
reports/                    脱敏检查结果
```

未添加未经抓包验证的职位 API，也没有把抖音协议字段改名后套用到 BOSS。原工作区的 `tools/qr_session.py` 和 `tools/probe_login_bootstrap.py` 是早期证据采集脚本，不包含在交付源码包中，也不是新框架的调用入口。

## 安装与离线运行

以 Python 3.12 为验证环境，依赖版本固定在 `requirements.txt`。项目安装后默认不联网，运行 `main.py` 只打印能力和未完成项。

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
python -m unittest discover -s tests -v
python tools/check_framework.py --report reports/framework-checks.json
```

本次云端已准备好的解释器是 `/home/user/workspace/reverse-toolkit/runtime/py/bin/python`，无需再次安装即可运行。该绝对路径仅适用于当前工作区，不是用户 Windows 路径。

## 正常扫码观察

以下命令会向 BOSS 正常接口创建登录挑战，应该只为本人账号运行，并在手机官方 App 中核对设备提示。示例命令不会自动交换登录凭据、发送短信、投递简历或发消息。

```bash
python main.py qr-create --live \
  --state evidence/private/qr-new.json \
  --image evidence/private/qr-new.png
python main.py qr-watch --live \
  --state evidence/private/qr-new.json --seconds 90
```

`qr-create` 要求新的状态文件和图片路径，不覆盖已有挑战。`qr-watch` 最多观察 90 秒、最多 20 次状态轮询；初始扫描等待窗口为该版本前端使用的 30 秒，不能把窗口结束写成“实测服务端 TTL”。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)

第二扫描阶段采用发布组件中的一秒回退路径，不获取头像，也不宣称重建了完整浏览器 UI。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)

```text
WAITING_FOR_SCAN
  → WAITING_FOR_CONFIRMATION
  → CONFIRMED_AWAITING_EXCHANGE / CANCELLED
```

遇到超时、验证/风控返回或未知响应形状时停止，不自动破解、重试或刷新挑战。`dispatcher` 未纳入请求允许列表，真实手机确认之后还需要核对该请求的实际字段和授权，再实现并验证凭据兑换。

## 会话保存与复核

`BossAuth` 保存 Cookie 的 domain、path、secure、expires、host-only 标记和扩展属性，私有 JSON 采用临时文件原子替换。Linux 文件权限为 600；跨进程加载只恢复 Cookie，不把旧的成功观察当作当前已登录。

下面的命令读取由 `BossAuth.save()` 生成的认证状态文件，并对账号接口发送一次正常 GET。QR 状态文件和认证状态文件是不同结构，不能互换；当前尚未产生经过真实登录验证的认证状态文件。

```bash
python main.py verify-session --live --state evidence/private/auth.json
```

## cURL 对照

`replay_capture.py` 接受 Chrome DevTools MCP 的单请求 JSON，默认只生成私有 cURL 配置。只有增加 `--execute` 才发送一次请求，不跟随重定向，不自动重试。

```bash
python tools/replay_capture.py evidence/private/request-21.json \
  --private-dir evidence/private/replay-user-info \
  --report reports/replay-user-info-current.json
```

工具保留原始 URL query、普通请求头与空请求头，并检查 HTTP/2 伪头和 URL 是否一致。`GET` 不天然代表只读，因此 BOSS 主站仅允许当前已确认的 `getUserInfo.json`，不会用此工具重放 `dispatcher` 等可能改变账号状态的 GET。

对照分为请求字段、HTTP 状态、JSON 内容、解码后 UTF-8 字节四层。缺少原响应正文时绝不报告响应一致；即使响应字节相同，也不代表 TLS 指纹、HTTP/2 帧、压缩传输字节或登录生命周期一致。

普通诊断客户端使用明确的诊断 User-Agent，没有复制浏览器环境指纹。不要把 `httpx` 请求生成器和“已抓包请求的 cURL 复现”混为同一种精度承诺。

## 隐私与操作边界

- **默认离线**：网络操作需要 `--live`，或测试明确注入 MockTransport。
- **状态脱敏**：控制台只输出阶段、业务码和 Cookie 名，不输出 Cookie 值、QR 标识、用户 ID。
- **私有目录**：原始抓包和会话保存在 `evidence/private/`，不提交、不打包、不公开部署。
- **有限访问**：没有私信、简历投递、短信、批量职位枚举、验证码绕过或安全 Cookie 伪造功能。
- **正常登录**：必须使用本人的官方账号并完成正常确认；不能用测试夹具中的成功 JSON 代替真实账号验证。
