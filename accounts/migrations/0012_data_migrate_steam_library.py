from django.db import migrations
import django.utils.timezone


def forwards_migrate_library(apps, schema_editor):
    SteamAccount = apps.get_model('accounts', 'SteamAccount')
    SteamLibrary = apps.get_model('accounts', 'SteamLibrary')
    LibraryGame = apps.get_model('accounts', 'LibraryGame')

    status_map = {
        'idle': 'not_synced',
        'syncing': 'syncing',
        'success': 'success',
        'private': 'private',
        'error': 'error',
    }

    now = django.utils.timezone.now()
    for sa in SteamAccount.objects.all():
        old_status = getattr(sa, 'sync_status', 'idle')
        new_status = status_map.get(old_status, 'not_synced')
        games = LibraryGame.objects.filter(steam_account_id=sa.id)
        last_attempt = getattr(sa, 'sync_requested_at', None) or getattr(sa, 'synced_at', None) or now
        err = getattr(sa, 'last_error', '') or ''
        lib, _ = SteamLibrary.objects.get_or_create(
            steam_account=sa,
            defaults={
                'status': new_status,
                'total_games': games.count(),
                'last_attempt_at': last_attempt,
                'error_message': err,
            },
        )
        games.update(library=lib)


def backwards_migrate_library(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_steamlibrary_and_librarygame_library'),
    ]

    operations = [
        migrations.RunPython(forwards_migrate_library, backwards_migrate_library),
    ]
