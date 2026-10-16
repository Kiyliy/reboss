# BOSS 正常登录协议与版本边界

本文记录公开发布脚本中可定位的登录构造链，并说明本项目的恢复范围。它不是服务器正式 API 文档，所有字段是否必填、期限和服务端绑定仍需要真实正常流程核验。

2026-10-16 已通过一次本人正常 App 扫码、客户端交接、账号核验和跨进程复核，记录见 `docs/EVIDENCE.md`。手机号与微信流程仍只有静态契约和离线测试，不能把 App 路径的成功外推给它们。

## 手机号构建版本

| 行为 | `sign_v5333` | `geek_spa_v6763` |
| --- | --- | --- |
| 发送短信 `version=1` | 当前调用链添加。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 当前调用链未添加。[组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js) |
| 保存短信响应 token | `zpData.token` 留作登录建议请求。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 本次读取的构造链没有这一行为。[组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js) |
| `getLoginSuggest` | 在最终 phone 请求前调用。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 本次读取的构造链没有这一调用。[组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js) |
| 最终 phone 请求自动加入短信 token | 没有；token 用于建议请求。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 没有上述 token 流程。[组件](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/boss-login-332c3023.bf146895.js) |

必须由调用者明确选择 profile，不根据接口名字猜版本。页面构建更新后需要重新核验，不能把两个版本的字段叠加成一个所谓“通用完整 payload”。

## 正常验证结果与四组接口

验证类型由官方 SDK 的 `ready({type})` 回调决定，初始类型为空；`success` 提供验证结果，不是本项目自己选择供应商或生成 proof。[独立登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 本项目只检查调用者传入材料的结构，`origin` 标签不构成真实性证明。

| 类型 | 发送 / 登录路径后缀 | 显式 proof 与限制 |
| --- | --- | --- |
| 1 | `smsCodeV2` / `phoneV2` | `challenge`、`validate`、`seccode`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 2 | `smsCode` / `phone` | gate 检查 `csessionId`，但 builder 未显式复制它；隐式通道未知，专用执行器阻止联网。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 3 | `smsCodeV3` / `phoneV3` | `captcha`、`randKey`，包含正常人工输入环节。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 4 | `smsCodeByWy` / `phoneByWy` | `validate`，不拼入其他类型字段。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |

发送路径前缀是 `/wapi/zppassport/send/`，登录路径前缀是 `/wapi/zppassport/login/`，均为表单 POST。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) `VerificationMaterial` 的测试值只能进入 MockTransport，不能把夹具 proof 当作真实请求材料。

## 请求构造与编码

- **手机号**：正常 builder 将 `phone` 替换为 `encryptedAccount`，同时保留 `regionCode`、页面 `pk`、`smsType=7` 和选择的 `purpose`；登录再加入用户输入的 `phoneCode`。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)
- **加密格式**：公开脚本常量解码为 16 字节原始 AES key，采用随机 16 字节 IV、CBC、PKCS7、UTF-8，并输出 `Base64(IV || ciphertext)`；不是密码 KDF 或 `Salted__` 格式。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)
- **SMS 表单**：qs 默认 RFC3986 规则，数组用下标、undefined 省略、null 为空值，`+86` 和 Base64 中的保留字符需要转义。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)
- **SPA 表单**：module 86344 的 `hc/hk` 路径使用另一种 serializer，数组逆序、原样 `key[]`、null 为 `null`、undefined 为空字符串。[SPA helper](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js)
- **真实上下文**：`fp`、`environment`、应用 token、Cookie 及额外来源字段来自实际页面或正常会话；源码存在算法或 fallback 不等于能补造一组生产有效值。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js)

普通 API 客户端使用诊断 UA，未重建 traceId、完整浏览器指纹、所有 axios 默认行为或 TLS。这里的构造实现和抓包 cURL 重放是不同能力，不作“所有字段及传输完全一致”的承诺。

## 状态机和副作用

```text
正常官方验证完成
  → prepare_send：待确认请求
  → send_sms：一次已批准发送
  → SMS_SENT_AWAITING_USER_CODE
  → prepare_login：条款、可能注册、账号和类型一致性检查
  → sign_v5333 登录建议 / geek_spa_v6763 直接进入最终计划
  → 必要时暂停，确认是否使用原先选择的身份
  → 一次已批准的最终登录
  → 额外安全验证，或 getUserInfo 复核
  → ACCOUNT_VERIFIED / SESSION_UNVERIFIED / STOPPED
```

首次手机号验证可能注册账号，`code=0` 后仍可能进入 `commonDevice` 安全确认或资料完善流程。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 因而本项目要求显式条款确认和注册风险确认，并在额外安全步骤暂停，不替用户接受条款或选择身份。

身份提示比较用户选择的目的身份与已有身份，确认不应把已构建的 `purpose` 改成服务器返回的已有身份。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 本项目 `review_identity(purpose=原先选择值, confirmed=True)` 保留原请求正文，再要求对剩余请求单独审批。

本项目的 60 秒短信冷却、20 次观察预算、异常后禁止重复提交与停止策略属于保守客户端约束。部分时序来自网页 UI，但不代表测量了服务端 TTL、频控阈值或短信实际送达。

## App 与微信扫码

| 步骤 | App | 微信小程序 |
| --- | --- | --- |
| 标识来源 | `randkey.zpData.qrId`，第二阶段另外取 key。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | `randkey.zpData.shortRandKey`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 扫描观察 | `scan(uuid=原始 qrId)`，随后手机确认 `scanLogin(qrId=原始 qrId)`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | `getMpCode(uuid=shortRandKey)` 后 `scanByMp(uuid=shortRandKey)`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 最终交接 | GET `qrcode/dispatcher`，用原始 `qrId`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | GET `qrcode/loginConfirm`，`uuid=shortRandKey`。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |
| 后续 | 正常响应仍需判断安全页和复核账号。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) | 同样不能只凭扫码状态认定账号已登录。[组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) |

`validate/allweb` 是首次 App 扫描响应中的事件上下文，不应凭空塞进 dispatcher 作为 proof。[登录组件](https://static.zhipin.com/zhipin-sign/v5333/static/js/user-login.5398946e.js) 本项目不会用 App 的 `qrId` 替换小程序短 key，也不会声称恢复了微信通用 OAuth。

## 退出与会话复核

当前退出适配使用 v6763 的空正文表单 POST，避免假定旧版非空 logout options 的两层序列化规则。[SPA helper](https://static.zhipin.com/zhipin-geek-spa/web/v6763/static/js/app~2.4f650b7a.js) 退出响应后再次查询账号，只报告当前客户端是否变成未登录，不能据此声称所有设备会话已撤销。

Cookie、短信 token、应用 header token、二维码标识和安全 Cookie 各有来源，不互相替代。历史状态加载仅恢复材料，不把历史 `VERIFIED` 直接视为当前登录成功。
