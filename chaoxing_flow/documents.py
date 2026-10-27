"""下载章节内嵌文档并抽取可读文本。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
import requests

from .config import Settings
from .models import Attachment, Material


def _safe_name(name: str, fallback: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or fallback
    return name[:120]


class DocumentReader:
    def __init__(self, session: requests.Session, settings: Settings):
        self.session = session
        self.settings = settings

    def _status(self, object_id: str) -> dict:
        url = f"https://mooc1.chaoxing.com/ananas/status/{object_id}?flag=normal"
        r = self.session.get(
            url,
            timeout=self.settings.timeout,
            headers={"Referer": "https://mooc1.chaoxing.com/ananas/modules/ppt/index.html"},
        )
        r.raise_for_status()
        return r.json()

    def fetch(self, attachment: Attachment) -> Material:
        if not attachment.object_id:
            raise ValueError("附件缺少 objectid")
        status = self._status(attachment.object_id)
        pdf_url = status.get("pdf")
        if not pdf_url:
            raise RuntimeError(f"文档没有可用的 PDF 预览地址: {attachment.title}")

        key = hashlib.sha1(attachment.object_id.encode("utf-8")).hexdigest()[:12]
        name = _safe_name(attachment.title or key, key)
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        path = self.settings.cache_dir / f"{key}_{name}"
        if not path.is_file() or path.stat().st_size == 0:
            r = self.session.get(pdf_url, timeout=max(60, self.settings.timeout))
            r.raise_for_status()
            path.write_bytes(r.content)

        text = self._extract_pdf(path)
        return Material(
            attachment=attachment,
            text=text,
            local_path=str(path),
            source_url=pdf_url,
        )

    @staticmethod
    def _extract_pdf(path: Path) -> str:
        parts: list[str] = []
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, 1):
                page_text = page.get_text("text")
                if page_text.strip():
                    parts.append(f"\n\n--- 第 {i} 页 ---\n{page_text}")
        return "\n".join(parts).strip()

    def save_metadata(self, materials: list[Material], path: Path) -> None:
        data = [m.to_dict() for m in materials]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
