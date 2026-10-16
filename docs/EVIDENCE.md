# BOSS 验证台账

检查日期为 2026-10-16，当前基线包含 178 项 Python 离线测试及 10 项 JavaScript 离线测试。本人正常 App 扫码、一次客户端凭据交接、有效账号核验、跨进程复核及已登录账号响应的 cURL 对照已通过，职位、手机号和微信流程仍未完成真实验收。

## 目标与原始证据

目标是 BOSS 网页正常登录与获准访问的 API 兼容，不是对其基础设施进行入侵。架构参考固定到 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 的 `fc8b9c2490a9561265425c26058290f01c064eda`，未执行参考项目入口。

| 发布文件 | SHA-256 | 获取与用途 |
| --- | --- | --- |
| `app.85b65004.js` | `8c678738585c5bbd42e3d778176408a462031bde5eb6ea08dc0ca0e2f06a44de` | 公开下载，登录入口拦截链。[发布文件](https://static.zhipin.com/zhipin-sign/v5333/static/js/app.85b65004.js) |
| `user-login.5398946e.js` | `04b4040d344479f2b093b82fd2e9e03b9bf5ee62701ccd00ec34a3e0aaa963b0` | 公开下载，sign v5333 登录流程。[发布文件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| `vendors.9a2efe85.js` | `5a6e06340abd02c6b77472f4465b16fc23fdcfc3f2ace5a32863a3d6f12ca6a3` | 公开下载，公共依赖。[发布文件](https://static.zhipin.com/zhipin-sign/v5333/static/js/vendors.9a2efe85.js) |
| SEO v5481 `main.js` | `e6462d632b02299430a5b6bcea197913507e5de7939a51a0621427eea9781fd0` | 浏览器保留正文，首页 API 候选。[发布文件](https://static.zhipin.com/zhipin-geek-seo/v5481/web/geek/js/main.js) |
| SPA v6763 `app~2.4f650b7a.js` | `92814a7eae376741b6cef3bf732066abb7f979e61c0a9a37ad5033a78d8dc437` | 浏览器保留正文，模块 86344 的方法和编码映射。[发布文件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js) |
| SPA v6763 `boss-login-332c3023.bf146895.js` | `91f7f1a795eec55b42bf5f298d9fba4458da2354d9aebf26a04e85cd6b932250` | 浏览器保留正文，登录版本差异。[发布文件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js) |

原始输入未修改，可读副本另存；完整文件清单和捕获来源 URL 在 `catalog/api_registry.json`。初次公开下载的登录脚本不能追溯宣称与早期已丢失的浏览器响应逐字节相同，后续保留的浏览器正文则有独立哈希。

## REA 分析记录

使用固定 REA 6.5.0，完整 Evidence 留在私有工作区，不分发含原始目标代码的分析输出。下列编号仅标识本次静态分析，不代表调用了真实业务接口。

| 代号 | Evidence ID | 覆盖与限制 |
| --- | --- | --- |
| L | `ev_9b732c8ca1c11ba2e62557470c3d204120163f82851cd1a431b7ee7befd927dd` | v5333 登录组件及依赖 |
| A | `ev_81d3c6710c54cc5790a3cda032fd663c316f77836f310b339492d9a8124d61ad` | v5333 入口脚本 |
| H | `ev_444b3dc7ada3d9aa30671c3ce739668c49b2f30dd7d7124e176e2d1df17f5399` | SEO 首页脚本；未选择的文件不算已分析 |
| S | `ev_e997675ec072e157a54da85fa4af80b02ffad7317ab4e153db0b1fa7e2b0006c` | 6 个 SPA 文件、204733 个 AST 节点、97 个模块，语法解析无失败；登录 chunk 和两个 job chunk 的语义图达到输出预算，不能宣称完整语义覆盖 |

补充 AST 提取使用固定 Babel 7.29.0，按词法绑定解析 module 86344 的导入，防止嵌套作用域同名变量误报。最终得到 218 个局部静态调用契约；目标 JavaScript 仅作为文本解析，没有通过 `eval` 或导入执行。

## 运行观察和响应比较

两次新增浏览器捕获分别记录 92、94 个目标域请求，保留 16、47 份响应正文，捕获 7、39 份脚本记录。这些是两次独立运行的记录数，存在重复，不能相加当作独立接口数。

首页和职位页加载后均曾跳到 `about:blank`，原因没有确认。未把这种现象写成已经证实的反自动化机制，也没有通过绕过验证来继续。

| 报告 | 实际结果 | 结论边界 |
| --- | --- | --- |
| `reports/framework-checks.json` | 历史 49 项离线测试；新空会话的账号 GET 返回 HTTP 200、业务码 7 | 匿名失败路径正确，不是登录 |
| `reports/expanded-checks.json` | 当前 178 项 Python 离线测试；本次检查不额外联网 | 覆盖实现，不证明服务器兼容 |
| `reports/ast-checks.tap` | 10 项作用域、动态路径及编码覆盖测试 | 合成源码夹具，不是全站分析 |
| `reports/replay-jobs-user-info.json` | HTTP/2、HTTP 200、业务码 7；原正文可用，JSON 和 62 字节 UTF-8 正文相同 | 仅这一次匿名响应比较通过 |
| `reports/qr-confirmation-recheck.json` | 用户正常手机确认后，单次 `scanLogin` 观察到确认 | 不以用户回复直接替代服务端结果 |
| `reports/qr-login-current.json` | `dispatcher` 和账号接口均为 HTTP 200、code 0，有有效账号标识 | 一次正常 App QR 登录通过，原始材料仅私下保留 |
| `reports/auth-persistence-current.json` | 新进程加载私有状态，再请求账号，得到 `VERIFIED` | 跨进程复核通过，不表示测出了 Cookie 有效期 |
| `reports/replay-authenticated-user-info.json` | code 0，JSON 与 615 字节 UTF-8 正文均相同 | HTTP 适配器请求与 cURL 对照，不是浏览器原请求 |

匿名正文 SHA-256 为 `5bee8ca3a29f89b783c1962212c740cb668f2bc6e98b1a5dd9a281993f72fe56`，已登录正文摘要单独保存在相应比较报告。`verified_equivalent: true` 仅表示状态与解码正文比较通过，不包括原始头顺序、重复头、TLS、HTTP/2 帧、压缩传输字节；账号有效性另外由账号接口的业务码及有效标识判定。

这次 App 登录先遇到观察器的 `ReadTimeout`，未自动重试；用户明确表示手机已确认后，单次正常 `scanLogin` 补查成功，才继续 `dispatcher`。页面 key 从同一客户端正常入口 HTML 读取，没有伪造 `fp` 或安全 Cookie；一次缺省字段可成功不证明所有环境都可省略这些字段。

## 重建验收表

| 行为 | 目标证据 | 实现 | 改变输入的检查 | 当前状态 |
| --- | --- | --- | --- | --- |
| 初始化与创建 App QR | L、真实正常挑战 | `LoginAPI.create` | 缺标识、失败码、正常三步 | 此次挑战用于本人确认并完成交接 |
| 扫描与手机确认 | L 的字段、真实 `scanLogin` | `LoginAPI.poll_once` / `reconcile_confirmation` | 扫描、取消、未知状态、超时单次恢复、风险停止不可恢复 | 手机确认有真实观察；完整浏览器 UI 未复现 |
| App / 微信凭据交接 | L 的 dispatcher / loginConfirm | `QRLoginAPI` | 原始标识与短 key、错误标识、失败后不可重放 | App 真实交接通过；微信仍未实测 |
| 两版本手机号登录 | L、S | `PhoneLoginAPI` | version、token、四种验证类型、重复请求、同号码绑定 | 已实现，未发送真实短信 |
| 身份切换提示 | L 的已构建 purpose 与 UI callback | `review_identity` | 不把现有身份替代用户选择、拒绝未经确认切换 | 离线通过，保留用户原始 purpose |
| 请求编码 | L 的 qs 与 S 的 SPA helper | `sms_form`、`spa_form` | 空值、undefined、数组顺序、Base64 字符 | 语义恢复，非完整浏览器 wire 等价 |
| 账号登录判定 | A、S、真实匿名 code 7、本人账号 code 0 | `BossAuth` / `BossAPI` | code 0 缺 ID、历史状态、风险码、失效 | 真实成功与失败均观察到，跨进程复核通过 |
| 职位搜索与详情 | S 的 POST 搜索和 GET 详情 | `JobsAPI` | 表单、pageSize、第二页登录限制、重复参数 | 已实现，真实业务未通过 |
| 退出 | S 的空正文 POST | `AccountAPI` | 显式审批、退出后账号复核 | 已实现，服务端撤销未实测 |
| 分组 API 目录 | H、S、匿名捕获 | `BossSurface` | 387 个入口、未知项阻止执行 | 不等于全站接口全集 |

登录行为可追溯到[独立登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)和[SPA 登录组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js)，请求 helper 与业务映射可追溯到[SPA 业务模块](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)。测试中的成功 JSON 和手机样例都是本地夹具，不是观察到的真实账号材料。

## 尚需本人参与的验收

本人 App 扫码、交接、账号核验和跨进程复核已经完成，后续仍需验证有限的只读职位请求及其他登录方式。短信、账号注册风险、身份切换与退出分别确认，不以本次扫码许可代替。

Type 2 的隐式验证通道、真实 `fp`、浏览器安全 Cookie、所有接口的完整参数与响应 schema、招聘端和登录后懒加载模块仍未闭合。当前实现不会用占位材料、假成功日志或测试夹具补齐这些缺口。
