# import os
#
# from django.apps import AppConfig
# from django.contrib.contenttypes.models import ContentType
# from django.test import TestCase
#
# import tests.models

# class MakeNotificationTests(TestCase):
#
#     @staticmethod
#     def test_make_notifications():
#         cmd = make_notifications.Command()
#         assert Notification.objects.all().count() == 0
#         # dry run
#         cmd.handle(dry_run=True)
#         assert Notification.objects.all().count() == 0
#         # test basic notification making
#         cmd.handle(verbose=True)
#         assert Notification.objects.all().count() == 3
#         # gather some general things
#         article_ct = ContentType.objects.get_for_model(
#             tests.models.Article)
#         user_ct = ContentType.objects.get_for_model(
#             tests.models.User)
#
#         # make a notification to delete
#         Notification.objects.create(
#             codename='foo',
#             content_type=article_ct,
#             from_code=True,
#         )
#         assert Notification.objects.all().count() == 4
#         cmd.handle()
#         assert Notification.objects.all().count() == 3
#         # here's one that shouldn't get deleted
#         Notification.objects.create(
#             codename='foo',
#             content_type=article_ct,
#             from_code=False,
#         )
#         assert Notification.objects.all().count() == 4
#         cmd.handle()
#         assert Notification.objects.all().count() == 4
#         # now we'll change one and it should get reverted
#         acn = Notification.objects.get_by_natural_key(
#             'tests', 'article', 'created')
#         acn.source_model = user_ct
#         acn.save()
#         cmd.handle(verbose=True)
#         acn = Notification.objects.get_by_natural_key(
#             'tests', 'article', 'created')
#         assert acn.source_model is None
#
#     @staticmethod
#     def test_bad_appconfig():
#         config = AppConfig('os', os)
#         make_notifications.make_notifications(config)
