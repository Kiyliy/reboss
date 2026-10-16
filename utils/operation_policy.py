"""Reviewed read operations. HTTP verb alone never grants write permission."""

READ_OPERATIONS = frozenset({
    ("GET", "/wapi/zpuser/wap/getUserInfo.json"),
    ("GET", "/wapi/zppassport/smsSwitch"),
    ("GET", "/wapi/zpuser/countryCode"),
    ("GET", "/wapi/zpgeek/common/data/header.json"),
    ("GET", "/wapi/zpgeek/common/data/footer.json"),
    ("GET", "/wapi/zpgeek/common/data/defaultcity.json"),
    ("GET", "/wapi/zpgeek/common/data/city/site.json"),
    ("GET", "/wapi/zpgeek/pc/all/filter/conditions.json"),
    ("GET", "/wapi/zpgeek/webtopbanner/query.json"),
    ("GET", "/wapi/zpgeek/job/detail.json"),
    ("GET", "/wapi/zpgeek/job/card.json"),
    ("GET", "/wapi/zpgeek/search/job/condition.json"),
    ("GET", "/wapi/zpgeek/pc/recommend/job/list.json"),
    ("GET", "/wapi/zpgeek/pc/recommend/conditions.json"),
    ("POST", "/wapi/zpgeek/search/joblist.json"),
    ("GET", "/wapi/zpCommon/data/cityGroup.json"),
    ("GET", "/wapi/zppassport/qrcode/getMpCode"),
    ("GET", "/wapi/zppassport/qrcode/scanByMp"),
    ("GET", "/wapi/zppassport/qrcode/getHeadImg"),
    ("GET", "/wapi/zppassport/qrcode/scanSecond"),
})


def operation_effect(method, path):
    if (method, path) in READ_OPERATIONS:
        return "READ"
    if path.startswith("/wapi/zppassport/"):
        return "AUTHENTICATION_OR_REGISTRATION"
    return "UNREVIEWED_OR_STATE_CHANGE"
