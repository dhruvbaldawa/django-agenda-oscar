from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class KudozConfig(AppConfig):
    name = 'schedule'
    verbose_name = _('Schedule')

    def ready(self):
        import django_agenda.signals
        django_agenda.signals.setup()
