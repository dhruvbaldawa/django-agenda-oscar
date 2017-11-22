'''
Scheduling models

There are three levels of scheduling:

1. Availabilities are intended for users to create & edit. They indicate
   when a user/item is not busy. Availabilities may overlap, but overlapping
   doesn't mean that they're any more available.
2. Availability Occurrences are an internally used data model mainly used
   to improve performance.
3. Time Slots are what get selected when bookings are created. A time
   slot can either be busy or free, and they should never overlap. Time
   slots are automatically re-generated from availability occurances, but
   once a booking is made for a time slot, it will 'stick'

In effect, availabilities represent the user's intent, and time slots
represent what is actually scheduled to happen.

Important Notes:

Each of these models has a generic relation to an "owner". An owner can be anything:
a user, a group, a locations. Whatever the owner is, that is the thing that
'''

from datetime import datetime, date, timedelta
from typing import List, Tuple

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
import django.utils
from django.utils.dateformat import DateFormat, TimeFormat
from django.utils.translation import ugettext_lazy as _
import pytz
from recurrence.fields import RecurrenceField
from timezone_field import TimeZoneField


class Availability(models.Model):
    '''
    Represents a (possibly) recurring available time.

    These availabilities are used to generate time slots.
    '''

    class Meta:
        verbose_name_plural = _('availabilities')
        default_permissions = ()

    start_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    recurrence = RecurrenceField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    timezone = TimeZoneField()

    subject_type = models.ForeignKey(
        ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))

    subject = GenericForeignKey('subject_type', 'subject_id')

    @property
    def start_localized(self):
        return self.timezone_localize(
            datetime.combine(self.start_date, self.start_time))

    @property
    def end_localized(self):
        return self.timezone_localize(
            datetime.combine(self.start_date, self.end))

    @property
    def duration(self):
        return (datetime.combine(date(1, 1, 1), self.end_time)
                - datetime.combine(date(1, 1, 1), self.start_time))

    def timezone_localize(self, value: datetime):
        # TODO: this is hacky
        if hasattr(self.timezone, 'localize'):
            return self.timezone.localize(value)
        return pytz.timezone(self.timezone).localize(value)

    def get_recurrences(self, start, end):
        duration = self.duration
        starts = self.recurrence.between(
            start, end, inc=True, dtstart=self.start_localized)
        for time in starts:
            yield time, time + duration

    def __str__(self):
        result = '{0}-{1}'.format(
            TimeFormat(self.start_time).format(settings.TIME_FORMAT),
            TimeFormat(self.end_time).format(settings.TIME_FORMAT),
        )
        if not self.recurrence:
            result = '{0} {1}'.format(
                DateFormat(self.start_date).format(settings.DATE_FORMAT),
                result
            )
        return result

    def recreate_occurrences(self, start: datetime, end: datetime):
        '''
        Recreate all availability occurrences between start and end

        This is intended to be used when an availability get saved.
        '''
        # get all the original ones
        all_slots = self.occurrences.all()
        duration = self.duration
        # note, we can have multiple occurrences at the same start time
        occurrence_dict = {}
        for occurrence in all_slots:
            occurrence_dict[(occurrence.start, occurrence.end)] = occurrence
        # TODO: this matching is really inefficient
        for r_start, r_end in self.get_recurrences(start, end):
            if (r_start, r_end) in occurrence_dict:
                # yay we matched our occurrence, pop it
                del occurrence_dict[(r_start, r_end)]
            else:
                occurrence = AvailabilityOccurrence.objects.create(
                    availability=self,
                    start=r_start,
                    end=r_end,
                    subject_type=self.subject_type,
                    subject_id=self.subject_id,
                )
                occurrence.regen()
        # remaining occurrence_dict items need to die
        for occurrence in occurrence_dict.values():
            # just in case
            occurrence.predelete()
            occurrence.delete()


class AvailabilityOccurrence(models.Model):
    '''
    A specific instance of an availability

    This data is an implementation detail and it's used to speed
    up and simplify the scheduling system by caching when a an
    availability recurs.

    An AvailabilityOccurrence has a start, end, and availability.
    The start and end should be in UTC
    '''

    class Meta:
        verbose_name = _('availability occurrence')
        verbose_name_plural = _('availability occurrences')
        default_permissions = ()

    start = models.DateTimeField()
    end = models.DateTimeField()
    availability = models.ForeignKey(
        Availability, blank=True, related_name='occurrences')
    subject_type = models.ForeignKey(
        ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))

    subject = GenericForeignKey('subject_type', 'subject_id')

    def __str__(self):
        if self.start.date() == self.end.date():
            return '{0} {1}-{2}'.format(
                DateFormat(self.start).format(settings.DATE_FORMAT),
                TimeFormat(self.start).format(settings.TIME_FORMAT),
                TimeFormat(self.end).format(settings.TIME_FORMAT),
            )

        return '{0}-{1}'.format(
            DateFormat(self.start).format(settings.DATETIME_FORMAT),
            DateFormat(self.end).format(settings.DATETIME_FORMAT),
        )

    def predelete(self):
        '''
        Stuff to do before you delete an availability occurrence
        '''
        time_slots = self.time_slots.all()
        for slot in time_slots:
            slot.disconnect(self)

    def _join_slots(self, slots: 'TimeSlot',
                    start: datetime, end: datetime):
        '''
        A little helper method that only makes sense here

        Creates a slot between start and end, joining the related
        availability occurrences + `occurrence`, and deleting
        the old slots

        Note: start >= occurrence.start and end <= occurrence.end (unless it's not)
        '''
        for slot in slots:
            if slot.start < start:
                start = slot.start
            if slot.end > end:
                end = slot.end
        new_slot = TimeSlot(
            start=start, end=end,
            subject_id=self.subject_id,
            subject_type=self.subject_type)
        new_slot.save()
        new_slot.availability_occurrences.add(self)
        new_slot.save()
        assert new_slot.availability_occurrences.exists()
        for slot in slots:
            for slot_occurrence in slot.availability_occurrences.all():
                new_slot.availability_occurrences.add(slot_occurrence)
            slot.delete()
        return new_slot

    def _maybe_join_slots(self, extant_slots, start, end):
        if start < end:
            current_slots = [slot for slot in extant_slots
                             if (not slot.bookings.exists() and
                                 slot.start <= end and
                                 slot.end >= start)]
            self._join_slots(current_slots, start, end)

    def regen(self):
        '''Stuff to do after you create an availability occurrence

        Look through the existing time slots and either add this on
        to an existing one, create an new slot, or do nothing if a
        booking is in the way.
        '''
        # delete surplus time slots
        surplus_slots = TimeSlot.objects.filter(
            availability_occurrences__in=[self],
            start__gt=self.end, end__lt=self.start)
        for slot in surplus_slots:
            slot.disconnect(self)
        # load these all once
        extant_slots = TimeSlot.objects.order_by('start').filter(
            end__gte=self.start, start__lte=self.end,
            subject_id=self.subject_id, subject_type=self.subject_type)
        booked_slots = (
            slot for slot in extant_slots if slot.bookings.exists())
        cursor = self.start
        for booked_slot in booked_slots:
            self._maybe_join_slots(extant_slots,
                                   cursor, booked_slot.start)
            # reload slots, since they may have been deleted
            extant_slots = TimeSlot.objects.order_by('start').filter(
                end__gte=self.start, start__lte=self.end,
                subject_id=self.subject_id, subject_type=self.subject_type)
            cursor = booked_slot.end
        # handle remaining time
        self._maybe_join_slots(extant_slots, cursor, self.end)


class TimeSlot(models.Model):
    '''
    A segment of time that can be scheduled.

    Time slots are non-recurring and their times are always stored in UTC.
    '''

    class Meta:
        verbose_name_plural = "time slots"
        default_permissions = ()

    start = models.DateTimeField()
    end = models.DateTimeField()
    busy = models.BooleanField(default=False)

    subject_type = models.ForeignKey(
        ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))

    subject = GenericForeignKey('subject_type', 'subject_id')

    availability_occurrences = models.ManyToManyField(
        AvailabilityOccurrence, blank=True, related_name='time_slots')

    slot_before = models.ForeignKey(
        'TimeSlot', blank=True, null=True, on_delete=models.SET_NULL,
        related_name='+')
    slot_after = models.ForeignKey(
        'TimeSlot', blank=True, null=True, on_delete=models.SET_NULL,
        related_name='+')

    def __str__(self):
        if self.start.date() == self.end.date():
            return '{0} {1}-{2}'.format(
                DateFormat(self.start).format(settings.DATE_FORMAT),
                TimeFormat(self.start).format(settings.TIME_FORMAT),
                TimeFormat(self.end).format(settings.TIME_FORMAT),
            )

        return '{0}-{1}'.format(
            DateFormat(self.start).format(settings.DATETIME_FORMAT),
            DateFormat(self.end).format(settings.DATETIME_FORMAT),
        )

    def disconnect(self, occurrence: AvailabilityOccurrence):
        '''
        Called when an availability occurrence isn't in the same time
        as a time slot, either because it was deleted or moved.

        If the time slot is connected to any other time slots,
        we remove the availability occurrence and resize the slot,
        since it might not be as large anymore. Otherwise we delete
        the slot.
        '''
        self.availability_occurrences.remove(occurrence)
        if self.availability_occurrences.exists():
            # probably not the most efficient, but it works
            old_slots = list(self.availability_occurrences.all())
            self.delete()
            for old_occurrence in old_slots:
                old_occurrence.regen()
        else:
            self.delete()

    def bookable(self, start: datetime, end: datetime) -> bool:
        '''
        Check if a slot can fit a booking inside of it.

        The start and end of the booking are specified by `start` and `end`.
        If the slot is already booked, the start and end must line up exactly
        (so that the slot is not split), otherwise the start and end have to
        fit inside the slots start and end.
        '''
        if self.start == start and self.end == end:
            return True
        return (self.start <= start and self.end >= end and
                not self.bookings.exists())

    @property
    def available(self):
        return not self.busy

    @available.setter
    def available(self, value):
        self.busy = not value


class InvalidState(Exception):
    '''
    Exception for the booking being set in an invalid state.
    '''
    pass


class InvalidTime(InvalidState):
    '''
    Exception for booking requests/confirmations at invalid times
    '''


class TimeUnavailableError(ValidationError):
    pass


class AbstractBooking(models.Model):

    class Meta:
        abstract = True

    DURATION = timedelta(minutes=90)

    STATE_UNCONFIRMED = 'UNC'
    # this means it's either scheduled to happen
    # or has just happened and hasn't been moved
    # to
    STATE_CONFIRMED = 'CNF'
    STATE_DECLINED = 'DCL'
    STATE_COMPLETED = 'CMP'
    STATE_CANCELED = 'CAN'
    # expired is for things that haven't been confirmed
    STATE_EXPIRED = 'EXP'
    # missed means that it was confirmed, but nobody showed
    STATE_MISSED = 'MIS'

    STATES = (
        (STATE_UNCONFIRMED, 'Unconfirmed'),
        (STATE_DECLINED, 'Declined'),
        (STATE_EXPIRED, 'Expired'),
        (STATE_CONFIRMED, 'Confirmed'),
        (STATE_COMPLETED, 'Completed'),
        (STATE_CANCELED, 'Canceled'),
        (STATE_MISSED, 'Missed'),
    )
    # states in which the time slots stay reserved.
    RESERVED_STATES = (STATE_UNCONFIRMED, STATE_CONFIRMED, STATE_COMPLETED,
                       STATE_MISSED)

    state = models.CharField(
        choices=STATES, max_length=3, default=STATE_UNCONFIRMED)

    subject_type = models.ForeignKey(
        ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject id'))
    subject = GenericForeignKey('subject_type', 'subject_id')

    def __str__(self):
        return 'Booking'

    def slot_diff(self):
        '''
        Return the difference between the existing time slots and the ones
        suggested by the current times & state
        '''
        slot_times = dict()
        add_times = []
        if self.pk is not None:
            for slot in self.time_slots.all():
                slot_times[(slot.start, slot.end)] = slot
        for start, end in self.get_reserved_spans():
            if (start, end) in slot_times.keys():
                del slot_times[(start, end)]
            else:
                add_times.append((start, end))

        return add_times, list(slot_times.values())

    def clear_slots(self, slots):
        '''
        '''
        changed_times = []
        for slot in slots:
            self._disconnect_slot(slot)
            if not slot.bookings.exists():
                slot.delete()
                changed_times.append((slot.start, slot.end))
        for start, end in changed_times:
            for occurrence in AvailabilityOccurrence.objects.filter(
                    subject_id=self.subject_id,
                    subject_type=self.subject_type,
                    start__lte=end, end__gte=start):
                occurrence.regen()

    def find_slots(self,
                   spans: List[Tuple[datetime, datetime]]):
        for start, end in spans:
            # get all slots that have some space in this span
            # all of these should be
            all_slots = self.subject.time_slots.filter(
                start__lt=end, end__gt=start).all()
            if any(s.busy for s in all_slots):
                # this for sure blocks us
                raise TimeUnavailableError(
                    'Requested time is busy')
            # now all the slots are free
            free_slot = next(
                (x for x in all_slots if x.bookable(start, end)), None)
            if free_slot is not None:
                yield free_slot, start, end
            else:
                if not self._book_unscheduled():
                    raise TimeUnavailableError(
                        'Requested time is unavailable')
                if any(s.bookings.exist() for s in all_slots):
                    raise TimeUnavailableError(
                        'Part of requested time is booked')
                # all these slots can be pushed around
                for old_slot in all_slots:
                    if old_slot.start >= start and old_slot.end <= end:
                        old_slot.delete()
                    else:
                        if old_slot.start <= end:
                            old_slot.start = end
                        if old_slot.end >= end:
                            old_slot.end = end
                        old_slot.save()
                slot = TimeSlot.objects.create(
                    start=start, end=end,
                    subject_type=self.subject_type,
                    subject_id=self.subject_id)
                yield slot, start, end

    def save(self, *args, **kwargs):
        # reserve slots if necessary
        add_times, rm_slots = self.slot_diff()

        with transaction.atomic():
            self.clear_slots(rm_slots)
            add_slots = list(self.find_slots(add_times))
            for slot, start, end in add_slots:
                if slot.start < start:
                    original_start = slot.start
                    original_slot_before = slot.slot_before
                    pre_slot = TimeSlot.objects.create(
                        start=original_start,
                        end=start,
                        subject_id=self.subject_id,
                        subject_type=self.subject_type,
                        slot_before=original_slot_before,
                        slot_after=slot,
                        busy=(start - original_start <
                              AbstractBooking.DURATION)
                    )
                    pre_slot.availability_occurrences = slot.availability_occurrences.all()
                    slot.start = start
                    slot.slot_before = pre_slot
                    pre_slot.save()
                    assert pre_slot.availability_occurrences.exists()
                if slot.end > end:
                    original_end = slot.end
                    original_slot_after = slot.slot_after
                    post_slot = TimeSlot.objects.create(
                        start=end,
                        end=original_end,
                        subject_id=self.subject_id,
                        subject_type=self.subject_type,
                        slot_before=slot,
                        slot_after=original_slot_after,
                        busy=(original_end - end <
                              AbstractBooking.DURATION)
                    )
                    post_slot.availability_occurrences = slot.availability_occurrences.all()
                    slot.end = end
                    slot.slot_after = post_slot
                    post_slot.save()
                    assert post_slot.availability_occurrences.exists()

                slot.availability_occurrences.clear()
                slot.busy = not self._is_booked_slot_busy(slot)

            super().save(*args, **kwargs)

            self._add_slots([slot for slot, start, end in add_slots])
        # end transaction

    def _is_booked_slot_busy(self, slot):
        return self.subject.allow_multiple_bookings

    def _book_unscheduled(self):
        '''
        If this returns true, bookings will automatically create slots in
        unscheduled space.
        '''
        return False

    def _add_slots(self, slots: List[TimeSlot]):
        '''
        Add the time slots into the `time_slots` relation

        This should save the related date without calling Booking.save
        '''
        raise NotImplementedError

    def _disconnect_slot(self, slot: TimeSlot):
        # something like this
        slot.bookings.remove(self)

    def get_reserved_times(self):
        '''
        Return a list of times that should be reserved
        '''
        raise NotImplementedError

    # state change methods
    def cancel(self):
        '''
        Cancel a booking

        In order to cancel a booking it must be either in the unconfirmed
        or confirmed state. Bookings in other states have no need to be
        canceled.
        '''
        if self.state == AbstractBooking.STATE_UNCONFIRMED:
            self.state = AbstractBooking.STATE_DECLINED
        elif self.state == AbstractBooking.STATE_CONFIRMED:
            self.state = AbstractBooking.STATE_CANCELED
        else:
            raise InvalidState(
                'Only unconfirmed & unconfirmed bookings can be canceled')
        self.state = AbstractBooking.STATE_CANCELED

    def confirm(self, time: datetime):
        self.state = AbstractBooking.STATE_CONFIRMED


def recreate_time_slots(start=None, end=None):
    '''Remove all the time slots and start from scratch

    New time slots are created between start & end inclusive
    '''
    if start is None:
        start = django.utils.timezone.now()
    if end is None:
        end = start + timedelta(days=100)

    for availability in Availability.objects.all():
        availability.recreate_occurrences(start, end)
