from datetime import date, datetime, time

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

from . import models


def create_host():
    return User.objects.create(email='host@example.org', username="host")


class OccurrenceUnitTests(TestCase):

    def setUp(self):
        self.host = create_host()

    def testAll(self):
        timezone = pytz.timezone('America/Vancouver')
        availability1 = models.Availability.objects.create(
            start_date=date(2001, 1, 1),
            start_time=time(8),
            end_time=time(15),
            recurrence='RRULE:FREQ=WEEKLY',
            schedule=self.host,
            timezone=timezone,
        )
        models.Availability.objects.create(
            start_date=date(2001, 3, 5),
            start_time=time(8),
            end_time=time(15),
            recurrence='',
            schedule=self.host,
            timezone=timezone,
        )
        start = timezone.localize(datetime(2001, 3, 4))
        end = timezone.localize(datetime(2001, 3, 15))
        models.recreate_time_slots(start, end)

        all_slots = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(all_slots), 3)
        availability1.recurrence = 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR'
        availability1.save()
        models.recreate_time_slots(start, end)
        all_slots = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(all_slots), 6)

    def testDaylightSavings(self):
        timezone = pytz.timezone('America/Vancouver')
        start = datetime(2018, 10, 30)
        end = datetime(2018, 11, 10)
        start_time = time(8)
        end_time = time(15)
        models.Availability.objects.create(
            start_date=start.date(),
            start_time=start_time,
            end_time=end_time,
            recurrence='RRULE:FREQ=WEEKLY',
            schedule=self.host,
            timezone=timezone,
        )
        utc_start = pytz.utc.localize(start)
        utc_end = pytz.utc.localize(end)
        models.recreate_time_slots(utc_start, utc_end)

        all_slots = models.AvailabilityOccurrence.objects.filter(
            schedule=self.host)
        self.assertEqual(len(all_slots), 2)
        self.assertEqual(datetime(2018, 10,  30, 15, tzinfo=pytz.utc),
                         all_slots[0].start)
        self.assertEqual(datetime(2018, 10,  30, 22, tzinfo=pytz.utc),
                         all_slots[0].end)
        self.assertEqual(datetime(2018, 11,  6, 16, tzinfo=pytz.utc),
                         all_slots[1].start)
        self.assertEqual(datetime(2018, 11,  6, 23, tzinfo=pytz.utc),
                         all_slots[1].end)
