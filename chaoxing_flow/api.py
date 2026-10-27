"""学习通网页接口封装：课程、章节、文档、作业、暂存。"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .fontmap import FontDecoder, decode
from .models import Attachment, Chapter, Course, Question, TaskPointResult, WorkPage

MOOC1 = "https://mooc1.chaoxing.com"
MOOC2 = "https://mooc2-ans.chaoxing.com"


class ChaoxingError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _normalize_judgement_label(label: str, text: str) -> str:
    """判断题的 data 可能是 true/false，也可能是 A/B，用选项文字兜底。"""
    value = (label or "").strip().lower()
    if value in ("true", "false"):
        return value
    option = (text or "").strip()
    if option in ("对", "正确", "是"):
        return "true"
    if option in ("错", "错误", "否"):
        return "false"
    if value in ("a", "t", "1"):
        return "true"
    if value in ("b", "f", "0"):
        return "false"
    return value


def _request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> requests.Response:
    """带重试的请求；代理偶尔抖动时自动重试。"""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = session.request(method, url, timeout=timeout, **kwargs)
            if r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except (requests.RequestException, requests.HTTPError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise ChaoxingError(f"请求失败: {url}\n{last_exc}") from last_exc


class ChaoxingClient:
    def __init__(self, session: requests.Session, settings: Settings):
        self.session = session
        self.settings = settings

    # ---------- 课程 ----------
    def list_courses(self) -> list[Course]:
        r = _request(
            self.session,
            "GET",
            "https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&rss=1",
            timeout=self.settings.timeout,
        )
        data = r.json()
        if not data.get("result"):
            raise ChaoxingError(data.get("msg") or "课程列表获取失败")
        result: list[Course] = []
        seen: set[tuple[str, str]] = set()
        for item in data.get("channelList", []):
            content = item.get("content") or {}
            course_data = ((content.get("course") or {}).get("data") or [])
            if not course_data:
                continue
            info = course_data[0]
            course_id = str(info.get("id") or "")
            class_id = str(content.get("id") or item.get("id") or "")
            cpi = str(item.get("cpi") or content.get("cpi") or "")
            name = str(info.get("name") or content.get("name") or "")
            if not course_id or not class_id or not cpi:
                continue
            key = (course_id, class_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                Course(
                    course_id=course_id,
                    class_id=class_id,
                    cpi=cpi,
                    name=name,
                    teacher=str(content.get("teacher") or info.get("teacher") or ""),
                    image=str(info.get("imageurl") or ""),
                )
            )
        return result

    def find_course(self, query: str) -> Course:
        courses = self.list_courses()
        q = query.strip().lower()
        exact = [c for c in courses if c.name.strip().lower() == q]
        if exact:
            return exact[0]
        matches = [c for c in courses if q in c.name.lower()]
        if not matches:
            names = "\n".join(f"  - {c.name} ({c.course_id})" for c in courses)
            raise ChaoxingError(f"找不到课程“{query}”。可选课程：\n{names}")
        if len(matches) > 1:
            lines = "\n".join(f"  - {c.name} | courseId={c.course_id}" for c in matches)
            raise ChaoxingError(f"课程名不唯一，请写得更具体：\n{lines}")
        return matches[0]

    def course_enc(self, course: Course) -> str:
        r = _request(
            self.session,
            "GET",
            f"{MOOC2}/mooc2-ans/mycourse/studentcourse",
            timeout=self.settings.timeout,
            params={
                "courseid": course.course_id,
                "clazzid": course.class_id,
                "cpi": course.cpi,
                "ut": "s",
                "t": str(int(time.time() * 1000)),
            },
        )
        m = re.search(r'id="enc"[^>]*value="([^"]+)"', r.text)
        if not m:
            m = re.search(r'name="enc"[^>]*value="([^"]+)"', r.text)
        if not m:
            raise ChaoxingError("无法从课程页解析 enc 参数")
        return m.group(1)

    # ---------- 章节 ----------
    def chapters(self, course: Course, enc: str | None = None) -> list[Chapter]:
        enc = enc or self.course_enc(course)
        r = _request(
            self.session,
            "GET",
            f"{MOOC1}/mycourse/studentstudycourselist",
            timeout=self.settings.timeout,
            params={
                "courseId": course.course_id,
                "chapterId": "0",
                "clazzid": course.class_id,
                "cpi": course.cpi,
                "mooc2": "1",
                "isMicroCourse": "false",
            },
            headers={"Referer": f"{MOOC1}/mycourse/studentstudy?chapterId=0&courseId={course.course_id}"},
        )
        soup = BeautifulSoup(r.text, "html.parser")
        result: list[Chapter] = []
        seen: set[str] = set()
        for div in soup.select("div.posCatalog_select"):
            raw_id = div.get("id") or ""
            chapter_id = raw_id[3:] if raw_id.startswith("cur") else raw_id
            if not chapter_id.isdigit() or chapter_id in seen:
                continue
            seen.add(chapter_id)
            title_el = div.select_one(".posCatalog_title") or div.select_one(".posCatalog_name")
            title = ""
            if title_el:
                title = title_el.get("title") or title_el.get_text(" ", strip=True)
            title = _clean(title or div.get("title") or "")
            number = ""
            num_el = div.select_one(".posCatalog_sbar")
            if num_el:
                number = num_el.get_text(strip=True)
            # 去掉标题开头的编号
            title = re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", title).strip()
            status = ""
            if div.select_one(".icon_Completed"):
                status = "已完成"
            elif div.select_one(".icon_NotCompleted"):
                status = "未完成"
            job_count = 0
            for j in div.select(".jobUnfinishCount"):
                val = j.get("value") or j.get_text(strip=True)
                try:
                    job_count += int(val)
                except (TypeError, ValueError):
                    pass
            result.append(
                Chapter(
                    chapter_id=chapter_id,
                    title=title,
                    number=number,
                    status=status,
                    job_count=job_count,
                )
            )
        return result

    def find_chapter(self, course: Course, query: str) -> Chapter:
        chapters = self.chapters(course)
        q = query.strip().lower()
        exact = [c for c in chapters if c.number == q or c.title.lower() == q]
        if exact:
            return exact[0]
        matches = [c for c in chapters if q in c.number.lower() or q in c.title.lower()]
        if not matches:
            lines = "\n".join(f"  - {c.number} {c.title} ({c.chapter_id})" for c in chapters)
            raise ChaoxingError(f"找不到章节“{query}”。可选章节：\n{lines}")
        if len(matches) > 1:
            lines = "\n".join(f"  - {c.number} {c.title} ({c.chapter_id})" for c in matches)
            raise ChaoxingError(f"章节不唯一，请写得更具体：\n{lines}")
        return matches[0]

    # ---------- 卡片 / 附件 ----------
    @dataclass
    class Cards:
        attachments: list[Attachment]
        defaults: dict[str, Any]
        title: str

    def get_marg(self, course: Course, chapter: Chapter) -> dict[str, Any]:
        r = _request(
            self.session,
            "GET",
            f"{MOOC1}/mooc-ans/knowledge/cards",
            timeout=self.settings.timeout,
            params={
                "clazzid": course.class_id,
                "courseid": course.course_id,
                "knowledgeid": chapter.chapter_id,
                "num": "0",
                "ut": "s",
                "cpi": course.cpi,
                "v": "2025-0424-1038-4",
                "mooc2": "1",
                "isMicroCourse": "false",
                "editorPreview": "0",
                "crossId": "",
            },
            headers={
                "Referer": (
                    f"{MOOC1}/mycourse/studentstudy?chapterId={chapter.chapter_id}"
                    f"&courseId={course.course_id}&clazzid={course.class_id}&cpi={course.cpi}"
                )
            },
        )
        text = r.text
        m = re.search(r"mArg\s*=\s*(\{)", text)
        if not m:
            raise ChaoxingError("章节页中找不到 mArg 数据")
        payload = text[m.start(1) :]
        try:
            marg, _ = json.JSONDecoder().raw_decode(payload)
        except json.JSONDecodeError as exc:
            raise ChaoxingError("解析章节 mArg 失败") from exc
        if not isinstance(marg, dict):
            raise ChaoxingError("章节 mArg 格式异常")
        return marg

    def cards(self, course: Course, chapter: Chapter) -> "ChaoxingClient.Cards":
        marg = self.get_marg(course, chapter)

        attachments: list[Attachment] = []
        for att in marg.get("attachments", []):
            prop = att.get("property") or {}
            module = str(prop.get("module") or att.get("type") or "")
            if module == "insertdoc" or prop.get("objectid"):
                attachments.append(
                    Attachment(
                        kind="document",
                        title=str(prop.get("title") or prop.get("name") or ""),
                        object_id=str(prop.get("objectid") or ""),
                        enc=str(att.get("enc") or ""),
                        job_id=str(prop.get("jobid") or att.get("jobid") or ""),
                        mid=str(prop.get("mid") or att.get("mid") or ""),
                        size=int(prop.get("size") or 0),
                        file_type=str(prop.get("type") or ""),
                    )
                )
            if module == "work" or prop.get("workid"):
                attachments.append(
                    Attachment(
                        kind="work",
                        title=str(prop.get("title") or "章节测验"),
                        work_id=str(prop.get("workid") or ""),
                        enc=str(att.get("enc") or ""),
                        job_id=str(prop.get("jobid") or att.get("jobid") or ""),
                        mid=str(prop.get("mid") or att.get("mid") or ""),
                    )
                )
        return ChaoxingClient.Cards(
            attachments=attachments,
            defaults=marg.get("defaults") or {},
            title=str(marg.get("knowledgename") or chapter.title),
        )

    # ---------- 任务点 ----------
    def complete_jobs(
        self,
        course: Course,
        chapter: Chapter,
        delay: float = 1.0,
    ) -> list[TaskPointResult]:
        """完成章节任务点。

        目前支持文档类任务点（PDF/PPT/Word 等）。视频/音频需要模拟播放，
        作业任务点需要提交作业，均不在本方法内静默处理。
        """
        marg = self.get_marg(course, chapter)
        results: list[TaskPointResult] = []
        pending = [att for att in marg.get("attachments", []) if att.get("job")]
        for index, att in enumerate(pending):
            prop = att.get("property") or {}
            title = str(prop.get("title") or prop.get("name") or "任务点")
            kind = str(att.get("type") or prop.get("module") or "")
            job_id = str(
                att.get("jobid") or prop.get("jobid") or prop.get("_jobid") or ""
            )
            if not job_id:
                results.append(TaskPointResult("", title, kind, False, "缺少 jobid"))
                continue

            if kind == "document":
                jtoken = str(att.get("jtoken") or "")
                if not jtoken:
                    results.append(TaskPointResult(job_id, title, kind, False, "缺少 jtoken"))
                    continue
                try:
                    r = _request(
                        self.session,
                        "GET",
                        f"{MOOC1}/ananas/job/document",
                        timeout=self.settings.timeout,
                        params={
                            "jobid": job_id,
                            "knowledgeid": chapter.chapter_id,
                            "courseid": course.course_id,
                            "clazzid": course.class_id,
                            "jtoken": jtoken,
                        },
                        headers={
                            "Referer": (
                                f"{MOOC1}/mycourse/studentstudy?chapterId={chapter.chapter_id}"
                                f"&courseId={course.course_id}&clazzid={course.class_id}"
                                f"&cpi={course.cpi}"
                            )
                        },
                    )
                    try:
                        data = r.json()
                    except ValueError:
                        data = {}
                    ok = bool(data.get("status"))
                    message = str(
                        data.get("msg") or ("完成" if ok else f"HTTP {r.status_code}")
                    )
                    results.append(TaskPointResult(job_id, title, kind, ok, message))
                except Exception as exc:
                    results.append(TaskPointResult(job_id, title, kind, False, str(exc)))
            elif kind in ("workid", "work"):
                results.append(
                    TaskPointResult(
                        job_id,
                        title,
                        "workid",
                        False,
                        "作业任务点需提交作业（并可能需要等待批阅）后才会完成；"
                        "本工具不会提交作业",
                    )
                )
            elif kind in ("video", "audio"):
                results.append(
                    TaskPointResult(job_id, title, kind, False, "暂不支持视频/音频任务点")
                )
            else:
                results.append(
                    TaskPointResult(job_id, title, kind, False, f"暂不支持的任务点类型: {kind}")
                )

            if index < len(pending) - 1 and delay > 0:
                time.sleep(delay)
        return results

    # ---------- 作业 ----------
    def open_work(self, course: Course, chapter: Chapter, att: Attachment, ktoken: str = "") -> WorkPage:
        if not att.work_id:
            raise ChaoxingError("作业附件缺少 workid")
        params = {
            "workId": att.work_id,
            "courseid": course.course_id,
            "knowledgeid": chapter.chapter_id,
            "userid": "",
            "ut": "s",
            "classId": course.class_id,
            "jobid": att.job_id or f"work-{att.work_id}",
            "type": "",
            "isphone": "false",
            "submit": "false",
            "enc": att.enc,
            "utenc": "",
            "cpi": course.cpi,
            "ktoken": ktoken,
            "mooc2": "1",
            "skipHeader": "true",
            "workExtInfoEnc": "null",
            "oriNodeId": "0",
            "originJobId": att.job_id or f"work-{att.work_id}",
            "teacherPreview": "0",
            "fromType": "",
        }
        r = _request(
            self.session,
            "GET",
            f"{MOOC1}/mooc-ans/workHandle/handle",
            timeout=self.settings.timeout,
            params=params,
            allow_redirects=True,
            headers={
                "Referer": (
                    f"{MOOC1}/mycourse/studentstudy?chapterId={chapter.chapter_id}"
                    f"&courseId={course.course_id}&clazzid={course.class_id}&cpi={course.cpi}"
                )
            },
        )
        if "doHomeWorkNew" not in r.url and "questionLi" not in r.text and "TiMu" not in r.text:
            raise ChaoxingError(f"未能打开作业页面，最终地址: {r.url}")
        decoder = FontDecoder.from_html(r.text, cache_dir=self.settings.cache_dir / "fontmaps")
        return self.parse_work(r.text, r.url, decoder)

    @staticmethod
    def parse_work(
        html_text: str,
        url: str,
        font_decoder: FontDecoder | None = None,
    ) -> WorkPage:
        soup = BeautifulSoup(html_text, "html.parser")
        # 查看/已评分页面也可能有一个 form1，但题目不在 form 内；
        # 因此只选择真正包含 .TiMu 的表单。
        form = None
        for candidate in soup.find_all("form"):
            if candidate.select_one(".TiMu"):
                form = candidate
                break
        has_form = form is not None
        root = form or soup

        decoder = font_decoder or FontDecoder.from_html(html_text)
        if decoder is None:
            decode_text = decode
            if "font-cxsecret" in html_text:
                print(
                    "[警告] 页面使用了 font-cxsecret 字体，但未能解析内嵌字体；"
                    "将使用旧映射兜底，题干可能有误。"
                )
        else:
            decode_text = decoder.decode
            if decoder.unknown:
                print(
                    f"[提示] 字体解码有 {len(decoder.unknown)} 个字符未能识别，"
                    "题干中可能仍有乱码。"
                )

        fields: list[tuple[str, str]] = []
        if form:
            for inp in form.find_all("input"):
                name = inp.get("name")
                if name:
                    fields.append((str(name), str(inp.get("value") or "")))
            for ta in form.find_all("textarea"):
                name = ta.get("name")
                if name:
                    fields.append((str(name), ta.get_text() or ""))

        field_map = dict(fields)
        enc_work = field_map.get("enc_work", "")
        total = field_map.get("totalQuestionNum", "")

        questions: list[Question] = []
        for qel in root.select(".TiMu"):
            type_el = qel.select_one(".newZy_TItle")
            type_text = _clean(type_el.get_text(" ", strip=True)) if type_el else ""
            qtype = decode_text(type_text.strip("【】"))
            if not qtype:
                qtype = "未知"
            stem_el = qel.select_one(".Zy_TItle")
            stem = _clean(stem_el.get_text(" ", strip=True)) if stem_el else ""
            stem = stem.replace(type_text, "", 1).strip()
            stem = re.sub(r"^\s*\d+\s*", "", stem)
            stem = decode_text(stem)

            qid = ""
            parent = qel if "singleQuesId" in (qel.get("class") or []) else qel.find_parent(
                "div", class_="singleQuesId"
            )
            if parent and parent.get("data"):
                qid = str(parent.get("data"))
            if not qid:
                for inp in qel.find_all("input"):
                    name = str(inp.get("name") or "")
                    m = re.fullmatch(r"answer(\d+)", name)
                    if m:
                        qid = m.group(1)
                        break
            if not qid:
                continue

            options: dict[str, str] = {}
            option_display: dict[str, str] = {}
            for li in qel.select(".Zy_ulTop li"):
                num = li.select_one(".num_option, .num_option_dx")
                label = ""
                visible = ""
                if num:
                    label = _clean(str(num.get("data") or ""))
                    visible = _clean(num.get_text(" ", strip=True))
                if not label:
                    letter_el = li.select_one("i")
                    if letter_el:
                        label = re.sub(r"[、.．\s]", "", letter_el.get_text(strip=True))
                a = li.select_one("a")
                text = _clean(a.get_text(" ", strip=True)) if a else _clean(
                    li.get_text(" ", strip=True)
                )
                if qtype == "判断题":
                    label = _normalize_judgement_label(label, text)
                else:
                    label = label.strip()[:1].upper()
                if label and text:
                    options[label] = decode_text(text)
                    if qtype != "判断题" and visible:
                        shown = visible.strip()[:1].upper()
                        if shown and shown != label:
                            option_display[label] = shown

            current = ""
            for name, value in fields:
                if name == f"answer{qid}":
                    current = decode_text(value)
                    break
            if not current:
                ans_el = qel.select_one(".answerCon")
                if ans_el:
                    current = decode_text(_clean(ans_el.get_text(" ", strip=True)))
            blank_count = 1
            for name, value in fields:
                if name == f"tiankongsize{qid}":
                    try:
                        blank_count = int(value)
                    except ValueError:
                        pass
            questions.append(
                Question(
                    qid=qid,
                    qtype=qtype,
                    stem=stem,
                    options=options,
                    option_display=option_display,
                    current_answer=current,
                    blank_count=blank_count,
                )
            )

        return WorkPage(
            url=url,
            form_action=(form.get("action") or "") if form else "",
            fields=fields,
            questions=questions,
            enc_work=enc_work,
            total_question_num=total,
        )


    # ---------- 暂存 ----------
    def save_work(self, work: WorkPage, answers: dict[str, str]) -> dict[str, Any]:
        """只调用“暂时保存”，绝不提交。

        answers: question_id -> 答案。单选 A/B/C/D；判断 true/false；
        多选 ABC；简答/填空为文本。
        """
        if not work.form_action:
            raise ChaoxingError("当前作业是查看/已评分状态，页面没有可编辑表单，无法暂存修改。")
        if not work.enc_work:
            raise ChaoxingError("缺少 enc_work，无法暂存")

        # 保留表单全部字段，替换答案
        data: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name, value in work.fields:
            if name.startswith("answerEditor"):
                # 形如 answerEditor<qid><blankIndex>
                m = re.match(r"answerEditor(\d+)(\d+)$", name)
                if m and m.group(1) in answers:
                    value = answers[m.group(1)]
            elif name.startswith("answer") and name[6:] in answers:
                value = answers[name[6:]]
            data.append((name, value))
            seen.add(name)

        # 补充缺失的答案字段
        for q in work.questions:
            if q.qid not in answers:
                continue
            if q.qtype == "填空题":
                key = f"answerEditor{q.qid}1"
            else:
                key = f"answer{q.qid}"
            if key not in seen:
                data.append((key, answers[q.qid]))
                seen.add(key)

        # 覆盖 pyFlag / answerwqbid
        replaced: list[tuple[str, str]] = []
        for name, value in data:
            if name == "pyFlag":
                value = "1"
            elif name == "answerwqbid":
                value = ",".join(q.qid for q in work.questions)
            replaced.append((name, value))
        data = replaced
        if "pyFlag" not in seen:
            data.append(("pyFlag", "1"))
        if "answerwqbid" not in seen:
            data.append(("answerwqbid", ",".join(q.qid for q in work.questions)))

        action_qs = parse_qs(urlparse(work.form_action).query)
        class_id = (action_qs.get("_classId") or [""])[0] or dict(work.fields).get("classId", "")
        course_id = (action_qs.get("courseid") or [""])[0] or dict(work.fields).get("courseId", "")
        total = work.total_question_num or dict(work.fields).get("totalQuestionNum", "")

        params = {
            "_classId": class_id,
            "courseid": course_id,
            "token": work.enc_work,
            "totalQuestionNum": total,
            "ua": "pc",
            "formType": "post",
            "saveStatus": "1",
            "version": "1",
            "tempsave": "1",  # 只暂存
        }
        assert params["tempsave"] == "1" and "submit" not in params

        r = _request(
            self.session,
            "POST",
            f"{MOOC1}/mooc-ans/work/addStudentWorkNew",
            timeout=max(60, self.settings.timeout),
            params=params,
            data=data,
            headers={
                "Referer": work.url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        try:
            result = r.json()
        except json.JSONDecodeError:
            result = {"status": False, "msg": r.text[:500]}
        return result


def attachment_summary(att: Attachment) -> str:
    if att.kind == "work":
        return f"作业/测验: {att.title} (workid={att.work_id})"
    return f"文档: {att.title} ({att.file_type}, objectid={att.object_id})"
