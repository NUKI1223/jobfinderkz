# Перенос на другое устройство

Есть две независимые части:

- Git / source.zip / project.bundle: исходники, инструкции и доступная история решений. Без ключей, аккаунтов и базы.
- backups/transfer-*/: **приватные данные** — jobfinder.dump, storage/, .env и SHA256.json. Не отправлять в Git или публичный облачный доступ. Архив не зашифрован; переносить лично через защищённый носитель/канал.

Восстановление полного текста всех чатов требует отдельного экспорта через приложение, где эти чаты велись. SESSION_HANDOFF + WORKLOG + CODE_CHANGES сохраняют рабочий контекст проекта, но не являются дословным архивом разговоров или восстановлением интерфейса старых сессий.

## На текущем устройстве

`powershell -ExecutionPolicy Bypass -File scripts/backup-transfer.ps1` создаёт приватную копию в backups/. API и worker останавливаются на время согласованного снимка и возвращаются в прежнее состояние. PostgreSQL остаётся запущенным. Копируется только основная база jobfinder, не тестовые фикстуры.

## На новом устройстве

1. Установить Git, Docker Desktop с WSL2/виртуализацией; для локальной разработки frontend — Node.js. Python/FFmpeg/Deno есть в образах.
2. Клонировать Git-репозиторий. Без remote можно использовать `git clone project.bundle jofinderkz`; source.zip содержит исходники без Git-истории.
3. Перенести приватную папку backup отдельно. Проверить размеры/SHA256 по SHA256.json. Скопировать сохранённый .env в корень проекта. Не печатать его в чат. Сохранённая .env.example содержит только шаблон.
4. Работать в новой папке и с пустыми Docker volumes. Не выполнять следующие шаги поверх существующей ценной базы. Сначала `docker compose up -d db`, затем дождаться healthy (`docker compose ps`). API/worker пока не запускать.
5. В PowerShell выполнить, заменив путь backup:

```powershell
$transferBackup = 'D:\Private\transfer-YYYYMMDD-HHMMSS'
$dbContainer = (docker compose ps -q db).Trim()
docker cp "$transferBackup\jobfinder.dump" "${dbContainer}:/tmp/jobfinder-restore.dump"
docker exec $dbContainer pg_restore -U jobfinder -d jobfinder --no-owner --no-acl --exit-on-error /tmp/jobfinder-restore.dump
```

Остановиться при ошибке восстановления. Dump включает схему, данные, pgvector и alembic_version; не запускать миграции перед pg_restore на чистой базе. Проверка `pg_restore --list` подтверждает читаемость оглавления, но не заменяет успешное восстановление.

6. Восстановить файлы в новый volume до запуска worker:

```powershell
docker compose build api worker web
docker compose create api
$apiContainer = (docker compose ps -a -q api).Trim()
docker cp "$transferBackup\storage\." "${apiContainer}:/storage"
docker compose run --rm --no-deps --user root api chown -R worker:worker /storage
docker compose up -d
```

7. Открыть http://localhost:5173, войти прежним аккаунтом. Проверить API `/api/v1/health`, 5 опубликованных вопросов Python junior RU, 10 опубликованных материалов и исходники двух видео. Ключ Gemini и квота зависят от провайдера; восстановление файлов не гарантирует доступную квоту. HH ещё нужно подключить.
8. Тестовую базу создать отдельно: `docker compose exec db createdb -U jobfinder jobfinder_test`, затем миграции с DATABASE_URL на jobfinder_test. Никогда не запускать тестовые seed/TRUNCATE на jobfinder.

Не копировать сырые файлы PostgreSQL volume между ОС вместо SQL dump. Пароли/сессии и CV находятся в dump/storage: хранить всю резервную копию как приватную. После переноса удалить временный dump из контейнера точной командой `docker exec $dbContainer rm -f /tmp/jobfinder-restore.dump`.

## Продолжение работы с агентом

Передать AGENTS.md и docs/SESSION_HANDOFF.md. Сначала прочитать WORKLOG, IMPLEMENTATION_PLAN, PROGRESS; следующий продуктовый шаг — живая оценка синтетических ответов Gemini на отдельной тестовой базе. Список отложенных работ и границы реальных проверок находятся в этих документах.
