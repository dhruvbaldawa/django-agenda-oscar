from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class Config(AppConfig):
    name = 'django_agenda'
    verbose_name = _('Agenda')

    def ready(self):
        import django_agenda.signals
        django_agenda.signals.setup()
