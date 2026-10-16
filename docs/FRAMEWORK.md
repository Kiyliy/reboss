# cv-cat 框架映射

参考对象已确定为 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider)，本次检出的提交为 `fc8b9c2490a9561265425c26058290f01c064eda`。检查了入口、API、登录、认证、请求构建、HTTP 工具和样例测试；没有执行参考项目的入口。

## 职责映射

| 参考项目 | 本项目 | 本次实际落地 |
| --- | --- | --- |
| `main.py / Data_Spider` | `main.py / Data_Spider` | 默认离线入口、会话复核、扫码观察编排 |
| `dy_apis/douyin_api.py` | `boss_apis/boss_api.py` | 已观察的账号信息接口；不虚构职位接口 |
| `dy_apis/login_api.py` | `boss_apis/login_api.py` | 独立正常登录状态机，明确未兑换凭据 |
| `builder/auth.py / DouyinAuth` | `builder/auth.py / BossAuth` | Cookie 属性、跨进程保存、重新验证 |
| `builder/header.py` | `builder/header.py` | 请求头合法性与已确认的 bst → zp_token 关系 |
| `builder/params.py` | `builder/params.py` | 有序键值对、重复字段、空值、不可变原始 query |
| `utils/http_client.py` | `utils/http_client.py` | 共享 Session、允许列表、请求预算和停止策略 |
| `tests/` | `tests/` | 离线 MockTransport、参数边界和 cURL 转换测试 |

表中左列结构来自参考仓库，右列为本次独立实现，不代表复制或完整移植了参考项目的全部功能。[参考仓库](https://github.com/cv-cat/DouYin_Spider)

## 明确没有照搬的部分

- **平台协议**：没有复用抖音的签名、设备标识、passport 参数或发布/私信协议。
- **传输伪装**：没有把参考项目的传输配置当作 BOSS 浏览器一致性的证据。
- **副作用入口**：没有运行参考项目入口，也没有发送任何消息或提交职位申请。
- **第三方源码**：本次有限目录检查未发现独立 LICENSE 文件，因此交付包只包含原创适配代码和说明，不打包参考源码。

分层结构已落地，账号登录和职位业务仍未通过真实目标对照。这个阶段应称为“参照 cv-cat 架构的 BOSS 诊断适配器”，不应称为“完整 BOSS 爬虫已经完成”。
