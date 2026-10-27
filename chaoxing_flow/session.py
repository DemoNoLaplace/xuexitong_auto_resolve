"""读取学习通客户端 Cookie 并构造 HTTP 会话。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import requests

from .config import Settings

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
COURSE_API = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&rss=1"


class CookieError(RuntimeError):
    pass


class NotLoggedIn(RuntimeError):
    pass


def _read_cookie_rows(db_path: Path) -> list[tuple[str, str, str]]:
    if not db_path.is_file():
        raise CookieError(
            f"找不到 Cookie 数据库: {db_path}\n"
            "请先启动并登录 PC 学习通客户端，至少打开一次课程。"
        )

    tmp_path: Path | None = None
    try:
        # 客户端运行时数据库可能被占用，复制一份只读快照
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(db_path, tmp_path)
        conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
        try:
            rows = list(
                conn.execute(
                    "select host_key, name, value from cookies "
                    "where host_key like '%chaoxing%' and length(value) > 0"
                )
            )
        finally:
            conn.close()
        return [(str(h), str(n), str(v)) for h, n, v in rows]
    except Exception as exc:
        raise CookieError(f"读取 Cookie 失败: {exc}") from exc
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_cookies(settings: Settings) -> dict[str, str]:
    rows = _read_cookie_rows(settings.cookies_db)
    if not rows:
        raise CookieError("Cookie 数据库为空，请先在客户端登录。")
    # 同名 Cookie 以 .chaoxing.com 为主
    cookies: dict[str, str] = {}
    for host, name, value in rows:
        if host.endswith("chaoxing.com") or name not in cookies:
            cookies[name] = value
    if "_uid" not in cookies and "UID" not in cookies:
        raise NotLoggedIn("未找到学习通登录 Cookie，请先在客户端登录。")
    return cookies


def build_session(settings: Settings, cookies: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if settings.proxy:
        session.proxies = {"http": settings.proxy, "https": settings.proxy}
    session.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    session.cookies.update(cookies or load_cookies(settings))
    return session


def check_login(session: requests.Session, timeout: int = 30) -> dict[str, Any]:
    """返回 backclazzdata 的 JSON；未登录时抛 NotLoggedIn。"""
    r = session.get(COURSE_API, timeout=timeout)
    if r.status_code != 200:
        raise NotLoggedIn(f"课程接口 HTTP {r.status_code}")
    try:
        data = r.json()
    except json.JSONDecodeError as exc:
        raise NotLoggedIn("课程接口返回的不是 JSON，登录可能已失效。") from exc
    if not data.get("result"):
        raise NotLoggedIn(str(data.get("msg") or "请重新登录"))
    return data


def refresh_session(settings: Settings) -> tuple[requests.Session, dict[str, Any]]:
    session = build_session(settings)
    try:
        data = check_login(session, settings.timeout)
    except NotLoggedIn:
        # 客户端可能在运行中刷新了 Cookie，重新读一次
        session = build_session(settings)
        data = check_login(session, settings.timeout)
    return session, data


def load_any_cookies(settings: Settings) -> dict[str, str]:
    """只读 Cookie，不检查登录，供 doctor 使用。"""
    try:
        return load_cookies(settings)
    except (CookieError, NotLoggedIn):
        return {}
