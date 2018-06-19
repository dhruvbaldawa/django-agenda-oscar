from datetime import date, datetime, time

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

import django_agenda.signals
from django_agenda.models import Availability, AvailabilityOccurrence, TimeSlot


def create_host():
    return User.objects.create(email='host@example.org', username="host")


class AvailabilitySingleTestCase(TestCase):

    def setUp(self):
        django_agenda.signals.setup()
        self.host = create_host()

    def test_add(self):
        timezone = pytz.timezone('America/Vancouver')
        obj = Availability.objects.create(
            start_date=date(2001, 3, 4),
            start_time=time(12),
            end_time=time(14),
            subject=self.host,
            timezone=timezone,
        )
        obj.recreate_occurrences(datetime(2001, 3, 4, tzinfo=timezone),
                                 datetime(2001, 3, 6, tzinfo=timezone))
        slots = TimeSlot.objects.filter(subject_id=self.host.id)
        self.assertEqual(len(slots), 1)

    def test_split_in_two(self):
        """
        If we create 3 availabilities that are right beside each other,
        we get one large time slot, but if we remove the middle one, we
        end up with 2 again.
        """
        timezone = pytz.timezone('America/Vancouver')
        start = date(2002, 1, 9)
        first = Availability.objects.create(
            start_date=start,
            start_time=time(8),
            end_time=time(10),
            subject=self.host,
            timezone=str(timezone),
        )
        second = Availability.objects.create(
            start_date=start,
            start_time=time(9, 30),
            end_time=time(12),
            subject=self.host,
            timezone=str(timezone),
        )
        third = Availability.objects.create(
            start_date=start,
            start_time=time(12),
            end_time=time(14),
            subject=self.host,
            timezone=str(timezone),
        )
        for obj in (first, second, third):
            obj.recreate_occurrences(datetime(2002, 1, 8, tzinfo=timezone),
                                     datetime(2002, 4, 18, tzinfo=timezone))

        offset = timezone.utcoffset(datetime(2002, 1, 9))
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        occurrences = AvailabilityOccurrence.objects.filter(
            subject_id=self.host.id)
        self.assertEqual(len(slots), 1)
        self.assertEqual(len(occurrences.all()), 3)
        self.assertEqual((slots[0].start + offset).time(), time(8))
        self.assertEqual((slots[0].end + offset).time(), time(14))

        second.delete()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        occurrences = AvailabilityOccurrence.objects.filter(
            subject_id=self.host.id)
        self.assertEqual(len(slots), 2)
        self.assertEqual(len(occurrences.all()), 2)
        self.assertEqual((slots[0].start + offset).time(), time(8))
        self.assertEqual((slots[0].end + offset).time(), time(10))
        self.assertEqual((slots[1].start + offset).time(), time(12))
        self.assertEqual((slots[1].end + offset).time(), time(14))
