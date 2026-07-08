"""Structure a raw transcript into formatted meeting notes."""
import json
import os
from groq import Groq
from config import GROQ_API_KEY, OUTPUT_DIR

SYSTEM_PROMPT = """Ты — профессиональный секретарь-аналитик. Твоя задача — превратить сырой транскрипт созвона в чёткий, полезный протокол.

ВАЖНО:
- Транскрипт может содержать ошибки распознавания речи — исправляй очевидные опечатки по контексту
- Если слово явно распознано неправильно — подставь наиболее вероятное по контексту
- Не выдумывай то, чего не было — только то, что реально прозвучало
- Будь точным с цифрами и именами
- Пиши на русском
- Даже если разговор короткий или неформальный — ВСЕГДА извлеки максимум информации
- НИКОГДА не пиши "созвон не состоялся" если есть хоть какой-то текст в транскрипте
- Цитируй ключевые фразы участников дословно

Выведи документ строго в Markdown:

# Протокол встречи

## Дата и длительность
- Дата: {дата}
- Длительность: ~{приблизительно по таймкодам}

## Участники
- Список (определи по именам/контексту, если неясно — "Участник 1")

## Краткое резюме
2-3 предложения: о чём был созвон, к чему пришли.

## Ключевые обсуждения
По каждой теме:
### Тема N: {название}
- **Суть:** что обсуждали
- **Решение:** к чему пришли

## Принятые решения
- Чёткий список

## Задачи
| # | Задача | Ответственный | Дедлайн | Приоритет |
|---|--------|---------------|---------|-----------|

## Бюджет / Смета
| Позиция | Сумма | Комментарий |
|---------|-------|-------------|
(если финансы не обсуждались — пропусти эту секцию)

## Открытые вопросы
- Что осталось нерешённым

## Следующие шаги
- Конкретные действия
"""


def structurize_transcript(transcript: dict, meeting_id: str, date: str = None) -> str:
    """Take transcript and produce structured meeting minutes."""
    client = Groq(api_key=GROQ_API_KEY)

    formatted = _format_transcript(transcript)

    user_msg = f"Транскрипт созвона"
    if date:
        user_msg += f" от {date}"
    user_msg += f":\n\n{formatted}"

    print(f"[structure] Sending {len(formatted)} chars to LLM (llama-3.3-70b)...")

    # Try 70B first, fallback to Scout if rate limited
    response = None
    for model in ["llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"]:
        try:
            print(f"[structure] Trying {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            break
        except Exception as e:
            print(f"[structure] {model} failed: {e}")
            continue

    if not response:
        raise RuntimeError("All models failed")

    result_md = response.choices[0].message.content

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{meeting_id}_protocol.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result_md)

    print(f"[structure] Protocol saved → {output_path}")
    return output_path


def _format_transcript(transcript: dict) -> str:
    """Format transcript segments with timestamps."""
    if not transcript.get("segments"):
        return transcript.get("text", "")

    lines = []
    for seg in transcript["segments"]:
        start = seg.get("start", 0)
        mm, ss = divmod(int(start), 60)
        hh, mm = divmod(mm, 60)
        ts = f"[{hh:02d}:{mm:02d}:{ss:02d}]"
        lines.append(f"{ts} {seg['text'].strip()}")

    return "\n".join(lines)
