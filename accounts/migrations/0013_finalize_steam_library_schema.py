import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_data_migrate_steam_library'),
    ]

    operations = [
        migrations.AlterField(
            model_name='librarygame',
            name='library',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='games', to='accounts.steamlibrary', verbose_name='Библиотека Steam'),
        ),
        migrations.RemoveConstraint(
            model_name='librarygame',
            name='unique_library_game_per_account',
        ),
        migrations.RemoveField(
            model_name='librarygame',
            name='steam_account',
        ),
        migrations.RemoveField(
            model_name='librarygame',
            name='game',
        ),
        migrations.RemoveField(
            model_name='librarygame',
            name='achievements_synced_at',
        ),
        migrations.AlterField(
            model_name='librarygame',
            name='name',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='Название из Steam'),
        ),
        migrations.AlterField(
            model_name='librarygame',
            name='header_image',
            field=models.URLField(blank=True, default='', max_length=500, verbose_name='Обложка (URL)'),
        ),
        migrations.AlterField(
            model_name='librarygame',
            name='achievement_status',
            field=models.CharField(choices=[('not_synced', 'Не синхронизировано'), ('syncing', 'Синхронизируется'), ('synced', 'Синхронизировано'), ('no_achievements', 'В игре нет достижений'), ('private', 'Статистика скрыта приватностью'), ('error', 'Ошибка')], default='not_synced', max_length=20, verbose_name='Статус достижений'),
        ),
        migrations.AddConstraint(
            model_name='librarygame',
            constraint=models.UniqueConstraint(fields=('library', 'steam_app_id'), name='unique_library_game_per_library'),
        ),
        migrations.RemoveField(
            model_name='steamaccount',
            name='sync_status',
        ),
        migrations.RemoveField(
            model_name='steamaccount',
            name='synced_at',
        ),
        migrations.RemoveField(
            model_name='steamaccount',
            name='sync_requested_at',
        ),
        migrations.RemoveField(
            model_name='steamaccount',
            name='last_error',
        ),
        migrations.AlterField(
            model_name='steamaccount',
            name='steam_id',
            field=models.CharField(max_length=32, unique=True, verbose_name='SteamID64'),
        ),
        migrations.AlterField(
            model_name='steamaccount',
            name='show_steam',
            field=models.BooleanField(default=True, verbose_name='Показывать Steam в публичном профиле'),
        ),
    ]
