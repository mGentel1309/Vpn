# ⚡ Быстрые команды для тестирования

## 🎯 Основные команды

### Лучшие серверы по-default (рекомендуется)
```bash
cd /Users/mgentel/VPN/vpn-configs-for-russia
bash tools/update_and_pick.sh
```

### Только супер-стабильные серверы
```bash
python3 tools/vpn_picker.py --max-cv 10 --top 5
```

### Стабильные + быстрые
```bash
python3 tools/vpn_picker.py --max-cv 20 --tries 5
```

### Просто самые быстрые
```bash
python3 tools/vpn_picker.py --tries 3
```

## 📊 Просмотр результатов

### Таблица лучших серверов с метриками
```bash
cat local-out/ping_top.tsv
```

### Полный отчет в JSON
```bash
cat local-out/report.json | python3 -m json.tool
```

### Лучший сервер
```bash
cat local-out/best.txt
```

### Скопировать лучший в subscription
```bash
cp local-out/best.txt subscription.txt
```

## 🔍 Диагностика

### Посмотреть доступные опции
```bash
python3 tools/vpn_picker.py --help
```

### Посчитать сколько серверов в файле
```bash
grep -c "^vless://" BLACK_VLESS_RUS_mobile.txt
```

### Показать топ-1 сервер с полной информацией
```bash
python3 -c "import json; r=json.load(open('local-out/report.json')); import pprint; pprint.pprint(r['best'])"
```

## ⚙️ Примеры с переменными окружения

### Тестировать 50 серверов
```bash
LIMIT=50 bash tools/update_and_pick.sh
```

### Увеличить количество попыток пинга
```bash
TRIES=5 bash tools/update_and_pick.sh
```

### Использовать разные наборы конфигов
```bash
SUBSCRIPTION=BLACK_VLESS_RUS.txt bash tools/update_and_pick.sh
```

## 📱 Для мобильных пользователей (низкий разброс пингов)
```bash
python3 tools/vpn_picker.py --max-ping-spread 1.0 --tries 5 --top 5
```

## 📈 Интерпретация метрик

| Метрика | Хорошо | Плохо |
|---------|--------|-------|
| ping_ms | < 2 мс | > 100 мс |
| cv% | < 15% | > 50% |
| spread | < 1 мс | > 5 мс |
| stdev | < 0.5 мс | > 2 мс |

---

**Совет**: Начните с `--max-cv 20` если не уверены в выборе настроек.
