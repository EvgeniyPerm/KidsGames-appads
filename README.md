# KidsGames app-ads.txt updater

Автоматическое ежедневное обновление `app-ads.txt` и `ads.txt` для KidsGames.

## Как работает

Сервис запускается каждый день через GitHub Actions.

1. Скачивает основной исходный файл:
   `https://raw.githubusercontent.com/cleveradssolutions/App-ads.txt/master/app-ads.txt`
2. Проверяет дату в первой строке.
3. Если дата не сегодняшняя и не завтрашняя, пишет `YYYY-MM-DD HH:MM checked` в лог и завершает работу.
4. Если дата свежая, собирает новый файл:
   - добавляет блок KidsGames с текущей датой;
   - добавляет основной исходный файл;
   - вторую строку исходного файла заменяет на `OwnerDomain=kidsgames.top`;
   - добавляет включенные дополнительные источники из `EXTRA_SOURCES`.
5. Загружает на FTP:
   - `app-ads.txt`
   - `ads.txt`
   - `YYYY-MM-DD KidsGames app-ads.txt`
6. Проверяет:
   - `https://www.kidsgames.top/ads.txt`
   - `https://www.kidsgames.top/app-ads.txt`
7. Отправляет сообщение в Telegram.

## Локальный запуск

Проверить сборку без FTP:

```powershell
python app_ads_updater.py --dry-run
```

Проверить конкретный источник:

```powershell
python app_ads_updater.py --test-source unity
```

Запустить тесты:

```powershell
python -m unittest discover -s tests
```

## GitHub Secrets

Минимально нужны:

```text
FTP_HOST=kidsgames.top
FTP_PORT=21
FTP_USER=...
FTP_PASSWORD=...
FTP_REMOTE_DIR=kidsgames.top
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
NOTIFICATIONS_ENABLED=false
```

`NOTIFICATIONS_ENABLED=false` оставляет Telegram-уведомления выключенными на время разработки.
GitHub Actions также не завершает ручные dev-запуски красным по умолчанию; для строгой проверки запустите workflow с `fail_on_error=true`.

Дополнительные источники включаются через `EXTRA_SOURCES`, например:

```text
EXTRA_SOURCES=mintegral,unity,vungle,ironsource,dtexchange,yandex,chartboost
```

Для Unity используются:

```text
UNITY_SOURCE_URL=...
UNITYADS_AUTH=...
UNITY_AUTH=...
UNITY_COOKIE=...
UNITY_PUBLISHER_WEB_URL=https://www.kidsgames.top/app-ads.txt
```
