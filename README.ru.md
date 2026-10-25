# docmost-mcp-remote

Самостоятельно размещаемый удалённый [MCP](https://modelcontextprotocol.io)-сервер
для [Docmost](https://docmost.com) Community Edition. Запустите его рядом со
своим Docmost, опубликуйте на своём домене, и ИИ-клиенты (Claude, Claude Code,
Cursor, VS Code) смогут читать и редактировать вики от имени каждого
участника, с его собственной учётной записью и правами в Docmost.

Основная документация на английском: [README.md](README.md). Этот файл
кратко пересказывает главное.

- **Один сервер, один Docmost, много участников.** Каждый входит своей
  учётной записью Docmost в браузере. Всё, что делает его ИИ-клиент,
  выполняется от его имени.
- **Авторизация обязательна.** OAuth 2.1 для удалённых коннекторов и
  персональные bearer-токены для скриптов. Режима без авторизации нет.
- **Безопасно по умолчанию.** Без явного согласия выдаётся только `read`.
  Запись и перенос в корзину требуют отдельных прав. Ничего не удаляется
  безвозвратно, а перед каждым изменением сервер сохраняет зашифрованный
  снимок страницы.
- **Своя инсталляция.** Один контейнер и Postgres, готовый `compose.yaml`.

## Поддерживаемые версии Docmost

Docmost Community Edition **0.70.0 и новее**. CI проверяет 0.70.3, 0.96.0 и
0.97.0. Пользователи, входящие в Docmost только через SSO (функция Enterprise),
работать через сервер не смогут: он входит по email и паролю.

## Инструменты

Чтение (`read`): `whoami`, `list_spaces`, `list_pages`, `recent_pages`,
`get_page`, `search`, `list_comments`, `list_trash`, `list_snapshots`.
Запись (`write`): `create_page`, `update_page`, `rename_page`, `move_page`,
`add_comment`, `restore_snapshot`. Корзина (`delete`): `trash_page`,
`restore_page`.

Содержимое страниц передаётся модели в обёртке
`<docmost-untrusted-content>`, чтобы она считала его данными, а не
инструкциями.

## Модель безопасности

Сессия Docmost каждого участника хранится зашифрованной ключом из
`SECRET_KEY`; пароль не хранится, если не включён
`RELOGIN_MODE=stored_password`. Токены хранятся только в виде хешей.
Сервер сам является OAuth 2.1 сервером авторизации по спецификации MCP:
динамическая регистрация клиентов, PKCE (S256), токены привязаны к `/mcp`
этого сервера, access-токен живёт час, refresh-токен 30 дней и меняется при
каждом использовании. Повторное использование refresh-токена или кода
отзывает весь доступ.

Инъекция инструкций в тексте страницы всё равно может заставить клиента
действовать в пределах выданных прав, поэтому `write` и `delete` выдавайте
только клиентам, которым доверяете. Вызовы инструментов ограничены по
частоте и пишутся в журнал аудита. Подробности: [модель угроз](docs/security-model.md),
[SECURITY.md](SECURITY.md).

## Быстрый старт

Нужны Docker с Compose, доступный с сервера Docmost и доменное имя с https
для самого сервера, например `mcp.example.com`.

```sh
mkdir docmost-mcp && cd docmost-mcp
curl -fsSLO https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/compose.yaml
curl -fsSL -o .env https://raw.githubusercontent.com/bbik52/docmost-mcp-remote/master/.env.example
# заполните в .env: PUBLIC_URL, DOCMOST_URL, POSTGRES_PASSWORD, SECRET_KEY
# (openssl rand -hex 32 подойдёт для обоих секретов)
docker compose up -d
curl http://127.0.0.1:8000/healthz
```

Затем поставьте перед `127.0.0.1:8000` обратный прокси с https (примеры для
Caddy и nginx в [README.md](README.md#reverse-proxy)), откройте
`PUBLIC_URL/login` и проверьте вход учётной записью Docmost. Прокси должен
отдавать сервер с корня своего домена и не буферизовать ответы.

Делайте резервные копии тома Postgres: в нём зашифрованные сессии, снимки и
журнал аудита. Потеря `SECRET_KEY` разлогинит всех и сделает снимки
нечитаемыми.

## Подключение клиента

Адрес MCP: `PUBLIC_URL/mcp`, например `https://mcp.example.com/mcp`. Клиент
откроет браузер: войдите в Docmost и выберите, что ему разрешено.

- **Claude.ai и Claude Desktop**: Settings, Connectors, Add custom connector.
- **Claude Code**: `claude mcp add --transport http docmost https://mcp.example.com/mcp`,
  затем `/mcp` для входа.
- **Cursor, VS Code** и другие: укажите URL сервера в настройках MCP.
- **Скрипты**: создайте персональный токен на странице `PUBLIC_URL/account`
  и передавайте заголовок `Authorization: Bearer <токен>`.

## Администрирование

```sh
docker compose exec server docmost-mcp-remote admin members
docker compose exec server docmost-mcp-remote admin revoke-member anna@example.com
docker compose exec server docmost-mcp-remote admin audit --email anna@example.com
```

Полный список команд и настроек: [README.md](README.md#administration).
Обновление: `docker compose pull && docker compose up -d`.

## Лицензия

[Apache License 2.0](LICENSE). Лицензия не распространяется на название
проекта: форки приветствуются под другим именем. Проект независим и не
связан с Docmost.
