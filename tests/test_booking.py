from datetime import datetime, time, timedelta

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

import django_agenda.signals
from django_agenda.models import (Availability, InvalidState, TimeSlot,
                                  TimeUnavailableError)

from . import models


class BaseCase(TestCase):

    def check_time_slots(self, expected_data, slots):
        min_len = min(len(expected_data), len(slots))
        for idx, (start, end, busy) in enumerate(expected_data):
            if not idx < min_len:
                break
            self.assertEqual(
                start, (slots[idx].start + self.offset).time(),
                'Slot {} did not have the right start time'.format(idx))
            self.assertEqual(
                end, (slots[idx].end + self.offset).time(),
                'Slot {} did not have the right end time'.format(idx))
            self.assertEqual(
                busy, slots[idx].busy,
                'Slot {} did not have the right busy state'.format(idx))
        self.assertEqual(
            len(expected_data), len(slots), 'Incorrect number of slots')


class BookingTests(BaseCase):

    def setUp(self):
        """
        Test the ability of a booking to divide time slots

        In this test we create a large availability, and then do a booking
        inside it. The result is that the time slot should get split up.
        """
        self.timezone = pytz.timezone('America/Vancouver')
        self.birthday = datetime(1984, 12, 11, tzinfo=self.timezone)
        django_agenda.signals.setup()
        self.host = User.objects.create(
            email='host@example.org', username="host")
        self.availability = Availability.objects.create(
            start_date=self.birthday.date(),
            start_time=time(8),
            end_time=time(14),
            subject=self.host,
            timezone=str(self.timezone)
        )
        self.offset = self.timezone.utcoffset(datetime(1984, 12, 11))
        self.availability.recreate_occurrences(
            self.birthday, self.birthday + timedelta(days=1))
        slots = TimeSlot.objects.filter(subject_id=self.host.id)
        self.assertEqual(len(slots), 1)

        self.guest = User.objects.create(
            email='guest@example.org', username="guest")
        self.second_guest = User.objects.create(
            email='second_guest@example.org', username="second_guest")
        self.booking_time = pytz.utc.localize(
            datetime.combine(self.birthday.date(), time(11)) - self.offset)
        self.booking = models.Booking.objects.create(
            guest=self.guest,
            host=self.host,
            subject=self.host,
            requested_time_1=self.booking_time,
        )
        # This should result in 5 time slots:
        # * 8-10:30
        # * 10:30-11
        # * 11-12
        # * 12-12:30
        # * 12:30-14:00
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)

        booking_slots = models.BookingTime.objects.all()
        self.assertEqual(len(booking_slots), 1)
        self.assertEqual(
            len(booking_slots[0].time_slot.availability_occurrences.all()), 0)

    def test_create_slots(self):
        """
        The host can create a booking in a space with no availabilities
        """
        booking = models.Booking(
            guest=self.guest,
            host=self.host,
            subject=self.host,
            requested_time_1=(self.booking_time + timedelta(days=1)),
        )
        with self.assertRaises(TimeUnavailableError):
            booking.save()

        with booking.set_editor(self.host):
            booking.save()

    def test_availability_time_slot_interaction(self):
        """
        Make sure availabilities and busy time slots don't kill each other.

        If you create a booking, and then alter the availability it was in,
        the time slot for the booking should persist. When you cancel a
        booking, the availability should free up.
        """
        # now adjust the availability to 15-19 (+1 hour if DST)
        self.availability.end_time = time(12)
        self.availability.save()
        self.availability.recreate_occurrences(
            self.birthday, self.birthday + timedelta(days=1))
        # now we should have a time slot from 15-18,
        # and a reserved booking slot from 18-19:30
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True))
        self.check_time_slots(times, slots)
        # make sure the slots free up after the booking is saved
        self.booking.state = models.Booking.STATE_CANCELED
        self.booking.save()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(12), False),)
        self.check_time_slots(times, slots)

    def test_add_overlapping_booking(self):
        """
        Create a booking, and then create another one 30 minutes earlier.

        The second booking should fail to create.
        """
        overlapping_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(minutes=30),
        )
        with self.assertRaises(TimeUnavailableError):
            overlapping_booking.save()

    def test_booking_reschedule(self):
        with self.booking.set_editor(self.guest):
            self.booking.reschedule(
                [self.booking_time - timedelta(hours=1)])
            self.booking.save()

        # This should result in 5 time slots:
        # * 8-9:30
        # * 9:30-10
        # * 10-11
        # * 11-11:30
        # * 11:30-14:00
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(9, 30), False),
                 (time(9, 30), time(10), True),
                 (time(10), time(11), True),
                 (time(11), time(11, 30), True),
                 (time(11, 30), time(14), False))
        self.check_time_slots(times, slots)

        booking_slots = self.booking.time_slots.all()
        self.assertEqual(len(booking_slots), 1)
        self.assertEqual(
            len(booking_slots[0].availability_occurrences.all()), 0)

    def test_contingent_slots(self):
        extra_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        extra_booking.save()
        # This should result in 8 time slots:
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(8, 30), False),
                 (time(8, 30), time(9), True),
                 (time(9), time(10), True),  # second booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)
        # now, if the second booking is declined, the contingent slots should
        # free up
        with extra_booking.set_editor(self.host):
            extra_booking.cancel_with_reason('test slot freeing', '')
            extra_booking.save()
        # This should result in 5 time slots:
        # * 8-9, free
        # * 9-10:30, busy
        # * 10:30-14, free
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)

    def test_disallow_multiple_bookings(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.save()
        second_multiple_booking = models.Booking(
            guest=self.second_guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        # Now we should not be able to create another booking at the same time
        with self.assertRaises(TimeUnavailableError):
            second_multiple_booking.save()

    def test_multiple_booking_cancel(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.allow_multiple_bookings = True
        multiple_booking.save()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        # Now we should be able to create another booking at the same time
        second_multiple_booking = models.Booking(
            guest=self.second_guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        second_multiple_booking.allow_multiple_bookings = True
        second_multiple_booking.save()
        with multiple_booking.set_editor(self.host):
            multiple_booking.cancel_with_reason('foo', 'bar')
            multiple_booking.save()
        times = ((time(8), time(8, 30), False),
                 (time(8, 30), time(9), True),
                 (time(9), time(10), False),  # multiple booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)
        times = ((time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        with second_multiple_booking.set_editor(self.host):
            second_multiple_booking.cancel_with_reason('foo', 'bar')
            second_multiple_booking.save()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        self.check_time_slots(times, slots)

    def test_multiple_bookings(self):
        self.host.save()
        multiple_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        multiple_booking.allow_multiple_bookings = True
        multiple_booking.save()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(8, 30), False),
                 (time(8, 30), time(9), True),
                 (time(9), time(10), False),  # multiple booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)
        # Now we should be able to create another booking at the same time
        second_multiple_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=self.booking_time - timedelta(hours=2),
        )
        second_multiple_booking.allow_multiple_bookings = True
        with self.assertRaises(InvalidState):
            second_multiple_booking.save()
        second_multiple_booking.guest = self.second_guest
        # a booking in an offset time should fail
        second_multiple_booking.requested_time_1 = \
            self.booking_time - timedelta(hours=2, minutes=30)
        with self.assertRaises(TimeUnavailableError):
            second_multiple_booking.save()
        # set it back to the overlapping spot, and this should work
        second_multiple_booking.requested_time_1 = \
            self.booking_time - timedelta(hours=2)
        second_multiple_booking.save()
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(8, 30), False),
                 (time(8, 30), time(9), True),
                 (time(9), time(10), False),  # multiple booking slot
                 (time(10), time(10, 30), True),
                 (time(10, 30), time(11), True),
                 (time(11), time(12, 00), True),  # original booking slot
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)

    def test_cancel(self):
        other_booking_time = self.booking_time - timedelta(minutes=90)
        other_booking = models.Booking(
            guest=self.guest,
            subject=self.host,
            host=self.host,
            requested_time_1=other_booking_time
        )
        other_booking.save()
        with other_booking.set_editor(self.host):
            other_booking.confirm(other_booking_time)
            other_booking.save()
        with self.booking.set_editor(self.guest):
            self.booking.confirm(self.booking_time)
            self.booking.save()

        with other_booking.set_editor(self.host):
            other_booking.cancel_with_reason('foo', 'bar')
            other_booking.save()
        with self.booking.set_editor(self.guest):
            self.booking.cancel_with_reason('foo', 'bar')
            self.booking.save()
        times = ((time(8), time(14), False),)
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        self.check_time_slots(times, slots)


class AdvancedBookingTests(BaseCase):

    def setUp(self):
        """
        Test the ability of a booking to divide time slots

        In this test we create a large availability, and then do a booking
        inside it. The result is that the time slot should get split up.
        """
        self.timezone = pytz.timezone('America/Vancouver')
        self.date = datetime(1990, 3, 3, tzinfo=self.timezone)
        django_agenda.signals.setup()
        self.host = User.objects.create(
            email='host@example.org', username="host")
        self.offset = self.timezone.utcoffset(datetime(1990, 3, 3))

    def test_multiple_request_times(self):
        first_avail = Availability.objects.create(
            start_date=self.date.date(),
            start_time=time(8),
            end_time=time(14),
            subject=self.host,
            timezone=str(self.timezone)
        )
        second_avail = Availability.objects.create(
            start_date=datetime(1990, 3, 5, tzinfo=self.timezone).date(),
            start_time=time(8),
            end_time=time(14),
            subject=self.host,
            timezone=str(self.timezone)
        )

        for avail in (first_avail, second_avail):
            avail.recreate_occurrences(
                self.date, self.date + timedelta(days=10))
        slots = TimeSlot.objects.filter(subject_id=self.host.id)
        self.assertEqual(len(slots), 2)

        times = ((time(8), time(14), False),
                 (time(8), time(14), False))
        self.check_time_slots(times, slots)

        self.guest = User.objects.create(
            email='guest@example.org', username="guest")
        first_booking_time = pytz.utc.localize(
            datetime.combine(first_avail.start_date, time(11)) - self.offset)
        second_booking_time = pytz.utc.localize(
            datetime.combine(second_avail.start_date, time(11)) - self.offset)

        self.booking = models.Booking.objects.create(
            guest=self.guest,
            host=self.host,
            subject=self.host,
            requested_time_2=second_booking_time,
            requested_time_1=first_booking_time,
        )
        # This should result in 5 time slots:
        # * 8-10:30
        # * 10:30-11
        # * 11-12
        # * 12-12:30
        # * 12:30-14:00
        slots = TimeSlot.objects.filter(
            subject_id=self.host.id).order_by('start')
        times = ((time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False),
                 (time(8), time(10, 30), False),
                 (time(10, 30), time(11), True),
                 (time(11), time(12), True),
                 (time(12), time(12, 30), True),
                 (time(12, 30), time(14), False))
        self.check_time_slots(times, slots)

        booking_slots = models.BookingTime.objects.all()
        self.assertEqual(2, len(booking_slots))


