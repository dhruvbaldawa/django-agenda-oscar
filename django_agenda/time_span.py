from datetime import datetime, timedelta
from typing import List

from django.conf import settings
from django.utils.dateformat import DateFormat, TimeFormat

__all__ = ['AbstractTimeSpan', 'TimeSpan', 'PaddedTimeSpan']


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

    @staticmethod
    def merge_spans(spans: List[AbstractTimeSpan]) -> 'List[TimeSpan]':
        """
        Return a list that has any overlapping spans joined
        """
        result = []
        it_sort = iter(sorted(spans, key=lambda x: x.start))
        try:
            first = next(it_sort)
        except StopIteration:
            return result
        last_start = first.start
        last_end = first.end
        for span in it_sort:
            if span.start > last_end:
                result.append(TimeSpan(last_start, last_end))
                last_start = span.start
            last_end = span.end
        result.append(TimeSpan(last_start, last_end))
        return result

    def __eq__(self, other: 'TimeSpan'):
        return self.start == other.start and self.end == other.end


class PaddedTimeSpan(TimeSpan):

    def __init__(self, start: datetime, end: datetime, padding: timedelta):
        super().__init__(start, end)
        self.padded_start = self.start - padding
        self.padded_end = self.end + padding
