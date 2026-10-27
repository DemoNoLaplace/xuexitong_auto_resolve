"""命令行入口：接入客户端、找课程/章节、读文档、做题、仅暂存。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .api import ChaoxingClient, ChaoxingError, attachment_summary
from .app_control import AppControlError, ensure_login, open_app
from .config import (
    Settings,
    find_app_exe,
    llm_api_key,
    llm_base_url,
    llm_model,
    load_env_files,
    package_root,
)
from .documents import DocumentReader
from .models import Chapter, Course, Material, WorkPage
from .session import CookieError, NotLoggedIn, load_any_cookies
from .solver import AnswerBankSolver, SolverResult, choose_solver, normalize_text


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings(
        app_exe=Path(args.app).expanduser() if args.app else find_app_exe(),
        cache_dir=Path(args.cache).expanduser() if args.cache else package_root() / "data" / "cache",
        proxy=args.proxy,
        timeout=args.timeout,
    )
    return settings.prepare()


def _client(args: argparse.Namespace, need_login: bool = True) -> tuple[ChaoxingClient, Settings]:
    settings = _settings(args)
    if need_login:
        session = ensure_login(settings, interactive=not args.non_interactive)
    else:
        from .session import refresh_session

        session, _ = refresh_session(settings)
    return ChaoxingClient(session, settings), settings


def _resolve_course(client: ChaoxingClient, args: argparse.Namespace) -> Course:
    if getattr(args, "course_id", None):
        missing = [x for x in ("class_id", "cpi") if not getattr(args, x)]
        if missing:
            raise ChaoxingError("使用 --course-id 时还需要 --class-id 和 --cpi")
        return Course(
            course_id=args.course_id,
            class_id=args.class_id,
            cpi=args.cpi,
            name=args.course or args.course_id,
        )
    if not args.course:
        raise ChaoxingError("请用 --course 指定课程名，或提供 --course-id/--class-id/--cpi")
    return client.find_course(args.course)


def _resolve_chapter(client: ChaoxingClient, course: Course, args: argparse.Namespace) -> Chapter:
    if getattr(args, "chapter_id", None):
        return Chapter(chapter_id=args.chapter_id, title=args.chapter or args.chapter_id)
    if not args.chapter:
        raise ChaoxingError("请用 --chapter 指定章节，例如 5.1")
    return client.find_chapter(course, args.chapter)


def _pick_work(attachments, selector: str | None):
    works = [a for a in attachments if a.kind == "work" and a.work_id]
    if not works:
        raise ChaoxingError("该章节没有找到作业/测验；如果只有阅读材料，请用 materials 命令。")
    if selector:
        sel = selector.strip().lower()
        matched = [
            w
            for i, w in enumerate(works, 1)
            if sel == str(i) or sel in w.work_id.lower() or sel in w.title.lower()
        ]
        if not matched:
            lines = "\n".join(f"  {i}. {attachment_summary(w)}" for i, w in enumerate(works, 1))
            raise ChaoxingError(f"找不到指定作业。可选：\n{lines}")
        return matched[0]
    return works[0]


def _load_work(
    client: ChaoxingClient, course: Course, chapter: Chapter, work_selector: str | None
) -> tuple[WorkPage, Any]:
    cards = client.cards(course, chapter)
    att = _pick_work(cards.attachments, work_selector)
    work = client.open_work(course, chapter, att, ktoken=str(cards.defaults.get("ktoken") or ""))
    return work, cards


def _print_questions(work: WorkPage) -> None:
    print(f"\n作业：{work.url.split('?')[0]}")
    print(f"题目数：{len(work.questions)}")
    for i, q in enumerate(work.questions, 1):
        print(f"\n[{i}] {q.qtype}  id={q.qid}")
        print(f"    {q.stem}")
        for label, text in q.options.items():
            shown = q.option_display.get(label)
            suffix = f"  [界面 {shown}]" if shown else ""
            print(f"    {label}. {text}{suffix}")
        if q.qtype in ("简答题", "填空题"):
            print(f"    （当前答案：{q.current_answer or '空'}）")


def _materials(
    client: ChaoxingClient,
    settings: Settings,
    course: Course,
    chapter: Chapter,
) -> tuple[list[Material], Any]:
    cards = client.cards(course, chapter)
    docs = [a for a in cards.attachments if a.kind == "document" and a.object_id]
    if not docs:
        raise ChaoxingError("该章节没有内嵌文档/PPT。")
    reader = DocumentReader(client.session, settings)
    materials: list[Material] = []
    for att in docs:
        print(f"下载并解析：{att.title or att.object_id} ...")
        mat = reader.fetch(att)
        materials.append(mat)
        print(f"  -> {mat.local_path}，提取 {len(mat.text)} 字")
    out_dir = settings.cache_dir / f"chapter_{chapter.chapter_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    combined = "\n\n".join(m.text for m in materials if m.text)
    (out_dir / "materials.txt").write_text(combined, encoding="utf-8")
    (out_dir / "materials.json").write_text(
        json.dumps([m.to_dict() for m in materials], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return materials, cards


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"项目目录: {package_root()}")
    print(f"学习通程序: {settings.app_exe or '未找到'}")
    print(f"客户端数据: {settings.app_data}")
    print(f"Cookie 文件: {settings.cookies_db} ({'存在' if settings.cookies_db.is_file() else '不存在'})")
    print(f"代理: {settings.proxy or '直连'}")
    env_files = load_env_files()
    print(f"环境文件: {', '.join(str(p) for p in env_files) if env_files else '未找到 .env'}")
    key = llm_api_key()
    if key:
        masked = key if len(key) <= 8 else f"{key[:5]}...{key[-4:]}"
        print(f"大模型 Key: 已配置 ({masked})")
    else:
        print("大模型 Key: 未配置（在 exe 同目录 .env 中设置 CX_LLM_API_KEY）")
    print(f"大模型接口: {llm_base_url()}")
    print(f"大模型名称: {llm_model()}")
    cookies = load_any_cookies(settings)
    print(f"可读 Cookie 数量: {len(cookies)}")
    try:
        client, _ = _client(args, need_login=True)
        courses = client.list_courses()
        print(f"登录校验: OK，课程数 {len(courses)}")
        for c in courses[:20]:
            print(f"  - {c.name}  courseId={c.course_id} classId={c.class_id} cpi={c.cpi}")
    except (Exception, KeyboardInterrupt) as exc:
        print(f"登录/课程校验失败: {exc}")
        return 1
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    open_app(settings)
    ensure_login(settings, interactive=True)
    print("学习通客户端已启动并完成登录校验。")
    return 0


def cmd_courses(args: argparse.Namespace) -> int:
    client, _ = _client(args)
    courses = client.list_courses()
    if args.json:
        _print_json([c.to_dict() for c in courses])
    else:
        for i, c in enumerate(courses, 1):
            print(f"{i:>2}. {c.name}")
            print(f"    courseId={c.course_id}  classId={c.class_id}  cpi={c.cpi}")
    return 0


def cmd_chapters(args: argparse.Namespace) -> int:
    client, _ = _client(args)
    course = _resolve_course(client, args)
    chapters = client.chapters(course)
    if args.json:
        _print_json([c.to_dict() for c in chapters])
    else:
        print(f"课程：{course.name}")
        for c in chapters:
            status = f" [{c.status}]" if c.status else ""
            jobs = f" ({c.job_count} 个待完成任务点)" if c.job_count else ""
            print(f"  {c.number:>6}  {c.title}{status}{jobs}  id={c.chapter_id}")
    return 0


def cmd_materials(args: argparse.Namespace) -> int:
    client, settings = _client(args)
    course = _resolve_course(client, args)
    chapter = _resolve_chapter(client, course, args)
    materials, _ = _materials(client, settings, course, chapter)
    for m in materials:
        print(f"\n===== {m.attachment.title} =====")
        print(m.text[: args.preview] + ("\n..." if len(m.text) > args.preview else ""))
    return 0


def cmd_questions(args: argparse.Namespace) -> int:
    client, _ = _client(args)
    course = _resolve_course(client, args)
    chapter = _resolve_chapter(client, course, args)
    work, _ = _load_work(client, course, chapter, args.work)
    if args.json:
        _print_json(work.to_dict())
    else:
        _print_questions(work)
    return 0


def _normalize_answer(q, answer: str) -> str:
    """把大模型/答案库返回的答案统一成平台需要的格式。"""
    ans = (answer or "").strip()
    if q.qtype in ("单选题", "多选题"):
        valid = {str(key).upper() for key in (q.options or {}) if len(str(key)) == 1}
        letters = "".join(sorted({ch for ch in re.findall(r"[A-Z]", ans.upper()) if not valid or ch in valid}))
        if not letters:
            letters = "".join(sorted(set(re.findall(r"[A-Da-d]", ans.upper()))))
        if q.qtype == "单选题":
            return letters[:1]
        return letters
    if q.qtype == "判断题":
        low = ans.lower().strip("。. ")
        if low in ("true", "对", "正确", "a", "是", "t", "1"):
            return "true"
        if low in ("false", "错", "错误", "b", "否", "f", "0"):
            return "false"
    return ans


def _format_answer(q, res: SolverResult) -> str:
    answer = res.answer
    if q.qtype == "判断题":
        if answer.lower() in ("true", "对", "正确", "a"):
            return "对 (true)"
        if answer.lower() in ("false", "错", "错误", "b"):
            return "错 (false)"
    return answer


def _answer_detail(q, answer: str) -> str:
    """把选项字母展开成“字母. 选项文字”，并标出界面显示的字母。"""
    if not q.options or not answer:
        return ""
    labels = list(answer) if q.qtype == "多选题" else [answer]
    parts: list[str] = []
    for label in labels:
        text = q.options.get(label)
        if not text:
            continue
        shown = q.option_display.get(label)
        suffix = f"（界面 {shown}）" if shown else ""
        parts.append(f"{label}. {text}{suffix}")
    return ("  " + "；".join(parts)) if parts else ""


def cmd_solve(args: argparse.Namespace) -> int:
    client, settings = _client(args)
    course = _resolve_course(client, args)
    chapter = _resolve_chapter(client, course, args)

    materials: list[Material] = []
    if not args.no_materials:
        try:
            materials, _ = _materials(client, settings, course, chapter)
        except ChaoxingError as exc:
            print(f"[提示] 未读取到内嵌文档：{exc}")

    work, _ = _load_work(client, course, chapter, args.work)
    _print_questions(work)

    do_jobs = bool(getattr(args, "complete_jobs", False) or args.save) and not getattr(
        args, "no_complete_jobs", False
    )
    do_save = bool(args.save and work.form_action)
    if args.save and not work.form_action:
        print(
            "\n当前作业处于“查看/已评分”状态，页面没有可编辑表单，"
            "无法调用“暂时保存”。"
        )
        if not do_jobs:
            print("未做任何修改。")
            return 1
        print("将继续处理章节任务点。")

    solver = choose_solver(
        bank=args.bank,
        use_llm=args.llm,
        allow_guess=args.allow_guess,
        llm_model=args.llm_model,
    )
    material_text = "\n\n".join(m.text for m in materials)
    results = solver.solve(work.questions, material_text)

    print("\n" + "=" * 72)
    print("作答结果（未写入平台）")
    print("=" * 72)
    answers: dict[str, str] = {}
    missing: list[str] = []
    for i, q in enumerate(work.questions, 1):
        res = results.get(q.qid)
        if not res or not res.answer:
            missing.append(q.qid)
            print(f"[{i}] {q.qtype}  {q.stem[:60]}  ->  [未作答]")
            continue
        normalized = _normalize_answer(q, res.answer)
        if not normalized:
            missing.append(q.qid)
            print(f"[{i}] {q.qtype}  {q.stem[:60]}  ->  [答案格式无法识别: {res.answer!r}]")
            continue
        res.answer = normalized
        answers[q.qid] = normalized
        print(
            f"[{i}] {q.qtype}  {q.stem[:60]}\n"
            f"    -> {_format_answer(q, res)}{_answer_detail(q, normalized)}   "
            f"置信度={res.confidence:.2f}  来源={res.source}"
        )
        if res.reason:
            print(f"       理由：{res.reason[:200]}")
    print(f"\n已作答 {len(answers)}/{len(work.questions)} 题。")
    if missing:
        print("未作答题目 id: " + ", ".join(missing))
        print("提示：可补充 --bank，或使用 --llm 让大模型基于材料补全。")

    if not do_save and not do_jobs:
        print("\n当前为预览模式；没有调用“暂时保存”，也没有处理任务点。")
        print("确认答案后，加 --save 再运行一次（程序只会暂存，不会提交）。")
        return 0

    if do_save and not answers:
        print("没有可保存的答案。")
        if not do_jobs:
            return 1
        do_save = False

    actions: list[str] = []
    if do_jobs:
        actions.append("完成章节文档类任务点")
    if do_save:
        actions.append("调用平台的“暂时保存”")
    print("\n即将" + "，并".join(actions) + "；不会提交作业。")
    if not args.yes:
        tip = input("确认执行？输入 yes 继续：").strip().lower()
        if tip != "yes":
            print("已取消。")
            return 0

    job_ok = False
    if do_jobs:
        print("\n任务点：")
        try:
            job_results = client.complete_jobs(course, chapter)
        except ChaoxingError as exc:
            print(f"[警告] 完成任务点失败: {exc}")
        else:
            if not job_results:
                print("  （没有待完成的任务点）")
                job_ok = True
            for r in job_results:
                status = "完成" if r.ok else "未完成"
                print(f"  [{status}] {r.kind}  {r.title}  {r.message}")
                if r.ok:
                    job_ok = True

    if do_save:
        result = client.save_work(work, answers)
        _print_json(result)
        ok = bool(result.get("status") or result.get("result") == 1)
        if not ok:
            print("暂存失败，请检查上面的返回信息。")
            return 1
        print("已调用“暂时保存”。")

        if args.verify:
            print("\n重新读取作业，核对已保存答案 ...")
            work2, _ = _load_work(client, course, chapter, args.work)
            for q in work2.questions:
                expected = answers.get(q.qid)
                if expected is None:
                    continue
                current = q.current_answer
                ok = normalize_text(current) == normalize_text(expected)
                print(f"  {q.qid}: {'OK' if ok else '不一致'}  当前={current[:80]!r}  期望={expected[:80]!r}")
        print("完成：只暂存，未提交。")
        return 0

    print("\n任务点处理完成。")
    return 0 if job_ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    """一条命令完成：登录 -> 找课 -> 找章节 -> 读材料 -> 任务点 -> 作答 -> 暂存。"""
    args.save = True
    return cmd_solve(args)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--app", help="cxstudy.exe 路径")
    common.add_argument("--cache", help="缓存目录")
    common.add_argument("--proxy", default="auto", help="代理地址，或 auto/direct")
    common.add_argument("--timeout", type=int, default=30)
    common.add_argument("--non-interactive", action="store_true", help="不要等待人工登录确认")

    course = argparse.ArgumentParser(add_help=False)
    course.add_argument("--course", help="课程名（支持子串）")
    course.add_argument("--course-id", help="courseId（可选，配合 class-id/cpi）")
    course.add_argument("--class-id", help="classId")
    course.add_argument("--cpi", help="cpi")

    chapter = argparse.ArgumentParser(add_help=False)
    chapter.add_argument("--chapter", help="章节号或标题，如 5.1")
    chapter.add_argument("--chapter-id", help="直接指定 chapterId")

    p = argparse.ArgumentParser(
        prog="chaoxing-flow",
        description="PC 学习通流程工具：登录、找课、读章节文档、做题、仅暂存。",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", parents=[common], help="检查客户端、Cookie、登录和课程")
    sub.add_parser("login", parents=[common], help="启动客户端并完成登录校验")
    c = sub.add_parser("courses", parents=[common], help="列出课程")
    c.add_argument("--json", action="store_true")

    c = sub.add_parser("chapters", parents=[common, course], help="列出章节")
    c.add_argument("--json", action="store_true")

    c = sub.add_parser("materials", parents=[common, course, chapter], help="下载并解析章节内嵌文档")
    c.add_argument("--preview", type=int, default=3000)

    c = sub.add_parser("questions", parents=[common, course, chapter], help="读取章节作业题目")
    c.add_argument("--work", help="作业序号/workid/标题子串")
    c.add_argument("--json", action="store_true")

    c = sub.add_parser(
        "solve",
        parents=[common, course, chapter],
        help="基于答案库/大模型作答；--save 时完成文档任务点并暂存",
    )
    c.add_argument("--work", help="作业序号/workid/标题子串")
    c.add_argument("--bank", default=str(package_root() / "answer_banks" / "example.json"))
    c.add_argument("--llm", action="store_true", help="使用 OpenAI 兼容接口")
    c.add_argument("--llm-model", help="模型名（也可用 CX_LLM_MODEL）")
    c.add_argument("--allow-guess", action="store_true", help="允许关键词启发式猜选择题（保守）")
    c.add_argument("--no-materials", action="store_true", help="不下载文档，仅用答案库")
    c.add_argument("--save", action="store_true", help="调用“暂时保存”（绝不会提交）")
    c.add_argument("--complete-jobs", action="store_true", help="完成章节文档类任务点（使用 --save 时默认开启）")
    c.add_argument("--no-complete-jobs", action="store_true", help="即使使用 --save 也不处理任务点")
    c.add_argument("--yes", action="store_true", help="跳过暂存确认")
    c.add_argument("--verify", action="store_true", help="暂存后重新读取并核对")

    c = sub.add_parser(
        "run",
        parents=[common, course, chapter],
        help="一条命令完成任务点、作答和暂存（默认会询问确认）",
    )
    c.add_argument("--work", help="作业序号/workid/标题子串")
    c.add_argument("--bank", default=str(package_root() / "answer_banks" / "example.json"))
    c.add_argument("--llm", action="store_true")
    c.add_argument("--llm-model")
    c.add_argument("--allow-guess", action="store_true")
    c.add_argument("--no-materials", action="store_true")
    c.add_argument("--complete-jobs", action="store_true", help="完成章节文档类任务点（默认开启）")
    c.add_argument("--no-complete-jobs", action="store_true", help="不处理任务点")
    c.add_argument("--yes", action="store_true")
    c.add_argument("--verify", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.proxy.lower() in ("direct", "none", "off"):
        args.proxy = None
    try:
        handlers = {
            "doctor": cmd_doctor,
            "login": cmd_login,
            "courses": cmd_courses,
            "chapters": cmd_chapters,
            "materials": cmd_materials,
            "questions": cmd_questions,
            "solve": cmd_solve,
            "run": cmd_run,
        }
        return handlers[args.command](args)
    except (ChaoxingError, AppControlError, CookieError, NotLoggedIn, RuntimeError) as exc:
        print(f"\n[错误] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
