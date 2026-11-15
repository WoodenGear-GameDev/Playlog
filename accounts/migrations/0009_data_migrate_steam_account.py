from django.db import migrations


def forwards_migrate_steam(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    SteamAccount = apps.get_model('accounts', 'SteamAccount')
    LibraryGame = apps.get_model('accounts', 'LibraryGame')
    Game = apps.get_model('catalog', 'Game')
    Achievement = apps.get_model('catalog', 'Achievement')
    UserAchievement = apps.get_model('catalog', 'UserAchievement')

    for profile in Profile.objects.exclude(steam_id=''):
        steam_account, _ = SteamAccount.objects.get_or_create(
            user=profile.user,
            defaults={
                'steam_id': profile.steam_id,
                'show_steam': profile.show_steam,
                'synced_at': profile.library_synced_at,
                'sync_requested_at': profile.library_sync_requested_at,
            },
        )

        # Migrate library games
        for lib_game in LibraryGame.objects.filter(profile=profile):
            lib_game.steam_account = steam_account
            # Try to connect with catalog.Game if exists
            cat_game = Game.objects.filter(steam_app_id=lib_game.steam_app_id).first()
            if cat_game:
                lib_game.game = cat_game
            if lib_game.achievements_total > 0:
                lib_game.achievement_status = 'synced'
            lib_game.save(update_fields=['steam_account', 'game', 'achievement_status'])

        # Migrate unlocked achievements
        unlocked_achs = Achievement.unlocked_by.through.objects.filter(profile_id=profile.id)
        for rel in unlocked_achs:
            UserAchievement.objects.get_or_create(
                steam_account=steam_account,
                achievement_id=rel.achievement_id,
            )


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
