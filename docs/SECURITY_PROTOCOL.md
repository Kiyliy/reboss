# BOSS 请求头与动态安全校验

当前结论是：`traceId` 已按 SPA v6763 的源码做了独立实现和离线算术对照；`__zp_stoken__` 的有效生成与服务端接受仍未完成。正常扫码登录、账号接口成功、接口目录和离线测试都不能替代这项验收。

## 先区分五种不同的值

| 项目 | 来源与位置 | 本项目当前状态 |
| --- | --- | --- |
| `traceId` | 请求头；13 位十六进制时间、6 个随机 base62 字符、3 个校验字符，前缀为 `F-`。[SPA module 94627](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js) | `builder/trace_id.py` 已实现；132 组合成输入的 Python/JavaScript 结果一致，未因本次改动重试真实职位接口。 |
| `zp_token` | 请求头；拦截器从 `bst` Cookie 读取，而不是对每次请求正文直接做本地 AES。[请求拦截器](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js) | 已转发实际 Cookie；这不等于恢复了服务端签发 `bst` 的内部算法。 |
| `token` | 请求头；当前 SPA 从 `window._PAGE.token` 取值，保留 `|` 前的部分。[请求拦截器](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js) | 适配器使用真实账号响应提供的 token，已用于一次成功账号查询；它不是动态安全 Cookie。 |
| 手机号编码 | 手机登录请求字段，不是通用请求头；v5333 登录组件包含 AES-CBC 编码链。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 已有离线实现，真实短信登录未验收。 |
| `__zp_stoken__` | Cookie，随 HTTP `Cookie` 头携带；安全页加载动态脚本，调用 `new ABC().z(...)` 后写入。[官方安全页](https://www.zhipin.com/web/passport/zp/security.html) | 已取得并静态分析本次脚本，完整计算与真实服务端验证尚未完成。 |

`traceId` 是可由客户端生成的请求标识，不能当作登录凭据或安全 Cookie。抓包重放必须保留原请求已有的值，不要调用新生成器去改写原 cURL；本次没有修改重放工具的头部保留行为。

## 当前 code 37 的真实处理路线

本次只读诊断先得到账号 HTTP 200/code 0，随后一次职位 POST 得到 HTTP 200/code 37，立即停止，没有详情、翻页或重试。结果保存在 `reports/jobs-current.json`，其中 `BLOCKED` 是本地客户端对风险响应的停止状态，不代表已经证明账号被封禁。

当前 SPA 的响应分支不会在 code 37 上直接调用旧的 iframe 刷新器 `h()`；它把完整响应交给 module 7364，控制器读取 `data.zpData.seed/name/ts` 后转向安全页。[SPA 响应处理](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)、[安全控制器](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)

```text
职位响应 code 37
  -> module 7364 的 SECURITY_CHECK 分支
  -> /web/passport/zp/security.html
  -> 相对地址 security-js/{name}.js
  -> window.ABC 的实例方法 z(seed, 经时区调整的 ts)
  -> 非空结果写入 __zp_stoken__，再检查 Cookie 是否可读
  -> 按官方页面的白名单与循环保护逻辑返回 callbackUrl
```

安全页的参数检查、脚本加载、Cookie 写入和返回流程已从本次实际取得的页面中定位；这条图表示源码数据流，不是一次已经执行成功的安全验证记录。[官方安全页](https://www.zhipin.com/web/passport/zp/security.html)

- **时间参数**：外层调用传入 `parseInt(ts) + (480 + getTimezoneOffset()) * 60000`，不能不加区分地只传服务器整数。[官方安全页](https://www.zhipin.com/web/passport/zp/security.html)
- **Cookie 策略**：页面对结果做 URI 编码，设置 `/` 路径与当前域派生的域名，客户端配置过期时间为 64 小时；这不是实测服务端有效期。[官方安全页](https://www.zhipin.com/web/passport/zp/security.html)
- **返回约束**：页面使用回调 URL 白名单、同页检查和 `_security_check` 循环计数，并非单纯“写 Cookie 后无限重试”。[官方安全页](https://www.zhipin.com/web/passport/zp/security.html)
- **不同错误码**：当前 SPA 中 `122` 才有一次 `set/zpToken` 后重试的分支，不能拿它替代 `37` 的安全页流程。[SPA 响应处理](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)、[bootstrap 调用](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~3.a43b3372.js)

仅凭 code 37 无法确定是缺少 `traceId`、Cookie 不合适、浏览器上下文、请求参数还是其他服务端条件触发。本次 code 37 记录早于新 `traceId` 代码，不能写成“添加 traceId 后已解决”，也不能据此断言唯一原因就是某个 Cookie。

## 动态脚本取得了，但算法未验收

响应中实际出现的脚本名对应 `e5a1794d.js`，本次从[安全页使用的公开脚本路径](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)取得 320971 字节，SHA-256 为 `641c23791eddaceea84d307930bf90a2ccd2d0c93eaa07175426b085d87fa65a`。另一个[旧加载器路径](https://www.zhipin.com/web/common/security-js/e5a1794d.js)本次返回的字节相同，但不把一次相同推断成所有版本永久等价。

该文件包含大量分支和状态分派，静态语法中还存在 `window`、`document`、`navigator`、`screen`、`localStorage` 和 `performance` 引用；这说明还需恢复具体数据流，不能把每个出现的对象都当成已证实的指纹输入。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)

文件前部存在 MD5 实现，但“包含 MD5 库”不等于“最终 stoken 就是 MD5(seed)”；从入口、浏览器上下文到最终输出的完整关系仍待证明。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)

### 已实现五段局部计算，不是完整生成器

本轮进一步拆出字符串 UTF-16 单元、加 3 后循环键异或、异或与偏移的数组变换、1/2/3 字节数值编码以及字节数组 Base64 五段；其中 `15983` 是字符单元循环，不能因同文件含 MD5 就把它叫作 MD5。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) 独立实现位于 `builder/security_codec.py`，具体公式、范围、正常完成假设和改变输入的离线检查见 `docs/SECURITY_CODEC.md`。

五段模型通过 13 项 Python 与 4 项 JavaScript 检查，但它们不包含完整真实输入包、初始化环境或服务端验收。本项目没有提供冒充已完成的 `generate_stoken`，也没有把合成向量或局部输出接入真实 Cookie。

### 已定位的方法绑定

末尾初始化器从状态 `217` 开始，静态整理出 118 个有效状态块；构造出的 `ABC` 函数的原型方法 `z`，对应一个保留 `this` 和原实参的包装器，该包装器把 `6375` 作为第一个实参交给内部 `l` 分派器。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) 这项结论以初始化正常完成为条件，未假定全局 `Function`、`window`、数组方法、环境分支或不透明调用的运行效果已经验证。

关键原始字节范围为：包装器 `[314842,314929)`、入口字面量 `[314876,314880)`、原型方法赋值 `[315533,315542)`、导出属性赋值 `[318941,318950)`；范围按 0 起始、右端不包含计算，本文件这些范围的 UTF-16 与 UTF-8 偏移一致。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) `6375` 是此文件的分派初始状态，不是密钥、签名结果或跨版本稳定的函数编号。

`tools/analyze_security_bootstrap.mjs` 实现这一保守的 AST/控制流检查，输入必须匹配已记录 SHA-256；不会导入目标文件、调用它的函数、创建真实 `Function`、执行 VM 或联网。简要结果在 `reports/security-bootstrap-current.json`，完整 AST 事实只在显式提供一个新输出路径时生成。

```bash
npm install --ignore-scripts
npm run test:security-static

# 手动取得同一公开脚本后，指定本地文件；工具不会下载或执行它。
node tools/analyze_security_bootstrap.mjs \
  --input evidence/private/e5a1794d.js \
  --output reports/security-bootstrap-new.json
```

默认测试包括 19 项合成语法、作用域、输入变化与保守性检查，另有一项需要 `BOSS_DYNAMIC_SCRIPT` 指向独立取得的原文件，未提供时明确跳过。本工作区使用实际原文件执行了全部 20 项并通过；它们证明分析器的检查结果，不证明真实安全验证已通过。

### 分析身份与覆盖限制

完整 REA Evidence 保留在私有工作区，公开记录身份和限制，不分发 BOSS 原始代码。动态脚本的语法解析成功，但语义分析达到工作进程堆限制；不能将该次分析称为完整还原。

| Evidence | 本次范围 | 结果与限制 |
| --- | --- | --- |
| `ev_a41f8954521227ed6bf92d76d6748b0be29f00e7e569291478a1090c0ff196e4` | 动态脚本，320971 字节 | 134062 个 AST 节点，语法解析无失败；语义阶段 heap 耗尽，图不完整。 |
| `ev_45f3ecf3815322645773badf4b66e8100c63e03b3f2da63db3bfd01a274f3888` | v6763 `vendor-1`，54386 字节 | 18333 个 AST 节点、16 个模块；仅选定文件，不代表完整应用。 |
| `ev_976aec3d23ea219c62caef07b4cf2f8099d15ad8496a1e58cc9235f54ab64379` | 安全页 HTML，43335 字节 | 发现 12 个内联脚本；该 HTML 路线没有分析脚本正文，所以继续做了下一行的显式提取。 |
| `ev_469ba4bc2fe0f3573d124d8279eb1121c46bb7b70cc02f6398aa43a4cf367b28` | 按原 HTML 字节范围提取的 helper、BaseMixin、入口和来源清单 | 3 个 JavaScript 文件、2370 个 AST 节点；其他 9 个内联脚本不计入此次语义覆盖。 |

安全页 HTML SHA-256 为 `8e2c8ac3de172ce0278a6354ddaee0b2296b7479a038dcbdd3234750f682bc42`，是无账号 Cookie、无挑战值的公开页面取证。以上工作没有运行整个动态脚本，没有计算真实会话的 stoken，也没有重新发送被阻断的职位请求。

## traceId 实现的细节与边界

实现对应 v6763 module 94627 的浏览器分支，包含 signed int32 溢出、unsigned shift 和 JavaScript Number 乘法舍入；若直接用 Python 任意精度整数乘法，部分输入会产生不同校验值。[生成函数](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)

`JobsAPI` 的三个已审阅 SPA 请求规划会使用该 profile；通用目录需显式指定 `trace_profile="geek_spa_v6763"`，其他登录流程不会被自动改成这个版本。默认随机数在本地新产生，不声称恢复了某次浏览器的 PRNG 状态、设备指纹或 TLS 行为。

```python
from builder.trace_id import generate_trace_id, valid_trace_id

# 合成输入示例，不属于任何真实账号或请求。
value = generate_trace_id(now_ms=0, random_values=[0, 0, 0, 0, 0, 0])
assert value == "F-0000000000000000000LSB"
assert valid_trace_id(value)  # 只验证格式和校验字符，不验证服务端接受。
```

离线检查包括 132 组 JS Number 算术参考向量、时间截断边界、随机输入校验、头部 profile 选择和不可变请求计划。JavaScript 参考由项目独立实现，不执行第三方 bundle，因此这些测试属于源码辅助实现检查，不是浏览器真实目标等价证明。

## 验收尚缺什么

- **生成数据流**：将本次 `ABC.z` 的控制流和实际输入依赖恢复到可逐项解释的输出，不能用测试 fixture 或环境占位值充当真实生成材料。
- **正常页面观察**：当前云端职位页曾变成顶层 `about:blank`，原因未确认；源代码中的隐藏 `about:blank` iframe 不能解释这一现象。另已找到页面退出与清空的静态候选分支，见下节，但没有当次运行调用栈，不能认定它已被触发。
- **服务端结果**：在官方流程完成后，必须观察到获准业务请求返回有效结果，才能说动态校验通过。HTTP 200、账号 code 0、生成了一个字符串或通过本地测试都不够。
- **逐项 cURL 对照**：需要原始请求和响应作为比较基线；现有账号 GET 对照不覆盖职位 POST，更不覆盖 TLS、HTTP/2 帧或所有后续会话。

## 浏览器空白：已找到候选分支，未确定实际原因

这部分只解释为何真实页面观察可能中断，不是 `__zp_stoken__` 的计算实现。已对固定哈希的 v6763 `vendor-1` 做独立字符串解码与作用域检查，没有运行目标模块，也没有修改或关闭页面检测。

module 54294 的 `noDebug` 在检测反应方法中包含 `window.open("", "_self")`、`window.close()`、`history.back()`，随后还安排清空正文、给 `location.href` 赋空字符串以及隐藏页面元素的操作；这些都是源码中的条件分支，不是本次浏览器已经执行它们的证据。[公开 vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)

同一模块的另一个失败处理函数包含大量对象和数组分配，外层 SPA 入口也有相似的条件性分配逻辑；因此不能为了验证猜想而直接执行整段检测代码，更不能把潜在内存压力断言为已观察到的崩溃原因。[公开 vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)、[SPA 入口](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~3.a43b3372.js)

以下范围针对原始 `vendor-1.a73b9143.js`，SHA-256 为 `1249371f6d360d9e5b693eb2962d09ad65c1e2947e4c62b49d4c624616e56367`；坐标均为 0 起始、右端不包含，UTF-8 与 UTF-16 不可混用。[公开 vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js)

| 静态范围 | UTF-16 | UTF-8 字节 | 结论边界 |
| --- | --- | --- | --- |
| 检测反应方法 | `[10992,12724)` | `[11094,12826)` | 存在页面退出、清空与隐藏操作；当次是否触发未知。[vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js) |
| 大量分配函数 `tn` | `[8164,8806)` | `[8266,8908)` | 仅证明静态语法，不证明内存耗尽或浏览器崩溃。[vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js) |
| 原生方法检查 `tf` | `[10322,10561)` | `[10424,10663)` | 源码检查方法字符串中的 native-code 标记，不能据此恢复本次检测结果。[vendor-1](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/vendor-1.a73b9143.js) |

机器可读边界保存在 `reports/browser-guard-current.json`。目前仍缺正常浏览器当次的导航事件、检测调用栈与业务请求对应关系；本项目不通过替换原生方法、禁用检测或伪造设备环境把未知状态包装成通过。
