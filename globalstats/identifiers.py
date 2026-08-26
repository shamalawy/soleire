"""Generation of anonymous account handles.

Contributors do not choose their own username. People reach for something they
already use — a real name, a work handle, an email local-part — and that one
field would undo the point of an anonymous dataset. The site issues a handle
instead, and never asks for anything else.

The alphabet is deliberately word-based rather than random characters: the
handle has to survive being written on paper and typed back months later, and
`bright-heron-4712` does that far better than `k7M2q9Xz`. Nothing in either
word list is a personal name, a place, or a word that could pair into something
unpleasant.
"""

import secrets

from django.contrib.auth.models import User

ADJECTIVES = (
    "amber",
    "azure",
    "balmy",
    "brave",
    "breezy",
    "bright",
    "brisk",
    "calm",
    "clear",
    "coastal",
    "copper",
    "crisp",
    "dawn",
    "drifting",
    "dusky",
    "eager",
    "early",
    "emerald",
    "fair",
    "fleet",
    "gentle",
    "gilded",
    "glad",
    "gleaming",
    "golden",
    "hardy",
    "hazel",
    "hidden",
    "high",
    "hushed",
    "idle",
    "keen",
    "kindly",
    "lively",
    "lofty",
    "lucid",
    "mellow",
    "mild",
    "misty",
    "noble",
    "nimble",
    "northern",
    "open",
    "patient",
    "placid",
    "quiet",
    "radiant",
    "restful",
    "rising",
    "rugged",
    "russet",
    "sandy",
    "shining",
    "silver",
    "sunlit",
    "steady",
    "still",
    "sunny",
    "tidal",
    "tranquil",
    "upland",
    "vivid",
    "warm",
    "westerly",
    "willing",
    "windswept",
)

NOUNS = (
    "alder",
    "ash",
    "aster",
    "badger",
    "beacon",
    "beech",
    "birch",
    "bracken",
    "bramble",
    "breeze",
    "brook",
    "cedar",
    "clover",
    "cove",
    "crest",
    "curlew",
    "daisy",
    "dipper",
    "dune",
    "eddy",
    "elder",
    "estuary",
    "fern",
    "field",
    "finch",
    "fjord",
    "furze",
    "gale",
    "glen",
    "gorse",
    "hare",
    "harbour",
    "hawthorn",
    "heather",
    "heron",
    "hillside",
    "holly",
    "inlet",
    "island",
    "kestrel",
    "lantern",
    "lapwing",
    "lark",
    "ledge",
    "linnet",
    "meadow",
    "moorland",
    "orchard",
    "otter",
    "panel",
    "pasture",
    "pine",
    "plover",
    "puffin",
    "quarry",
    "rowan",
    "sedge",
    "shore",
    "sorrel",
    "spruce",
    "stream",
    "thistle",
    "thrush",
    "tide",
    "valley",
    "willow",
)

# 66 x 66 x 9000 ≈ 39 million handles. Uniqueness is still checked against the
# database — the point of the number is that a handle cannot be guessed, not
# that collisions are impossible.
SUFFIX_LOW = 1000
SUFFIX_HIGH = 9999

MAX_ATTEMPTS = 12


class UsernameGenerationError(RuntimeError):
    """Raised when no free handle turned up, which should never happen."""


def build_username():
    """One candidate handle. Uses `secrets`, not `random`: a predictable handle
    would let someone enumerate contributors."""
    adjective = secrets.choice(ADJECTIVES)
    noun = secrets.choice(NOUNS)
    suffix = secrets.randbelow(SUFFIX_HIGH - SUFFIX_LOW + 1) + SUFFIX_LOW
    return f"{adjective}-{noun}-{suffix}"


def generate_username(attempts=MAX_ATTEMPTS):
    """A handle that is not already taken."""
    for _ in range(attempts):
        candidate = build_username()
        if not User.objects.filter(username=candidate).exists():
            return candidate
    raise UsernameGenerationError(f"Could not find an unused handle in {attempts} attempts.")
