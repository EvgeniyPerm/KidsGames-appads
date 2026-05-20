# Update app-ads.txt (AZON)

Автоматическое ежедневное обновление `app-ads.txt` и `ads.txt` для AZON.

## Как работает

Сервис запускается каждый день в 06:00 по `Africa/Johannesburg` через GitHub Actions.

1. Скачивает исходный файл:
   `https://raw.githubusercontent.com/cleveradssolutions/App-ads.txt/master/app-ads.txt`
2. Проверяет дату в первой строке.
3. Если дата не сегодняшняя и не завтрашняя, пишет `YYYY-MM-DD HH:MM checked` в лог и завершает работу.
4. Если дата свежая, собирает новый файл:
   - добавляет блок AZON с текущей датой;
   - добавляет исходный файл;
   - вторую строку исходного файла заменяет на `OwnerDomain=AZON.games`.
5. Загружает на FTP три одинаковые копии:
   - `app-ads.txt`
   - `ads.txt`
   - `YYYY-MM-DD AZON app-ads.txt`
6. Проверяет:
   - `https://www.AZON.games/ads.txt`
   - `https://www.AZON.games/app-ads.txt`
7. Отправляет сообщение в Telegram.

## Логи

Лог пишется в `logs/app-ads-updater.log`.

В GitHub Actions этот файл сохраняется как artifact `app-ads-updater-log`. Кроме того, все важные сообщения видны прямо в логе запуска workflow.

Если обновления нет, строка в логе выглядит так:

```text
2026-05-20 21:19 checked
```

## GitHub Secrets

В приватном репозитории нужно открыть:

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Добавить:

```text
FTP_HOST=tairgames.top
FTP_PORT=21
FTP_USER=...
FTP_PASSWORD=...
FTP_REMOTE_DIR=tairgames.top
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`TELEGRAM_CHAT_ID` нельзя надежно заменить username `@EvgeniyPerm`: боту нужно получить числовой chat id после того, как вы один раз напишете ему `/start`.

## Локальный запуск

Проверить сборку без FTP:

```powershell
python app_ads_updater.py --dry-run
```

Запустить тесты:

```powershell
python -m unittest discover -s tests
```

## Создание приватного репозитория

Имя репозитория на GitHub лучше сделать без пробелов и спецсимволов:

```text
Update-app-ads-txt-AZON
```

Отображаемое название в README уже оставлено как `Update app-ads.txt (AZON)`.

Если установить GitHub CLI и авторизоваться, репозиторий можно создать командой:

```powershell
gh repo create EvgeniyPerm/Update-app-ads-txt-AZON --private --source . --remote origin --push
```

Без GitHub CLI нужно один раз вручную создать private repository в браузере и выполнить команды из блока, который GitHub покажет для existing repository.
