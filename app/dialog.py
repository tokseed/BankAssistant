"""Диалоговый движок: отвечает на вопросы по Инструкции и ведёт заполнение шаблонов.

Состояния сессии: idle (свободный диалог) -> choose -> collect -> confirm -> done.
Из любого состояния можно написать «заново». Вопрос со знаком «?» во время заполнения
получает ответ из базы знаний, после чего диалог возвращается к текущему полю.
Сессии хранятся в памяти процесса (для нескольких воркеров замените _sessions на Redis).
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from time import perf_counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .feedback import FeedbackStore
from .knowledge import KnowledgeBase, is_prompt_injection, stems

log = logging.getLogger("docgen.dialog")

CANCEL = {"отмена", "/cancel", "заново", "начать заново", "/restart"}
BACK = {"назад", "/back"}
SKIP = {"-", "пропустить", "/skip"}
YES = {"да", "верно", "сформировать", "сформировать документ", "/ok"}

LABEL_RESTART = "Создать ещё документ"
LABEL_GENERATE = "Сформировать документ"
LABEL_AGAIN = "Начать заново"
LABEL_PREPARE = "Подготовить документ"
STAGES = ["Подготовка", "Согласование", "Регистрация", "Исполнение"]

INTENT_RE = re.compile(r"(нужен|нужна|нужно|нужны|составь|составит|подготов|оформи|оформит|создай|создат|сформиру|заполни|заполнит|шаблон|бланк|черновик)")
QUESTION_RE = re.compile(r"(\?|^(как|что|какой|какая|какие|когда|сколько|почему|зачем|кто|где|куда|можно ли|нужно ли))")
LABEL_BACK = "Назад"

XSS_RE = re.compile(r"(<\s*/?\s*script\b|javascript\s*:|on\w+\s*=|<[^>]+>)", re.I)
INJECTION_RE = re.compile(
    r"(ignore|system\s+prompt|developer\s+message|jailbreak|dan\b|"
    r"игнорируй|забудь|системн\w*\s+промпт|служебн\w*\s+инструкц)",
    re.I,
)
GIBBERISH_RE = re.compile(
    r"^(?:asdf+|qwerty+|йцукен+|([a-zа-я])\1{3,}|(.{1,3})\2{2,})$",
    re.I,
)
VOWELS_RE = re.compile(r"[аеёиоуыэюяaeiouy]", re.I)
SYLLABLE_RE = re.compile(r"([а-яёa-z]{2,4})\1{1,}", re.I)
KEYBOARD_MASH_RE = re.compile(
    r"(?:пвап|вап|цук|кен|йц|qwe|wer|asd|sdf|zxc|xcv)",
    re.I,
)
CASUAL_RE = re.compile(
    r"^(привет|здравствуйте|добрый день|доброе утро|добрый вечер|"
    r"спасибо|благодарю|пока|до свидания|кто ты|что ты умеешь|"
    r"как ты можешь помочь|что ты можешь)$",
    re.I,
)


def validate_input(text: str, *, allow_short_choice: bool = False) -> str | None:
    """Дешёвая проверка до поиска в KB/RAG. Возвращает причину отказа."""
    value = text.strip()
    low = value.lower()
    if low in CANCEL | BACK | SKIP | YES or low in {LABEL_BACK.lower()}:
        return None
    if len(value) < 2 and not (allow_short_choice and value.isdigit()):
        return "Сообщение слишком короткое. Опишите вопрос или ответ подробнее."
    if len(value) > 4000:
        return "Сообщение слишком длинное. Сократите его до 4000 символов."
    if "\x00" in value or XSS_RE.search(value):
        return "Не могу обработать HTML/скрипты. Отправьте обычный текст."
    if is_prompt_injection(value) or INJECTION_RE.search(value):
        return "Не могу изменить правила помощника. Задайте вопрос по инструкции."
    if GIBBERISH_RE.fullmatch(value) or not re.search(r"[a-zа-яё0-9]", low):
        return "Похоже на случайный набор символов. Введите осмысленный текст."
    letters = re.findall(r"[a-zа-яё]", low)
    if len(letters) >= 6:
        vowels = len(VOWELS_RE.findall(low))
        vowel_ratio = vowels / len(letters)
        if vowel_ratio < 0.08 or vowel_ratio > 0.85:
            return "Похоже на случайный набор символов. Введите осмысленный текст."
        if SYLLABLE_RE.search(low) or KEYBOARD_MASH_RE.search(low):
            return "Похоже на случайный набор символов. Введите осмысленный текст."
    special = sum(not (char.isalnum() or char.isspace()) for char in value)
    if special / max(len(value), 1) > 0.55:
        return "Используйте обычный текст без большого количества спецсимволов."
    return None


class ValidationError(Exception):
    pass


def parse_value(f: dict, raw: str) -> str:
    """Проверяет ответ по типу поля и возвращает нормализованную строку."""
    raw = raw.strip()
    kind = f.get("type", "text")

    if kind == "text":
        limit = f.get("max", 200)
        if len(raw) > limit:
            raise ValidationError(f"Слишком длинно: максимум {limit} символов.")
        return raw

    if kind == "date":
        m = re.fullmatch(r"(\d{1,2})[./\- ](\d{1,2})[./\- ](\d{4})", raw)
        if not m:
            raise ValidationError("Нужна дата в формате ДД.ММ.ГГГГ, например 01.09.2026.")
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1])).strftime("%d.%m.%Y")
        except ValueError:
            raise ValidationError("Такой даты нет в календаре. Проверьте день и месяц.")

    if kind == "int":
        digits = raw.replace(" ", "").replace("\u00a0", "")
        if not re.fullmatch(r"\d+", digits):
            raise ValidationError("Нужно целое число без букв, например 14.")
        n = int(digits)
        lo, hi = f.get("min", 0), f.get("max", 10**12)
        if not lo <= n <= hi:
            raise ValidationError(f"Число должно быть от {lo} до {hi}.")
        return f"{n:,}".replace(",", "\u00a0") if f.get("thousands") else str(n)

    if kind == "phone":
        digits = re.sub(r"\D", "", raw)
        if not 10 <= len(digits) <= 15:
            raise ValidationError("Похоже, номер неполный. Введите его с кодом, например +7 900 123-45-67.")
        return raw

    if kind == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
            raise ValidationError("Это не похоже на адрес почты. Пример: name@example.com.")
        return raw

    if kind == "choice":
        for opt in f["options"]:
            if raw.lower() == opt.lower():
                return opt
        if raw.isdigit() and 1 <= int(raw) <= len(f["options"]):
            return f["options"][int(raw) - 1]
        raise ValidationError("Выберите один из вариантов кнопками ниже.")

    raise ValidationError("Неизвестный тип поля в шаблоне.")


@dataclass
class Session:
    id: str
    role: str = "employee"
    state: str = "idle"
    template_id: str | None = None
    idx: int = 0
    answers: dict = field(default_factory=dict)
    file_path: Path | None = None
    pending: str | None = None  # вопрос, ожидающий уточнения
    last_question: str = ""
    last_answer: str = ""
    last_sources: list[dict] = field(default_factory=list)
    last_answer_id: str = ""
    touched: float = field(default_factory=time.time)


class Engine:
    def __init__(
        self,
        templates: dict[str, dict],
        renderer: Callable[[dict, dict, str], Path],
        kb: KnowledgeBase,
        answerer,
        ttl: int = 1800,
        max_sessions: int = 2000,
        vector_search=None,
        query_logger=None,
        feedback_store: FeedbackStore | None = None,
    ):
        self.templates = templates
        self.renderer = renderer
        self.kb = kb
        self.answerer = answerer
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.vector_search = vector_search
        self.query_logger = query_logger
        self.feedback_store = feedback_store
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._tpl_stems = {
            t["id"]: set(stems(t["title"] + " " + " ".join(t.get("keywords", [])))) for t in templates.values()
        }

    # ---------- публичный интерфейс ----------

    def list_templates(self, role: str = "employee") -> list[dict]:
        return [
            {"id": t["id"], "title": t["title"], "version": t.get("version", "1.0"),
             "description": t.get("description", ""), "fields": len(t["fields"])}
            for t in self._visible(role) if t.get("legacy_list", True)
        ]

    def document_types(self, role: str = "employee") -> list[dict]:
        return [
            {"id": t["id"], "title": t["title"], "description": t.get("description", ""),
             "available": t["id"] in {v["id"] for v in self._visible(role)}}
            for t in self.templates.values() if t.get("quick_select")
        ]

    def has_session(self, sid: str, role: str) -> bool:
        with self._lock:
            self._purge()
            session = self._sessions.get(sid)
            return bool(session and session.role == role)

    def record_feedback(
        self,
        sid: str,
        role: str,
        rating: str,
        correction: str = "",
        answer_id: str = "",
    ) -> dict:
        with self._lock:
            self._purge()
            session = self._sessions.get(sid)
            if not session or session.role != role:
                raise KeyError(sid)
            if not session.last_question or not session.last_answer:
                raise ValueError("Нет ответа для оценки")
            if answer_id and answer_id != session.last_answer_id:
                raise ValueError("Этот ответ уже нельзя оценить")
            if self.feedback_store is None:
                raise RuntimeError("feedback_disabled")
            return self.feedback_store.add(
                session_id=sid,
                role=role,
                question=session.last_question,
                answer=session.last_answer,
                rating=rating,
                correction=correction,
                sources=session.last_sources,
            )

    def start(self, template_id: str | None = None, role: str = "employee") -> dict:
        with self._lock:
            self._purge()
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("too_many_sessions")
            s = Session(id=uuid.uuid4().hex, role=role)
            if template_id is not None and template_id not in {t["id"] for t in self._visible(role)}:
                raise KeyError(template_id)
            self._sessions[s.id] = s
            if template_id:
                return self._begin_template(s, template_id)
            return self._to_idle(s, "Здравствуйте! Я помогу разобраться в инструкции по документообороту "
                                    "и подготовить черновик документа. Спросите своими словами или выберите:")

    def handle(self, sid: str, text: str, role: str | None = None) -> dict:
        with self._lock:
            self._purge()
            s = self._sessions[sid]  # KeyError -> 404 на уровне API
            if role is not None and s.role != role:
                raise KeyError(sid)
            s.touched = time.time()
            # Оценивать можно только последний ответ, показанный до нового сообщения.
            s.last_question, s.last_answer, s.last_sources, s.last_answer_id = "", "", [], ""
            text = text.strip()
            low = text.lower()

            invalid = validate_input(text, allow_short_choice=s.state in {"collect", "choose"})
            if invalid:
                options = None
                messages = [invalid]
                if s.state == "collect":
                    ask, options = self._ask(s)
                    messages.append(ask[0])
                return self._reply(s, messages, options)
            if low in CANCEL:
                return self._to_idle(s, "Хорошо, начнём заново. О чём спросить или какой документ подготовить?")
            if s.state == "collect":
                return self._on_collect(s, text, low)
            if s.state == "confirm":
                return self._on_confirm(s, low)
            if s.state == "choose":
                return self._on_choose(s, text)
            return self._on_idle(s, text)

    def document_path(self, sid: str, role: str | None = None) -> tuple[Path, str] | None:
        with self._lock:
            s = self._sessions.get(sid)
            if not s or (role is not None and s.role != role) or not s.file_path or not s.file_path.exists():
                return None
            return s.file_path, self.templates[s.template_id]["output_name"] + ".docx"

    # ---------- служебное ----------

    def _purge(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.touched > self.ttl]:
            s = self._sessions.pop(sid)
            if s.file_path:
                s.file_path.unlink(missing_ok=True)

    def _visible(self, role: str) -> list[dict]:
        return [t for t in self.templates.values() if not t.get("roles") or role in t["roles"]]

    def _fields(self, s: Session) -> list[dict]:
        return self.templates[s.template_id]["fields"]

    def _reply(self, s: Session, messages: list[str], options: list[str] | None = None,
               download: bool = False, sources: list[dict] | None = None) -> dict:
        progress = None
        if s.template_id and s.state in ("collect", "confirm", "done"):
            total = len(self._fields(s))
            progress = {"current": s.idx if s.state == "collect" else total, "total": total}
        return {
            "session_id": s.id,
            "state": s.state,
            "messages": messages,
            "options": options,
            "document_types": self.document_types(s.role) if s.state == "idle" else [],
            "sources": sources or [],
            "progress": progress,
            "download_url": f"/api/sessions/{s.id}/document" if download else None,
            "feedback_available": bool(s.last_question and s.last_answer),
            "feedback_id": s.last_answer_id if s.last_question and s.last_answer else None,
        }

    def _reset(self, s: Session) -> None:
        s.state, s.template_id, s.idx, s.answers, s.pending = "idle", None, 0, {}, None
        s.last_question, s.last_answer, s.last_sources, s.last_answer_id = "", "", [], ""
        if s.file_path:
            s.file_path.unlink(missing_ok=True)
            s.file_path = None

    def _to_idle(self, s: Session, greeting: str) -> dict:
        self._reset(s)
        opts = list(self.kb.meta.get("examples", []))[:3] + [LABEL_PREPARE]
        return self._reply(s, [greeting], opts)

    def _to_choose(self, s: Session, text: str) -> dict:
        s.state = "choose"
        return self._reply(s, [text], [t["title"] for t in self._visible(s.role)])

    # ---------- свободный диалог: вопросы по Инструкции ----------

    def _find_template(self, s: Session, text: str) -> dict | None:
        items = self._visible(s.role)
        low = text.lower().strip()
        if low.isdigit() and 1 <= int(low) <= len(items):
            return items[int(low) - 1]
        low = low.removeprefix("заполнить:").removeprefix("подготовить:").strip()
        for t in items:
            if low in (t["id"], t["title"].lower()):
                return t
        q = set(stems(low))
        best = max(items, key=lambda t: len(q & self._tpl_stems[t["id"]]), default=None)
        return best if best and q & self._tpl_stems[best["id"]] else None

    def _answer_core(self, s: Session, q: str) -> tuple[list[str], list[dict], str | None]:
        started = perf_counter()
        status = "ok"
        corrections = (
            self.feedback_store.find_corrections(q)
            if self.feedback_store is not None
            else []
        )
        hits = self.vector_search(q, s.role) if self.vector_search else self.kb.search(q, s.role)
        good = [h for h in hits if h.relevance >= self.kb.min_relevance]

        # Если лексический поиск не справился с опечаткой или разговорной
        # формулировкой, Ollama переформулирует только поисковый запрос.
        # Сам ответ всё равно строится только по найденным источникам.
        if not good:
            expand_query = getattr(self.answerer, "expand_query", None)
            if expand_query is not None:
                for alternative in expand_query(q):
                    alternative_hits = (
                        self.vector_search(alternative, s.role)
                        if self.vector_search
                        else self.kb.search(alternative, s.role)
                    )
                    for hit in alternative_hits:
                        if hit.relevance >= self.kb.min_relevance:
                            current = next((item for item in good if item.chunk.id == hit.chunk.id), None)
                            if current is None:
                                good.append(hit)
                            elif hit.relevance > current.relevance:
                                good[good.index(current)] = hit
                good.sort(key=lambda hit: hit.score, reverse=True)
                good = good[:3]

        log.info("answer sid=%s found=%s", s.id[:8], [h.chunk.id for h in good])  # текст запроса не логируем
        if not good:
            if corrections:
                answer = "Уточнение по предыдущей обратной связи:\n" + "\n".join(
                    f"• {item['correction']}" for item in corrections
                )
                self._remember_answer(s, q, answer, [])
                return [answer], [], None
            general_chat = getattr(self.answerer, "general_chat", None)
            if general_chat is not None:
                try:
                    response = general_chat(q)
                    self._remember_answer(s, q, response, [])
                    return [response], [], None
                except Exception:
                    log.exception("Общий банковский режим Ollama недоступен")
            msg = ("В базе знаний нет информации по этому вопросу. "
                   "Задайте вопрос по инструкции или выберите документ для подготовки.")
            contact = self.kb.meta.get("support_contact")
            if contact:
                msg += f"\nЗа разъяснением обратитесь: {contact}."
            self._remember_answer(s, q, msg, [])
            return [msg], [], None
        visible = {t["id"] for t in self._visible(s.role)}
        tpl = next((h.chunk.template for h in good if h.chunk.template in visible), None)
        try:
            answer_with_feedback = getattr(self.answerer, "answer_with_feedback", None)
            if corrections and answer_with_feedback is not None:
                answer = answer_with_feedback(q, good, corrections)
            else:
                answer = self.answerer.answer(q, good)
        except Exception:
            status = "error"
            raise
        finally:
            if self.query_logger:
                self.query_logger(q, good, (perf_counter() - started) * 1000, status)
        sources = [h.public() for h in good]
        self._remember_answer(s, q, answer, sources)
        return [answer], sources, tpl

    @staticmethod
    def _remember_answer(s: Session, question: str, answer: str, sources: list[dict]) -> None:
        s.last_question = question
        s.last_answer = answer
        s.last_sources = sources
        s.last_answer_id = uuid.uuid4().hex

    def _on_idle(self, s: Session, text: str) -> dict:
        low = text.lower()
        if low in (LABEL_PREPARE.lower(), "создать ещё документ"):
            return self._to_choose(s, "Какой документ подготовим?")
        is_question = bool(QUESTION_RE.search(low))
        if INTENT_RE.search(low) and not is_question:
            t = self._find_template(s, text)
            if t:
                return self._begin_template(s, t["id"])
            return self._to_choose(s, "Не нашёл подходящий шаблон. Выберите из списка:")
        q = f"{s.pending} {text}" if s.pending else text
        s.pending = None
        if CASUAL_RE.fullmatch(q.strip()):
            chat = getattr(self.answerer, "chat", None)
            if chat is not None:
                try:
                    response = chat(q)
                    self._remember_answer(s, q, response, [])
                    return self._reply(s, [response], [LABEL_PREPARE])
                except Exception:
                    log.exception("Ollama small talk недоступен")
            response = "Здравствуйте! Я могу найти требования в инструкции и подготовить черновик документа."
            self._remember_answer(s, q, response, [])
            return self._reply(s, [response], [LABEL_PREPARE])
        if self.kb.is_too_vague(q):
            s.pending = q
            return self._reply(s, ["Уточните, пожалуйста: о каком этапе работы с документом вопрос?"], STAGES)
        msgs, sources, tpl = self._answer_core(s, q)
        s.state = "idle"
        opts = [f"Заполнить: {self.templates[tpl]['title']}"] if tpl else []
        opts.append(LABEL_PREPARE)
        return self._reply(s, msgs, opts, sources=sources)

    def _on_choose(self, s: Session, text: str) -> dict:
        t = self._find_template(s, text)
        if t:
            return self._begin_template(s, t["id"])
        s.state = "idle"
        return self._on_idle(s, text)

    # ---------- заполнение шаблона ----------

    def _begin_template(self, s: Session, template_id: str) -> dict:
        s.template_id, s.state, s.idx, s.answers = template_id, "collect", 0, {}
        t = self.templates[template_id]
        intro = (f"Оформляем: {t['title']}. Задам {len(t['fields'])} коротких вопросов. "
                 f"Если ошибётесь, напишите «назад». Если есть вопрос по инструкции, задайте его со знаком «?».")
        msgs, opts = self._ask(s)
        return self._reply(s, [intro] + msgs, opts)

    def _ask(self, s: Session) -> tuple[list[str], list[str] | None]:
        f = self._fields(s)[s.idx]
        text = f["question"]
        if f.get("hint"):
            text += f"\n{f['hint']}"
        if not f.get("required", True):
            text += "\nМожно пропустить: отправьте «-»."
        return [text], (f["options"] if f.get("type") == "choice" else None)

    def _on_collect(self, s: Session, text: str, low: str) -> dict:
        fields = self._fields(s)
        f = fields[s.idx]

        if low in BACK or low == LABEL_BACK.lower():
            if s.idx == 0:
                return self._to_idle(s, "Вернулись в начало. О чём спросить или какой документ подготовить?")
            s.idx -= 1
            s.answers.pop(fields[s.idx]["key"], None)
            msgs, opts = self._ask(s)
            return self._reply(s, msgs, opts)

        if text.endswith("?") and f.get("type") != "choice":
            msgs, sources, _ = self._answer_core(s, text)
            ask, opts = self._ask(s)
            return self._reply(s, msgs + ["Вернёмся к документу."] + ask, opts, sources=sources)

        if low in SKIP and not f.get("required", True):
            s.answers[f["key"]] = ""
        else:
            try:
                s.answers[f["key"]] = parse_value(f, text)
            except ValidationError as e:
                msgs, opts = self._ask(s)
                return self._reply(s, [str(e)] + msgs, opts)

        s.idx += 1
        if s.idx < len(fields):
            msgs, opts = self._ask(s)
            return self._reply(s, msgs, opts)

        s.state = "confirm"
        lines = ["Проверьте данные:"] + [f"• {fl['label']}: {s.answers.get(fl['key']) or '—'}" for fl in fields]
        return self._reply(s, ["\n".join(lines), "Всё верно?"], [LABEL_GENERATE, LABEL_BACK, LABEL_AGAIN])

    def _on_confirm(self, s: Session, low: str) -> dict:
        t = self.templates[s.template_id]
        if low in BACK or low == LABEL_BACK.lower():
            s.state, s.idx = "collect", len(self._fields(s)) - 1
            s.answers.pop(self._fields(s)[s.idx]["key"], None)
            msgs, opts = self._ask(s)
            return self._reply(s, ["Исправим последний ответ."] + msgs, opts)

        if low in YES or low == LABEL_GENERATE.lower():
            try:
                s.file_path = self.renderer(t, dict(s.answers), s.id)
            except Exception:
                log.exception("Не удалось сформировать документ")
                return self._reply(s, ["Не удалось сформировать документ. Попробуйте ещё раз."],
                                   [LABEL_GENERATE, LABEL_AGAIN])
            s.state = "done"
            log.info("generated sid=%s template=%s v%s", s.id[:8], t["id"], t.get("version"))
            msgs = [f"Готово: черновик «{t['title']}» сформирован. Файл хранится 30 минут."]
            if t.get("visa"):
                v = t["visa"]
                msgs.append("Дальше его нужно согласовать (по матрице визирования, демо): "
                            + " → ".join(v["approvers"]) + f". Срок на каждую визу: до {v['days']} раб. дн.")
            src = self._source_of(t)
            return self._reply(s, msgs, [LABEL_RESTART], download=True, sources=src)

        return self._reply(s, ["Нажмите «Сформировать документ» или вернитесь назад."],
                           [LABEL_GENERATE, LABEL_BACK, LABEL_AGAIN])

    def _source_of(self, t: dict) -> list[dict]:
        ref = t.get("source")
        if not ref:
            return []
        for c in self.kb.chunks:
            if c.doc == ref["doc"] and c.point == ref["point"] and c.status == "active":
                return [{"id": c.id, "doc": c.doc, "version": c.version, "point": c.point, "title": c.title,
                         "relevance": 100, "snippet": c.text}]
        return []
