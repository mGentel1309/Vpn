## Автообновление + выбор “самого быстрого” конфига

Этот набор скриптов делает две вещи:

- **обновляет** репозиторий `vpn-configs-for-russia` (`git pull`)
- **тестирует** конфиги из TXT‑подписки по задержке до `host:port` и выбирает минимальную

Важно: это **не полноценный тест работоспособности VPN‑туннеля**, а быстрый и безопасный “пробник” — измерение времени TCP‑подключения к адресу конфига + (где возможно) дополнительная проверка **TLS/HTTP**. Для `hysteria2/tuic` (UDP/QUIC) тест пропускается. По умолчанию скрипт **избегает Anycast/CDN** (они часто “пингуются” красиво, но в реальности бывают медленными/нестабильными).

### Быстрый запуск

Из папки `vpn-configs-for-russia`:

```bash
bash tools/update_and_pick.sh
```

Скрипт выведет **лучший** конфиг в stdout и сохранит результаты в `local-out/`:

- `local-out/best.txt` — 1 строка, лучший конфиг
- `local-out/top.txt` — топ‑N конфигов
- `local-out/report.json` — подробный отчёт, в т.ч. **`ping_ms`**, **`ping_min_ms` / `ping_max_ms` / `ping_avg_ms`** и блок **`ping`** с пояснением (это **не ICMP**, а измерение TCP connect)
- `local-out/ping_top.tsv` — таблица топа по пингу для быстрого просмотра в редакторе

### Настройка через переменные

```bash
SUBSCRIPTION="BLACK_SS+All_RUS.txt" TOP=20 LIMIT=300 TRIES=3 TIMEOUT=2.0 bash tools/update_and_pick.sh
```

По умолчанию выбирается только `vless`. Если хочешь тестировать ещё `ss`:

```bash
SCHEMES="vless,ss" bash tools/update_and_pick.sh
```

Если нужно разрешить Anycast/CDN (не рекомендуется), запусти напрямую:

```bash
python3 tools/vpn_picker.py --allow-anycast
```

Доступные подписки в корне репо, например:

- `BLACK_VLESS_RUS_mobile.txt`
- `BLACK_VLESS_RUS.txt`
- `BLACK_SS+All_RUS.txt`
- `WHITE-CIDR-RU-all.txt`
- `WHITE-SNI-RU-all.txt`

