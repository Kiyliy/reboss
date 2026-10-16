"""Account verification and explicit, single-request logout."""
from boss_apis.boss_api import BossAPI
from boss_apis.surface_api import BossSurface
from utils.http_client import ProtocolStopped


class AccountAPI:
    @staticmethod
    def prepare_logout(auth):
        # Empty-body v6763 hc contract; non-empty legacy options are not assumed.
        return BossSurface(auth).endpoint("/wapi/zppassport/user/logout")(
            method="POST", data={},
        )

    @staticmethod
    def logout(auth, plan, *, approval):
        if plan.method != "POST" or plan.path != "/wapi/zppassport/user/logout":
            raise ValueError("A reviewed logout request is required")
        body = auth.ensure_http_session().execute_plan(plan, approval=approval)
        if body.get("code") != 0:
            raise ProtocolStopped("Logout rejected; current session state has not been erased locally")
        BossAPI.get_user_info(auth)
        return {
            "logout_response_accepted": True,
            "current_client_logged_out": auth.status == "INVALID",
            "global_session_revocation_verified": False,
            **auth.safe_status(),
        }
