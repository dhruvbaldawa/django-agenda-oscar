from datetime import date, datetime, time

import pytz
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

import django_agenda.signals
from django_agenda.models import (Availability, AvailabilityOccurrence,
                                  recreate_time_slots)


def create_host():
    return User.objects.create(email='host@example.org', username="host")


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
            subject=self.host,
            timezone=timezone,
        )
        Availability.objects.create(
            start_date=date(2001, 3, 5),
            start_time=time(8),
            end_time=time(15),
            recurrence='',
            subject=self.host,
            timezone=timezone,
        )
        start = timezone.localize(datetime(2001, 3, 4))
        end = timezone.localize(datetime(2001, 3, 15))
        recreate_time_slots(start, end)

        user_type = ContentType.objects.get_for_model(User)
        all_slots = AvailabilityOccurrence.objects.filter(
            subject_type__pk=user_type.id, subject_id=self.host.id)
        self.assertEqual(len(all_slots), 3)
        availability1.recurrence = 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR'
        availability1.save()
        recreate_time_slots(start, end)
        all_slots = AvailabilityOccurrence.objects.filter(
            subject_type__pk=user_type.id, subject_id=self.host.id)
        self.assertEqual(len(all_slots), 6)

    def testDaylightSavings(self):
        timezone = pytz.timezone('America/Vancouver')
        start = datetime(2018, 10, 30)
        end = datetime(2018, 11, 10)
        start_time = time(8)
        end_time = time(15)
        Availability.objects.create(
            start_date=start.date(),
            start_time=start_time,
            end_time=end_time,
            recurrence='RRULE:FREQ=WEEKLY',
            subject=self.host,
            timezone=timezone,
        )
        utc_start = pytz.utc.localize(start)
        utc_end = pytz.utc.localize(end)
        recreate_time_slots(utc_start, utc_end)

        user_type = ContentType.objects.get_for_model(User)
        all_slots = AvailabilityOccurrence.objects.filter(
            subject_type__pk=user_type.id, subject_id=self.host.id)
        self.assertEqual(len(all_slots), 2)
        self.assertEqual(datetime(2018, 10,  30, 15, tzinfo=pytz.utc),
                         all_slots[0].start)
        self.assertEqual(datetime(2018, 10,  30, 22, tzinfo=pytz.utc),
                         all_slots[0].end)
        self.assertEqual(datetime(2018, 11,  6, 16, tzinfo=pytz.utc),
                         all_slots[1].start)
        self.assertEqual(datetime(2018, 11,  6, 23, tzinfo=pytz.utc),
                         all_slots[1].end)

