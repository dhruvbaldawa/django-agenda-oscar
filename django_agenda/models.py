"""
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

Each of these models has a generic relation to an "owner".
An owner can be anything: a user, a group, a locations.
Whatever the owner is, that is the thing that
"""

from datetime import date, datetime, timedelta
from typing import List

import django.core.exceptions
import django.utils.timezone
import pytz
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Q
from django.utils.dateformat import DateFormat, TimeFormat
from django.utils.translation import ugettext_lazy as _
from recurrence.fields import RecurrenceField
from timezone_field import TimeZoneField


class AbstractTimeSpan:
    @property
    def length(self):
        return self.end - self.start

    @property
    def is_real(self):
        return self.start < self.end

    def __iter__(self):
        yield self.start
        yield self.end

    def expanded(self, other):
        return TimeSpan(min(self.start, other.start),
                        max(self.end, other.end))

    def time_equals(self, other):
        return (self.start == other.start
                and self.end == other.end)

    def contains(self, other):
        return (other.start >= self.start
                and other.end <= self.end)

    def connects(self, other):
        return (other.start <= self.end
                or other.end >= self.start)

    def overlaps(self, other):
        return (other.start < self.end
                and other.end > self.start)

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


class TimeSpan(AbstractTimeSpan):
    def __init__(self, start: datetime, end: datetime):
        self.start = start
        self.end = end


def start_sorted(spans: List[TimeSpan]):
    return sorted(spans, key=lambda x: x.start)


class PaddedTimeSpan(TimeSpan):

    def __init__(self, start: datetime, end: datetime, padding: timedelta):
        super().__init__(start, end)
        self.padded_start = self.start - padding
        self.padded_end = self.end + padding


class Availability(models.Model):
    """
    Represents a (possibly) recurring available time.

    These availabilities are used to generate time slots.
    """

    class Meta:
        verbose_name_plural = _('availabilities')
        default_permissions = ()

    objects = models.Manager()

    start_date = models.DateField()  # type: date
    start_time = models.TimeField()  # type: datetime.time
    end_time = models.TimeField()  # type: datetime.time
    recurrence = RecurrenceField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    timezone = TimeZoneField()

    subject_type = models.ForeignKey(
        to=ContentType, verbose_name=_('subject type'),
        on_delete=models.CASCADE,
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))

    subject = GenericForeignKey('subject_type', 'subject_id')

    # regular properties
    @property
    def start_localized(self) -> datetime:
        return self.timezone_localize(
            datetime.combine(self.start_date, self.start_time))

    @property
    def end_localized(self) -> datetime:
        return self.timezone_localize(
            datetime.combine(self.start_date, self.end_time))

    @property
    def duration(self) -> timedelta:
        return (datetime.combine(date(1, 1, 1), self.end_time)
                - datetime.combine(date(1, 1, 1), self.start_time))

    def get_timezone(self):
        # TODO: this is hacky
        if hasattr(self.timezone, 'localize'):
            return self.timezone
        return pytz.timezone(self.timezone)

    def timezone_localize(self, value: datetime):
        return self.get_timezone().localize(value)

    def get_recurrences(self, span: TimeSpan):
        duration = self.duration
        zone = self.get_timezone()
        dtstart = datetime.combine(self.start_date, self.start_time)
        naive_start = django.utils.timezone.make_naive(
            span.start, span.start.tzinfo)
        naive_end = django.utils.timezone.make_naive(
            span.end, span.start.tzinfo)
        starts = self.recurrence.between(
            naive_start, naive_end, inc=True, dtstart=dtstart)
        for start_time in starts:
            try:
                start_time = django.utils.timezone.make_aware(
                    start_time, zone)
            except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                # if the user schedules something on a dst boundary, then
                # sometimes we just have to guess the desired time
                start_time = django.utils.timezone.make_aware(
                    start_time, zone, is_dst=False)

            yield start_time, start_time + duration

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
        """
        Recreate all availability occurrences between start and end

        This is intended to be used when an availability get saved.
        """
        span = TimeSpan(start, end)
        # get all the original ones
        with transaction.atomic():
            all_slots = self.occurrences.all()
            # note, we can have multiple occurrences at the same start time
            occurrence_dict = {}
            for occurrence in all_slots:
                occurrence_dict[
                    (occurrence.start, occurrence.end)] = occurrence
            # TODO: this matching is really inefficient
            for r_start, r_end in self.get_recurrences(span):
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
    """
    A specific instance of an availability

    This data is an implementation detail and it's used to speed
    up and simplify the scheduling system by caching when a an
    availability recurs.

    An AvailabilityOccurrence has a start, end, and availability.
    The start and end should be in UTC
    """

    class Meta:
        verbose_name = _('availability occurrence')
        verbose_name_plural = _('availability occurrences')
        default_permissions = ()

    objects = models.Manager()

    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(db_index=True)
    availability = models.ForeignKey(
        on_delete=models.CASCADE, to=Availability, blank=True,
        related_name='occurrences')
    subject_type = models.ForeignKey(
        verbose_name=_('subject type'), to=ContentType,
        on_delete=models.CASCADE,
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))
    subject = GenericForeignKey('subject_type', 'subject_id')

    # regular properties
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
        """
        Stuff to do before you delete an availability occurrence
        """
        self.disconnect_slots(self.time_slots.all())

    def disconnect_slots(self, slots):
        """
        Called when an availability occurrence isn't in the same time
        as a time slot, either because it was deleted or moved.

        If the time slot is connected to any other time slots,
        we remove the availability occurrence and resize the slot,
        since it might not be as large anymore. Otherwise we delete
        the slot.
        """
        slot_ids = {slot.id for slot in slots}

        regen_q = ~models.Q(id=self.id) & models.Q(time_slots__in=slot_ids)
        regen_list = list(AvailabilityOccurrence.objects.filter(
            regen_q
            # pk__ne=self.id, time_slot_id__in=slot_ids,
        ))
        slots.delete()

        for occurrence in regen_list:
            occurrence.regen()

    def _join_slots(self, slots: List['TimeSlot'], span: TimeSpan):
        """
        A little helper method that only makes sense here

        Creates a slot between start and end, joining the related
        availability occurrences + `occurrence`, and deleting
        the old slots

        Note: start >= occurrence.start and end <= occurrence.end
        (unless it's not)
        """
        for slot in slots:
            span = span.expanded(slot)
        new_slot = TimeSlot(
            start=span.start, end=span.end,
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

    def _maybe_join_slots(self, extant_slots, span: TimeSpan):
        if span.is_real:
            current_slots = [slot for slot in extant_slots
                             if (not slot.bookings.exists() and
                                 slot.connects(span))]
            self._join_slots(current_slots, span)

    def regen(self):
        """
        Stuff to do after you create an availability occurrence

        Look through the existing time slots and either add this on
        to an existing one, create an new slot, or do nothing if a
        booking is in the way.

        Warning: this is slow and we should avoid it.
        """
        # delete surplus time slots
        surplus_slots = TimeSlot.objects.filter(
            availability_occurrences__in=[self],
            start__gt=self.end, end__lt=self.start)
        self.disconnect_slots(surplus_slots)
        # load these all once
        extant_slots = TimeSlot.objects.order_by('start').filter(
            end__gte=self.start, start__lte=self.end,
            subject_id=self.subject_id, subject_type=self.subject_type,
        ).prefetch_related(
            'availability_occurrences', 'bookings').order_by('start')
        ao_through_model = TimeSlot.availability_occurrences.through
        new_ao_rels = []
        span = TimeSpan(self.start, self.start)
        merge_slots = []
        delete_slot_ids = set()
        for ex_slot in extant_slots:
            if ex_slot.busy or ex_slot.bookings.exists():
                span.end = ex_slot.start
                if span.is_real:
                    rels, ds_id = self._maybe_make_slots(span, merge_slots)
                    delete_slot_ids = delete_slot_ids.union(ds_id)
                    for rel in rels:
                        new_ao_rels.append(rel)
                merge_slots = []
                span.start = ex_slot.end
            else:
                merge_slots.append(ex_slot)
        span.end = self.end
        if span.is_real:
            rels, ds_id = self._maybe_make_slots(span, merge_slots)
            delete_slot_ids = delete_slot_ids.union(ds_id)
            for rel in rels:
                new_ao_rels.append(rel)

        TimeSlot.objects.filter(id__in=delete_slot_ids).delete()
        ao_through_model.objects.bulk_create(new_ao_rels)

    def _maybe_make_slots(self, span, merge_slots):
        ao_through_model = TimeSlot.availability_occurrences.through
        # no slots, make a new one
        if len(merge_slots) < 1:
            new_slot = TimeSlot.objects.create(
                start=span.start,
                end=span.end,
                subject_id=self.subject_id,
                subject_type=self.subject_type)
            return [ao_through_model(
                availabilityoccurrence_id=self.id,
                timeslot_id=new_slot.id)], []
        else:
            all_ao_ids = {self.id}
            new_span = span.expanded(merge_slots[0])
            for slot in merge_slots[1:]:
                for ao in slot.availability_occurrences.all():
                    all_ao_ids.add(ao.id)
                new_span = new_span.expanded(slot)
            for ao in merge_slots[0].availability_occurrences.all():
                all_ao_ids.discard(ao.id)
            merge_slots[0].start = new_span.start
            merge_slots[0].end = new_span.end
            merge_slots[0].save()
            delete_slot_ids = set(slot.id for slot in merge_slots[1:])

            ao_throughs = [
                ao_through_model(
                    availabilityoccurrence_id=ao_id,
                    timeslot_id=merge_slots[0].id) for ao_id in all_ao_ids]

            return ao_throughs, delete_slot_ids


class TimeSlot(models.Model, AbstractTimeSpan):
    """
    A segment of time that can be scheduled.

    Time slots are non-recurring and their times are always stored in UTC.
    """

    class Meta:
        verbose_name_plural = "time slots"
        default_permissions = ()

    objects = models.Manager()

    start = models.DateTimeField(db_index=True)  # type: datetime
    end = models.DateTimeField(db_index=True)  # type: datetime
    busy = models.BooleanField(default=False, db_index=True)

    subject_type = models.ForeignKey(
        on_delete=models.CASCADE, to=ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject'))

    subject = GenericForeignKey('subject_type', 'subject_id')

    availability_occurrences = models.ManyToManyField(
        AvailabilityOccurrence, blank=True, related_name='time_slots')

    padding_for = models.ForeignKey(
        'TimeSlot', blank=True, null=True, on_delete=models.CASCADE,
        related_name='padded_by')

    def avoid_span(self, span: TimeSpan):
        if self.start <= span.end:
            self.start = span.end
        if self.end >= span.start:
            self.end = span.start


class InvalidState(django.core.exceptions.ValidationError):
    """
    Exception for the booking being set in an invalid state.
    """
    pass


class InvalidTime(InvalidState):
    """
    Exception for booking requests/confirmations at invalid times
    """


class TimeUnavailableError(InvalidTime):
    pass


class OverlappingTimeError(TimeUnavailableError):

    def __init__(self):
        super().__init__(
            'There’s already a booking in part of this time, '
            'try either requesting the exact same time of the '
            'booking or a later time')


class AbstractBooking(models.Model):

    class Meta:
        abstract = True

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
        max_length=3, db_index=True,
        choices=STATES, default=STATE_UNCONFIRMED)

    subject_type = models.ForeignKey(
        on_delete=models.CASCADE, to=ContentType,
        verbose_name=_('subject type'),
    )
    subject_id = models.PositiveIntegerField(verbose_name=_('subject id'))
    subject = GenericForeignKey('subject_type', 'subject_id')

    def __str__(self):
        return 'Booking'

    def slot_diff(self):
        """
        Return the difference between the existing time slots and the ones
        suggested by the current times & state

        :returns: Tuple of a list of timespans and a list of timeslots
        """
        slot_times = dict()
        add_times = []
        padding = self._get_padding()
        if self.pk is not None:
            for slot in self.time_slots.all():
                slot_times[(slot.start, slot.end)] = slot
        for start, end in self.get_reserved_spans():
            start_utc = start.astimezone(pytz.utc)
            end_utc = end.astimezone(pytz.utc)
            if (start_utc, end_utc) in slot_times.keys():
                del slot_times[(start_utc, end_utc)]
            else:
                add_times.append(PaddedTimeSpan(start_utc, end_utc, padding))

        return add_times, list(slot_times.values())

    def clear_slots(self, slots):
        """
        """
        self._disconnect_slots(slots)
        delete_ids = set()
        changed_times = set()
        for slot in slots:
            if not slot.bookings.exists():
                delete_ids.add(slot.id)
                changed_times.add(TimeSpan(slot.start, slot.end))
        TimeSlot.objects.filter(id__in=delete_ids).delete()
        regen_query = AvailabilityOccurrence.objects.filter(
            subject_id=self.subject_id,
            subject_type=self.subject_type)
        if changed_times:
            first_time = changed_times.pop()
            query = models.Q(
                start__lte=first_time.end, end__gte=first_time.start)
            for span in changed_times:
                query = query | models.Q(
                    start__lte=span.end, end__gte=span.start)
            regen_query = regen_query.filter(query)
        for occurrence in regen_query:
            occurrence.regen()

    def find_slots(self, spans: List[PaddedTimeSpan]):
        """
        Look through existing slots and return ones that match

        Generally, the time slots have to be free. If `_book_unscheduled`
        returns True, a time slot is created it it doesn't exist.

        :return: Iterator[Tuple[List[TimeSpan], List[TimeSlot]]]
        """
        spans = start_sorted(spans)
        return_spans = []
        return_slots = {}
        last_time = None
        for span in spans:
            # get all slots that have some space in this span
            # all of these should be
            subject_ct = ContentType.objects.get_for_model(type(self.subject))
            all_slots = TimeSlot.objects.filter(
                subject_id=self.subject_id, subject_type=subject_ct,
                start__lt=span.padded_end, end__gt=span.padded_start
            ).order_by('start').prefetch_related(
                'availability_occurrences', 'bookings').all()
            found_span, found_slots = self.find_slot_for_span(span, all_slots)
            return_spans.append(found_span)
            for slot in found_slots:
                if slot.id not in return_slots:
                    return_slots[slot.id] = slot
            if last_time is not None and last_time < span.start:
                yield return_spans, start_sorted(return_slots.values())
                return_spans = []
                return_slots = {}
        if return_slots or return_spans:
            yield return_spans, start_sorted(return_slots.values())

    def find_slot_for_span(self, span: PaddedTimeSpan, slots: List[TimeSlot]):
        """
        :return: Tuple[TimeSpan, List[TimeSlot]]
        """
        free_slots = []
        busy_slots = []
        for slot in slots:
            if span.overlaps(slot):
                if slot.busy:
                    busy_slots.append(slot)
                else:
                    if slot.bookings.exists():
                        if slot.time_equals(span):
                            for booking in slot.bookings.all():
                                if self.is_duplicate(booking):
                                    raise InvalidState('Duplicate booking')
                            return span, [slot]
                        elif not self._book_overlapping():
                            raise OverlappingTimeError()
                    if slot.contains(span):
                        return span, [slot]
                    else:
                        free_slots.append(slot)
            else:
                if slot.bookings.exists():
                    raise OverlappingTimeError()
        if busy_slots:
            raise TimeUnavailableError(
                'Requested time is busy')
        if free_slots:
            return span, free_slots
        else:
            if not self._book_unscheduled():
                raise TimeUnavailableError(
                    'Requested time is unavailable')
            # all these slots can be pushed around
            for old_slot in slots:
                if span.contains(old_slot):
                    old_slot.delete()
                else:
                    old_slot.avoid_span(span)
                    old_slot.save()
            return span, []

    def save(self, *args, **kwargs):
        # reserve slots if necessary
        add_times, rm_slots = self.slot_diff()
        padding = self._get_padding()

        with transaction.atomic():
            # clear slots in case that means we can book again
            # this is important for rescheduling, especially with lots
            # of padding
            self.clear_slots(rm_slots)
            found_data = list(self.find_slots(add_times))
            # the main new slots
            new_slots = []
            padded_slots = []
            old_ids = set()
            # n.b. anything in a group that is not busy must be free
            # for in between the gaps with-in a group
            inter_aos = []
            ao_through_model = TimeSlot.availability_occurrences.through
            # first pass, create spans and padding for each grouping
            for found_spans, found_slots in found_data:
                for slot in found_slots:
                    old_ids.add(slot.id)
                for found_span in found_spans:
                    new_slot = TimeSlot.objects.create(
                        start=found_span.start,
                        end=found_span.end,
                        busy=self._is_booked_slot_busy(),
                        subject_id=self.subject_id,
                        subject_type=self.subject_type)
                    new_slots.append(new_slot)
                    if padding:
                        padded_slots.append(TimeSlot(
                            start=found_span.padded_start,
                            end=found_span.start,
                            busy=True,
                            subject_id=self.subject_id,
                            subject_type=self.subject_type,
                            padding_for=new_slot))
                        padded_slots.append(TimeSlot(
                            start=found_span.end,
                            end=found_span.padded_end,
                            busy=True,
                            subject_id=self.subject_id,
                            subject_type=self.subject_type,
                            padding_for=new_slot))

                inter_slots = []
                if found_slots:
                    s_bound = found_slots[0].start
                    for found_slot in found_slots:
                        s_bound = max(s_bound, found_slot.start)
                        for found_span in found_spans:
                            if s_bound >= found_span.padded_start:
                                s_bound = max(s_bound, found_span.padded_end)
                                continue
                            if found_slot.end < found_span.padded_start:
                                break
                            # create now so we get the ID
                            # could optimize on postgres
                            inter_slots.append(TimeSlot.objects.create(
                                start=s_bound,
                                end=found_span.padded_start,
                                subject_id=self.subject_id,
                                subject_type=self.subject_type))
                            s_bound = found_span.padded_end
                        if s_bound < found_slot.end:
                            inter_slots.append(TimeSlot.objects.create(
                                start=s_bound,
                                end=found_slot.end,
                                subject_id=self.subject_id,
                                subject_type=self.subject_type))

                for inter_slot in inter_slots:
                    match_ao_ids = set()
                    for slot in found_slots:
                        if slot.overlaps(inter_slot):
                            for ao in slot.availability_occurrences.all():
                                match_ao_ids.add(ao.id)
                    for ao_id in match_ao_ids:
                        inter_aos.append(ao_through_model(
                            availabilityoccurrence_id=ao_id,
                            timeslot_id=inter_slot.id,
                        ))
            ao_through_model.objects.bulk_create(inter_aos)
            TimeSlot.objects.bulk_create(padded_slots)
            TimeSlot.objects.filter(id__in=old_ids).delete()
            super().save(*args, **kwargs)
            self._connect_slots(new_slots)
        # end transaction

    def is_duplicate(self, other_booking):
        """
        Assuming the times are the same, is this a duplicate booking?

        Always returning False effectively disables duplicate checking
        """
        return False

    def _get_padding(self) -> timedelta:
        """
        Return the amount of time required between bookings.

        This time will get marked as busy.
        """
        return timedelta(0)

    def _padding_changed(self):
        """
        Notify booking that the padding has changed

        It's the booking's responsibility to update itself if required
        """
        subject_q = Q(subject_id=self.subject_id,
                      subject_type=self.subject_type)
        padding_length = self._get_padding()
        my_slots = TimeSlot.objects.filter(subject_q)
        padding_slots = TimeSlot.objects.filter(
            padding_for__in=my_slots).order_by('start')
        changed_slots = set()
        changed_free_slots = set()
        delete_free_slots = set()
        for slot in padding_slots:
            start = slot.start
            end = slot.end
            if slot.padding_for.start > slot.start:
                # it's padding before
                start = end - padding_length
            else:
                end = start + padding_length
            if (end != slot.end) or (start != slot.start):
                slot.start = start
                slot.end = end
                changed_slots.add(slot)
        # only do something if things actually changed
        regen_time = None
        for slot in changed_slots:
            if regen_time is None:
                regen_time = slot
            else:
                regen_time = regen_time.expanded(slot)

        if regen_time is not None:
            for slot in changed_slots:
                slot.save()
            # from free slots may need to be shortened
            overlap_q = (Q(end__gte=regen_time.start) |
                         Q(start__lte=regen_time.end))
            regen_query = TimeSlot.objects.filter(
                subject_q & overlap_q).filter(busy=False).order_by('start')
            changed_slot_idx = 0
            csl = list(changed_slots)
            for slot in regen_query:
                if slot.bookings.exists():
                    continue
                for cs in csl[changed_slot_idx:]:
                    if cs.start <= slot.start:
                        if cs.end >= slot.end:
                            delete_free_slots.add(slot)
                        elif cs.end > slot.start:
                            slot.start = cs.end
                            changed_free_slots.add(slot)
                        else:
                            changed_slots.discard(cs)
                    else:
                        if cs.start < slot.end:
                            slot.end = cs.start
                            changed_free_slots.add(slot)
                        else:
                            continue
            for slot in changed_slots:
                slot.save()
            for slot in changed_free_slots:
                slot.save()
            for slot in delete_free_slots:
                slot.delete()

    def _is_booked_slot_busy(self):
        """
        If a slot is booked, determine whether it can be booked again.
        """
        return True

    def _book_unscheduled(self):
        """
        If this returns true, bookings will automatically create slots in
        unscheduled space.
        """
        return False

    def _book_overlapping(self):
        """
        If this returns true, overlapping bookings can be created.
        """
        return False

    def _connect_slots(self, slots: List[TimeSlot]):
        """
        Add the time slots into the `time_slots` relation

        This should save the related date without calling Booking.save
        """
        raise NotImplementedError

    def _disconnect_slots(self, slots: List[TimeSlot]):
        """
        Used before a slot is going to be deleted.

        This needs to disconnect any booking objects and other relations
        that don't automatically get disconnected.
        """
        raise NotImplementedError

    def get_reserved_spans(self) -> List[TimeSpan]:
        """
        Return a list of times that should be reserved
        """
        raise NotImplementedError

    # state change methods
    def cancel(self):
        """
        Cancel a booking

        In order to cancel a booking it must be either in the unconfirmed
        or confirmed state. Bookings in other states have no need to be
        canceled.
        """
        if self.state == AbstractBooking.STATE_UNCONFIRMED:
            self.state = AbstractBooking.STATE_DECLINED
        elif self.state == AbstractBooking.STATE_CONFIRMED:
            self.state = AbstractBooking.STATE_CANCELED
        else:
            raise InvalidState(
                'Only unconfirmed & unconfirmed bookings can be canceled')
        self.state = AbstractBooking.STATE_CANCELED

    def confirm(self, when: datetime):
        self.state = AbstractBooking.STATE_CONFIRMED


def recreate_time_slots(start=None, end=None):
    """Remove all the time slots and start from scratch

    New time slots are created between start & end inclusive
    """
    if start is None:
        start = django.utils.timezone.now()
    if end is None:
        end = start + timedelta(days=100)

    for availability in Availability.objects.all():
        availability.recreate_occurrences(start, end)
