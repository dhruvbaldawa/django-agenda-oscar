from django.apps import AppConfig

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
        from . import signals
        signals.setup()
        setup_databases(verbosity=3, interactive=False)
        from django.contrib.auth.models import User
        User.objects.create_superuser('admin', 'admin@example.org', 'admin')
        # add fixtures
        # call_command('loaddata', 'demo')
