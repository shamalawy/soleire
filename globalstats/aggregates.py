"""PostgreSQL ordered-set aggregates that Django does not ship.

Medians and quartiles matter here: a handful of mistyped readings will drag a
mean specific yield badly off, while the median barely moves. Switching the
database to PostgreSQL is what makes these available.
"""

from django.db.models import Aggregate, FloatField


class PercentileCont(Aggregate):
    """``percentile_cont(p) WITHIN GROUP (ORDER BY expr)`` — interpolated percentile."""

    function = "PERCENTILE_CONT"
    name = "percentilecont"
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, percentile=0.5, **extra):
        if not 0 <= percentile <= 1:
            raise ValueError(f"percentile must be between 0 and 1, got {percentile!r}")
        super().__init__(expression, percentile=percentile, **extra)


def Median(expression, **extra):  # Capitalised: it reads as an aggregate class at call sites.
    return PercentileCont(expression, percentile=0.5, **extra)
