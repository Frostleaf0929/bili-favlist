# -*- coding: utf-8 -*-
"""B站收藏夹 API 封装：读/写、限速、重试、错误码处理。

安全约束：
- 所有请求强制 https，host 白名单仅允许 api.bilibili.com，发请求前校验；
- Cookie 只在内存中拼装，任何日志/输出都不得包含 Cookie 明文。
"""
from __future__ import annotations

import random
import time
from urllib.parse import urlparse

import requests

API_HOST = "api.bilibili.com"
BASE_URL = f"https://{API_HOST}"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)

RISK_CODES = {-412, -352, -799}   # 风控/频率限制：指数退避后重试
AUTH_CODES = {-101, -111}         # 未登录/csrf 失效：立即终止
SKIP_CODES = {11010, 11011}       # 资源不存在等：跳过该条继续


class BiliApiError(Exception):
    """接口返回非 0 业务码，或 HTTP 层异常。"""

    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") != API_HOST:
        raise ValueError(f"非法请求地址（仅允许 https://{API_HOST}/）: {url}")


class BiliApi:
    def __init__(
        self,
        sessdata: str,
        bili_jct: str,
        dede_user_id,
        user_agent: str = DEFAULT_UA,
        read_rate=(0.8, 1.6),
        write_rate=(0.5, 2.0),
        timeout: int = 20,
    ):
        self.csrf = str(bili_jct)
        self.mid = str(dede_user_id)
        self.read_rate = read_rate
        self.write_rate = write_rate
        self.timeout = timeout
        self._rng = random.SystemRandom()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "Cookie": (
                    f"SESSDATA={sessdata}; bili_jct={bili_jct}; "
                    f"DedeUserID={dede_user_id}"
                ),
            }
        )

    # ---------- 基础请求 ----------

    def _sleep(self, rng) -> None:
        time.sleep(self._rng.uniform(*rng))

    def _request(self, method: str, path: str, *, params=None, data=None, retries=3):
        url = BASE_URL + path
        validate_url(url)
        last_error = None
        for attempt in range(retries):
            try:
                resp = self.session.request(
                    method, url, params=params, data=data, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
                continue
            if resp.status_code >= 500:
                last_error = BiliApiError(resp.status_code, f"HTTP {resp.status_code}")
                time.sleep(2**attempt)
                continue
            if resp.status_code != 200:
                raise BiliApiError(resp.status_code, f"HTTP {resp.status_code}")
            payload = resp.json()
            code = payload.get("code", -1)
            if code == 0:
                return payload.get("data")
            if code in RISK_CODES:
                last_error = BiliApiError(code, payload.get("message", ""))
                time.sleep(3 * (2**attempt))
                continue
            raise BiliApiError(code, payload.get("message", ""))
        raise last_error if last_error else BiliApiError(-1, "未知错误")

    # ---------- 读接口 ----------

    def whoami(self) -> dict:
        data = self._request("GET", "/x/web-interface/nav", params={"platform": "web"})
        return data or {}

    def list_created_folders(self) -> list:
        data = self._request(
            "GET",
            "/x/v3/fav/folder/created/list-all",
            params={"up_mid": self.mid, "jsonp": "jsonp"},
        )
        if isinstance(data, dict):
            return data.get("list") or []
        return data or []

    def iter_folder_resources(self, media_id, ps: int = 20, max_pages=None):
        """逐页产出 (page_no, info, medias)。"""
        pn = 1
        while True:
            data = self._request(
                "GET",
                "/x/v3/fav/resource/list",
                params={
                    "media_id": media_id,
                    "pn": pn,
                    "ps": ps,
                    "order": "mtime",
                    "type": 0,
                    "tid": 0,
                    "platform": "web",
                },
            ) or {}
            info = data.get("info") or {}
            medias = data.get("medias") or []
            yield pn, info, medias
            if not data.get("has_more") or not medias:
                return
            if max_pages is not None and pn >= max_pages:
                return
            pn += 1
            self._sleep(self.read_rate)

    def list_folder_aids(self, media_id) -> set:
        aids = set()
        for _, _, medias in self.iter_folder_resources(media_id):
            for m in medias:
                if m.get("id"):
                    aids.add(int(m["id"]))
        return aids

    def fetch_tags(self, bvid: str) -> list:
        data = self._request("GET", "/x/tag/archive/tags", params={"bvid": bvid}) or []
        return [t.get("tag_name") or "" for t in data if t.get("tag_name")]

    # ---------- 写接口（只提供新建与移动，不提供删除）----------

    def create_folder(self, title: str, intro: str = "", privacy: int = 1) -> dict:
        self._sleep(self.write_rate)
        return self._request(
            "POST",
            "/x/v3/fav/folder/add",
            data={"title": title, "intro": intro, "privacy": privacy, "csrf": self.csrf},
        )

    def move_resources(self, src_media_id, tar_media_id, aids, *, retries=3) -> None:
        """把 aids（avid 列表）从 src 收藏夹移动到 tar 收藏夹，type 固定 2（视频）。"""
        resources = ",".join(f"{aid}:2" for aid in aids)
        self._sleep(self.write_rate)
        self._request(
            "POST",
            "/x/v3/fav/resource/move",
            data={
                "src_media_id": src_media_id,
                "tar_media_id": tar_media_id,
                "mid": self.mid,
                "resources": resources,
                "platform": "web",
                "csrf": self.csrf,
            },
            retries=retries,
        )
