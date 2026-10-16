# BOSS 验证台账

本项目分别标注发布脚本静态分析、真实匿名观察和离线夹具测试，避免把三者混为真实账号跑通。当前没有已确认的账号登录，也没有成功职位搜索响应。

本次检查完成于 2026-10-16，49 个离线测试全部通过。新框架以空 CookieJar 实际调用一次账号信息接口，返回 HTTP 200、业务码 7，正确记录为 `INVALID`；没有执行账号登录或最终凭据兑换。

## 目标身份

- **目标**：BOSS 网页端正常登录及只读账号状态接口，不是对其基础设施进行入侵测试。
- **参考框架**：[cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider)，提交 `fc8b9c2490a9561265425c26058290f01c064eda`。
- **分析工具**：REA 6.5.0，完整 Evidence 保留在私有工作区，未打包发布。
- **发布脚本**：`app.85b65004.js`、`user-login.5398946e.js`、`vendors.9a2efe85.js`，原输入未修改；可读副本另存。

| 文件 | SHA-256 |
| --- | --- |
| `app.85b65004.js` | `8c678738585c5bbd42e3d778176408a462031bde5eb6ea08dc0ca0e2f06a44de` |
| `user-login.5398946e.js` | `04b4040d344479f2b093b82fd2e9e03b9bf5ee62701ccd00ec34a3e0aaa963b0` |
| `vendors.9a2efe85.js` | `5a6e06340abd02c6b77472f4465b16fc23fdcfc3f2ace5a32863a3d6f12ca6a3` |

发布路径分别是 [入口脚本](https://static.zhipin.com/zhipin-sign/v5333/static/js/app.85b65004.js)、[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 和 [公共依赖](https://static.zhipin.com/zhipin-sign/v5333/static/js/vendors.9a2efe85.js)。

## 重建验证表

| 行为 | 目标证据 | 实现位置 | 改变输入的测试 | 状态 |
| --- | --- | --- | --- | --- |
| 匿名初始化与创建 QR | `login-bootstrap.json` 记录入口 200、bootstrap 0、randkey 0；静态证据 L | `login_api.create` | bootstrap 失败、缺少 qrId、正常三步 | 旧观察器有真实匿名验证；新实现离线通过 |
| 区分扫描与手机确认 | 发布组件 `scaned` / `login`；静态证据 L | `login_api.poll_once` | 未扫描、确认、取消、异常类型、缺少第二标识 | 仅静态恢复和离线通过；无真实手机确认 |
| 区分等待窗口和服务端 TTL | 发布组件 30 秒前端计时；静态证据 L | `WAIT_WINDOW_ENDED` | 31 秒后不发送请求、不宣称服务端过期 | 离线通过；服务端 TTL 未测量 |
| bst 与 zp_token 关系 | 入口拦截器；静态证据 A | `HeaderBuilder` | 有 bst、无 bst、路径限定 | 静态恢复和离线通过；未验证登录后绑定 |
| 有效账号状态 | `getUserInfo` / userId；静态证据 A；真实匿名业务码 7 | `BossAPI` / `BossAuth` | code 0 无 ID、code 7、模拟 ID、复核失败 | 失败路径有真实观察；成功账号仅夹具 |
| Cookie 持久化 | 本项目实现选择，不宣称恢复了浏览器全部 Cookie 行为 | `BossAuth` | 属性保存、路径、过期、异域拒绝、加载后重验 | 离线通过；真实登录跨进程复用未验证 |
| cURL 请求重放 | `request-21.json` 元数据，原响应正文缺失 | `replay_capture.py` | 重复参数、空头、伪头不符、注入、状态相同正文缺失 | 已发送过匿名请求；完整一致性未验证 |
| 最终凭据兑换 | 静态 `dispatcher`；静态证据 L | 未启用 | 允许列表拒绝该操作 | 阻塞于正常用户确认与实际字段核验 |
| 职位查询与详情 | 尚无有效请求证据 | 未添加虚构接口 | 无 | 未验证 |

表中的静态证据 L 为 `ev_9b732c8ca1c11ba2e62557470c3d204120163f82851cd1a431b7ee7befd927dd`，A 为 `ev_81d3c6710c54cc5790a3cda032fd663c316f77836f310b339492d9a8124d61ad`。对应协议行为来自 [登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 和 [入口脚本](https://static.zhipin.com/zhipin-sign/v5333/static/js/app.85b65004.js)，静态关系不证明运行成功。

## 仍保留的限制

云端浏览器登录页曾加载后变为空白，尚未确认根因。发布脚本下载内容与抓包中的 URL 一致，但原浏览器正文已丢失，不能证明下载文件与当时浏览器收到的字节完全相同。

新的 HTTP 客户端不是浏览器，也没有重建环境字段 `fp`、store token 或安全挑战 Cookie。扫码后的 `dispatcher` 还涉及 `pk`、可用的 `fp` 和组件额外参数；这些不能仅凭接口名称假定可以省略。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)

源码包中的成功登录 JSON 只存在于离线测试夹具。所有真实请求结果以 `reports/` 的明确记录为准，旧 cURL 报告保留历史状态，不追溯修改成“已经完成框架对齐时的结果”。
