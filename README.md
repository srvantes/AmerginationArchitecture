# Amergination backend

## Локальный запуск

Требуются Python 3.14, PostgreSQL и Redis. Для инфраструктуры можно использовать Docker:

```powershell
docker compose up -d postgres redis
```

Создайте `.env` из `.env.example` и замените `POSTGRES_PASSWORD` и `SECRET_KEY`. Случайный секрет можно получить командой:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Установите зависимости и примените миграцию:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Запустите API:

```powershell
.\.venv\Scripts\python.exe main.py
```

Документация будет доступна по адресу `http://127.0.0.1:8080/docs`.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m compileall -q backend migrations main.py
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
```

Кэш внешних сервисов продолжает работать в режиме пропуска при недоступном Redis. Отзыв JWT при logout требует работающий Redis и возвращает `503`, если сохранить отзыв токена невозможно.
