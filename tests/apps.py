from django.apps import AppConfig
# from django.core.management import call_command

try:
    from django.test.utils import setup_databases
except ImportError:  # workaround for django 1.10
    from django.test.runner import setup_databases


class AgendaTestConfig(AppConfig):
    name = 'tests'
    verbose_name = 'Agenda Test'

    def ready(self):
        setup_databases(verbosity=3, interactive=False)


class AgendaDemoConfig(AppConfig):
    name = 'tests'
    verbose_name = 'Agenda Demo'

    def ready(self):
        setup_databases(verbosity=3, interactive=False)
        # add notification objects
        # call_command('make_notifications')
        # call_command('loaddata', 'demo')
