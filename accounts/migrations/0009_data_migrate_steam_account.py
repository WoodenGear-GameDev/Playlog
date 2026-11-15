from django.db import migrations


def forwards_migrate_steam(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    SteamAccount = apps.get_model('accounts', 'SteamAccount')
    LibraryGame = apps.get_model('accounts', 'LibraryGame')
    Game = apps.get_model('catalog', 'Game')
    Achievement = apps.get_model('catalog', 'Achievement')
    UserAchievement = apps.get_model('catalog', 'UserAchievement')

    try:
        profiles = list(Profile.objects.exclude(steam_id__isnull=True).exclude(steam_id=''))
    except Exception:
        try:
            profiles = list(Profile.objects.exclude(steam_id=''))
        except Exception:
            profiles = []

    for profile in profiles:
        steam_account, _ = SteamAccount.objects.get_or_create(
            user=profile.user,
            defaults={
                'steam_id': getattr(profile, 'steam_id', ''),
                'show_steam': getattr(profile, 'show_steam', False),
                'synced_at': getattr(profile, 'library_synced_at', None),
                'sync_requested_at': getattr(profile, 'library_sync_requested_at', None),
            },
        )

        # Migrate library games
        try:
            for lib_game in LibraryGame.objects.filter(profile=profile):
                lib_game.steam_account = steam_account
                cat_game = Game.objects.filter(steam_app_id=lib_game.steam_app_id).first()
                if cat_game:
                    lib_game.game = cat_game
                if getattr(lib_game, 'achievements_total', 0) > 0:
                    lib_game.achievement_status = 'synced'
                lib_game.save(update_fields=['steam_account', 'game', 'achievement_status'])
        except Exception:
            pass

        # Migrate unlocked achievements safely (handles catalog.010 running before accounts.009)
        try:
            unlocked_by_field = getattr(Achievement, 'unlocked_by', None)
            if unlocked_by_field and hasattr(unlocked_by_field, 'through'):
                for rel in unlocked_by_field.through.objects.filter(profile_id=profile.id):
                    UserAchievement.objects.get_or_create(
                        steam_account=steam_account,
                        achievement_id=rel.achievement_id,
                    )
            else:
                from django.db import connection
                table_name = 'catalog_achievement_unlocked_by'
                if table_name in connection.introspection.table_names():
                    with connection.cursor() as cursor:
                        cursor.execute(f"SELECT achievement_id FROM {table_name} WHERE profile_id = %s", [profile.id])
                        for row in cursor.fetchall():
                            UserAchievement.objects.get_or_create(
                                steam_account=steam_account,
                                achievement_id=row[0],
                            )
        except Exception:
            pass


def backwards_migrate_steam(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_steamaccount_and_more'),
        ('catalog', '0009_game_steam_review_tier_alter_achievement_unlocked_by_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards_migrate_steam, backwards_migrate_steam),
    ]
