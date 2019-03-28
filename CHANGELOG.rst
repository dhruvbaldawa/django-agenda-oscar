CHANGES
=======

0.6.3
-----

* Add `django_agenda.version`, drop pbr

0.6.2
-----

* add a related name for the bookings relation

0.6.1
-----

* Bug fix for case where foreign key wasn't called schedule

0.6.0
-----

A major rewrite & simplification. This version works *very* differently
from 0.5, don't expect to migrate easily.

* Time slots are now primarily for marking busy state, and
  availability occurrences are for free times.
* You have to create your own models, subclassing the abstract
  models in django_agenda.models. The good thing about this is
  that this allows us to use real foreign keys instead of
  generic ones.
* To that end, you'll have to migrate the data into your models.
  Django Agenda won't delete any of it's own models, but you'll
  have to migrate the data into the new models that you make.
* Booking validation is now done in AbstractBooking.clean
  instead of AbstractBooking.save. Make sure you call full_clean!
* You can use django_agenda.models.get_free_times to find all the
  free time spans in a particular space of time.

0.5.4
-----

* Add the ability to overlap busy slots

0.5.3
-----

* Add ability to overlap bookings

0.5.2
-----

* Add support for django 2

0.5.1
----`-

* Fix bug if the start/end time weren't in the same zone as the availability

0.5.0
-----

* Fix handling of daylight savings

0.4.0–0.4.9
-----------

* Small improvements to the regen method
* Fix problem where `_padding_changed` would crash with big changes
* Improve error messaging
* Fix issue where slots were being skipped during regeneration
* Update config so it works more naturally
* Fix issue where `_padding_changed` would alter same slot multiple times
* Add a method to handle non-static padding values
* Fix problem with app config, and gitlab ci
* Fix bug making overlapping slots when a booking spanned existing slots
* Add support for disallowing duplicate bookings
* Fix instruction formatting in readme
* Rewrite scheduling logic
* Add a reasonable number of tests
