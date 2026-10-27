"""PC 学习通客户端窗口控制：启动、聚焦、一键登录。"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import uiautomation as auto

from .config import Settings, find_app_exe
from .session import NotLoggedIn, check_login, refresh_session


class AppControlError(RuntimeError):
    pass


def _iter_controls(ctrl: Any, depth: int = 0, max_depth: int = 30):
    if depth > max_depth:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:
        return
    for child in children:
        yield child
        yield from _iter_controls(child, depth + 1, max_depth)


def find_main_window() -> Any | None:
    root = auto.GetRootControl()
    candidates = []
    for win in root.GetChildren():
        try:
            name = win.Name or ""
            r = win.BoundingRectangle
            if "学习通" in name and r.width() > 400 and r.height() > 300:
                candidates.append(win)
        except Exception:
            pass
    if not candidates:
        return None
    return max(candidates, key=lambda w: w.BoundingRectangle.width() * w.BoundingRectangle.height())


def is_app_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq cxstudy.exe", "/NH"],
            text=True,
            encoding="mbcs",
            errors="ignore",
            timeout=5,
        )
        return "cxstudy.exe" in out.lower()
    except Exception:
        return False


def launch_app(settings: Settings) -> Path:
    exe = settings.app_exe or find_app_exe()
    if not exe:
        raise AppControlError(
            "找不到 cxstudy.exe。请用 --app 指定路径，例如：\n"
            r"  --app C:\path\to\cxstudy\latest\cxstudy.exe"
        )
    if not is_app_running():
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
    return exe


def wait_main_window(timeout: int = 20) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        win = find_main_window()
        if win is not None:
            return win
        time.sleep(0.5)
    raise AppControlError("等待学习通主窗口超时")


def focus_main_window(timeout: int = 20) -> Any:
    win = wait_main_window(timeout)
    try:
        win.SetActive()
        win.SetFocus()
    except Exception:
        pass
    time.sleep(0.5)
    return win


def click_saved_login(win: Any) -> bool:
    """如果出现“用户登录”弹窗，点击其中的“登录”按钮（依赖客户端保存的会话）。"""
    login_btn = None
    for ctrl in _iter_controls(win, max_depth=25):
        try:
            if ctrl.ControlTypeName == "ButtonControl" and ctrl.Name.strip() == "登录":
                r = ctrl.BoundingRectangle
                if r.width() > 0 and r.height() > 0:
                    login_btn = ctrl
                    break
        except Exception:
            pass
    if login_btn is None:
        return False
    try:
        login_btn.Click()
        return True
    except Exception as exc:
        raise AppControlError(f"点击登录按钮失败: {exc}") from exc


def ensure_login(settings: Settings, interactive: bool = True) -> Any:
    """返回已登录的 requests.Session；必要时启动客户端并点击一键登录。"""
    session = None
    try:
        session, _ = refresh_session(settings)
    except NotLoggedIn:
        pass

    win = None
    if session is None:
        launch_app(settings)
        win = focus_main_window()
        click_saved_login(win)
        time.sleep(3)
        try:
            session, _ = refresh_session(settings)
        except NotLoggedIn as exc:
            if not interactive:
                raise
            print("客户端当前未登录，或保存的登录会话已失效。")
            print("请在弹出的学习通窗口中完成登录，登录成功后回到这里按 Enter。")
            input()
            session, _ = refresh_session(settings)

    if session is None:
        raise AppControlError("登录校验失败")
    return session


def open_app(settings: Settings) -> None:
    launch_app(settings)
    win = focus_main_window()
    click_saved_login(win)
