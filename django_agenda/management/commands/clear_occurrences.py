from django.core.management.base import BaseCommand

from django_agenda.models import AvailabilityOccurrence


class Command(BaseCommand):
    args = ''
    help = 'Deletes all the availability occurrences'

    def handle(self, *args, **options):
        for occurrence in AvailabilityOccurrence.objects.all():
            occurrence.delete()
