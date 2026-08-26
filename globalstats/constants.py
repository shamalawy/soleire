"""Domain vocabulary for Irish domestic PV.

Single source of truth: the models, forms, seed command and statistics layer all
import from here. Previously these lists were duplicated between `models.py` and
`management/commands/generate_data.py` and had already drifted ("Waterfor" vs
"Waterford"), which silently split one county into two buckets.
"""

from django.db import models


class Month(models.IntegerChoices):
    """Calendar months stored as 1–12.

    Stored as integers rather than names so that ORDER BY and range filters are
    chronological. Sorting the old CharField put April before January.
    """

    JANUARY = 1, "January"
    FEBRUARY = 2, "February"
    MARCH = 3, "March"
    APRIL = 4, "April"
    MAY = 5, "May"
    JUNE = 6, "June"
    JULY = 7, "July"
    AUGUST = 8, "August"
    SEPTEMBER = 9, "September"
    OCTOBER = 10, "October"
    NOVEMBER = 11, "November"
    DECEMBER = 12, "December"


MONTH_ABBREVIATIONS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


class Season(models.TextChoices):
    """Meteorological seasons — the natural grouping for PV output in Ireland."""

    WINTER = "winter", "Winter (Dec–Feb)"
    SPRING = "spring", "Spring (Mar–May)"
    SUMMER = "summer", "Summer (Jun–Aug)"
    AUTUMN = "autumn", "Autumn (Sep–Nov)"


MONTH_TO_SEASON = {
    12: Season.WINTER,
    1: Season.WINTER,
    2: Season.WINTER,
    3: Season.SPRING,
    4: Season.SPRING,
    5: Season.SPRING,
    6: Season.SUMMER,
    7: Season.SUMMER,
    8: Season.SUMMER,
    9: Season.AUTUMN,
    10: Season.AUTUMN,
    11: Season.AUTUMN,
}


class Province(models.TextChoices):
    LEINSTER = "leinster", "Leinster"
    MUNSTER = "munster", "Munster"
    CONNACHT = "connacht", "Connacht"
    ULSTER = "ulster", "Ulster"


# Counties of the island of Ireland. Grouped choices render as <optgroup>s.
# The 26 southern counties come first because that is where the existing data
# sits; the six northern counties are included because "solar generation in
# Ireland" reasonably covers the whole island. Removing that second group is a
# one-line change if the community decides otherwise.
REPUBLIC_COUNTIES = [
    "Carlow",
    "Cavan",
    "Clare",
    "Cork",
    "Donegal",
    "Dublin",
    "Galway",
    "Kerry",
    "Kildare",
    "Kilkenny",
    "Laois",
    "Leitrim",
    "Limerick",
    "Longford",
    "Louth",
    "Mayo",
    "Meath",
    "Monaghan",
    "Offaly",
    "Roscommon",
    "Sligo",
    "Tipperary",
    "Waterford",
    "Westmeath",
    "Wexford",
    "Wicklow",
]

NORTHERN_COUNTIES = [
    "Antrim",
    "Armagh",
    "Down",
    "Fermanagh",
    "Londonderry",
    "Tyrone",
]

ALL_COUNTIES = REPUBLIC_COUNTIES + NORTHERN_COUNTIES

COUNTY_CHOICES = [
    ("Republic of Ireland", [(c, c) for c in REPUBLIC_COUNTIES]),
    ("Northern Ireland", [(c, c) for c in NORTHERN_COUNTIES]),
]

COUNTY_TO_PROVINCE = {
    # Leinster
    "Carlow": Province.LEINSTER,
    "Dublin": Province.LEINSTER,
    "Kildare": Province.LEINSTER,
    "Kilkenny": Province.LEINSTER,
    "Laois": Province.LEINSTER,
    "Longford": Province.LEINSTER,
    "Louth": Province.LEINSTER,
    "Meath": Province.LEINSTER,
    "Offaly": Province.LEINSTER,
    "Westmeath": Province.LEINSTER,
    "Wexford": Province.LEINSTER,
    "Wicklow": Province.LEINSTER,
    # Munster
    "Clare": Province.MUNSTER,
    "Cork": Province.MUNSTER,
    "Kerry": Province.MUNSTER,
    "Limerick": Province.MUNSTER,
    "Tipperary": Province.MUNSTER,
    "Waterford": Province.MUNSTER,
    # Connacht
    "Galway": Province.CONNACHT,
    "Leitrim": Province.CONNACHT,
    "Mayo": Province.CONNACHT,
    "Roscommon": Province.CONNACHT,
    "Sligo": Province.CONNACHT,
    # Ulster (all nine, north and south of the border)
    "Cavan": Province.ULSTER,
    "Donegal": Province.ULSTER,
    "Monaghan": Province.ULSTER,
    "Antrim": Province.ULSTER,
    "Armagh": Province.ULSTER,
    "Down": Province.ULSTER,
    "Fermanagh": Province.ULSTER,
    "Londonderry": Province.ULSTER,
    "Tyrone": Province.ULSTER,
}

# Legacy spellings seen in the pre-existing data, mapped to the canonical name.
# Used by the data migration and by the form so old bookmarks keep working.
COUNTY_ALIASES = {
    "Waterfor": "Waterford",
    "Derry": "Londonderry",
}


class Orientation(models.TextChoices):
    """Compass direction(s) the array faces.

    Ordered roughly best-to-worst for the northern hemisphere so the form's
    dropdown leads with the common cases.
    """

    SOUTH = "S", "South"
    SOUTH_EAST = "SE", "South-East"
    SOUTH_WEST = "SW", "South-West"
    EAST_WEST = "EW", "East–West (split array)"
    EAST = "E", "East"
    WEST = "W", "West"
    SOUTH_EAST_WEST = "SEW", "South + East + West"
    NORTH_SOUTH = "NS", "North–South (split array)"
    FLAT = "FLAT", "Flat / horizontal"
    NORTH_EAST = "NE", "North-East"
    NORTH_WEST = "NW", "North-West"
    NORTH = "N", "North"
    OTHER = "OTHER", "Other / mixed"


# The old free-form values ("S/W", "E/N/W", ...) mapped onto the codes above.
# Anything unmapped becomes OTHER rather than being dropped.
ORIENTATION_ALIASES = {
    "N": Orientation.NORTH,
    "E": Orientation.EAST,
    "S": Orientation.SOUTH,
    "W": Orientation.WEST,
    "N/E": Orientation.NORTH_EAST,
    "N/W": Orientation.NORTH_WEST,
    "S/E": Orientation.SOUTH_EAST,
    "S/W": Orientation.SOUTH_WEST,
    "E/W": Orientation.EAST_WEST,
    "N/S": Orientation.NORTH_SOUTH,
    "E/S/W": Orientation.SOUTH_EAST_WEST,
    "FLAT": Orientation.FLAT,
    "N/E/S": Orientation.OTHER,
    "N/W/S": Orientation.OTHER,
    "E/N/W": Orientation.OTHER,
}


# Buckets used for "how does my system size compare" charts. Upper bound is
# exclusive; the last band is open-ended.
SYSTEM_SIZE_BANDS = [
    ("Under 2 kWp", None, 2),
    ("2–4 kWp", 2, 4),
    ("4–6 kWp", 4, 6),
    ("6–8 kWp", 6, 8),
    ("8–12 kWp", 8, 12),
    ("12 kWp and over", 12, None),
]

# Earliest year the site accepts a reading for. Domestic PV in Ireland is
# essentially a post-2010 phenomenon, and the SEAI grant scheme began in 2018.
FIRST_DATA_YEAR = 2010

# Plausibility envelope for a monthly specific yield in Ireland, kWh per kWp.
# Ireland receives roughly 800–1,100 kWh/kWp/year; no single month should
# exceed ~200. Values outside this are almost always unit mix-ups (Wh vs kWh)
# or a mistyped array size, so the form warns and the statistics exclude them.
MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD = 250
