def fetch_app_details(app_id):
    """
    Заглушка. Реальный запрос к Steam реализует отдельный участник.

    Должна вернуть словарь или None, если игру получить не удалось:
    {
        'title': str,
        'description': str,
        'release_date': datetime.date или None,
        'header_image': str (URL),
        'categories': list[str] (названия жанров Steam),
    }
    Любого ключа может не быть. Дату нужно преобразовать в date самому:
    Steam отдаёт её строкой.
    """
    return None