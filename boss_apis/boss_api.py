"""Read-only account adapter. Job endpoints await real browser evidence."""
from builder.header import HeaderBuilder, ORIGIN
from utils.http_client import ENDPOINTS


class BossAPI:
    @staticmethod
    def get_user_info(auth):
        # A failed recheck must not leave a previous success looking current.
        auth.status = "UNVERIFIED"
        auth.verified_at = None
        auth.last_code = None
        url = ORIGIN + ENDPOINTS["user_info"][1]
        body = auth.ensure_http_session().json(
            "user_info", headers=HeaderBuilder.build(auth, url).get()
        )
        auth.observe_user_info(body)
        return body
