from datetime import datetime, time, date
from django.contrib.auth.models import User

from django.test import TestCase
import pytz

from django_agenda.models import (Availability, AvailabilityOccurrence,
                                  TimeUnavailableError, recreate_time_slots)
import django_agenda.signals


def create_host():
    return User.objects.create(email='host@example.org', username="host")


def create_booker():
    return User.objects.create(email='booker@example.org', username='booker')


class OccurrenceUnitTests(TestCase):

    def setUp(self):
        django_agenda.signals.teardown()
        self.host = create_host()

    def testAll(self):
        timezone = pytz.timezone('America/Vancouver')
        availability1 = Availability.objects.create(
            start_date=date(2001, 1, 1),
            start_time=time(8),
            end_time=time(15),
            recurrence='RRULE:FREQ=WEEKLY',
            subject=host,
            timezone=timezone,
        )
        Availability.objects.create(
            start_date=date(2001, 3, 5),
            start_time=time(8),
            end_time=time(15),
            recurrence='',
            subject=host,
            timezone=timezone,
        )
        start = timezone.localize(datetime(2001, 3, 4))
        end = timezone.localize(datetime(2001, 3, 15))
        recreate_time_slots(start, end)

        user_type = ContentType.objects.get_for_model(User)
        all_slots = AvailabilityOccurrence.objects.filter(
            content_type__pk=user_type.id, content_id=self.host.id)
        self.assertEqual(len(all_slots), 3)
        availability1.recurrence = 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR'
        availability1.save()
        recreate_time_slots(start, end)
        all_slots = AvailabilityOccurrence.objects.filter(
            content_type__pk=user_type.id, content_id=self.host.id)
        self.assertEqual(len(all_slots), 6)
