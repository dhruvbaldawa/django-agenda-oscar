from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class DjangoAgendaConfig(AppConfig):
    name = 'agenda'
    verbose_name = _('Agenda')

    def ready(self):
        import django_agenda.signals
        django_agenda.signals.setup()
