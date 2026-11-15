from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import Profile, SteamAccount, SteamLibrary, LibraryGame
from catalog.models import Game, Achievement, UserAchievement

User = get_user_model()


class SteamIdentityAndLibraryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='password123')
        self.client = Client()
        self.client.login(username='tester', password='password123')

    def test_steam_account_and_library_fsm(self):
        sa = SteamAccount.objects.create(
            user=self.user,
            steam_id='76561198000000001',
            show_steam=True,
        )
        self.assertEqual(sa.steam_id, '76561198000000001')
        self.assertTrue(sa.show_steam)
        self.assertIsNotNone(sa.created_at)

        # Create library
        lib = SteamLibrary.objects.create(
            steam_account=sa,
            status=SteamLibrary.Status.NOT_SYNCED,
        )
        self.assertEqual(lib.status, 'not_synced')
        self.assertEqual(lib.total_games, 0)
        self.assertEqual(lib.error_message, '')

        # Add library game
        lg = LibraryGame.objects.create(
            library=lib,
            steam_app_id=413150,
            name='Stardew Valley',
            playtime_minutes=120,
            header_image='https://example.com/stardew.jpg',
            achievement_status=LibraryGame.AchievementStatus.NOT_SYNCED,
        )
        self.assertEqual(lg.playtime_hours, 2.0)
        self.assertEqual(lg.display_name, 'Stardew Valley')
        self.assertEqual(lg.display_cover, 'https://example.com/stardew.jpg')

        # Test profile view rendering
        res = self.client.get(reverse('profile'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '76561198000000001')
        self.assertContains(res, '[НЕ СИНХРОНИЗИРОВАНО]')

    def test_steam_unlink(self):
        sa = SteamAccount.objects.create(
            user=self.user,
            steam_id='76561198000000002',
        )
        lib = SteamLibrary.objects.create(steam_account=sa)
        LibraryGame.objects.create(library=lib, steam_app_id=100)

        res = self.client.post(reverse('steam_unlink'))
        self.assertRedirects(res, reverse('profile'))
        self.assertFalse(SteamAccount.objects.filter(pk=sa.pk).exists())
        self.assertFalse(SteamLibrary.objects.filter(pk=lib.pk).exists())
        self.assertFalse(LibraryGame.objects.filter(steam_app_id=100).exists())
