# 请求计划、正常登录与有限业务调用

以下示例说明库的组合方式，示例中的 `normal_context`、`official_sdk_result` 和确认结果都必须来自真实正常流程。不要用测试夹具、猜测的页面值或聊天中粘贴的 Cookie 填充这些变量。

当前已验收一次真实 App 扫码交接和跨进程账号复核，完整结果见验证台账。其他代码示例仍需按各自接口的运行证据判定，不能仅凭代码存在认定已跑通。

## 只读请求

默认先检查计划，再显式执行一次。需要登录的操作应先用本人正常登录得到的私有认证文件复核，客户端不会自动翻页。

```python
from builder.auth import BossAuth
from boss_apis.boss_api import BossAPI
from boss_apis.jobs_api import JobsAPI

# auth.json 由正常登录后的 auth.save() 生成，不是 QR challenge 文件。
with BossAuth.load("evidence/private/auth.json", live=True) as auth:
    BossAPI.get_user_info(auth)
    if auth.status != "VERIFIED":
        raise RuntimeError("先完成本人正常登录")
    jobs = JobsAPI(auth)
    plan = jobs.search("Python", page=1, page_size=15)
    print(plan.preview())
    response = auth.ensure_http_session().execute_plan(plan)
    # response 可能包含个人数据；按需私下处理，不打印或提交整份响应。
```

## App 扫码后的交接

先用 README 中的 CLI 创建二维码并观察本人手机确认。确认后的私有 challenge 状态只说明手机确认被观察到，下面的独立交接才会尝试建立客户端登录会话。

```python
from builder.auth import BossAuth
from builder.request_plan import ActionApproval
from boss_apis.qr_login_api import QRLoginAPI
from utils.private_state import load_private, save_private

saved = load_private("evidence/private/qr-new.json")
state = saved["challenge"]
with BossAuth.from_state(saved["auth"], live=True) as auth:
    plan = QRLoginAPI.prepare_dispatch(
        state,
        pk=normal_context["pk"],
        fp=normal_context.get("fp"),
    )
    print(plan.preview())
    # user_confirmed 必须来自用户对云端会话登录的明确确认。
    approval = ActionApproval.for_request(
        plan, confirmed=user_confirmed, reason="本人确认本次云端会话登录"
    )
    try:
        result = QRLoginAPI.exchange(auth, state, plan, approval=approval)
        print(result)
        if result["account_logged_in"]:
            auth.save("evidence/private/auth.json")
    finally:
        save_private("evidence/private/qr-new.json", {
            "schema_version": 1, "auth": auth.to_state(), "challenge": state,
        })
```

如果结果是 `ADDITIONAL_VERIFICATION_REQUIRED`，回到官方正常页面完成安全步骤，不构造凭据或重放尝试。失败后的同一 challenge 状态不可重复兑换。

`tools/complete_qr_login.py` 已将入口页面 key 提取、私有捕获、一次交接、账号核验和状态保存串联起来，CLI 见 README。若观察器只发生读取超时或等待窗口结束，而本人随后确已确认，可显式使用 `--recheck-confirmation` 单次补查；该选项不能恢复风控停止或重放已经执行过的交接。

## 手机号登录

两种 profile 的流程必须分开，不把 v5333 的短信 token 带入 SPA 流程。`VerificationMaterial` 接收官方 SDK 正常回调的真实值，执行器不负责验证码求解。

下面展示库的控制流，并非已经通过实测的一键登录程序。SDK 验证材料与浏览器会话的服务端绑定尚未核验，不能假定浏览器生成的 proof 可以直接移植到一个新建的 HTTP 会话；真实验收应在本人正常验证上下文中逐步核对，失败即停止。

```python
from builder.auth import BossAuth
from builder.request_plan import ActionApproval
from boss_apis.phone_login_api import PhoneLoginAPI, VerificationMaterial

with BossAuth(live=True) as auth:
    flow = PhoneLoginAPI(auth, profile=observed_profile)
    verification = VerificationMaterial(
        official_sdk_result["type"], official_sdk_result["values"]
    )
    send = flow.prepare_send(
        phone=user_phone, verification=verification, pk=normal_context["pk"],
        purpose=user_selected_purpose,
        environment=normal_context.get("send_environment"),
    )
    print(send.preview())
    send_approval = ActionApproval.for_request(
        send, confirmed=user_confirmed_sms, reason="本人确认向该号码发送一条登录短信"
    )
    flow.send_sms(send, approval=send_approval)

    # 此处等待用户收到短信，并在安全交互中输入验证码、确认条款及注册风险。
    plans = flow.prepare_login(
        phone=user_phone, code=user_sms_code, verification=verification,
        pk=normal_context["pk"], purpose=user_selected_purpose,
        fp=normal_context.get("fp"),
        environment=normal_context.get("login_environment"),
        terms_confirmed=user_accepted_terms,
        registration_acknowledged=user_acknowledged_possible_registration,
    )
    for plan in plans:
        print(plan.preview())
    approvals = [
        ActionApproval.for_request(
            plan, confirmed=user_confirmed_login, reason="本人确认当前登录请求"
        )
        for plan in plans
    ]
    result = flow.submit_login(plans, approvals=approvals)
    print(result)
    if result["account_logged_in"]:
        auth.save("evidence/private/auth.json")
```

示例里的多个确认变量不是预置的 `True`，需由实际调用界面取得用户确认。若出现 `IDENTITY_REVIEW_REQUIRED`，先展示 `identity_review` 中的现有身份与请求身份，再用原本选择的 `purpose` 调用 `review_identity`，对返回的剩余请求重新审批。

## 微信小程序与退出

`QRLoginAPI.create_mini_program` 返回私有 `mpCodeUrl` 和短 key，不自动下载图片或公开打印。正常展示官方图片并完成扫描后，按 `poll_mini_program`、`prepare_mini_program_confirm`、`exchange` 顺序推进。

`AccountAPI.prepare_logout` 只生成请求，`AccountAPI.logout(..., approval=...)` 才执行退出并查询账号状态。不要用删除本地 Cookie 文件冒充服务端已退出；本项目不自动进行跨设备退出。

## 补充新抓包后的静态目录

下列工具只处理调用者已经取得的授权脚本与私有捕获文件。它们不会替用户获取登录后脚本，也不会执行目标 JavaScript。

```bash
python tools/discover_api_catalog.py \
  --scripts-dir evidence/scripts --output catalog/discovered-new.json
node tools/extract_spa_contracts.mjs \
  --scripts evidence/scripts --output catalog/spa-helper-new.json
python tools/compile_api_registry.py \
  --discovered catalog/discovered-new.json \
  --helpers catalog/spa-helper-new.json \
  --captures evidence/private/capture-run \
  --adapter-report reports/qr-login-current.json \
  --output catalog/api-registry-new.json \
  --markdown docs/API-COVERAGE-new.md
```

通用发现器是保守词法扫描，不做全程序数据流分析；SPA 提取器只处理已核验的 module 86344 helper 和绑定关系，并校验原始文件哈希。换版本后应先重新分析映射，不通过修改哈希检查来假装旧契约仍然有效。
