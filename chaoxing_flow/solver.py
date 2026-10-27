"""答案来源：本地答案库、OpenAI 兼容大模型、可选的关键词启发式。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import llm_api_key, llm_base_url, llm_model, load_env_files
from .models import Question


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"[，。？！,.?!：:；;（）()【】\[\]“”\"‘’'、《》<>]", "", text)
    return text.lower()


@dataclass
class SolverResult:
    answer: str
    confidence: float = 0.0
    reason: str = ""
    source: str = ""


class Solver:
    def solve(self, questions: list[Question], materials: str = "") -> dict[str, SolverResult]:
        raise NotImplementedError


class AnswerBankSolver(Solver):
    def __init__(self, bank_path: str | Path):
        self.bank_path = Path(bank_path)
        data = json.loads(self.bank_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("answers", data.get("items", []))
        self.entries: list[dict[str, Any]] = list(data)

    def solve(self, questions: list[Question], materials: str = "") -> dict[str, SolverResult]:
        out: dict[str, SolverResult] = {}
        norm_entries = []
        for entry in self.entries:
            norm_stem = normalize_text(str(entry.get("stem") or entry.get("question") or ""))
            contains = [normalize_text(str(x)) for x in entry.get("contains", [])]
            norm_entries.append((entry, norm_stem, contains))
        for q in questions:
            stem = normalize_text(q.stem)
            for entry, norm_stem, contains in norm_entries:
                if norm_stem and norm_stem == stem:
                    out[q.qid] = SolverResult(
                        answer=str(entry["answer"]),
                        confidence=1.0,
                        reason=str(entry.get("note") or "本地答案库精确匹配"),
                        source=f"bank:{self.bank_path.name}",
                    )
                    break
                if contains and all(c in stem for c in contains):
                    out[q.qid] = SolverResult(
                        answer=str(entry["answer"]),
                        confidence=0.95,
                        reason=str(entry.get("note") or "本地答案库关键词匹配"),
                        source=f"bank:{self.bank_path.name}",
                    )
                    break
        return out


class LLMSolver(Solver):
    """OpenAI 兼容的 /chat/completions 接口。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 90,
    ):
        load_env_files()
        self.api_key = (api_key or llm_api_key()).strip() or None
        self.base_url = (base_url or llm_base_url()).rstrip("/")
        self.model = model or llm_model()
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def solve(self, questions: list[Question], materials: str = "") -> dict[str, SolverResult]:
        if not self.api_key:
            from .config import LOADED_ENV_FILES, env_file_candidates

            searched = "\n".join(f"  - {p}" for p in env_file_candidates())
            loaded = "\n".join(f"  - {p}" for p in LOADED_ENV_FILES) or "  （无）"
            raise RuntimeError(
                "未配置大模型 API Key。请设置 CX_LLM_API_KEY（或 OPENAI_API_KEY），"
                "或在 .env 中写入 CX_LLM_API_KEY=...；也可用 --bank 指定本地答案库。\n"
                f"已加载的 .env：\n{loaded}\n已查找的位置：\n{searched}"
            )
        if not questions:
            return {}
        q_payload = []
        for q in questions:
            item = {
                "id": q.qid,
                "type": q.qtype,
                "stem": q.stem,
                "options": q.options,
            }
            if q.qtype == "填空题":
                item["blanks"] = q.blank_count
            q_payload.append(item)

        system = (
            "你是严谨的课程助教。只能依据提供的课程材料作答；材料没有覆盖时，"
            "把 confidence 设为 0.3 以下并在 reason 中说明。不要编造。"
            "单选题返回一个大写字母；多选题返回按字母排序的字符串（如 ABC）；"
            "判断题返回 true 或 false；简答题返回简洁中文段落；填空题只返回填空内容。"
            "只输出 JSON，不要输出 Markdown。"
        )
        user = (
            "课程材料：\n"
            + materials[:60000]
            + "\n\n题目：\n"
            + json.dumps(q_payload, ensure_ascii=False)
            + '\n\n输出格式：{"answers":[{"id":"...","answer":"...","confidence":0.0,"reason":"..."}]}'
        )
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        out: dict[str, SolverResult] = {}
        for item in data.get("answers", []):
            qid = str(item.get("id") or "")
            if not qid:
                continue
            answer = str(item.get("answer") or "").strip()
            out[qid] = SolverResult(
                answer=answer,
                confidence=float(item.get("confidence") or 0.0),
                reason=str(item.get("reason") or ""),
                source=f"llm:{self.model}",
            )
        return out


class HeuristicSolver(Solver):
    """仅做保守的关键词重合猜测，默认不启用。"""

    def __init__(self, min_margin: float = 2.0):
        self.min_margin = min_margin

    @staticmethod
    def _tokens(text: str) -> set[str]:
        text = normalize_text(text)
        words = set(re.findall(r"[a-zA-Z]{3,}", text))
        zh = re.sub(r"[a-zA-Z0-9]+", "", text)
        words.update(zh[i : i + 2] for i in range(max(0, len(zh) - 1)))
        return {w for w in words if w}

    def solve(self, questions: list[Question], materials: str = "") -> dict[str, SolverResult]:
        mat = self._tokens(materials)
        out: dict[str, SolverResult] = {}
        for q in questions:
            if q.qtype not in ("单选题", "多选题") or not q.options:
                continue
            scores = {
                label: len(self._tokens(text) & mat)
                for label, text in q.options.items()
            }
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            if not ranked:
                continue
            top_label, top = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0
            if top <= 0 or (top - second) < self.min_margin:
                continue
            if q.qtype == "单选题":
                answer = top_label
            else:
                answer = "".join(sorted(label for label, s in scores.items() if s == top))
            out[q.qid] = SolverResult(
                answer=answer,
                confidence=0.45,
                reason=f"关键词重合启发式（{top} vs {second}）",
                source="heuristic",
            )
        return out


class CompositeSolver(Solver):
    def __init__(self, solvers: Iterable[Solver], fill_missing_from_llm: bool = True):
        self.solvers = list(solvers)
        self.fill_missing_from_llm = fill_missing_from_llm

    def solve(self, questions: list[Question], materials: str = "") -> dict[str, SolverResult]:
        out: dict[str, SolverResult] = {}
        for solver in self.solvers:
            remaining = [q for q in questions if q.qid not in out]
            if not remaining:
                break
            try:
                got = solver.solve(remaining, materials)
            except Exception as exc:
                print(f"[警告] 答案源 {solver.__class__.__name__} 失败: {exc}")
                continue
            out.update({k: v for k, v in got.items() if v.answer})
        return out


def choose_solver(
    bank: str | None,
    use_llm: bool,
    allow_guess: bool = False,
    llm_model: str | None = None,
) -> Solver:
    solvers: list[Solver] = []
    if bank:
        bank_path = Path(bank)
        if bank_path.is_file():
            solvers.append(AnswerBankSolver(bank_path))
        else:
            print(f"[提示] 答案库不存在，已跳过: {bank_path}")
    if use_llm:
        solvers.append(LLMSolver(model=llm_model))
    if allow_guess:
        solvers.append(HeuristicSolver())
    if not solvers:
        raise RuntimeError("没有可用的答案来源：请指定 --bank 或 --llm")
    return CompositeSolver(solvers)
