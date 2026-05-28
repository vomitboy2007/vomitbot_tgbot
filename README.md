# vomitboy_tg

Telegram-бот-персонаж в стиле канала **v0mitboy//** (Ярослав Вомитов / вомитбойчик).
Стиль ответов и характер построены на парсинге `messages.html` — экспортированной истории канала.
Реплики генерирует **xAI Grok** (`grok-4.3` по умолчанию).

## Архитектура

- `bot/__main__.py` — точка входа, поднимает long-polling Telegram и health-сервер для Railway.
- `bot/handlers.py` — реакция в личке и группах, история диалога на чат.
- `bot/persona.py` — системный промпт + few-shot из реального корпуса канала.
- `bot/grok_client.py` — async-клиент к xAI Chat Completions (OpenAI-совместимый).
- `bot/config.py` — все настройки через env.
- `scripts/parse_messages.py` — генерит `data/persona_corpus.json` из `messages.html`.

## Поведение

- **В личке** бот отвечает на каждое текстовое сообщение.
- **В группах** бот отвечает если:
  - его упомянули `@username`;
  - ему ответили (reply);
  - в тексте встречается одно из имён из `BOT_NAME_ALIASES` (`ярик`, `вомит`, `вомитбойчик`, ...);
  - случайно — с вероятностью `GROUP_REPLY_CHANCE` (по умолчанию 5%).
- `/reset` — очистить контекст диалога в текущем чате.
- `/start` — фирменное «я и кто.»

### Privacy mode в группах

По умолчанию Telegram-боты создаются в **Privacy Mode** — они видят в группах
**только** сообщения, где их упомянули `@`, на которые ответили, и команды.
Это нормальный режим для базовой работы (упоминание/реплай — всё работает).

Если хочешь, чтобы бот мог **случайно вписываться** в групповую беседу
(`GROUP_REPLY_CHANCE > 0`), нужно выключить Privacy Mode:

1. В Telegram пиши `@BotFather` → `/setprivacy` → выбери своего бота → **Disable**.
2. Удали и заново добавь бота в группу (или сделай его админом) — Telegram кэширует флаг.

Если режим включён, бот всё равно работает на упоминаниях и реплаях — просто без рандомных вбросов.

## Локальный запуск

```bash
python -m pip install -r requirements.txt

# 1) Регенерировать корпус из messages.html (один раз)
python scripts/parse_messages.py

# 2) Установить переменные окружения (Windows PowerShell)
$env:TG_BOT_TOKEN="..."
$env:XAI_API_KEY="..."
$env:XAI_MODEL="grok-4.3"

# 3) Запуск
python -u -m bot
```

Шаблон env-переменных — в `.env.example`.

## Деплой на Railway через GitHub

1. **Создай репозиторий на GitHub** и запушь этот проект:

   ```bash
   git init
   git add .
   git commit -m "init vomitboy bot"
   git branch -M main
   git remote add origin https://github.com/<твой-юзер>/vomitbot_tg.git
   git push -u origin main
   ```

2. На [railway.com](https://railway.com) → **New Project → Deploy from GitHub repo** → выбери репозиторий.

3. В разделе **Variables** добавь переменные:

   | Переменная        | Значение                                          |
   |-------------------|---------------------------------------------------|
   | `TG_BOT_TOKEN`    | токен от BotFather                                |
   | `XAI_API_KEY`     | ключ от xAI (`xai-...`)                           |
   | `XAI_MODEL`       | `grok-4.3` (или другой доступный)                 |
   | `XAI_BASE_URL`    | `https://api.x.ai/v1` (можно не задавать)         |
   | `LOG_LEVEL`       | `INFO`                                            |

   Остальное (`GROUP_REPLY_CHANCE`, `HISTORY_SIZE`, ...) — опционально.
   Не клади токены в коммит — только в Railway Variables.

4. Railway сам подхватит `railway.json` / `nixpacks.toml` / `Procfile`, поднимет Python 3.12 и запустит
   `python -u -m bot`. Healthcheck смотрит в `/healthz` на порту, который Railway передаёт через `$PORT`.

5. После старта зайди в логи Railway — должно появиться:

   ```
   Бот авторизован как @<bot_username>
   Health-сервер слушает 0.0.0.0:<port>
   Long polling запущен.
   ```

6. Напиши боту в личку или добавь в чат и упомяни `@<bot_username>`.

## Замечания по xAI / модели

- Если `grok-4.3` недоступен в твоём аккаунте — переопредели `XAI_MODEL` (например `grok-4-latest`, `grok-4`, `grok-3`).
  При ошибке от xAI бот не падает, а отвечает короткой репликой в стиле персонажа.
- `XAI_TEMPERATURE` по умолчанию `0.95` — повышен, чтобы стиль был живее. Снизь до `0.7` если несёт.

## Где хранится «личность»

- `data/persona_corpus.json` — все извлечённые сообщения с канала (488 шт.).
- На каждый запрос системный промпт собирается заново: базовый шаблон + случайная выборка коротких и длинных постов как few-shot. Это даёт стилевое разнообразие и снижает «зацикливание» модели на одних и тех же примерах.

## Лицензия

Internal / personal.
