"""配置、路径和 Windows 代理探测。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows 环境仅用于单元测试
    winreg = None  # type: ignore


APP_TITLE = "学习通"
APP_PROCESS = "cxstudy.exe"

DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"

# 已成功读取的 .env 文件，供 doctor 命令展示
LOADED_ENV_FILES: list[Path] = []


def package_root() -> Path:
    """源码运行时是项目根目录；PyInstaller 单文件运行时是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def env_file_candidates() -> list[Path]:
    """按优先级列出可能存在的 .env 文件，可用 CX_ENV_FILE 指定。"""
    candidates: list[Path] = []
    explicit = os.environ.get("CX_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    root = package_root()
    for base in (root, Path.cwd(), root / "dist", root.parent):
        candidates.append(base / ".env")
    found: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(resolved)
    return found


def _parse_env_file(path: Path) -> dict[str, str]:
    """解析简单的 KEY=VALUE 文件；支持引号、export 前缀和 # 注释。"""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def load_env_files() -> list[Path]:
    """加载 .env 到进程环境变量；已存在的环境变量优先，不会被覆盖。"""
    if LOADED_ENV_FILES:
        return LOADED_ENV_FILES
    for path in env_file_candidates():
        if not path.is_file():
            continue
        for key, value in _parse_env_file(path).items():
            if os.environ.get(key):
                continue
            os.environ[key] = value
        LOADED_ENV_FILES.append(path)
    return LOADED_ENV_FILES


def llm_api_key() -> str:
    load_env_files()
    return (os.environ.get("CX_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()


def llm_base_url() -> str:
    load_env_files()
    raw = (
        os.environ.get("CX_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_LLM_BASE_URL
    )
    return raw.strip().rstrip("/")


def llm_model() -> str:
    load_env_files()
    raw = os.environ.get("CX_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_LLM_MODEL
    return raw.strip()


def default_app_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "cxstudy"


def find_app_exe(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            return p
        if p.is_dir() and (p / APP_PROCESS).is_file():
            return p / APP_PROCESS
        raise FileNotFoundError(f"找不到学习通程序: {p}")

    candidates: list[Path] = []
    candidates.append(Path.cwd() / "cxstudy" / "latest" / APP_PROCESS)
    candidates.append(package_root() / "cxstudy" / "latest" / APP_PROCESS)
    candidates.append(package_root().parent / "cxstudy" / "latest" / APP_PROCESS)

    for parent in [Path.cwd(), *Path.cwd().parents, package_root()]:
        candidates.append(parent / "cxstudy" / "latest" / APP_PROCESS)
        candidates.append(parent / "cxstudy" / APP_PROCESS)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    # 兜底：在常见安装位置查找
    for base in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path("C:/Program Files"),
        Path("D:/"),
    ]:
        if not base.exists():
            continue
        try:
            for p in base.glob("**/cxstudy/latest/cxstudy.exe"):
                return p.resolve()
        except (OSError, PermissionError):
            pass
    return None


def detect_windows_proxy() -> str | None:
    """读取 IE/系统代理。返回形如 http://127.0.0.1:7890 的地址。"""
    if winreg is None:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        winreg.CloseKey(key)
        if not enabled or not server:
            return None
        server = str(server).strip()
        if "=" in server:
            # 形如 http=127.0.0.1:7890;https=127.0.0.1:7890
            parts = dict(item.split("=", 1) for item in server.split(";") if "=" in item)
            server = parts.get("https") or parts.get("http") or next(iter(parts.values()))
        if not server.startswith(("http://", "https://")):
            server = "http://" + server
        return server
    except Exception:
        return None


@dataclass
class Settings:
    app_exe: Path | None = None
    app_data: Path = default_app_dir()
    cache_dir: Path = package_root() / "data" / "cache"
    proxy: str | None = None
    timeout: int = 30

    def prepare(self) -> "Settings":
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.proxy == "auto":
            self.proxy = detect_windows_proxy()
        return self

    @property
    def cookies_db(self) -> Path:
        return self.app_data / "Network" / "Cookies"
