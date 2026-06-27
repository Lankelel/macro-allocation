"""东方财富研报中心客户端:列表(行业/个股/按代码)+ PDF 下载。无需登录。

API: https://reportapi.eastmoney.com/report/list (JSONP,传 cb 后剥壳)
  qType: 0=个股研报 1=行业研报 2=策略 3=宏观 4=券商晨报
  code:  6位代码(按股精准过滤)
PDF:  https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf
坑:连发请求会被 ConnectionReset(10054)限流 → Session 保活 + 每页重试退避。
"""
import json
import time

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/report/",
    "Connection": "keep-alive",
}
_LIST_URL = "https://reportapi.eastmoney.com/report/list"
_PDF_URL = "https://pdf.dfcfw.com/pdf/H3_{ic}_1.pdf"


def _strip_jsonp(text):
    return text[text.find("(") + 1: text.rfind(")")] if "(" in text else text


class EastMoneyReports:
    """东财研报列表 + PDF 下载。纯网络 IO,不含业务筛选(筛选见 screen.py)。"""

    def __init__(self, session=None, sleep_per_page=0.4):
        self.s = session or requests.Session()
        self.s.headers.update(_HEADERS)
        self.sleep_per_page = sleep_per_page

    def _get(self, params, tries=4):
        for i in range(tries):
            try:
                r = self.s.get(_LIST_URL, params=params, timeout=25)
                return json.loads(_strip_jsonp(r.text)).get("data", [])
            except Exception:
                time.sleep(0.8 * (i + 1))
        return None  # 持续失败

    def list_reports(self, q_type, begin, end, max_pages=40, keyword_filter=None, page_size=100):
        """翻页拉取 q_type 研报(0个股/1行业)。keyword_filter(title)->bool 做客户端粗筛。
        连续 3 页失败即停;返回命中条目列表。"""
        out, fails = [], 0
        for p in range(1, max_pages + 1):
            params = {"cb": "x", "industryCode": "*", "pageSize": page_size, "pageNo": p,
                      "qType": q_type, "beginTime": begin, "endTime": end, "fields": "",
                      "p": p, "pageNumbers": p, "rt": "0"}
            data = self._get(params)
            if data is None:
                fails += 1
                if fails >= 3:
                    break
                continue
            fails = 0
            if not data:
                break
            out += [it for it in data if keyword_filter is None or keyword_filter(it.get("title", ""))]
            time.sleep(self.sleep_per_page)
        return out

    def stock_reports(self, code, begin, end):
        """按股票代码精准拉该股个股研报(qType=0 + code)。"""
        params = {"cb": "x", "pageSize": 50, "pageNo": 1, "qType": 0, "code": code,
                  "beginTime": begin, "endTime": end, "fields": "", "p": 1, "pageNumbers": 1, "rt": "0"}
        return self._get(params) or []

    def download_pdf(self, info_code, path, tries=3):
        """下载研报 PDF 到 path;校验 %PDF 头。返回字节数(0=失败)。"""
        url = _PDF_URL.format(ic=info_code)
        for i in range(tries):
            try:
                rr = self.s.get(url, timeout=40)
                if rr.status_code == 200 and rr.content[:4] == b"%PDF":
                    with open(path, "wb") as f:
                        f.write(rr.content)
                    return len(rr.content)
                return 0
            except Exception:
                time.sleep(0.8 * (i + 1))
        return 0
