"""超星作业页 font-cxsecret 字体混淆的解码。

说明：
- 超星部分作业页会把题干中的常用汉字替换成生僻字，再用内嵌字体把
  生僻字渲染成正确的字形。直接读取 HTML 会得到乱码。
- 同一个乱码字在不同页面可能对应不同汉字，固定映射表并不可靠。
  新版页面会把 ``font-cxsecret`` 的 TTF 子集直接内嵌在 HTML 里，
  FontDecoder 会提取该字体，把每个字形渲染成小图，再和内置的常用
  汉字字形库比对，动态得到“乱码字 -> 真实汉字”的映射。
- FONT_MAP 是早期页面的人工映射，只在无法取得内嵌字体时兜底。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}", re.I | re.S)
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*['\"]?([^;'\"]+)", re.I)
BASE64_RE = re.compile(r"base64,\s*([A-Za-z0-9+/=\s]+)", re.I)

# 字形匹配阈值：距离越小越像；margin 是第一名和第二名的差距。
MAX_DISTANCE = 0.06
MIN_MARGIN = 0.006
CACHE_VERSION = 1


FONT_MAP: dict[str, str] = {
    "偸": "现",
    "奢": "使",
    "奤": "之",
    "奦": "选",
    "奨": "用",
    "奪": "库",
    "奫": "集",
    "奯": "核",
    "奰": "个",
    "奱": "于",
    "奲": "项",
    "妸": "合",
    "媃": "域",
    "媄": "最",
    "媅": "理",
    "媈": "育",
    "媉": "物",
    "媊": "通",
    "媋": "常",
    "媌": "类",
    "媍": "包",
    "媎": "种",
    "媐": "论",
    "媑": "文",
    "媒": "综",
    "媓": "性",
    "媔": "究",
    "媕": "应",
    "媖": "具",
    "媗": "是",
    "媘": "备",
    "媙": "不",
    "媚": "严",
    "媛": "密",
    "媜": "逻",
    "媝": "充",
    "媞": "分",
    "媟": "优",
    "媠": "美",
    "媡": "语",
    "媢": "可",
    "媣": "靠",
    "媤": "数",
    "媥": "准",
    "媦": "技",
    "媧": "中",
    "媨": "首",
    "媩": "要",
    "媫": "新",
    "媬": "响",
    "媭": "力",
    "媯": "出",
    "媰": "初",
    "媱": "纪",
    "媲": "计",
    "媳": "量",
    "媵": "流",
    "媶": "硕",
    "媷": "写",
    "媸": "英",
    "媹": "士",
    "媺": "结",
    "媻": "价",
    "媼": "学",
    "媾": "表",
    "嫀": "越",
    "嫃": "复",
    "嫄": "就",
    "嫅": "杂",
    "嫆": "其",
    "嫇": "成",
    "嫈": "程",
    "嫉": "门",
    "嫊": "提",
    "嫍": "些",
    "嫎": "以",
    "嫏": "做",
    "嫐": "高",
    "嫑": "时",
    "嫓": "段",
    "嫕": "逐",
    "嫖": "式",
    "嫗": "主",
    "嫘": "发",
    "嫙": "管",
    "嬡": "影",
    "嬪": "阶",
    "溓": "科",
    "裊": "升",
    "隗": "值",
    # 4 个由上下文确认的补充字符
    "奧": "下",
    "奣": "的",
    "媏": "一",
    "媴": "与",
}


@dataclass
class DecodeResult:
    text: str
    unknown: set[str]


def decode_text(text: str) -> DecodeResult:
    unknown: set[str] = set()
    out: list[str] = []
    for ch in text:
        if ch in FONT_MAP:
            out.append(FONT_MAP[ch])
        else:
            out.append(ch)
    return DecodeResult("".join(out), unknown)


def decode(text: str) -> str:
    return decode_text(text).text


def _resource_path(name: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "chaoxing_flow" / name
    return Path(__file__).resolve().parent / name


def _default_cache_dir() -> Path:
    from .config import package_root

    return package_root() / "data" / "cache" / "fontmaps"


def _extract_fonts(html_text: str) -> list[tuple[bytes, str]]:
    """提取 HTML 中所有 font-cxsecret 的 data URI 字体。"""
    fonts: list[tuple[bytes, str]] = []
    for match in FONT_FACE_RE.finditer(html_text):
        block = match.group(0)
        family = FONT_FAMILY_RE.search(block)
        if not family or "font-cxsecret" not in family.group(1).strip().lower():
            continue
        encoded = BASE64_RE.search(block)
        if not encoded:
            continue
        raw = re.sub(r"\s+", "", encoded.group(1))
        try:
            data = base64.b64decode(raw)
        except Exception:
            continue
        if data:
            fonts.append((data, "inline"))
    return fonts


def _reference_data():
    """加载内置的常用汉字字形库。"""
    import numpy as np

    path = _resource_path("font_ref.npz")
    with np.load(path) as data:
        chars = [str(ch) for ch in data["chars"].tolist()]
        sigs = data["sigs"].astype(np.float32) / 255.0
        dim = int(data["dim"])
    return chars, sigs, dim


def _render_glyph(font, ch: str):
    from PIL import Image, ImageDraw

    canvas = Image.new("L", (120, 120), 0)
    ImageDraw.Draw(canvas).text((60, 60), ch, font=font, fill=255, anchor="mm")
    bbox = canvas.getbbox()
    if bbox is None:
        return None
    img = canvas.crop(bbox)
    w, h = img.size
    scale = 44.0 / max(w, h)
    img = img.resize(
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        Image.Resampling.LANCZOS,
    )
    out = Image.new("L", (48, 48), 0)
    out.paste(img, ((48 - img.width) // 2, (48 - img.height) // 2))
    return out


def _glyph_signature(font, ch: str, dim: int):
    import numpy as np
    from PIL import Image

    img = _render_glyph(font, ch)
    if img is None:
        return None
    small = img.resize((dim, dim), Image.Resampling.LANCZOS)
    return np.asarray(small, dtype=np.float32).reshape(-1) / 255.0


def _cache_file(cache_dir: str | Path | None, key: str) -> Path:
    base = Path(cache_dir) if cache_dir else _default_cache_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{key}.json"


def _read_cache(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    if not isinstance(data.get("mapping"), dict) or not data["mapping"]:
        return None
    return data


def _write_cache(path: Path, decoder: "FontDecoder") -> None:
    payload = {
        "version": CACHE_VERSION,
        "font_name": decoder.font_name,
        "mapping": decoder.mapping,
        "unknown": sorted(decoder.unknown),
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


@dataclass
class FontDecoder:
    """根据页面内嵌的 font-cxsecret 字体动态解码乱码字。"""

    mapping: dict[str, str] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)
    font_name: str = ""

    def decode(self, text: str) -> str:
        return "".join(self.mapping.get(ch, ch) for ch in text)

    @classmethod
    def from_html(
        cls,
        html_text: str,
        cache_dir: str | Path | None = None,
    ) -> "FontDecoder | None":
        fonts = _extract_fonts(html_text)
        if not fonts:
            return None

        key = hashlib.sha1(b"\0".join(data for data, _ in fonts)).hexdigest()[:20]
        cache_path = _cache_file(cache_dir, key)
        cached = _read_cache(cache_path)
        if cached:
            return cls(
                mapping={str(k): str(v) for k, v in cached["mapping"].items()},
                unknown=set(cached.get("unknown") or []),
                font_name=str(cached.get("font_name") or ""),
            )

        try:
            import numpy as np
            from fontTools.ttLib import TTFont
            from PIL import ImageFont
        except ImportError:
            return None

        try:
            ref_chars, ref_sigs, dim = _reference_data()
        except (OSError, ValueError):
            return None

        mapping: dict[str, str] = {}
        unknown: set[str] = set()
        font_names: list[str] = []
        for data, _source in fonts:
            try:
                tt = TTFont(io.BytesIO(data))
            except Exception:
                continue
            try:
                name = tt["name"].getDebugName(1) or ""
            except Exception:
                name = ""
            if name:
                font_names.append(name)
            cmap = tt.getBestCmap() or {}
            try:
                pil_font = ImageFont.truetype(io.BytesIO(data), 80)
            except Exception:
                continue
            for cp in cmap:
                obf = chr(cp)
                sig = _glyph_signature(pil_font, obf, dim)
                if sig is None:
                    unknown.add(obf)
                    continue
                distances = ((ref_sigs - sig) ** 2).mean(axis=1)
                order = np.argsort(distances)
                best_index = int(order[0])
                best_distance = float(distances[best_index])
                second_distance = (
                    float(distances[int(order[1])]) if len(order) > 1 else 1.0
                )
                if best_distance <= MAX_DISTANCE and (second_distance - best_distance) >= MIN_MARGIN:
                    mapping[obf] = ref_chars[best_index]
                else:
                    unknown.add(obf)

        if not mapping:
            return None
        decoder = cls(
            mapping=mapping,
            unknown=unknown,
            font_name=", ".join(dict.fromkeys(font_names)),
        )
        _write_cache(cache_path, decoder)
        return decoder
