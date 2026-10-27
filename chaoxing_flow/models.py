"""数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Course:
    course_id: str
    class_id: str
    cpi: str
    name: str
    teacher: str = ""
    image: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Chapter:
    chapter_id: str
    title: str
    number: str = ""
    status: str = ""
    job_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attachment:
    kind: str
    title: str = ""
    object_id: str = ""
    work_id: str = ""
    enc: str = ""
    job_id: str = ""
    mid: str = ""
    size: int = 0
    file_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Question:
    qid: str
    qtype: str
    stem: str
    options: dict[str, str] = field(default_factory=dict)
    option_display: dict[str, str] = field(default_factory=dict)
    current_answer: str = ""
    blank_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkPage:
    url: str
    form_action: str
    fields: list[tuple[str, str]]
    questions: list[Question]
    enc_work: str = ""
    total_question_num: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "form_action": self.form_action,
            "enc_work": self.enc_work,
            "total_question_num": self.total_question_num,
            "questions": [q.to_dict() for q in self.questions],
        }


@dataclass
class Material:
    attachment: Attachment
    text: str
    local_path: str = ""
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment": self.attachment.to_dict(),
            "local_path": self.local_path,
            "source_url": self.source_url,
            "text_chars": len(self.text),
            "text_preview": self.text[:2000],
        }


@dataclass
class TaskPointResult:
    job_id: str
    title: str
    kind: str
    ok: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
