# docmost-mcp-remote

[English](README.md) · **Русский**

[![CI](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Python](https://img.shields.io/pypi/pyversions/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Container](https://img.shields.io/badge/ghcr.io-docmost--mcp--remote-blue?logo=docker&logoColor=white)](https://github.com/bbik52/docmost-mcp-remote/pkgs/container/docmost-mcp-remote)
[![Docmost](https://img.shields.io/badge/Docmost%20CE-0.70%2B-6d28d9)](#поддерживаемые-версии-docmost)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

Самостоятельно размещаемый удалённый [MCP](https://modelcontextprotocol.io)-сервер
для [Docmost](https://docmost.com) Community Edition. Запустите его рядом со
своим Docmost, опубликуйте на своём домене, и ИИ-клиенты (Claude, Claude Code,
Cursor, VS Code) смогут читать и редактировать вики от имени каждого
участника, с его собственной учётной записью и правами в Docmost.

> Независимый проект сообщества, не связанный с Docmost, Inc. и не одобренный ею.
> Docmost является товарным знаком Docmost, Inc.; название используется только
> для указания, с каким ПО работает этот сервер.

- **Один сервер, один Docmost, много участников.** Каждый участник входит
  своей учётной записью Docmost в браузере. Всё, что делает его ИИ-клиент,
  выполняется в Docmost от его имени.
- **Авторизация обязательна.** OAuth 2.1 для удалённых коннекторов и
  персональные bearer-токены для скриптов. Режима без авторизации нет.
- **Безопасно по умолчанию.** Без явного согласия выдаётся только `read`.
  Запись, перенос в корзину и управление пространствами требуют отдельных прав. Ничего не удаляется
  безвозвратно, а перед каждым изменением сервер сохраняет зашифрованный
  снимок тела страницы.
- **Своя инсталляция.** Один контейнер и Postgres, готовый `compose.yaml`.

[Быстрый старт](#быстрый-старт) · [Подключение клиента](#подключение-клиента) · [Инструменты](#инструменты) · [Ресурсы и промпты](#ресурсы-и-промпты) · [Модель безопасности](#модель-безопасности) · [Настройки](#настройки) · [Обновление](#обновление)

## Как это устроено

```mermaid
flowchart LR
    member(["Участник"]) -. "один раз входит<br/>своей учёткой Docmost" .-> server
    client["ИИ-клиент<br/>Claude, Cursor, VS Code"] -- "MCP по https<br/>OAuth 2.1 или персональный токен" --> server["docmost-mcp-remote"]
    server -- "API Docmost<br/>от имени участника" --> docmost["Docmost CE"]
    server --- db[("Postgres<br/>сессии, снимки,<br/>журнал аудита")]
```

При первом подключении клиента участник входит своей почтой и паролем
Docmost и выбирает, что клиенту разрешено. Все подключённые приложения и
токены видны на странице аккаунта, там же их можно отозвать.

<table>
<tr>
<td width="50%"><img src="docs/images/consent.png" alt="Страница согласия: разрешить Claude работать с Docmost от вашего имени, с правами read, write, delete и admin"></td>
<td width="50%"><img src="docs/images/account.png" alt="Страница аккаунта: подключённые приложения, персональные токены и форма создания токена"></td>
</tr>
<tr>
<td align="center">Выбор прав для клиента</td>
<td align="center">Подключённые приложения и персональные токены</td>
</tr>
</table>

## Поддерживаемые версии Docmost

Docmost Community Edition **0.70.0 и новее**. Более старые версии
отклоняются при входе. CI прогоняет интеграционные тесты на Docmost 0.70.3,
0.96.0 и 0.97.0; более новые релизы в большинстве случаев работают и пишут в
лог предупреждение, пока их не добавят в проверяемый диапазон. Пользователи,
которые входят в Docmost только через SSO (функция Enterprise), не смогут
работать через этот сервер: он входит по email и паролю. Метки и обратные
ссылки требуют Docmost 0.90 и новее, а фильтры поиска `title_only` и `labels`
и `list_attachments` требуют 0.96 и новее; на более старых версиях эти
инструменты отвечают, что Docmost нужно обновить.

## Инструменты

| Инструмент | Право | Что делает |
|---|---|---|
| `whoami` | read | Учётная запись Docmost, права и версия Docmost для этого подключения, а также ссылка на страницу аккаунта |
| `list_spaces` | read | Доступные вам пространства и ваша роль в них |
| `get_space` | read | Одно пространство: описание, видимость, число участников, ваша роль |
| `list_pages` | read | Дерево страниц пространства, по одному уровню за раз |
| `get_page_tree` | read | Несколько уровней дерева страниц за один вызов, с ограничением глубины и размера |
| `check_space_health` | read | Устаревшие, пустые и безымянные страницы, повторы названий, битые ссылки и главные авторы пространства |
| `recent_pages` | read | Недавно изменённые страницы |
| `get_page` | read | Одна страница в Markdown или в ProseMirror JSON со всем оформлением, по id, slug id или URL в Docmost |
| `get_page_outline` | read | Заголовки страницы, чтобы найти раздел, не читая всё тело |
| `get_section` | read | Один раздел страницы с хешем для `replace_section` |
| `suggest` | read | Быстрый поиск страниц, людей и групп по названию |
| `search` | read | Полнотекстовый поиск с фрагментами; фильтры по заголовку, меткам и своим страницам |
| `list_comments` | read | Комментарии и ответы на странице |
| `list_trash` | read | Страницы в корзине пространства |
| `list_snapshots` | read | Снимки, которые сервер сохранил перед вашими изменениями страницы |
| `list_page_history` | read | Версии страницы, сохранённые Docmost, и кто их менял |
| `get_page_version` | read | Одна сохранённая версия страницы в Markdown |
| `list_space_members` | read | Пользователи и группы с ролью в пространстве |
| `list_workspace_members` | read | Люди в рабочем пространстве и их роли |
| `list_groups` | read | Группы рабочего пространства |
| `diff_page` | read | Unified diff между текущим телом, сохранённой версией или снимком |
| `list_backlinks` | read | Страницы, которые ссылаются на страницу, или на которые ссылается она (Docmost 0.90+) |
| `list_labels` | read | Метки рабочего пространства или одной страницы (Docmost 0.90+) |
| `find_pages_by_label` | read | Страницы с меткой в пространстве (Docmost 0.90+) |
| `export_page` | read | Страница в Markdown или HTML; с дочерними или файлами — ссылка на zip |
| `export_space` | read | Ссылка на zip со всем пространством (для админов пространства) |
| `list_attachments` | read | Файлы, загруженные на страницу (Docmost 0.96+) |
| `get_attachment` | read | Сведения о файле и ссылка на скачивание; небольшие текстовые файлы сразу в ответе |
| `create_page` | write | Новая страница с телом в Markdown, при необходимости внутри родительской |
| `update_page` | write | Добавить в конец, в начало или заменить тело страницы на Markdown; `dry_run` показывает diff |
| `replace_section` | write | Заменить один раздел страницы; отказ, если раздел изменился после чтения |
| `rename_page` | write | Изменить заголовок страницы |
| `move_page` | write | Переместить страницу внутри пространства: в начало, в конец или после соседней |
| `move_page_to_space` | write | Перенести страницу с дочерними в другое пространство |
| `duplicate_page` | write | Скопировать страницу с дочерними в то же или в другое пространство |
| `add_comment` | write | Прокомментировать страницу или ответить на комментарий, можно с @-упоминанием людей, которым Docmost пришлёт уведомление |
| `update_comment` | write | Изменить текст своего комментария |
| `add_labels` | write | Добавить метки странице (Docmost 0.90+) |
| `remove_label` | write | Убрать метку со страницы (Docmost 0.90+) |
| `upload_attachment` | write | Загрузить файл (base64, до 10 МБ) и добавить его в конец страницы |
| `replace_page_json` | write | Заменить тело страницы на ProseMirror JSON, сначала проверив его по схеме редактора; `dry_run` показывает diff |
| `restore_snapshot` | write | Вернуть тело страницы к снимку |
| `restore_page_version` | write | Вернуть тело страницы к версии из истории вместе с оформлением |
| `trash_page` | delete | Переместить страницу в корзину |
| `restore_page` | delete | Восстановить страницу из корзины |
| `create_space` | admin | Создать пространство |
| `update_space` | admin | Изменить название, slug или описание пространства |
| `add_space_members` | admin | Дать пользователям (по почте) и группам (по названию) роль в пространстве |
| `change_space_member_role` | admin | Сменить роль пользователя или группы в пространстве |

Тела страниц, комментарии и фрагменты возвращаются в обёртке
`<docmost-untrusted-content>`, чтобы модель считала их данными.

Перед каждым изменением тела страницы сервер сохраняет текущее тело как
зашифрованный снимок в своей базе на `SNAPSHOT_RETENTION_DAYS` дней; если
снимок сохранить не удалось, ничего не записывается. После изменения сервер
перечитывает страницу и сообщает об ошибке, если Docmost его не применил (так
бывает, когда Docmost запущен с `COLLAB_DISABLE_REDIS`). Снимки могут хранить
содержимое страниц, позже удалённых в Docmost, пока не истечёт их срок.

Изменение, которое переписывает всё тело (замена, раздел, запись JSON,
восстановление), не выполняется, пока страницу редактирует кто-то другой, то
есть если другой человек сохранял её в последнюю минуту: иначе то, что он
печатает, пропало бы. Добавление в начало или конец сливается с его правками и
не блокируется.

## Ресурсы и промпты

Кроме инструментов, которые модель выбирает сама, сервер предлагает ресурсы и
промпты, которые выбираете вы в своём клиенте, если клиент их поддерживает
(Claude Desktop и Claude Code поддерживают, многие клиенты умеют только
инструменты).

| Ресурс | Что в нём |
|---|---|
| `docmost://spaces` | Пространства, к которым у вас есть доступ, и ваша роль |
| `docmost://pages/{page}` | Одна страница в Markdown с её местом и ссылкой. Пока вы вводите название, клиент получает подходящие страницы |

| Промпт | Право | О чём просит |
|---|---|---|
| `summarize_page` | read | Сводка страницы: назначение, главное, что выглядит устаревшим |
| `summarize_space` | read | Обзор пространства: что в нём есть, как оно устроено, чего не хватает |
| `answer_from_wiki` | read | Ответ только по страницам вики, со ссылками на них |
| `whats_new` | read | Что изменилось в вики или в пространстве за последние дни, по страницам |
| `draft_page` | write | Черновик страницы на тему после проверки, нет ли уже такой; создаётся после вашего согласия |
| `tidy_page` | write | Структура и формулировки страницы лучше, факты те же; запись после вашего согласия |

Промпт только формулирует запрос, работу делает модель теми инструментами,
которые разрешены подключению. Чтение ресурсов учитывается в
`TOOL_CALLS_PER_MINUTE` и попадает в журнал аудита как `read_resource`.

## Модель безопасности

Участники входят своей учётной записью Docmost; всё, что делает клиент,
выполняется от имени этого участника и с его правами в Docmost. Сервер
хранит сессионный токен Docmost зашифрованным ключом, производным от
`SECRET_KEY`, и не хранит пароли, если не включён
`RELOGIN_MODE=stored_password`. Персональные токены хранятся в виде хешей и
показываются один раз. Страница входа защищена от CSRF и ограничивает
частоту попыток по IP и по email.

Сервер сам является сервером авторизации OAuth 2.1 по спецификации
авторизации MCP: динамическая регистрация клиентов (с ограничением по IP;
redirect URI должен быть https, loopback http или схемой нативного
приложения), authorization code с PKCE (только S256), точное совпадение
redirect URI, токены привязаны к ресурсу `/mcp` этого сервера, access-токены
живут час, refresh-токены 30 дней и меняются при каждом использовании.
Повторное использование refresh-токена или кода отзывает весь доступ. OAuth-
доступы и персональные токены видны и отзываются на одной странице аккаунта.

Содержимое страниц считается недоверенными данными и помечается так для
модели. Инъекция инструкций в тексте страницы всё равно может заставить
клиента действовать в пределах прав, которые выдал участник, поэтому `write`,
`delete` и `admin` выдавайте только клиентам, которым доверяете. Вызовы инструментов
и чтение ресурсов ограничены по частоте для каждого участника и пишутся в
журнал аудита.

Экспорт нескольких страниц и скачивание файлов выдаются ссылками на этот
сервер, которые действуют десять минут. Ссылка в зашифрованном виде хранит,
кто и что запросил, поэтому любой, у кого она есть, может скачать файл, пока
она не истекла; сервер передаёт файл из Docmost с сессией этого участника и
ничего не сохраняет. В журнал доступа ссылки не попадают.

Подробнее: [модель угроз](docs/security-model.md),
[SECURITY.md](SECURITY.md) о том, как сообщить об уязвимости, и
[дизайн](docs/DESIGN.md) (на английском).

## Быстрый старт

Нужны Docker с Compose, Docmost, доступный с сервера, и доменное имя с https
для самого сервера, например `mcp.example.com`.

1. Скачайте файл compose и шаблон настроек:

   ```sh
   mkdir docmost-mcp && cd docmost-mcp
   curl -fsSLO https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/compose.yaml
   curl -fsSL -o .env https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/.env.example
   ```

2. Отредактируйте `.env`: укажите `PUBLIC_URL` (https-адрес этого сервера),
   `DOCMOST_URL`, длинный случайный `POSTGRES_PASSWORD` и `SECRET_KEY`
   (`openssl rand -hex 32` даёт подходящее значение для обоих). Подумайте об
   `ALLOWED_EMAILS`, чтобы ограничить, кто может входить.

3. Запустите и проверьте, что сервер работает:

   ```sh
   docker compose up -d
   curl http://127.0.0.1:8000/healthz
   ```

4. Поставьте перед `127.0.0.1:8000` обратный прокси с https (см. ниже),
   откройте в браузере `PUBLIC_URL/login` и проверьте, что входите своей
   учётной записью Docmost.

5. Подключите клиент (см. [Подключение клиента](#подключение-клиента)).

Сервер применяет миграции базы при старте. Делайте резервные копии тома
Postgres так же, как резервные копии Docmost: в нём зашифрованные сессии,
снимки и журнал аудита. Потеря `SECRET_KEY` разлогинит всех участников и
сделает снимки нечитаемыми.

<details>
<summary>Файл <code>compose.yaml</code></summary>

```yaml
# docmost-mcp-remote: the server and its Postgres.
# Copy .env.example to .env and fill in the required values first, then put a
# reverse proxy with https in front of port 8000.

services:
  server:
    # "1" follows 1.x releases; set IMAGE_TAG to a full version such as 1.1.0 to pin one.
    image: ghcr.io/bbik52/docmost-mcp-remote:${IMAGE_TAG:-1}
    restart: unless-stopped
    environment:
      PUBLIC_URL: ${PUBLIC_URL:?set PUBLIC_URL to the public https URL of this server}
      DOCMOST_URL: ${DOCMOST_URL:?set DOCMOST_URL to the base URL of your Docmost}
      DOCMOST_ALLOW_INSECURE_HTTP: ${DOCMOST_ALLOW_INSECURE_HTTP:-false}
      DATABASE_URL: postgresql://docmost_mcp:${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}@postgres:5432/docmost_mcp
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY to a random value of at least 32 characters}
      SECRET_KEY_PREVIOUS: ${SECRET_KEY_PREVIOUS:-}
      ALLOWED_EMAILS: ${ALLOWED_EMAILS:-}
      ALLOWED_SPACES: ${ALLOWED_SPACES:-}
      RELOGIN_MODE: ${RELOGIN_MODE:-ask}
      SNAPSHOT_RETENTION_DAYS: ${SNAPSHOT_RETENTION_DAYS:-30}
      AUDIT_RETENTION_DAYS: ${AUDIT_RETENTION_DAYS:-90}
      TOOL_CALLS_PER_MINUTE: ${TOOL_CALLS_PER_MINUTE:-60}
      MAX_PAGE_CHARS: ${MAX_PAGE_CHARS:-60000}
      # The port is published on 127.0.0.1 only, so every client is a local proxy.
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-*}
      LOG_LEVEL: ${LOG_LEVEL:-info}
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true

  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: docmost_mcp
      POSTGRES_DB: docmost_mcp
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U docmost_mcp -d docmost_mcp"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres-data:
```

</details>

Сервер также есть на PyPI (`pip install docmost-mcp-remote` или
`uvx docmost-mcp-remote`) для установок без контейнеров; ему нужен Postgres
и те же настройки в переменных окружения.

## Обратный прокси

Сервер слушает обычный http и ожидает обратный прокси, который терминирует
https. Отдавайте его с корня отдельного домена; размещение в подпути не
поддерживается. Прокси не должен буферизовать ответы, потому что MCP их
стримит.

Caddy (сам получает сертификаты):

```caddyfile
mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

<details>
<summary>nginx</summary>

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

</details>

Сервер использует `X-Forwarded-For` для ограничений частоты по IP. Файл
compose публикует порт только на 127.0.0.1 и доверяет этому заголовку от
любого клиента; если публикуете порт иначе, укажите в `FORWARDED_ALLOW_IPS`
адрес прокси.

## Подключение клиента

Адрес MCP: `PUBLIC_URL/mcp`, например `https://mcp.example.com/mcp`.
Клиенты с поддержкой авторизации MCP открывают окно браузера: войдите своей
почтой и паролем Docmost и выберите, что клиенту разрешено. `read` выдаётся
всегда; `write`, `delete` и `admin` отмечайте только для клиентов, которым
доверяете.

**Claude.ai и Claude Desktop**: Settings, Connectors, Add custom connector,
затем укажите адрес. Для Claude.ai сервер должен быть доступен из интернета
по https.

**Claude Code**:

```sh
claude mcp add --transport http docmost https://mcp.example.com/mcp
```

Затем выполните `/mcp` в Claude Code, чтобы войти.

**Cursor** (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "docmost": { "url": "https://mcp.example.com/mcp" }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "docmost": { "type": "http", "url": "https://mcp.example.com/mcp" }
  }
}
```

**С персональным токеном** (скрипты и клиенты без OAuth):

1. Откройте `PUBLIC_URL/login` и войдите почтой и паролем Docmost.
2. На странице аккаунта создайте персональный токен с нужными правами.
3. Настройте клиент на адрес MCP и заголовок
   `Authorization: Bearer <токен>`:

   ```sh
   claude mcp add --transport http docmost https://mcp.example.com/mcp \
     --header "Authorization: Bearer dmr_..."
   ```

Подключённые приложения и токены видны и отзываются на странице аккаунта,
`PUBLIC_URL/account`.

## Администрирование

Команда `admin` запускается там же, где сервер, с тем же окружением:

```sh
docker compose exec server docmost-mcp-remote admin members
docker compose exec server docmost-mcp-remote admin migrate
docker compose exec server docmost-mcp-remote admin grants anna@example.com
docker compose exec server docmost-mcp-remote admin revoke-grant <grant id>
docker compose exec server docmost-mcp-remote admin revoke-member anna@example.com
docker compose exec server docmost-mcp-remote admin disable-member anna@example.com
docker compose exec server docmost-mcp-remote admin audit --email anna@example.com
```

`revoke-member` отзывает все доступы участника и удаляет его сохранённую
сессию Docmost; `disable-member` блокирует его до `enable-member`. Каждый
вызов инструмента и каждое чтение ресурса пишутся в журнал аудита с
инструментом, id страницы или пространства и результатом, но никогда с содержимым или аргументами.

Смена `SECRET_KEY`: укажите старое значение в `SECRET_KEY_PREVIOUS` и новый
`SECRET_KEY`, перезапустите, выполните `admin rotate-key`, затем уберите
`SECRET_KEY_PREVIOUS` и перезапустите снова.

## Обновление

1. Прочитайте «Upgrade notes» в [журнале изменений](CHANGELOG.md).
2. Сделайте резервную копию базы:

   ```sh
   docker compose exec -T postgres pg_dump -U docmost_mcp -Fc docmost_mcp > docmost-mcp-$(date +%F).dump
   ```

3. Скачайте новый образ и перезапустите:

   ```sh
   docker compose pull && docker compose up -d
   ```

Сервер обновляет схему базы при старте, одной транзакцией и только одним
процессом одновременно, так что неудачное обновление оставляет старую схему.
`docker compose exec server docmost-mcp-remote admin migrate` показывает
версию схемы.

Тег образа `1` следует за релизами 1.x; чтобы закрепить версию, задайте
`IMAGE_TAG` в `.env`. Возврат на старую версию после обновления схемы не
поддерживается: старый сервер не запустится на новой схеме. Чтобы
откатиться, восстановите резервную копию со старым образом:

```sh
docker compose stop server
docker compose exec -T postgres pg_restore -U docmost_mcp -d docmost_mcp --clean --if-exists < docmost-mcp-2026-01-31.dump
IMAGE_TAG=1.1.0 docker compose up -d
```

## Настройки

| Переменная | Обязательна | По умолчанию | Значение |
|---|---|---|---|
| `PUBLIC_URL` | да | | Публичный https-адрес этого сервера |
| `DOCMOST_URL` | да | | Базовый адрес вашего Docmost |
| `DOCMOST_ALLOW_INSECURE_HTTP` | нет | `false` | Разрешить `http://` в `DOCMOST_URL` в доверенной частной сети |
| `DATABASE_URL` | да | | Адрес Postgres (`postgresql://user:password@host/db`) |
| `SECRET_KEY` | да | | Не короче 32 символов; шифрует сохранённые сессии Docmost и подписывает cookie |
| `SECRET_KEY_PREVIOUS` | нет | | Старый ключ во время смены |
| `ALLOWED_EMAILS` | нет | пусто | Email через запятую, которым разрешён вход; пусто: любой пользователь Docmost |
| `ALLOWED_SPACES` | нет | пусто | Slug или id пространств через запятую, доступных через этот сервер; пусто: все |
| `MAX_PAGE_CHARS` | нет | `60000` | Самое длинное возвращаемое тело страницы; длиннее обрезается |
| `SNAPSHOT_RETENTION_DAYS` | нет | `30` | Сколько дней хранится снимок тела страницы |
| `AUDIT_RETENTION_DAYS` | нет | `90` | Сколько дней хранится запись журнала аудита |
| `TOOL_CALLS_PER_MINUTE` | нет | `60` | Сколько вызовов инструментов и чтений ресурсов в минуту может сделать участник, по всем своим клиентам |
| `WEB_SESSION_HOURS` | нет | `12` | Сколько часов действует вход на страницу аккаунта |
| `RELOGIN_MODE` | нет | `ask` | `ask`: участник входит заново, когда истекает его сессия Docmost; `stored_password`: пароль хранится зашифрованным и используется для повторного входа |
| `DOCMOST_TIMEOUT_SECONDS` | нет | `15` | Таймаут одного запроса к Docmost |
| `DOCMOST_MAX_RESPONSE_BYTES` | нет | `5242880` | Самый большой ответ Docmost, который читает сервер |
| `FORWARDED_ALLOW_IPS` | нет | `127.0.0.1` | Прокси, которым доверяется `X-Forwarded-For` (`*` в файле compose) |
| `HOST` / `PORT` | нет | `0.0.0.0` / `8000` | Адрес, на котором слушает сервер |
| `LOG_LEVEL` | нет | `info` | `debug`, `info`, `warning` или `error` |
| `IMAGE_TAG` | нет | `1` | Тег образа в `compose.yaml` |

## Разработка

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
DATABASE_TEST_URL=postgresql://test:test@localhost:5433/test uv run pytest
```

Тесты, которым нужен Postgres, пропускаются без `DATABASE_TEST_URL`;
например,
`docker run -d -p 5433:5432 -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test postgres:17-alpine`.

Интеграционные тесты работают с настоящим Docmost:

```sh
DOCMOST_VERSION=0.97.0 docker compose -f tests/integration/compose.yaml up -d
DOCMOST_TEST_URL=http://localhost:3000 uv run pytest tests/integration
```

Запуск стека compose с локальной сборкой:

```sh
docker build -t ghcr.io/bbik52/docmost-mcp-remote:dev .
IMAGE_TAG=dev docker compose up -d
```

См. [CONTRIBUTING.md](CONTRIBUTING.md) и [план развития](docs/ROADMAP.md)
(на английском).

## Лицензия

[Apache License 2.0](LICENSE). Лицензия не распространяется на название
проекта: форки приветствуются под другим именем. Проект является независимой
реализацией и не связан с Docmost. Он вдохновлён
[docmost-mcp-oss](https://github.com/abelsr/docmost-mcp-oss).
