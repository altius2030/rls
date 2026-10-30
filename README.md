# МойСклад → Весы Rongta RLS1000

Решение для выгрузки товаров из МоегоСклада в торговые весы Rongta RLS1000.

## Архитектура

```
┌─────────────────────────────────────────────────────┐
│                   МойСклад (онлайн)                 │
│  ┌─────────────────────────────────────────────────┐ │
│  │               iframe (settings)                  │ │
│  │   • Загрузка товаров через JSON API 1.2          │ │
│  │   • Формирование TXP-файла                       │ │
│  │   • Вызов протокола rongta://                   │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                        │ rongta://
                        ▼
┌─────────────────────────────────────────────────────┐
│                  ПК пользователя                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │           Драйвер Rongta (driver.py)             │ │
│  │   • Регистрация URI-протокола rongta://          │ │
│  │   • Приём TXP-файла                              │ │
│  │   • Отправка в весы по TCP/IP                    │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                        │ TCP/IP
                        ▼
┌─────────────────────────────────────────────────────┐
│              Весы Rongta RLS1000                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │   • Приём PLU-данных по протоколу Rongta         │ │
│  │   • Обновление базы товаров                      │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Что нужно

| Компонент | Назначение |
|-----------|-----------|
| **vendor_api.py** | Сервер для активации/деактивации решения (только при установке) |
| **iframe (settings.html)** | UI внутри МоегоСклада — загрузка товаров, формирование TXP |
| **driver.py** | Драйвер на ПК — приём TXP и отправка в весы |

## Установка и настройка

### 1. Сервер активации (vendor_api.py)

Запускается на сервере с HTTPS (можно через ngrok для теста):

```bash
pip install -r requirements.txt
python -m uvicorn vendor_api.py --host 0.0.0.0 --port 8000
```

### 2. Дескриптор решения

```xml
<ServerApplication xmlns="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  xsi:schemaLocation="https://apps-api.moysklad.ru/xml/ns/appstore/app/v2
                  https://apps-api.moysklad.ru/xml/ns/appstore/app/v2/application-v2.xsd">
    <iframe>
        <sourceUrl>https://your-domain.com/settings</sourceUrl>
        <expand>true</expand>
    </iframe>
    <vendorApi>
        <endpointBase>https://your-domain.com</endpointBase>
    </vendorApi>
    <access>
        <resource>https://api.moysklad.ru/api/remap/1.2</resource>
        <scope>admin</scope>
    </access>
</ServerApplication>
```

### 3. Драйвер на ПК пользователя

```bash
# Регистрация URI-протокола (нужно запустить один раз от имени администратора)
python driver.py --install

# Ручная отправка TXP в весы (для теста)
python driver.py --file plu.txp --host 192.168.1.87 --port 9102
```

## Как работает

1. Пользователь устанавливает решение в МоегоСкладе
2. Vendor API сервер получает запрос активации, сохраняет access_token
3. Пользователь открывает iframe (настройки решения)
4. Iframe загружает товары через JSON API 1.2 (используя сохранённый токен)
5. Iframe формирует TXP-файл и вызывает `rongta://export?file=path`
6. Драйвер на ПК перехватывает протокол, читает TXP и отправляет в есы
7. Весы получают PLU-данные по TCP/IP и обновляют базу

## TXP-файл формат

Текстовый файл с табуляцией:

```
Hotkey	PLU Name	Fresh Commodity Code	Department	Unit Price	Weight	PLU Type	Price Type	Label Type	Barcode	Barcode Format	Valid Days	Packing Type
1	Яблоки Красные	000001	1	15900	0	0	0	0	4607025392808	0	7	0
2	Колбаса Докторская	000002	2	45000	0	1	2	0	4607025392809	0	14	0
```

## Rongta RLS1000 — настройки TCP/IP

1. На весах: Меню → SET → → IP Address → установить IP
2. Меню → File → Options → TCP/IP → включить и указать порт (>1024)
3. Указать IP компьютера (где работает драйвер)
4. Настроить расписание обновления PLU
