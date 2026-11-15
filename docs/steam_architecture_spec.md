# Эталонная спецификация интеграции Steam в Playlog

## Архитектурные принципы
1. **Единственность состояний (Single Source of Trust)**: никакой двусмысленности.
2. **Zero-Nullable States**: состояния FSM задаются строгими непустыми перечислениями (Enums/Choices). Никаких `null=True` для статусов, ошибок и счетчиков.
3. **Отсутствие пустых контейнеров (Zero Empty Voids)**: любая карточка на UI обязана иметь исходное видимое состояние (скелетон загрузки при асинхронном запросе, карточка с данными, карточка ошибки с кнопкой повтора, либо карточка «Ничего не найдено»).
4. **Изоляция сетевых вызовов**: добавление игры и открытие страниц сайта никогда не блокируются получением тяжелых данных (достижений). Каждая карточка управляет своими сетевыми запросами независимо.
5. **Обложки строго из API**: используются исключительно URL обложек, полученные от официальных эндпоинтов Steam API. Никаких самодельных и устаревших CDN-ссылок. При отсутствии картинки — брендовый плейсхолдер Playlog.

---

## Блок 1. Авторизация и привязка Steam-аккаунта (Steam Identity)

### 1.1. Назначение и границы ответственности
Отвечает **исключительно** за установление и разрыв связи: «Пользователь Playlog `@username` <-> SteamID64 `7656119...`». 
Не выполняет никаких синхронизаций контента, не хранит прогресс, не хранит ошибки сетевых запросов к библиотеке.

### 1.2. Модель данных (Zero-Nullable)
```python
class SteamAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='steam_account')
    steam_id = models.CharField('SteamID64', max_length=32, unique=True)
    show_steam = models.BooleanField('Показывать Steam в публичном профиле', default=True)
    created_at = models.DateTimeField('Дата привязки', auto_now_add=True)
```

### 1.3. Состояния карточки привязки в профиле
- **Состояние `UNLINKED` (Не привязан)**:
  - Бейдж: `[НЕ ПРИВЯЗАН]`.
  - Текст с описанием возможностей (импорт игр, учет личных ачивок).
  - Кнопка: `[Войти через Steam]` (инициирует OpenID).
- **Состояние `LINKED` (Привязан)**:
  - Бейдж: `[ПРИВЯЗАН]`, отображение SteamID64 и ссылка на профиль Steam.
  - Тумблер: «Показывать в публичном профиле».
  - Кнопка: `[Отвязать Steam]` (с подтверждением).

### 1.4. Пошаговый Flow
1. Пользователь нажимает `[Войти через Steam]`.
2. Playlog формирует стандартный OpenID 2.0 запрос и перенаправляет браузер на `https://steamcommunity.com/openid/login`.
3. Пользователь подтверждает вход на стороне Steam.
4. Steam перенаправляет обратно на `accounts/steam/callback/`.
5. **Серверная верификация**: Playlog делает POST-запрос `check_authentication` к Steam. Если ответ не содержит `is_valid:true` — запрос отвергается (400 Bad Request).
6. Из `openid.claimed_id` извлекается 64-битный числовой SteamID (`^https?://steamcommunity\.com/openid/id/(\d+)$`).
7. **Проверка конфликта**: если данный SteamID уже привязан к **другому** пользователю Playlog — операция отклоняется с сообщением: *«Этот аккаунт Steam уже привязан к другому профилю Playlog»*.
8. Создается запись `SteamAccount(user=user, steam_id=steam_id)`.
9. Автоматически создается пустая сущность библиотеки `SteamLibrary(steam_account=steam_account, status=NOT_SYNCED)`.
10. Редирект в профиль с сообщением об успехе (никаких тяжелых сетевых запросов во время callback!).

### 1.5. Отвязка аккаунта (Unlink Flow)
- Пользователь нажимает `[Отвязать Steam]` (строго POST + CSRF + JS-confirm).
- В транзакции удаляется `SteamAccount`. Каскадно удаляются `SteamLibrary`, записи `LibraryGame` и факты выбитых ачивок пользователя `UserAchievement`.
- Игры в общем каталоге и чужие данные не затрагиваются.
- Карточка переходит в статус `UNLINKED`.

---

## Блок 2. Синхронизация библиотеки пользователя (User Library)

### 2.1. Назначение и границы ответственности
Отвечает за получение из Steam списка купленных пользователем игр (`GetOwnedGames`), времени в игре и сопоставление их с играми нашего каталога по естественному ключу `steam_app_id`.

### 2.2. Модель данных (Zero-Nullable)
```python
class SteamLibrary(models.Model):
    class Status(models.TextChoices):
        NOT_SYNCED = 'not_synced', 'Не синхронизирована'
        SYNCING    = 'syncing',    'Синхронизируется'
        SUCCESS    = 'success',    'Синхронизирована'
        PRIVATE    = 'private',    'Профиль или игры скрыты приватностью'
        ERROR      = 'error',      'Ошибка сети / API'

    steam_account = models.OneToOneField(SteamAccount, on_delete=models.CASCADE, related_name='library')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_SYNCED)
    total_games = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(auto_now_add=True)  # для честного кулдауна
    error_message = models.CharField(max_length=500, default='', blank=True)

class LibraryGame(models.Model):
    class AchievementStatus(models.TextChoices):
        NOT_SYNCED     = 'not_synced',     'Не синхронизировано'
        SYNCING        = 'syncing',        'Синхронизируется'
        SYNCED         = 'synced',         'Синхронизировано'
        NO_ACHIEVEMENTS= 'no_achievements','В игре нет достижений'
        PRIVATE        = 'private',        'Статистика скрыта приватностью'
        ERROR          = 'error',          'Ошибка'

    library = models.ForeignKey(SteamLibrary, on_delete=models.CASCADE, related_name='games')
    steam_app_id = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=255, default='', blank=True)
    playtime_minutes = models.PositiveIntegerField(default=0)
    header_image = models.URLField(max_length=500, default='', blank=True)
    
    # Статус личных ачивок пользователя в этой конкретной игре:
    achievement_status = models.CharField(max_length=20, choices=AchievementStatus.choices, default=AchievementStatus.NOT_SYNCED)
    achievements_unlocked = models.PositiveIntegerField(default=0)
    achievements_total = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(auto_now_add=True)
    error_message = models.CharField(max_length=500, default='', blank=True)
```
*Примечание: `LibraryGame` связывается с каталогом `Game` по `steam_app_id` на уровне представлений (через единый запрос `catalog_map = {g.steam_app_id: g for g in Game.objects.filter(steam_app_id__in=app_ids)}`), без nullable внешних ключей в базе данных.*

### 2.3. Состояния карточки библиотеки в профиле
- **`NOT_SYNCED`**: Карточка «Ваша библиотека еще не загружена» + кнопка `[Синхронизировать библиотеку]`.
- **`SYNCING`**: Карточка с анимацией загрузки «Запрашиваем данные у Steam...» (кнопка заблокирована).
- **`SUCCESS`**: Отображается общее число игр `total_games`, дата последней синхронизации, кнопка `[Обновить]` (с кулдауном 120 сек) и сетка игр.
- **`PRIVATE`**: Предупреждающая карточка «Ваш профиль или список игр закрыт настройками приватности Steam. Откройте доступ в настройках Steam и повторите попытку» + кнопка `[Повторить]`.
- **`ERROR`**: Карточка ошибки с текстом `error_message` и кнопкой `[Повторить попытку]`.

### 2.4. Пошаговый Flow синхронизации
1. Пользователь нажимает `[Синхронизировать библиотеку]`.
2. Проверка кулдауна: если `now - last_attempt_at < 120` сек — выводится предупреждение с таймером обратного отсчета.
3. Статус меняется на `SYNCING`, `last_attempt_at = now()`.
4. Сервер делает ровно **один** HTTP-запрос к Steam Web API (`IPlayerService/GetOwnedGames`).
5. **Обработка ответа**:
   - Если профиль приватный -> `status = PRIVATE`, сохраняется понятный текст ошибки.
   - Если ошибка API / сети -> `status = ERROR`, сохраняется текст ошибки.
   - Если успех -> `status = SUCCESS`, обновляются записи `LibraryGame` (название, сыгранное время, `app_id`), `total_games = len(games)`.
6. Пользователь получает обновленную карточку библиотеки.

---

# Блок 3. Поиск игр в Steam (Steam Search)

### 3.1. Назначение и границы ответственности
Асинхронный компонент на странице поиска каталога. Ищет игры в магазине Steam Store API, сопоставляет их с уже существующими играми каталога Playlog и позволяет в один клик добавить отсутствующую игру.

### 3.2. Состояния карточки поиска (Никакой пустоты!)
В HTML страницы поиска контейнер `#steam-search-container` **изначально содержит видимый блок**:

1. **Состояние `LOADING` (Скелетон сразу в HTML)**:
   - Шапка: `[STEAM]` `ПОИСК В МАГАЗИНЕ STEAM` с пульсирующим бейджем `[ЗАГРУЗКА...]`.
   - Текст: «Связываемся со Steam Store API...»
   - Сетка из 4 пульсирующих карточек-скелетонов (плейсхолдер обложки, полоска названия, полоска кнопки). Пользователь **никогда не видит белой дыры**.
2. **Состояние `SUCCESS` (Игры найдены)**:
   - Сетка карточек найденных игр.
   - Каждая карточка: официальная обложка из API (или брендовый плейсхолдер Playlog, если Steam не прислал картинку), название, AppID.
   - Кнопка действия:
     - Если игра уже есть в каталоге: зеленая ссылка `[В КАТАЛОГЕ ->]`.
     - Если игры нет: акцентная кнопка `[+ ДОБАВИТЬ В КАТАЛОГ]`.
3. **Состояние `EMPTY` (В Steam ничего не найдено)**:
   - Аккуратная моноширинная карточка: *«В магазине Steam по запросу «{{ q }}» ничего не найдено»*.
4. **Состояние `ERROR` (Сбой связи со Steam)**:
   - Карточка предупреждения: *«Не удалось связаться с магазином Steam (ошибка сети или таймаут)»* + кнопка `[Повторить поиск]`.

### 3.3. Пошаговый Flow
1. Пользователь вводит поисковый запрос и открывает результаты.
2. В HTML страницы **сразу отрендерен скелетон** поиска Steam (`LOADING`).
3. JS отправляет запрос `GET /catalog/steam-search/?q=...`.
4. Бэкенд запрашивает Store API (`storesearch`), кэширует ответ на 1 час, сопоставляет найденные `steam_app_id` с таблицей `Game` Playlog.
5. Бэкенд возвращает HTML-фрагмент одного из трёх финальных состояний (`SUCCESS`, `EMPTY` или `ERROR`).
6. JS бесшовно заменяет скелетон на пришедший HTML.

---

# Блок 4. Добавление игры в каталог (Fast Game Import)

### 4.1. Назначение и границы ответственности
Отвечает за **быстрое, атомарное** добавление игры из магазина Steam в каталог Playlog.
**Критическое правило**: Добавление игры загружает **только** метаданные игры из Store API. Оно **не трогает и не загружает достижения**!

### 4.2. Модель данных каталога: `Game` (Zero-Nullable)
```python
class Game(models.Model):
    class SchemaStatus(models.TextChoices):
        NOT_FETCHED    = 'not_fetched',    'Схема не загружена'
        FETCHING       = 'fetching',       'Загрузка схемы'
        READY          = 'ready',          'Схема загружена'
        NO_ACHIEVEMENTS= 'no_achievements','В игре нет достижений в Steam'
        ERROR          = 'error',          'Ошибка загрузки схемы'

    steam_app_id = models.PositiveIntegerField('Steam AppID', unique=True, db_index=True)
    title = models.CharField('Название', max_length=255)
    description = models.TextField('Описание', default='', blank=True)
    header_image = models.URLField('Обложка (Store API)', max_length=500, default='', blank=True)
    release_date = models.DateField('Дата выхода', null=True, blank=True)
    
    # Категории / Жанры каталога Playlog
    categories = models.ManyToManyField(Category, related_name='games', blank=True)
    
    # Отзывы Steam
    steam_review_desc = models.CharField('Оценка отзывов', max_length=100, default='', blank=True)
    steam_review_percent = models.PositiveSmallIntegerField('Положительных отзывов (%)', default=0)
    steam_review_total = models.PositiveIntegerField('Всего отзывов', default=0)
    
    # Состояние схемы достижений
    schema_status = models.CharField(max_length=20, choices=SchemaStatus.choices, default=SchemaStatus.NOT_FETCHED)
    schema_last_attempt_at = models.DateTimeField(auto_now_add=True)
    schema_error = models.CharField(max_length=500, default='', blank=True)
```

### 4.3. Пошаговый Flow добавления
1. Пользователь нажимает `[+ ДОБАВИТЬ В КАТАЛОГ]` (из поиска или из своей библиотеки).
2. Показывается страница быстрого подтверждения (название, обложка).
3. При нажатии «Подтвердить» (POST) сервер делает **ровно один быстрый запрос** к Steam Store API (`appdetails`) и забирает: название, описание, жанры/категории, официальный `header_image`, сводку отзывов.
4. В транзакции создается `Game`:
   - Сохраняются метаданные и привязываются категории.
   - Выставляется `schema_status = NOT_FETCHED` (ачивки не запрашиваются!).
5. Время выполнения: **~150–250 миллисекунд**.
6. Мгновенный редирект на готовую страницу игры `game_detail`.

---

# Блок 5. Карточка достижений на странице игры (Achievements Card & Modal)

### 5.1. Назначение и границы ответственности
Полностью изолированный компонент на странице игры (`game_detail`). 
Никогда не блокирует открытие страницы игры. Отвечает за отображение справочника ачивок игры и личного прогресса текущего пользователя.

### 5.2. Модель данных: `Achievement` и `UserAchievement`
```python
class Achievement(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='achievements')
    api_name = models.CharField('Технический ID в Steam', max_length=128)
    name = models.CharField('Название', max_length=255)
    description = models.TextField('Описание', default='', blank=True)
    icon_url = models.URLField('Цветная иконка', max_length=500, default='', blank=True)
    icon_gray_url = models.URLField('Серая иконка', max_length=500, default='', blank=True)
    global_percent = models.FloatField('Редкость (%)', default=0.0)

    class Meta:
        unique_together = ('game', 'api_name')
        ordering = ['global_percent', 'pk']

class UserAchievement(models.Model):
    steam_account = models.ForeignKey(SteamAccount, on_delete=models.CASCADE, related_name='unlocked_achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='unlocked_by_users')
    unlocked_at = models.DateTimeField('Время получения в Steam', null=True, blank=True)

    class Meta:
        unique_together = ('steam_account', 'achievement')
```

### 5.3. Двухуровневая машина состояний карточки

#### Уровень 1: Состояние схемы игры (`game.schema_status`)
- **`READY`**: Схема ачивок есть в базе Playlog. Сразу рендерится список ачивок и статус пользователя.
- **`NOT_FETCHED`**: Схема еще не загружалась.
  - В HTML карточки сразу рендерится: шапка с бейджем `[ЗАГРУЗКА ДОСТИЖЕНИЙ STEAM...]` и пульсирующие скелетоны ачивок.
  - JS делает фоновый запрос `GET /catalog/games/<pk>/achievements-card/`.
  - Бэкенд выполняет фоновый контракт:
    1. Запрашивает схему у Steam Web API, сохраняет `Achievement` в базу, ставит `schema_status = READY` (или `NO_ACHIEVEMENTS`).
    2. Если текущий пользователь авторизован, у него привязан Steam и эта игра есть в его библиотеке со статусом `NOT_SYNCED` — бэкенд в этом же фоновом запросе забирает и его выбитые ачивки.
    3. Отдает отрендеренную карточку.
  - JS бесшовно заменяет скелетон на готовую карточку.
- **`NO_ACHIEVEMENTS`**: В игре нет ачивок. Карточка отображает: *«В этой игре нет достижений в Steam»*.
- **`ERROR`**: Ошибка связи. Карточка отображает: *«Не удалось загрузить схему достижений: [текст ошибки]»* + кнопка `[Повторить]`.

#### Уровень 2: Состояние прогресса пользователя (когда `schema_status == READY`)
В правой части шапки карточки выводится строго одно из состояний:
- **`ANONYMOUS`** (не залогинен): Ссылка «Войдите, чтобы отслеживать прогресс».
- **`NO_STEAM`** (нет привязки Steam): Ссылка «Привяжите Steam в профиле, чтобы отслеживать прогресс».
- **`NOT_IN_LIBRARY`** (Steam привязан, но игры нет в библиотеке пользователя):
  - Серый бейдж: `[НЕ В ВАШЕЙ БИБЛИОТЕКЕ STEAM]`.
  - Пояснение: *«У вас нет этой игры в Steam. Ачивки будут отслеживаться, если игра появится в вашей библиотеке»*.
  - **Никаких `0 / 31`!**
- **`NOT_SYNCED`** (игра есть в библиотеке, но ачивки пользователя еще не подтягивались):
  - Желтый бейдж: `[ПРОГРЕСС НЕ СИНХРОНИЗИРОВАН]`.
  - Кнопка: `[Загрузить мой прогресс]`.
  - **Никаких `0 / 31`!**
- **`PRIVATE`** (профиль Steam закрыт):
  - Желтый бейдж: `[ПРОФИЛЬ STEAM СКРЫТ]`.
  - Пояснение о настройках приватности Steam + кнопка `[Проверить снова]`.
- **`SYNCED`** (прогресс успешно получен):
  - Зеленый бейдж: `ПРОГРЕСС: 12 / 24 (50%)`.
  - Зеленый прогресс-бар.
  - Выбитые ачивки подсвечены зелёной рамкой и показывают дату получения (`unlocked_at`, если зафиксирована Steam).
  - Закрытые ачивки отображаются серыми и полупрозрачными.
  - Кнопка: `[Обновить ⟳]`.

### 5.4. Модальное окно достижений (Achievements Modal)
- Открывается по клику «Показать все достижения (N)».
- Если `user_status == SYNCED`:
  - В шапке крупный прогресс-бар и счетчик.
  - Фильтры: `[ВСЕ (N)]`, `[ВЫБИТО (K)]`, `[НЕ ВЫБИТО (M)]`, `[РЕДКИЕ ★ (R)]`.
- Если `user_status == NOT_IN_LIBRARY`:
  - В шапке плашка: *«Этой игры нет в вашей библиотеке Steam. Отображается общемировая статистика редкости достижений»*.
  - Фильтры «Выбито / Не выбито» скрыты, отображаются все ачивки с их глобальной редкостью.
