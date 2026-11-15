import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_remove_profile_unique_nonempty_steam_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SteamLibrary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('not_synced', 'Не синхронизирована'), ('syncing', 'Синхронизируется'), ('success', 'Синхронизирована'), ('private', 'Профиль или игры скрыты приватностью'), ('error', 'Ошибка сети / API')], default='not_synced', max_length=20, verbose_name='Статус')),
                ('total_games', models.PositiveIntegerField(default=0, verbose_name='Всего игр')),
                ('last_attempt_at', models.DateTimeField(auto_now_add=True, verbose_name='Последняя попытка')),
                ('error_message', models.CharField(blank=True, default='', max_length=500, verbose_name='Ошибка')),
                ('steam_account', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='library', to='accounts.steamaccount', verbose_name='Аккаунт Steam')),
            ],
            options={
                'verbose_name': 'Библиотека Steam',
                'verbose_name_plural': 'Библиотеки Steam',
            },
        ),
        migrations.AddField(
            model_name='librarygame',
            name='library',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='games', to='accounts.steamlibrary', verbose_name='Библиотека Steam'),
        ),
        migrations.AddField(
            model_name='librarygame',
            name='last_attempt_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='Последняя попытка'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='librarygame',
            name='error_message',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='Ошибка'),
        ),
        migrations.AddField(
            model_name='steamaccount',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='Дата привязки'),
            preserve_default=False,
        ),
    ]
