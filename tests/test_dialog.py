"""Запуск: python tests/test_dialog.py  (или pytest). FastAPI и docxtpl не нужны."""
import json, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dialog import Engine, parse_value, ValidationError
from app.feedback import FeedbackStore
from app.knowledge import KnowledgeBase, ExtractiveAnswerer, LocalRAGAnswerer, mask_pii
from app.render import load_templates, build_context


def fake_renderer(tpl, answers, sid):
    p = Path(tempfile.gettempdir()) / f"{sid}.docx"
    p.write_bytes(b"x")
    return p


def make():
    return Engine(load_templates(), fake_renderer, KnowledgeBase(ROOT / "kb" / "chunks.json"), ExtractiveAnswerer())


def test_answer_with_sources():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Сколько дней даётся на согласование проекта?")
    assert r["sources"] and r["sources"][0]["point"] == "3.4"
    assert "п. 3.4" in r["messages"][0] and "Простыми словами" in r["messages"][0]
    assert r["sources"][0]["relevance"] >= 45


def test_natural_question_finds_approval_matrix():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Как определить согласующих?")
    assert r["sources"]
    assert r["sources"][0]["relevance"] >= 45
    assert "матрице" in r["messages"][0].lower()


def test_uploaded_materials_are_searchable():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Какие документы и материалы используются при визировании?")
    assert r["sources"]
    assert any(source["id"].startswith("doc-") for source in r["sources"])


def test_no_answer_is_honest():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Какой курс доллара сегодня?")
    assert r["sources"] == [] and "нет информации" in r["messages"][0]


def test_feedback_correction_is_reused():
    store = FeedbackStore(Path(tempfile.mkdtemp()) / "feedback.jsonl")
    e = Engine(
        load_templates(),
        fake_renderer,
        KnowledgeBase(ROOT / "kb" / "chunks.json"),
        ExtractiveAnswerer(),
        feedback_store=store,
    )
    sid = e.start()["session_id"]
    e.handle(sid, "Какой курс доллара сегодня?")
    e.record_feedback(
        sid,
        "employee",
        "negative",
        "Для текущего курса нужно открыть официальный источник банка.",
    )
    sid = e.start()["session_id"]
    result = e.handle(sid, "Какой курс доллара сегодня?")
    assert "официальный источник банка" in result["messages"][0]


def test_local_rag_answerer_uses_only_sources():
    kb = KnowledgeBase(ROOT / "kb" / "chunks.json")
    hit = kb.search("срок согласования", "employee")[0]
    answer = LocalRAGAnswerer(ExtractiveAnswerer()).answer("срок согласования", [hit])
    assert f"п. {hit.chunk.point}" in answer
    assert "Основание:" in answer


def test_clarifying_question():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Согласование")
    assert r["options"] == ["Подготовка", "Согласование", "Регистрация", "Исполнение"]
    r = e.handle(sid, "Регистрация")  # объединяется с прошлым ответом
    assert r["sources"]


def test_template_flow_with_question_midway():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Нужна служебная записка")
    assert r["state"] == "collect" and r["progress"]["total"] == 7
    r = e.handle(sid, "Отдел кадров")
    r = e.handle(sid, "Какие реквизиты обязательны в служебной записке?")
    assert r["sources"] and "Вернёмся к документу" in r["messages"][1]
    assert r["progress"]["current"] == 1  # поле не пропущено
    for a in ["Директору Иванову И. И.", "Нехватка бланков", "Прошу закупить бланки", "-", "Начальник отдела", "Петров П. П."]:
        r = e.handle(sid, a)
    assert r["state"] == "confirm"
    r = e.handle(sid, "Сформировать документ")
    assert r["state"] == "done" and r["download_url"]
    assert "матрице визирования" in r["messages"][1] and r["sources"][0]["point"] == "2.3"
    assert e.document_path(sid)[1] == "Служебная записка.docx"
    assert build_context(load_templates()["memo"], {"deadline": ""})["deadline"] == "не установлен"


def test_question_offers_template_chip():
    e = make()
    sid = e.start()["session_id"]
    r = e.handle(sid, "Как оформить служебную записку?")
    assert "Заполнить: Служебная записка" in r["options"]
    r = e.handle(sid, "Заполнить: Служебная записка")
    assert r["state"] == "collect"


def test_roles():
    e = make()
    emp = e.start(role="employee")["session_id"]
    mgr = e.start(role="manager")["session_id"]
    assert [t["id"] for t in e.list_templates("employee")] == ["memo"]
    assert [t["id"] for t in e.list_templates("manager")] == ["memo", "order"]
    assert e.handle(emp, "Как оформить поручение?")["sources"]  # инструкция доступна сотруднику
    assert e.handle(mgr, "Как оформить поручение?")["sources"][0]["point"] == "5.2"
    try:
        e.start("order", role="employee"); assert False
    except KeyError:
        pass
    try:
        e.handle(mgr, "привет", role="employee"); assert False  # чужая сессия
    except KeyError:
        pass


def test_validation_and_back():
    e = make()
    sid = e.start("memo")["session_id"]
    for a in ["Отдел", "Директору", "Тема", "Суть"]:
        e.handle(sid, a)
    assert "нет в календаре" in e.handle(sid, "31.02.2026")["messages"][0]
    r = e.handle(sid, "назад")
    assert "суть" in r["messages"][0].lower()


def test_parse_value_and_pii():
    assert parse_value({"type": "date"}, "1.9.2026") == "01.09.2026"
    assert parse_value({"type": "int", "thousands": True}, "50000") == "50\u00a0000"
    assert mask_pii("пишите a@b.ru или +7 900 123-45-67") == "пишите [email] или [номер]"


def test_ingest_versioning():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "kb" / "chunks.json", tmp / "chunks.json")
    (tmp / "v2.txt").write_text("1. Общие положения\n3.4. Срок согласования составляет один рабочий день.\nПродолжение пункта.\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "app.ingest", str(tmp / "v2.txt"), "--doc", "Инструкция по документообороту (ДЕМО)",
                    "--version", "2.0", "--kb", str(tmp / "chunks.json")], cwd=ROOT, check=True, capture_output=True)
    kb = KnowledgeBase(tmp / "chunks.json")
    hit = kb.search("срок согласования", "employee")[0]
    assert hit.chunk.version == "2.0" and "один рабочий день" in hit.chunk.text
    assert kb.search("срок согласования", "employee")[0].chunk.version == "2.0"
    assert any(c.status == "archived" for c in kb.chunks)


def test_placeholders_match_fields():
    for t in load_templates().values():
        xml = zipfile.ZipFile(ROOT / "templates" / t["file"]).read("word/document.xml").decode("utf8")
        used = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", xml))
        sample = {f["key"]: "x" for f in t["fields"]}
        assert used <= set(build_context(t, sample)), (t["id"], used)
        assert {f["key"] for f in t["fields"]} <= used, (t["id"], "поле не используется в бланке")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
