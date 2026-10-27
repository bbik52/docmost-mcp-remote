<div align="center">

# docmost-mcp-remote

**ИИ-ассистенты вашей команды читают и редактируют вики Docmost, каждый участник от своего имени.**

Самостоятельно размещаемый удалённый [MCP](https://modelcontextprotocol.io)-сервер для [Docmost](https://docmost.com) Community Edition.

[![CI](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bbik52/docmost-mcp-remote/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Python](https://img.shields.io/pypi/pyversions/docmost-mcp-remote)](https://pypi.org/project/docmost-mcp-remote/)
[![Container](https://img.shields.io/badge/ghcr.io-docmost--mcp--remote-blue?logo=docker&logoColor=white)](https://github.com/bbik52/docmost-mcp-remote/pkgs/container/docmost-mcp-remote)
[![Docmost](https://img.shields.io/badge/Docmost%20CE-0.70%2B-6d28d9)](#supported-docmost-versions)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-0ea5e9)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.bbik52/docmost-mcp-remote)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/bbik52/docmost-mcp-remote?style=flat&logo=github&label=stars)](https://github.com/bbik52/docmost-mcp-remote/stargazers)

[English](README.md) · **Русский**

[Возможности](#highlights) · [Сравнение](#comparison) · [Быстрый старт](#quick-start) · [Подключение](#connecting-a-client) · [Инструменты](#tools) · [Безопасность](#security-model) · [Настройки](#configuration) · [Обратная связь](#feedback)

</div>

Запустите сервер рядом со своим Docmost, опубликуйте на своём домене и
подключите Claude, Claude Code, Cursor, VS Code или любой другой MCP-клиент.
Каждый участник входит своей учётной записью Docmost, поэтому ассистент видит
ровно то, что видит он сам, а каждое изменение в Docmost подписано его именем.

> Независимый проект сообщества, не связанный с Docmost, Inc. и не одобренный ею.
> Docmost является товарным знаком Docmost, Inc.; название используется только
> для указания, с каким ПО работает этот сервер.

<a id="highlights"></a>

## ✨ Возможности

- 👥 **Один сервер на всю команду.** Каждый участник один раз входит в
  браузере своей учётной записью Docmost. Всё, что делает его ИИ-клиент,
  выполняется от его имени и с его правами в Docmost.
- 🔐 **Настоящая авторизация.** OAuth 2.1 для удалённых коннекторов
  (Claude.ai, Claude Desktop, Claude Code, Cursor, VS Code) и персональные
  токены для скриптов. Режима без авторизации нет.
- 🛡️ **Безопасно по умолчанию.** Без явного согласия выдаётся только `read`;
  `write`, `delete` и `admin` включаются для каждого клиента отдельно. Ничего
  не удаляется безвозвратно, перед рискованными изменениями сервер спрашивает
  вас, а перед каждым изменением сохраняет зашифрованный снимок страницы.
- 🧰 **62 инструмента.** Чтение, поиск, правка по разделам, комментарии с
  @-упоминаниями, перемещение, метки, экспорт, возврат старых версий, проверка
  состояния пространства и управление рабочим пространством: пространства,
  группы, приглашения и роли.
- 📎 **Файлы без траты токенов.** Ассистент даёт ссылку для загрузки:
  перетащите файлы в браузере, расставьте по порядку, и они попадут в нужное
  место страницы.
- 🐳 **Легко развернуть.** Один контейнер и Postgres с готовым `compose.yaml`
  или `pip install`. CI проверяет работу с Docmost от 0.70 до 0.97.

> ⭐ **Если сервер вам пригодился, пожалуйста, [поставьте звезду репозиторию](https://github.com/bbik52/docmost-mcp-remote/stargazers).**
> Так его проще найти другим пользователям Docmost, а нам понятно, что работа нужна.

<a id="comparison"></a>

## 🆚 Сравнение

Открытых MCP-серверов для Docmost Community Edition несколько. Большинство из
них работают на компьютере одного человека с одной общей учётной записью
Docmost. Этот сервер сделан для команды.

| Возможность | Этот сервер | Другие MCP-серверы для Docmost CE |
|---|:---:|:---:|
| Удалённый сервер для многих людей со входом через OAuth 2.1 | ✅ | ❌ |
| Каждый участник работает своей учётной записью и с правами Docmost | ✅ | ❌ |
| Права для каждого клиента, по умолчанию только чтение | ✅ | ⚠️ в лучшем случае общий режим только для чтения |
| Ничего не удаляется безвозвратно | ✅ | ❌ |
| Зашифрованный снимок перед каждым изменением и возврат к нему | ✅ | ❌ |
| Проверка записи повторным чтением | ✅ | ⚠️ редко |
| Рискованные изменения сначала подтверждаете вы в клиенте (MCP elicitation) | ✅ | ⚠️ редко |
| Отказ переписывать страницу, которую сейчас редактирует другой | ✅ | ⚠️ редко |
| Правка одного раздела с отказом, если он изменился после чтения | ✅ | ⚠️ редко |
| Загрузка файлов по ссылке в браузере без траты токенов | ✅ | ❌ |
| Возврат версии страницы со всем оформлением | ✅ | ⚠️ редко |
| Содержимое страниц помечено для модели как недоверенное | ✅ | ⚠️ редко |
| Журнал аудита и ограничение частоты для каждого участника | ✅ | ❌ |
| Проверка пространства: устаревшие, пустые и повторяющиеся страницы, битые ссылки | ✅ | ⚠️ редко |
| Администрирование: приглашения, роли, группы | ✅ | ⚠️ редко |
| Ресурсы и промпты помимо инструментов | ✅ | ⚠️ редко |
| Релизы на PyPI, ghcr.io и в MCP Registry, CI на нескольких версиях Docmost | ✅ | ⚠️ редко |

По открытым MCP-серверам для Docmost CE, которые мы нашли в октябре 2026 года.
Они хорошо подходят одному человеку, работающему локально через stdio, а
некоторые умеют то, чего нет здесь, например удалять безвозвратно.

<a id="how-it-works"></a>

## 🧭 Как это устроено

<p align="center">
  <img src="https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/docs/images/how-it-works.ru.png" width="820" alt="Участник работает в ИИ-клиенте, который обращается к docmost-mcp-remote по MCP через https с OAuth 2.1 или персональным токеном. Участник один раз входит своей учётной записью Docmost. Сервер вызывает API Docmost от имени участника и хранит в Postgres зашифрованные сессии, снимки и журнал аудита.">
</p>

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

<a id="quick-start"></a>

## 🚀 Быстрый старт

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

4. Поставьте перед `127.0.0.1:8000` обратный прокси с https (см. [Обратный прокси](#reverse-proxy)),
   откройте в браузере `PUBLIC_URL/login` и проверьте, что входите своей
   учётной записью Docmost.

5. Подключите клиент (см. [Подключение клиента](#connecting-a-client)).

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
      UPLOAD_RETENTION_MINUTES: ${UPLOAD_RETENTION_MINUTES:-60}
      UPLOAD_MAX_MB: ${UPLOAD_MAX_MB:-50}
      TOOL_CALLS_PER_MINUTE: ${TOOL_CALLS_PER_MINUTE:-60}
      MAX_PAGE_CHARS: ${MAX_PAGE_CHARS:-60000}
      # Proxies on loopback or a private network; the client address is the last
      # untrusted one in X-Forwarded-For, so a header sent by the client is ignored.
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7}
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

<a id="reverse-proxy"></a>

### Обратный прокси

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
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

</details>

Сервер использует `X-Forwarded-For` для ограничений частоты по IP. Прокси
должен записывать в заголовок адрес, который видит сам, а не передавать
присланный клиентом: пример nginx выше делает это через `$remote_addr`, Caddy
и Traefik делают так по умолчанию. Файл compose доверяет прокси на loopback и
в частных сетях (`FORWARDED_ALLOW_IPS`); если прокси обращается к серверу с
публичного адреса, укажите этот адрес.

<a id="connecting-a-client"></a>

## 🔌 Подключение клиента

Адрес MCP: `PUBLIC_URL/mcp`, например `https://mcp.example.com/mcp`.
Клиенты с поддержкой авторизации MCP открывают окно браузера: войдите своей
почтой и паролем Docmost и выберите, что клиенту разрешено. `read` выдаётся
всегда; `write`, `delete` и `admin` отмечайте только для клиентов, которым
доверяете.

<details open>
<summary><strong>Claude.ai и Claude Desktop</strong></summary>

Settings, Connectors, Add custom connector, затем укажите адрес. Для
Claude.ai сервер должен быть доступен из интернета по https.

</details>

<details>
<summary><strong>Claude Code</strong></summary>

```sh
claude mcp add --transport http docmost https://mcp.example.com/mcp
```

Затем выполните `/mcp` в Claude Code, чтобы войти.

</details>

<details>
<summary><strong>Cursor</strong></summary>

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "docmost": { "url": "https://mcp.example.com/mcp" }
  }
}
```

</details>

<details>
<summary><strong>VS Code</strong></summary>

`.vscode/mcp.json`:

```json
{
  "servers": {
    "docmost": { "type": "http", "url": "https://mcp.example.com/mcp" }
  }
}
```

</details>

<details>
<summary><strong>Скрипты и клиенты без OAuth (персональный токен)</strong></summary>

1. Откройте `PUBLIC_URL/login` и войдите почтой и паролем Docmost.
2. На странице аккаунта создайте персональный токен с нужными правами.
   Он действует 90 дней, если не выбрать другой срок (от 7 дней до года или
   бессрочно).
3. Настройте клиент на адрес MCP и заголовок
   `Authorization: Bearer <токен>`:

   ```sh
   claude mcp add --transport http docmost https://mcp.example.com/mcp \
     --header "Authorization: Bearer dmr_..."
   ```

</details>

Подключённые приложения и токены видны и отзываются на странице аккаунта,
`PUBLIC_URL/account`.

<a id="tools"></a>

## 🧰 Инструменты

62 инструмента по группам. Право показывает, что нужно выдать клиенту, чтобы
он увидел инструмент: `read` выдаётся всегда, остальные по выбору.

**Аккаунт и пространства**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 1 | `whoami` | read | Учётная запись Docmost, права и версия Docmost для этого подключения, а также ссылка на страницу аккаунта |
| 2 | `list_spaces` | read | Доступные вам пространства и ваша роль в них |
| 3 | `get_space` | read | Одно пространство: описание, видимость, число участников, ваша роль |
| 4 | `check_space_health` | read | Устаревшие, пустые и безымянные страницы, повторы названий, битые ссылки и главные авторы пространства |

**Просмотр и чтение страниц**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 5 | `list_pages` | read | Дерево страниц пространства, по одному уровню за раз |
| 6 | `get_page_tree` | read | Несколько уровней дерева страниц за один вызов, с ограничением глубины и размера |
| 7 | `recent_pages` | read | Недавно изменённые страницы |
| 8 | `get_page` | read | Одна страница в Markdown или в ProseMirror JSON со всем оформлением, по id, slug id или URL в Docmost |
| 9 | `get_page_outline` | read | Заголовки страницы, чтобы найти раздел, не читая всё тело |
| 10 | `get_section` | read | Один раздел страницы с хешем для `replace_section` |

**Поиск**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 11 | `suggest` | read | Быстрый поиск страниц, людей и групп по названию |
| 12 | `search` | read | Полнотекстовый поиск с фрагментами; фильтры по заголовку, меткам и своим страницам |

**Запись страниц**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 13 | `create_page` | write | Новая страница с телом в Markdown, при необходимости внутри родительской |
| 14 | `update_page` | write | Добавить в конец, в начало или заменить тело страницы на Markdown; `dry_run` показывает diff |
| 15 | `replace_section` | write | Заменить один раздел страницы; отказ, если раздел изменился после чтения |
| 16 | `replace_page_json` | write | Заменить тело страницы на ProseMirror JSON, сначала проверив его по схеме редактора; `dry_run` показывает diff |
| 17 | `rename_page` | write | Изменить заголовок страницы |
| 18 | `move_page` | write | Переместить страницу внутри пространства: в начало, в конец или после соседней |
| 19 | `move_page_to_space` | write | Перенести страницу с дочерними в другое пространство |
| 20 | `duplicate_page` | write | Скопировать страницу с дочерними в то же или в другое пространство |

**Комментарии**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 21 | `list_comments` | read | Комментарии и ответы на странице |
| 22 | `add_comment` | write | Прокомментировать страницу или ответить на комментарий, можно с @-упоминанием людей, которым Docmost пришлёт уведомление |
| 23 | `update_comment` | write | Изменить текст своего комментария |

**История, снимки и возврат**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 24 | `list_page_history` | read | Версии страницы, сохранённые Docmost, и кто их менял |
| 25 | `get_page_version` | read | Одна сохранённая версия страницы в Markdown |
| 26 | `list_snapshots` | read | Снимки, которые сервер сохранил перед вашими изменениями страницы |
| 27 | `diff_page` | read | Unified diff между текущим телом, сохранённой версией или снимком |
| 28 | `restore_page_version` | write | Вернуть тело страницы к версии из истории вместе с оформлением |
| 29 | `restore_snapshot` | write | Вернуть тело страницы к снимку |

**Метки и ссылки**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 30 | `list_backlinks` | read | Страницы, которые ссылаются на страницу, или на которые ссылается она (Docmost 0.90+) |
| 31 | `list_labels` | read | Метки рабочего пространства или одной страницы (Docmost 0.90+) |
| 32 | `find_pages_by_label` | read | Страницы с меткой в пространстве (Docmost 0.90+) |
| 33 | `add_labels` | write | Добавить метки странице (Docmost 0.90+) |
| 34 | `remove_label` | write | Убрать метку со страницы (Docmost 0.90+) |

**Файлы и экспорт**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 35 | `export_page` | read | Страница в Markdown или HTML; с дочерними или файлами — ссылка на zip |
| 36 | `export_space` | read | Ссылка на zip со всем пространством (для админов пространства) |
| 37 | `list_attachments` | read | Файлы, загруженные на страницу (Docmost 0.96+) |
| 38 | `get_attachment` | read | Сведения о файле и ссылка на скачивание; небольшие текстовые файлы сразу в ответе |
| 39 | `create_upload_link` | write | Ссылка, по которой человек перетаскивает файлы в страницу через браузер, а ассистент может отправить их через `curl`; токены не тратятся |
| 40 | `get_upload_status` | read | Какие файлы пришли на ссылку для загрузки и попали ли они уже в страницу |
| 41 | `upload_attachment` | write | Загрузить файл в base64 (до 10 МБ, около миллиона токенов на мегабайт) и добавить его в страницу |

**Корзина**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 42 | `list_trash` | read | Страницы в корзине пространства |
| 43 | `trash_page` | delete | Переместить страницу в корзину |
| 44 | `restore_page` | delete | Восстановить страницу из корзины |

**Люди и группы**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 45 | `list_space_members` | read | Пользователи и группы с ролью в пространстве |
| 46 | `list_workspace_members` | read | Люди в рабочем пространстве и их роли |
| 47 | `list_groups` | read | Группы рабочего пространства |
| 48 | `list_group_members` | read | Участники группы |
| 49 | `list_invitations` | read | Ожидающие приглашения в рабочее пространство |

**Управление пространствами**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 50 | `create_space` | admin | Создать пространство |
| 51 | `update_space` | admin | Изменить название, slug или описание пространства |
| 52 | `add_space_members` | admin | Дать пользователям (по почте) и группам (по названию) роль в пространстве |
| 53 | `change_space_member_role` | admin | Сменить роль пользователя или группы в пространстве |

**Управление рабочим пространством**

| # | Инструмент | Право | Что делает |
|--:|---|---|---|
| 54 | `create_group` | admin | Создать группу, можно сразу с участниками |
| 55 | `update_group` | admin | Переименовать группу или сменить её описание |
| 56 | `add_group_members` | admin | Добавить людей в группу |
| 57 | `invite_people` | admin | Пригласить людей по почте с ролью в рабочем пространстве и группами; уже состоящие и уже приглашённые пропускаются |
| 58 | `resend_invitation` | admin | Отправить приглашение ещё раз |
| 59 | `revoke_invitation` | admin | Отозвать приглашение |
| 60 | `change_workspace_role` | admin | Сделать человека участником, администратором или владельцем рабочего пространства |
| 61 | `deactivate_member` | admin | Запретить человеку вход, сохранив его учётную запись |
| 62 | `activate_member` | admin | Вернуть отключённому участнику возможность входить |

Удалять людей из рабочего пространства или из групп и удалять группы нельзя.
Создать учётную запись или изменить чужой профиль Docmost не позволяет: люди
приходят по приглашению и сами задают пароль.

<a id="safety-nets"></a>

### 🛡️ Страховка

- **Снимки.** Перед каждым изменением тела страницы сервер сохраняет текущее
  тело как зашифрованный снимок в своей базе на `SNAPSHOT_RETENTION_DAYS`
  дней; если снимок сохранить не удалось, ничего не записывается. Снимки
  могут хранить содержимое страниц, позже удалённых в Docmost, пока не истечёт
  их срок.
- **Проверка записи.** После изменения сервер перечитывает страницу и
  сообщает об ошибке, если Docmost его не применил (так бывает, когда Docmost
  запущен с `COLLAB_DISABLE_REDIS`).
- **Подтверждение.** Перед рискованными изменениями сервер спрашивает вас в
  клиенте, если клиент это умеет (MCP elicitation): перемещение страницы в
  корзину, перенос или копирование страницы в другое пространство, роли людей
  и групп в пространстве, приглашения, смена роли в рабочем пространстве и
  отключение человека. Вопрос получаете вы, а не модель, поэтому текст на
  странице не может на него ответить. Если клиент заявил, что умеет
  спрашивать, но вопрос не удался, ничего не меняется. Клиенты, которые
  спрашивать не умеют, выполняют эти изменения без вопроса, в пределах
  выданных вами прав.
- **Занятые страницы.** Изменение, которое переписывает всё тело (замена,
  раздел, запись JSON, восстановление), не выполняется, пока страницу
  редактирует кто-то другой, то есть если другой человек сохранял её в
  последнюю минуту: иначе то, что он печатает, пропало бы. Добавление в начало
  или конец сливается с его правками и не блокируется.
- **Недоверенное содержимое.** Тела страниц, комментарии и фрагменты
  возвращаются в обёртке `<docmost-untrusted-content>`, чтобы модель считала
  их данными.

<a id="adding-files"></a>

### 📎 Добавление файлов

Передать файл через модель дорого: в base64 это около миллиона токенов на
мегабайт. Поэтому `create_upload_link` выдаёт одноразовую ссылку на страницу.
Человек открывает её, перетаскивает или выбирает один или несколько файлов,
расставляет их по порядку и нажимает Done; файлы появляются в странице в
конце, в конце раздела (`after_heading`) или после абзаца (`after_text`).
Ассистент, который умеет запускать команды, отправляет свои файлы на ту же
ссылку через `curl`. До нажатия Done файлы хранятся на этом сервере в
зашифрованном виде; ссылка работает `UPLOAD_RETENTION_MINUTES` минут, и всё,
что не попало в страницу за это время, удаляется. `upload_attachment`
принимает те же параметры места.

<p align="center">
  <img src="https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/docs/images/upload.png" width="560" alt="Страница загрузки: область для файлов, три картинки и PDF со стрелками для изменения порядка и кнопка Done">
</p>

<a id="resources-and-prompts"></a>

## 💬 Ресурсы и промпты

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

<a id="supported-docmost-versions"></a>

## 📦 Поддерживаемые версии Docmost

Docmost Community Edition **0.70.0 и новее**. Более старые версии
отклоняются при входе. CI прогоняет интеграционные тесты на Docmost 0.70.3,
0.96.0 и 0.97.0; более новые релизы в большинстве случаев работают и пишут в
лог предупреждение, пока их не добавят в проверяемый диапазон. Пользователи,
которые входят в Docmost только через SSO (функция Enterprise), не смогут
работать через этот сервер: он входит по email и паролю. Метки и обратные
ссылки требуют Docmost 0.90 и новее, а фильтры поиска `title_only` и `labels`
и `list_attachments` требуют 0.96 и новее; на более старых версиях эти
инструменты отвечают, что Docmost нужно обновить.

<a id="security-model"></a>

## 🔐 Модель безопасности

Участники входят своей учётной записью Docmost; всё, что делает клиент,
выполняется от имени этого участника и с его правами в Docmost. Сервер
хранит сессионный токен Docmost зашифрованным ключом, производным от
`SECRET_KEY`, и не хранит пароли, если не включён
`RELOGIN_MODE=stored_password`. Персональные токены хранятся в виде хешей,
показываются один раз и по умолчанию действуют 90 дней. Страница входа
защищена от CSRF и ограничивает частоту попыток по IP и по email, а кнопка
«Sign out everywhere» на странице аккаунта завершает её сессии во всех
браузерах.

Сервер сам является сервером авторизации OAuth 2.1 по спецификации
авторизации MCP: динамическая регистрация клиентов (с ограничением по IP;
redirect URI должен быть https, loopback http или схемой нативного
приложения), authorization code с PKCE (только S256), точное совпадение
redirect URI, токены привязаны к ресурсу `/mcp` этого сервера, access-токены
живут час, refresh-токены 30 дней и меняются при каждом использовании.
Повторное использование refresh-токена или кода отзывает весь доступ. OAuth-
доступы и персональные токены видны и отзываются на одной странице аккаунта.

Содержимое страниц считается недоверенными данными и помечается так для
модели; из заголовков и имён, которые возвращаются отдельными полями,
удаляются скрытые и управляющие символы, и они обрезаются до 300 символов. Инъекция инструкций в тексте страницы всё равно может заставить
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

<a id="administration"></a>

## 🛠️ Администрирование

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

<a id="upgrading"></a>

## ⬆️ Обновление

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

<a id="configuration"></a>

## ⚙️ Настройки

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
| `UPLOAD_RETENTION_MINUTES` | нет | `60` | Сколько минут работает ссылка для загрузки; файлы, не добавленные в страницу за это время, удаляются |
| `UPLOAD_MAX_MB` | нет | `50` | Наибольший общий размер файлов, отправленных на одну ссылку |
| `TOOL_CALLS_PER_MINUTE` | нет | `60` | Сколько вызовов инструментов и чтений ресурсов в минуту может сделать участник, по всем своим клиентам |
| `WEB_SESSION_HOURS` | нет | `12` | Сколько часов действует вход на страницу аккаунта |
| `RELOGIN_MODE` | нет | `ask` | `ask`: участник входит заново, когда истекает его сессия Docmost; `stored_password`: пароль хранится зашифрованным и используется для повторного входа |
| `DOCMOST_TIMEOUT_SECONDS` | нет | `15` | Таймаут одного запроса к Docmost |
| `DOCMOST_MAX_RESPONSE_BYTES` | нет | `5242880` | Самый большой ответ Docmost, который читает сервер |
| `FORWARDED_ALLOW_IPS` | нет | `127.0.0.1` | Прокси, которым доверяется `X-Forwarded-For` (loopback и частные сети в файле compose) |
| `HOST` / `PORT` | нет | `0.0.0.0` / `8000` | Адрес, на котором слушает сервер |
| `LOG_LEVEL` | нет | `info` | `debug`, `info`, `warning` или `error` |
| `IMAGE_TAG` | нет | `1` | Тег образа в `compose.yaml` |

<a id="development"></a>

## 🧑‍💻 Разработка

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

`docmost-mcp-remote --tool-catalog` отдаёт инструменты, ресурсы и промпты по
stdio без Docmost, базы данных и каких-либо настроек и отклоняет любой вызов.
Через этот режим каталоги MCP узнают, что умеет сервер, например
`docker run -i --rm ghcr.io/bbik52/docmost-mcp-remote --tool-catalog`.

См. [CONTRIBUTING.md](CONTRIBUTING.md) и [план развития](docs/ROADMAP.md)
(на английском).

<a id="feedback"></a>

## 🙌 Обратная связь

> ⭐ **Нравится? [Поставьте звезду репозиторию](https://github.com/bbik52/docmost-mcp-remote/stargazers).**
> Звёзды помогают другим командам на Docmost найти сервер и поддерживают проект.

[Issues](https://github.com/bbik52/docmost-mcp-remote/issues/new/choose) — не
только для ошибок. Попросите новый инструмент или функцию, расскажите, что
неудобно в вашей работе, или задайте вопрос: каждый запрос читается. О проблеме безопасности сообщайте по
[SECURITY.md](SECURITY.md), а не в issue.

## 📄 Лицензия

[Apache License 2.0](LICENSE). Лицензия не распространяется на название
проекта: форки приветствуются под другим именем. Проект является независимой
реализацией и не связан с Docmost. Он вдохновлён
[docmost-mcp-oss](https://github.com/abelsr/docmost-mcp-oss).
