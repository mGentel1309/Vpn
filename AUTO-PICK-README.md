# 🚀 VPN Server Auto-Picker

Автоматическое получение, проверка и отбор самых быстрых VPN серверов из репозитория [zieng2/wl](https://github.com/zieng2/wl).

## 📋 Возможности

✅ **Автоматическое обновление** конфигов каждые 6 часов (GitHub Actions)  
✅ **Тестирование скорости** через ICMP пинг  
✅ **Отбор топ-10** самых быстрых серверов  
✅ **Сохранение результатов** в `top-10.txt`  
✅ **Git интеграция** - автоматический commit и push  

## 🔧 Структура

```
.
├── tools/
│   ├── fetch-and-pick.sh      # Основной скрипт для отбора серверов
│   └── vpn_picker.py          # Python тулз для тестирования
├── .github/workflows/
│   └── auto-pick-servers.yml  # GitHub Actions (запуск каждые 6 часов)
├── vless.txt                  # Полный список конфигов
├── vless_lite.txt             # Облегченная версия
├── vless_universal.txt        # Универсальная версия
└── top-10.txt                 # Результат: топ-10 быстрых серверов
```

## 🚀 Использование

### Локальный запуск (вручную)

```bash
# Сделать скрипт исполняемым
chmod +x tools/fetch-and-pick.sh

# Запустить
./tools/fetch-and-pick.sh

# С параметрами
TRIES=3 TOP=10 ./tools/fetch-and-pick.sh
```

### GitHub Actions (автоматически)

- ⏰ Запускается **каждые 6 часов** (можно изменить в `.github/workflows/auto-pick-servers.yml`)
- 🔄 Автоматически коммитит результаты
- 📤 Пушит в `main` ветку

Или запустить вручную: **GitHub → Actions → Auto-Update & Pick Best Servers → Run workflow**

## ⚙️ Параметры

| Переменная | По умолчанию | Описание |
|-----------|-------------|---------|
| `TRIES` | 3 | Количество попыток пинга для каждого сервера |
| `TOP` | 10 | Количество серверов в результате |
| `SUBSCRIPTION` | `vless_universal.txt` | Исходный файл конфигов |
| `LIMIT` | 500 | Макс. серверов для проверки |
| `TIMEOUT` | 3.0 | Таймаут соединения (сек) |
| `CONCURRENCY` | 20 | Количество одновременных проверок |

Пример:
```bash
TRIES=5 TOP=20 SUBSCRIPTION=vless_lite.txt ./tools/fetch-and-pick.sh
```

## 📊 Результаты

Результаты сохраняются в файл `top-10.txt`:

```
vless://...@server1.com:443?...#Server1
vless://...@server2.com:443?...#Server2
...
```

Просмотреть: [top-10.txt](top-10.txt)

## 🔄 Git интеграция

После каждого запуска:

1. ✅ Обновляет конфиги с upstream
2. ✅ Получает топ-10 серверов
3. ✅ Коммитит: `⚡ Auto-update: 10 fastest servers`
4. ✅ Пушит в main

## 🛠 Как изменить расписание?

Отредактировать `.github/workflows/auto-pick-servers.yml`:

```yaml
on:
  schedule:
    # каждые 6 часов
    - cron: '0 */6 * * *'
    # ИЛИ каждые 2 часа
    # - cron: '0 */2 * * *'
    # ИЛИ каждый день в 00:00 UTC
    # - cron: '0 0 * * *'
```

[Cron Syntax Help](https://crontab.guru)

## 📞 Troubleshooting

**Нет результатов?**
- Проверьте интернет соединение
- Убедитесь что `vless_universal.txt` содержит конфиги
- Запустите с `TRIES=1` для быстрого теста

**Push failed?**
- Проверьте GitHub token доступ
- Убедитесь что репо позволяет write access

**Нужна помощь?**
- Смотрите логи GitHub Actions: Settings → Actions
- Запустите скрипт локально для отладки

## 📝 Лицензия

Часть от [vpn-configs-for-russia](https://github.com/igareck/vpn-configs-for-russia)
