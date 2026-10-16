"""Named job-reading adapters recovered from the v6763 UI call sites."""
from boss_apis.surface_api import BossSurface
from utils.http_client import ProtocolStopped


class JobsAPI:
    def __init__(self, auth):
        self.auth = auth
        self.surface = BossSurface(auth)

    def search(self, query, *, city="", page=1, page_size=15, filters=None, execute=False):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("An explicit search query is required")
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 15:
            raise ValueError("Use a positive page and page_size within the observed UI limit of 15")
        if page > 1 and self.auth.status != "VERIFIED":
            raise ProtocolStopped("The observed UI gates further pages on a verified login")
        fields = {"page": page, "pageSize": page_size, "query": query, "city": city, "scene": 1}
        for name, value in (filters or {}).items():
            if name in fields:
                raise ValueError("Filters cannot replace explicit search arguments")
            fields[name] = ",".join(map(str, value)) if isinstance(value, list) else value
        return self.surface.endpoint("/wapi/zpgeek/search/joblist.json")(
            method="POST", data=fields, execute=execute, trace_profile="geek_spa_v6763",
        )

    def detail(self, security_id, *, lid="", execute=False):
        if not isinstance(security_id, str) or not security_id:
            raise ValueError("Use securityId from a real accessible job result")
        return self.surface.endpoint("/wapi/zpgeek/job/detail.json")(
            params={"securityId": security_id, "lid": lid}, execute=execute,
            trace_profile="geek_spa_v6763",
        )

    def filter_conditions(self, *, execute=False):
        return self.surface.endpoint("/wapi/zpgeek/pc/all/filter/conditions.json")(
            execute=execute, trace_profile="geek_spa_v6763",
        )
