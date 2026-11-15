import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def set_schema_status_forward(apps, schema_editor):
    Game = apps.get_model('catalog', 'Game')
    Achievement = apps.get_model('catalog', 'Achievement')
    for game in Game.objects.all():
        if Achievement.objects.filter(game=game).exists():
            game.schema_status = 'ready'
            game.save(update_fields=['schema_status'])


def set_schema_status_backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_finalize_steam_library_schema'),
        ('catalog', '0010_remove_achievement_unlocked_by'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='achievement',
            options={'ordering': ['global_percent', 'pk'], 'verbose_name': 'Достижение', 'verbose_name_plural': 'Достижения'},
        ),
        migrations.AlterModelOptions(
            name='userachievement',
            options={'verbose_name': 'Выбитое достижение', 'verbose_name_plural': 'Выбитые достижения'},
        ),
        migrations.RemoveIndex(
            model_name='userachievement',
            name='catalog_use_steam_a_5720f7_idx',
        ),
        migrations.RemoveConstraint(
            model_name='userachievement',
            name='unique_user_achievement_unlock',
        ),
        migrations.RemoveField(
            model_name='achievement',
            name='unlocked_by_accounts',
        ),
        migrations.RemoveField(
            model_name='game',
            name='steam_review_tier',
        ),
        migrations.RemoveField(
            model_name='game',
            name='steam_synced_at',
        ),
        migrations.RemoveField(
            model_name='userachievement',
            name='created_at',
        ),
        migrations.AddField(
            model_name='game',
            name='schema_error',
            field=models.CharField(blank=True, default='', max_length=500, verbose_name='Ошибка схемы'),
        ),
        migrations.AddField(
            model_name='game',
            name='schema_last_attempt_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='Последняя попытка загрузки схемы'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='game',
            name='schema_status',
            field=models.CharField(choices=[('not_fetched', 'Схема не загружена'), ('fetching', 'Загрузка схемы'), ('ready', 'Схема загружена'), ('no_achievements', 'В игре нет достижений в Steam'), ('error', 'Ошибка загрузки схемы')], default='not_fetched', max_length=20, verbose_name='Статус схемы достижений'),
        ),
        migrations.AlterField(
            model_name='achievement',
            name='api_name',
            field=models.CharField(max_length=128, verbose_name='Технический ID в Steam'),
        ),
        migrations.AlterField(
            model_name='achievement',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='Описание'),
        ),
        migrations.AlterField(
            model_name='achievement',
            name='icon_gray_url',
            field=models.URLField(blank=True, default='', max_length=500, verbose_name='Серая иконка'),
        ),
        migrations.AlterField(
            model_name='achievement',
            name='icon_url',
            field=models.URLField(blank=True, default='', max_length=500, verbose_name='Цветная иконка'),
        ),
        migrations.AlterField(
            model_name='achievement',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Название'),
        ),
        migrations.AlterField(
            model_name='game',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='Описание'),
        ),
        migrations.AlterField(
            model_name='game',
            name='header_image',
            field=models.URLField(blank=True, default='', max_length=500, verbose_name='Обложка (Store API)'),
        ),
        migrations.AlterField(
            model_name='game',
            name='steam_review_desc',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Оценка отзывов'),
        ),
        migrations.AlterField(
            model_name='game',
            name='steam_review_percent',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='Положительных отзывов (%)'),
        ),
        migrations.AlterField(
            model_name='game',
            name='title',
            field=models.CharField(max_length=255, verbose_name='Название'),
        ),
        migrations.AlterField(
            model_name='userachievement',
            name='achievement',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unlocked_by_users', to='catalog.achievement', verbose_name='Достижение'),
        ),
        migrations.AlterField(
            model_name='userachievement',
            name='steam_account',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unlocked_achievements', to='accounts.steamaccount', verbose_name='Аккаунт Steam'),
        ),
        migrations.AlterField(
            model_name='userachievement',
            name='unlocked_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Время получения в Steam'),
        ),
        migrations.AlterUniqueTogether(
            name='achievement',
            unique_together={('game', 'api_name')},
        ),
        migrations.AlterUniqueTogether(
            name='userachievement',
            unique_together={('steam_account', 'achievement')},
        ),
        migrations.RunPython(set_schema_status_forward, set_schema_status_backward),
    ]
