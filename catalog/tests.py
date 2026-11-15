from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import SteamAccount, SteamLibrary, LibraryGame
from catalog.models import Game, Achievement, UserAchievement

User = get_user_model()


class CatalogGameAndAchievementsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='gamer', password='password123')
        self.client = Client()

    def test_game_zero_nullable_and_schema_status(self):
        game = Game.objects.create(
            steam_app_id=753640,
            title='Outer Wilds',
            header_image='https://example.com/ow.jpg',
            schema_status=Game.SchemaStatus.NOT_FETCHED,
        )
        self.assertEqual(game.schema_status, 'not_fetched')
        self.assertEqual(game.steam_review_percent, 0)
        self.assertEqual(game.steam_review_total, 0)

        # Create achievement
        ach = Achievement.objects.create(
            game=game,
            api_name='ACH_TRAVEL_1',
            name='Gone Exploring',
            global_percent=45.5,
        )
        self.assertEqual(ach.global_percent, 45.5)
        self.assertEqual(list(Achievement.objects.filter(game=game)), [ach])

        # Test game_detail view with NOT_FETCHED
        res = self.client.get(reverse('game_detail', args=[game.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'game-achievements-container')

    def test_game_achievements_modal_ownership_check(self):
        game = Game.objects.create(
            steam_app_id=1332010,
            title='Stray',
            schema_status=Game.SchemaStatus.READY,
        )
        ach = Achievement.objects.create(
            game=game,
            api_name='ACH_MEOW',
            name='A Little Chat',
            global_percent=88.2,
        )

        # 1. Anonymous user modal request
        res = self.client.get(reverse('game_achievements_modal', args=[game.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Этой игры нет в вашей библиотеке, показана общая статистика')

        # 2. Authenticated user without game in library
        self.client.login(username='gamer', password='password123')
        sa = SteamAccount.objects.create(user=self.user, steam_id='76561198000000003')
        lib = SteamLibrary.objects.create(steam_account=sa, status=SteamLibrary.Status.SUCCESS)

        res = self.client.get(reverse('game_achievements_modal', args=[game.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Этой игры нет в вашей библиотеке, показана общая статистика')

        # 3. User with game synced in library
        lg = LibraryGame.objects.create(
            library=lib,
            steam_app_id=1332010,
            achievement_status=LibraryGame.AchievementStatus.SYNCED,
            achievements_unlocked=1,
            achievements_total=1,
        )
        UserAchievement.objects.create(steam_account=sa, achievement=ach)

        res = self.client.get(reverse('game_achievements_modal', args=[game.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'Этой игры нет в вашей библиотеке, показана общая статистика')
        self.assertContains(res, 'Прогресс получения')
        self.assertContains(res, '1 / 1 (100%)')

    def test_steam_search_results_view(self):
        res = self.client.get(reverse('steam_search_results') + '?q=Portal')
        self.assertEqual(res.status_code, 200)
        # Should render either SUCCESS, EMPTY, or ERROR without breaking
        self.assertTrue(res.context['q'] == 'Portal')
