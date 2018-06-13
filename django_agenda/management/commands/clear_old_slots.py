import django.utils
from django.core.management.base import BaseCommand

from django_agenda import models


class Command(BaseCommand):
    args = ''
    help = 'Regenerates the time slots from the schedule'

    def handle(self, *args, **options):
        now = django.utils.timezone.now()
        for slot in models.TimeSlot.objects.filter(end__lte=now, busy=False):
            if not slot.is_booked():
                slot.delete()
