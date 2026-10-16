# cv-cat 框架映射

参考对象是 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider)，本次检出提交为 `fc8b9c2490a9561265425c26058290f01c064eda`。只参考目录职责和调用组织，没有运行其入口或移植抖音签名、设备模拟、消息和发布逻辑。

## 职责对应

| 参考结构 | 本项目 | 当前实现 |
| --- | --- | --- |
| `main.py / Data_Spider` | `main.py / Data_Spider` | 默认离线状态、目录、职位请求预览、会话复核、扫码观察 |
| `dy_apis/` | `boss_apis/` | 分组目录、正常登录、职位只读调用、账号与退出 |
| 独立 `login_api.py` | `phone_login_api.py`、`qr_login_api.py` | 按版本构建 SMS，按标识区分 App 和微信小程序，交接后复核 |
| `builder/auth.py` | `builder/auth.py` | 作用域 CookieJar、应用 token、私有持久化、历史状态重新验证 |
| `builder/header.py` | `builder/header.py` | 头校验、诊断 UA、真实会话值的正常绑定 |
| `builder/params.py` | `builder/params.py`、`form.py` | 原始 query、重复值、两种不同的表单编码 |
| HTTP 工具层 | `utils/http_client.py` | 共享客户端、请求预算、超时、精确操作审批、异常停止 |
| 测试入口 | `tests/` | MockTransport、状态边界、cURL 转换、目录发现与 AST 作用域 |

左列来自[参考仓库](https://github.com/cv-cat/DouYin_Spider)，右列为原创 BOSS 适配实现。对应结构不表示原仓库的全部功能已经移植或适用于另一平台。

## 本次设计选择

- **目录与业务分离**：`BossSurface` 覆盖已发现路径，专用 `JobsAPI`、`PhoneLoginAPI` 和 `QRLoginAPI` 提供有明确语义的调用。
- **计划与执行分离**：默认返回不可变 `RequestPlan`，不隐式执行；审批绑定方法、路径、query、头、正文和操作类型。
- **证据与成功分离**：静态调用点、浏览器曾发出请求、服务端业务成功和完整流程通过是四种不同状态。
- **保守差异**：短信建议失败、身份未知、网络异常、风险码都停止；不会照搬网页的自动重试或静默降级行为。
- **不分发第三方源码**：发布包仅包含本次代码、无值接口元数据、测试和说明，不打包参考项目或 BOSS 发布脚本。

这些保护属于本项目的工程选择，不是从官网恢复出的服务器限制。端到端验收仍以真实正常登录和目标响应为准，不能用自洽的夹具测试替代。
