from django.core.management.base import BaseCommand

from django_agenda.models import recreate_time_slots


class Command(BaseCommand):
    args = ''
    help = 'Regenerates the time slots from the schedule'

    def handle(self, *args, **options):
        recreate_time_slots()
