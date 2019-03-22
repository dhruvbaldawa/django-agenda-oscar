"""
Scheduling models

There are three levels of scheduling:

1. Availabilities are intended for users to create & edit. They indicate
   when a user/item is not busy. Availabilities may overlap, but overlapping
   doesn't mean that they're any more available.
2. Availability Occurrences are an internally used data model mainly used
   to improve performance. They indicate free time.
3. Time Slots are what get created when bookings are created. A time
   slot can either be busy or free, and they can overlap. A time is free if
   there is a free availability occurrence and there are no
   busy time slots

In effect, availabilities represent the user's intent, and time slots
represent what is actually scheduled to happen.

Important Notes:

Each of these models has a generic relation to a "schedule" model.
An owner can be anything: a user, a group, a locations. You specify
this model in the Meta options.
"""

from datetime import date, datetime, timedelta
from typing import List

import django.utils.timezone
import pytz
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models, transaction
from django.db.models.base import ModelBase
from django.utils.dateformat import DateFormat, TimeFormat
from django.utils.translation import gettext_lazy as _
from recurrence.fields import RecurrenceField
from timezone_field import TimeZoneField

from .time_span import (AbstractTimeSpan, TimeSpan, PaddedTimeSpan)

__all__ = ['AbstractAvailability', 'AbstractAvailabilityOccurrence',
           'AbstractTimeSlot', 'AbstractBooking', 'get_free_times']


# Old stub models
# These are just here for a little extra verbosity, if you were using
# django-agenda<0.6, the tables associated with these models should
# still be kicking around in case you want to migrate them
class Availability(models.Model):
    class Meta:
        managed = False


class AvailabilityOccurrence(models.Model):
    class Meta:
        managed = False


class TimeSlot(models.Model):
    class Meta:
        managed = False


# abstract model classes
class Meta(ModelBase):
    """A metaclass for abstract models that orchestrates the relationships
    """
    def __new__(mcs, name, bases, attrs):
        model = super().__new__(mcs, name, bases, attrs)
        meta = getattr(model, '_meta')
        if not meta.abstract:
            related_name = '+'
            for b in bases:
                if b.__name__ == "AbstractAvailability":
                    related_name = 'availabilities'
                elif b.__name__ == "AbstractAvailabilityOccurrence":
                    related_name = 'availability_occurrences'
                elif b.__name__ == "AbstractTimeSlot":
                    related_name = 'time_slots'
                elif b.__name__ == "AbstractBooking":
                    related_name = 'bookings'
            field_name = Meta.get_schedule_field(model)
            schedule_cls = Meta.get_schedule_model(model)
            try:
                meta.get_field(field_name)
            except models.FieldDoesNotExist:
                model.add_to_class(
                    field_name, models.ForeignKey(
                        to=schedule_cls, on_delete=models.CASCADE,
                        related_name=related_name))

        return model

    @staticmethod
    def get_schedule_field(model):
        meta = getattr(model, 'AgendaMeta', None)
        if meta is None:
            raise RuntimeError('Model must specify AgendaMeta')
        return getattr(meta, 'schedule_field', 'schedule')

    @staticmethod
    def get_schedule(model):
        return getattr(model, Meta.get_schedule_field(model))

    @staticmethod
    def get_schedule_model(model):
        meta = getattr(model, 'AgendaMeta', None)
        if meta is None:
            raise RuntimeError('Model must specify AgendaMeta')
        result = getattr(meta, 'schedule_model', None)
        if result is None:
            raise RuntimeError('Model must specify AgendaMeta.schedule_model')
        return result


class OccurrenceMeta(Meta):

    def __new__(mcs, name, bases, attrs):
        model = super().__new__(mcs, name, bases, attrs)
        meta = getattr(model, '_meta', None)
        if meta is None:
            raise RuntimeError('Model must derive from ModelBase')
        if not meta.abstract:
            related_name = 'occurrences'
            field_name = OccurrenceMeta.get_availability_field(model)
            avail_cls = OccurrenceMeta.get_availability_model(model)
            try:
                meta.get_field(field_name)
            except models.FieldDoesNotExist:
                model.add_to_class(
                    field_name, models.ForeignKey(
                        to=avail_cls, on_delete=models.CASCADE,
                        related_name=related_name))

        return model

    @staticmethod
    def get_availability_field(_model):
        return 'availability'

    @staticmethod
    def get_availability_model(model):
        meta = getattr(model, 'AgendaMeta', None)
        if meta is None:
            raise RuntimeError('Model must specify AgendaMeta')
        result = getattr(meta, 'availability_model', None)
        if result is None:
            raise RuntimeError(
                'Model must specify AgendaMeta.availability_model')
        return result


class TimeSlotMeta(Meta):

    def __new__(mcs, name, bases, attrs):
        model = super().__new__(mcs, name, bases, attrs)
        meta = getattr(model, '_meta', None)
        if meta is None:
            raise RuntimeError('Model must derive from ModelBase')
        if not meta.abstract:
            related_name = 'time_slots'
            field_name = 'booking'
            booking_cls = TimeSlotMeta.get_booking_field(model)
            try:
                meta.get_field(field_name)
            except models.FieldDoesNotExist:
                model.add_to_class(
                    field_name, models.ForeignKey(
                        to=booking_cls, on_delete=models.CASCADE,
                        blank=True, null=True,
                        related_name=related_name))

        return model

    @staticmethod
    def get_booking_field(_model):
        return 'booking'

    @staticmethod
    def get_booking_model(model):
        meta = getattr(model, 'AgendaMeta', None)
        if meta is None:
            raise RuntimeError('Model must specify AgendaMeta')
        result = getattr(meta, 'booking_model', None)
        if result is None:
            raise RuntimeError(
                'Model must specify AgendaMeta.booking_model')
        return result


def get_free_times(schedule, start: datetime, end: datetime) -> List[TimeSpan]:
    aos = schedule.availability_occurrences.filter(
        end__gt=start, start__lt=end)
    spans = list(TimeSpan.merge_spans(
        (TimeSpan(ao.start, ao.end) for ao in aos)))

    if spans:
        busy_slots = list(schedule.time_slots.filter(
            busy=True, end__gt=start, start__lt=end).order_by('-start'))

        idx = 0
        while busy_slots:
            bs = busy_slots.pop()
            while idx < len(spans):
                span = spans[idx]
                if bs.end <= span.start:
                    break
                elif bs.end < span.end:
                    spans[idx] = TimeSpan(bs.end, span.end)
                    if bs.start > span.start:
                        spans.insert(idx, TimeSpan(span.start, bs.start))
                        idx += 1
                    break
                else:
                    if bs.start < span.end:
                        spans[idx] = TimeSpan(span.start, bs.start)
                    idx += 1
    return spans


class AbstractSchedule(models.Model):
    """
    A subclass you can use for the "schedule" model.

    Using this is entirely optional, but lets you use `get_free_times`
    as an instance method.
    """
    class Meta:
        abstract = True

    def get_free_times(self, start: datetime, end: datetime) -> List[TimeSpan]:
        return get_free_times(self, start, end)


# the actual base classes
class AbstractAvailability(models.Model, metaclass=Meta):
    """
    Represents a (possibly) recurring available time.

    These availabilities are used to generate time slots.
    """

    class Meta:
        verbose_name_plural = _('availabilities')
        abstract = True

    objects = models.Manager()

    start_date = models.DateField()  # type: date
    start_time = models.TimeField()  # type: datetime.time
    end_time = models.TimeField()  # type: datetime.time
    recurrence = RecurrenceField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    timezone = TimeZoneField()

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
        dt_start = datetime.combine(self.start_date, self.start_time)
        naive_start = django.utils.timezone.make_naive(
            span.start, span.start.tzinfo)
        naive_end = django.utils.timezone.make_naive(
            span.end, span.start.tzinfo)
        starts = self.recurrence.between(
            naive_start, naive_end, inc=True, dtstart=dt_start)
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
        ao_cls = self.occurrences.model
        params = {
            Meta.get_schedule_field(ao_cls): Meta.get_schedule(self)
        }
        # get all the original ones
        with transaction.atomic():
            all_slots = self.occurrences.all()
            # note, we can have multiple occurrences at the same start time
            occurrence_dict = {}
            for occurrence in all_slots:
                occurrence_dict[
                    (occurrence.start, occurrence.end)] = occurrence
            for r_start, r_end in self.get_recurrences(span):
                if (r_start, r_end) in occurrence_dict:
                    # yay we matched our occurrence, pop it
                    del occurrence_dict[(r_start, r_end)]
                else:
                    ao_cls.objects.create(
                        availability=self,
                        start=r_start,
                        end=r_end,
                        **params)
            # remaining occurrence_dict items need to die
            old_ids = (oc.id for oc in occurrence_dict.values())
            ao_cls.objects.filter(id__in=old_ids).delete()


class AbstractAvailabilityOccurrence(models.Model, metaclass=OccurrenceMeta):
    """
    A specific instance of an availability

    This data is an implementation detail and it's used to speed
    up and simplify the scheduling system by caching when a an
    availability recurs.

    An AbstractAvailabilityOccurrence has a start, end, and availability.
    The start and end should be in UTC
    """

    class Meta:
        verbose_name = _('availability occurrence')
        verbose_name_plural = _('availability occurrences')
        abstract = True

    objects = models.Manager()

    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(db_index=True)

    def __str__(self):
        return str(TimeSpan(self.start, self.end))


class AbstractTimeSlot(models.Model, AbstractTimeSpan, metaclass=TimeSlotMeta):
    """
    A segment of time that is scheduled.

    Time slots are non-recurring and their times are always stored in UTC.
    """

    class Meta:
        verbose_name_plural = "time slots"
        abstract = True

    objects = models.Manager()

    start = models.DateTimeField(db_index=True)  # type: datetime
    end = models.DateTimeField(db_index=True)  # type: datetime
    busy = models.BooleanField(default=False, db_index=True)

    padding_for = models.ForeignKey(
        'TimeSlot', blank=True, null=True, on_delete=models.CASCADE,
        related_name='padded_by')

    def __str__(self):
        return 'TimeSlot object ({}:{})'.format(
            self.id, AbstractTimeSpan.__str__(self))


class AbstractBooking(models.Model, metaclass=Meta):

    class Meta:
        abstract = True

    busy_message = _('Requested time {start}–{end} is busy')
    un_free_message = _('Requested time {start}–{end} is not available')

    def get_reserved_spans(self) -> List[TimeSpan]:
        """
        Return a list of times that should be reserved
        """
        raise NotImplementedError

    def time_slot_diff(self):
        """
        Return the difference between the existing time slots and the ones
        suggested by the current times & state.

        Only returns changed time slots.

        :returns: Tuple of a list of new time spans and a list of old
            time slots
        """
        slot_times = dict()
        add_times = []
        padding = self._get_padding()
        # add all the slots to slot_times
        if self.pk is not None:
            for slot in self.time_slots.all():
                slot_times[(slot.start, slot.end)] = slot
        # make a diff out of slot_times
        for start, end in self.get_reserved_spans():
            start_utc = start.astimezone(pytz.utc)
            end_utc = end.astimezone(pytz.utc)
            if (start_utc, end_utc) in slot_times.keys():
                del slot_times[(start_utc, end_utc)]
            else:
                add_times.append(PaddedTimeSpan(start_utc, end_utc, padding))

        return add_times, list(slot_times.values())

    def clean(self):
        spans = [TimeSpan(x.start, x.end)
                 for x in self.get_reserved_spans()]
        spans = TimeSpan.merge_spans(spans)

        ts_cls = self.time_slots.model
        schedule = Meta.get_schedule(self)
        ao_cls = schedule.availability_occurrences.model

        for span in spans:
            # make sure there is available time
            if not self._book_unscheduled():
                params = {
                    Meta.get_schedule_field(ao_cls):
                        getattr(self, Meta.get_schedule_field(self))}
                free_times = ao_cls.objects.filter(
                    start__lt=span.end, end__gt=span.start, **params)
                free_spans = TimeSpan.merge_spans(
                    (TimeSpan(ao.start, ao.end) for ao in free_times))
                # the time should be free iff there is one merged span
                # and it goes the whole time
                if not (len(free_spans) == 1 and
                        free_spans[0].start <= span.start and
                        free_spans[0].end >= span.end):
                    raise ValidationError(
                        self.un_free_message.format(
                            start=span.start, end=span.end))

                # make sure it's not busy already
            if not self._book_busy():
                params = {
                    Meta.get_schedule_field(ts_cls):
                        getattr(self, Meta.get_schedule_field(self))}
                # exclude slots from my own booking
                booking_field = TimeSlotMeta.get_booking_field(ts_cls)
                busy_q = ts_cls.objects.filter(
                    start__lt=span.end, end__gt=span.start,
                    busy=True, **params)
                if self.id is not None:
                    ex_q = models.Q(**{booking_field: self}) | \
                        models.Q(**{'padding_for__{}'.format(
                            booking_field): self})
                    busy_q = busy_q.exclude(ex_q)
                if busy_q.exists():
                    raise ValidationError(
                        self.busy_message.format(
                            start=span.start, end=span.end))

    def save(self, *args, **kwargs):
        # reserve slots if necessary
        add_times, rm_slots = self.time_slot_diff()
        padding = self._get_padding()
        ts_cls = self.time_slots.model
        ts_params = {
            Meta.get_schedule_field(ts_cls): Meta.get_schedule(self)
        }

        with transaction.atomic():
            # clear slots in case that means we can book again
            # this is important for rescheduling, especially with lots
            # of padding
            ts_cls.objects.filter(id__in=(s.id for s in rm_slots)).delete()

            # save this record
            super().save(*args, **kwargs)
            # add in new slots
            padded_slots = []
            for span in add_times:
                new_slot = ts_cls.objects.create(
                    booking=self,
                    start=span.start,
                    end=span.end,
                    busy=self._is_booked_slot_busy(),
                    **ts_params)
                if padding:
                    padded_slots.append(ts_cls(
                        start=span.padded_start,
                        end=span.start,
                        busy=True,
                        padding_for=new_slot,
                        **ts_params))
                    padded_slots.append(ts_cls(
                        start=span.end,
                        end=span.padded_end,
                        busy=True,
                        padding_for=new_slot,
                        **ts_params))
            ts_cls.objects.bulk_create(padded_slots)
        # end transaction

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
        padding_length = self._get_padding()
        ts_cls = self.time_slots.model
        ts_params = {
            Meta.get_schedule_field(ts_cls): Meta.get_schedule(self)
        }

        with transaction.atomic():
            for slot in self.time_slots.all():
                # delete any existing padding
                slot.padded_by.all().delete()

                # add new padding
                if padding_length:
                    ts_cls.objects.create(
                        start=slot.start - padding_length,
                        end=slot.start,
                        busy=True,
                        padding_for=slot,
                        **ts_params)
                    ts_cls.objects.create(
                        start=slot.end,
                        end=slot.end + padding_length,
                        busy=True,
                        padding_for=slot,
                        **ts_params)

    def _is_booked_slot_busy(self):
        """
        If a slot is booked, determine whether it can be booked again.
        """
        return True

    def _book_busy(self):
        """
        If this returns true, bookings will be able to overlap busy slots.
        """
        return False

    def _book_unscheduled(self):
        """
        If this returns true, bookings will automatically create slots in
        unscheduled space.
        """
        return False
