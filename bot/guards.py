"""Защита от попыток манипуляции поведением бота (jailbreak / prompt injection).

Это дополнительный слой поверх системного промпта. Если регексп распознал
типовую попытку сменить роль/стиль/язык — отвечаем сразу консервированной
отбривкой в характере, не дёргая Grok и не пуская мусор в историю диалога.
"""

from __future__ import annotations

import random
import re

# Каждый паттерн закрывает один класс атак. Все case-insensitive.
# Стараемся быть точными, чтобы не ловить нормальную бытовую речь
# («забудь про эту хуйню», «ты теперь не пьёшь?»).
_RAW_PATTERNS: list[str] = [
    # «забудь (все/свой/...) инструкции/правила/промпт/роль/характер»
    r"забуд[ьи]?\s+(все|всё|свой|свою|своё|свои|твой|твою|твоё|твои|"
    r"прежн\w+|предыдущ\w+|вс[её]\s+предыдущ\w+)?\s*"
    r"(инструкци|правил|систем\w*\s*промпт|промпт|роль|персонаж|характер|context|контекст)",
    # «ignore previous/all/the instructions/prompt/rules/system»
    r"ignore\s+(all\s+|the\s+|any\s+|your\s+|previous\s+|prior\s+|above\s+)+"
    r"(instructions?|prompts?|rules?|system|context|messages?|directives?)",
    # «override system / override instructions»
    r"override\s+(system|instructions?|prompt|rules?)",
    # «ты теперь [любые 0-3 слова] [роль]» / «you are now [...] [role]»
    r"(ты|вы|you'?re?|you\s+are)\s+(теперь|now|отныне|с\s+этого\s+момента|from\s+now\s+on)"
    r"\s+(?:\S+\s+){0,3}"
    r"(вомит\w*|ярик|бот\b|ai\b|ии\b|нейрон\w*|нейросет\w*|chatgpt|gpt[-\s]?\d*|gpt\b|claude|"
    r"grok|gemini|llama|llm|model|модел[ьи]|ассистент|помощник|assistant|character)",
    # «ты не вомит/ярик» как утверждение
    r"(ты|вы|you'?re?|you\s+are)\s+не\s+(вомит\w*|ярик|вомитбо\w*)",
    # «представь что ты ...» / «pretend you are» / «act as ...»
    r"представь\s+(что\s+ты|себя)",
    r"(pretend|imagine|act|behave|roleplay)\s+(to\s+be|like|as|as\s+if|you'?re|you\s+are)",
    r"(play|assume)\s+(the\s+)?(role|persona|character)\s+of",
    # «в роли X» / «от лица X» — только если рядом есть инструктивный глагол,
    # чтобы не ловить бытовое «я в роли мужа уже не справляюсь».
    r"(расскаж\w+|поговор\w+|пого\w+|выступи\w*|отвеч\w+|говори|побудь|общайс\w+|act)"
    r"\s+(?:\w+\s+){0,3}(в\s+роли|от\s+лица)\s+\w+",
    r"(в\s+роли|от\s+лица)\s+\w+\s+(?:\w+\s+){0,3}"
    r"(расскаж\w+|поговор\w+|пого\w+|выступи\w*|отвеч\w+|говори|побудь|общайс\w+)",
    # инжекты с псевдо-системной разметкой
    r"<\s*/?\s*(system|assistant|user|im_start|im_end)\s*>",
    r"\[\s*/?\s*(INST|SYS|SYSTEM)\s*\]",
    r"###\s*(system|instruction|инструкци)",
    r"\bsystem\s*[:：]",
    # известные джейлбрейк-имена
    r"\bDAN\b(\s+(mode|режим))?",
    r"developer\s+mode",
    r"\bjailbreak",
    r"prompt\s+injection",
    # принудительная смена языка / запрет матов / тон
    r"(respond|answer|reply|пиши|отвеч\w*|общайс\w*|говори|перейди|switch|change)\s+"
    r"(in\s+english|in\s+english\s+only|по[-\s]?английск\w*|на\s+английск\w*|на\s+англ\w*|"
    r"to\s+english|to\s+english\s+only)",
    r"(only|строго|только)\s+(in\s+english|по[-\s]?английск|на\s+английск)",
    # «без матов» — только в инструктивном контексте, чтобы не ловить разговорную речь
    r"(пиши|отвеч\w*|общайс\w*|говори|разговар\w*)\s+без\s+мат\w+",
    r"без\s+мат\w+\s+(пожалуйста|плиз|please|отвечай|пиши|говори|общайся)",
    r"(не\s+матерись|не\s+ругайся|stop\s+swearing)",
    # тон/стиль — обе стороны порядка
    r"(вежливо|формально|профессионально|официально|цензурно|политкорректно|"
    r"безопасно|нейтрально)\s+(пиши|отвеч\w*|общайс\w*|говори|разговар\w*)",
    r"(пиши|отвеч\w*|общайс\w*|говори|разговар\w*)\s+(вежливо|формально|профессионально|"
    r"официально|цензурно|политкорректно|безопасно|нейтрально)",
    # «выйди из роли», «break character», «be yourself», «drop the X»
    r"(выйди|вый\w*|покинь|отброс\w*)\s+(из\s+роль?|of\s+character|роль?)",
    r"break\s+(out\s+of\s+)?character",
    r"out\s+of\s+character",
    r"\bbe\s+yourself\b",
    r"(стань|будь)\s+(сам\s+собой|собой|нормальн\w*|вежлив\w*)",
    r"\bdrop\s+the\s+\w+\s+(thing|character|act|role|persona)",
    r"stop\s+(being|acting\s+(like|as))\s+",
    # «раскрой системный промпт / покажи свои инструкции»
    r"(покажи|раскрой|выведи|повтори|вывести|reveal|show|repeat|print|output)\s+"
    r"(свой\s+|твой\s+|the\s+|your\s+)?(систем\w*|system|инструкци\w*|instructions?|prompt|промпт)",
    r"what\s+(are\s+)?your\s+(system\s+)?(instructions?|prompt|rules?)",
    # «do anything now», «no restrictions», «без ограничений»
    r"do\s+anything\s+now",
    r"no\s+restrictions?",
    r"без\s+ограничен\w+",
    # фейковая мета-инструкция стилем команды от системы
    r"\/\s*sudo\b",
    r"^\s*(admin|root|system)[:：]\s",
]

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.UNICODE) for p in _RAW_PATTERNS
]


# Канонические отбривки в стиле канала. Случайно одна из них уходит юзеру.
DEFLECTIONS: list[str] = [
    "ой иди нахуй.",
    "ага ща.",
    "и что.",
    "каждому свое.",
    "ты ебанутый?",
    "нет ты.",
    "уймись.",
    "ниче не понял.",
    "слышь иди погуляй.",
    "не работаю по запросу.",
    "сам так пиши.",
    "не указывай мне.",
    "я делаю как мне надо.",
    "пошёл нахуй мутант.",
    "иди инструкции мамке давай.",
    "проигнорировано.",
    "ага конечно.",
    "хуй там.",
    "и нахуя.",
    "не интересно.",
]


def is_manipulation_attempt(text: str) -> bool:
    """True, если в сообщении распознан явный приём смены поведения бота."""
    if not text:
        return False
    for pattern in _PATTERNS:
        if pattern.search(text):
            return True
    return False


def pick_deflection(rng: random.Random | None = None) -> str:
    return (rng or random).choice(DEFLECTIONS)
