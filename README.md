# soleire

**Solar statistics for Ireland, contributed anonymously by the people who own the panels.**

Members of the community file their monthly generation figures. The site turns
those into county league tables, seasonality curves, orientation comparisons and
personal benchmarking — without ever publishing anything that identifies a
household.

---

## Quick start

Requires Docker with the Compose plugin. Nothing else — no local Python, no
local PostgreSQL.

```bash
make init     # writes .env with freshly generated secrets
make up       # builds the images and starts Postgres + the web app
make seed     # optional: fill the database with plausible demo data
```

Then open <http://localhost:8000>. Change `WEB_PORT` in `.env` if 8000 is taken.

```bash
make superuser   # create an admin account
make test        # run the suite
make down        # stop, keeping the database
make clean       # stop and delete the database volume
make help        # every other task
```

## Running it for real

`docker-compose.override.yml` layers development conveniences (bind mount, live
reload, `runserver`) on top and is applied automatically. To run the
production-shaped stack — gunicorn, no bind mount, hashed static assets served
by WhiteNoise:

```bash
make prod            # docker compose -f docker-compose.yml up --build -d
```

Before exposing it publicly, in `.env`:

| Setting | Change it to |
| --- | --- |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | a fresh 64-character random string, never reused |
| `DJANGO_ALLOWED_HOSTS` | your real hostname(s) — not `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://your-host` |
| `DJANGO_BEHIND_PROXY` | `true` if a reverse proxy terminates TLS |
| `POSTGRES_PASSWORD` | something you generated |

There is no password-reset flow to configure, and that is deliberate — see
[Anonymity](#anonymity).

`make check` runs Django's deployment checklist and should report no issues.

Two things that catch people out when testing production mode locally:

- With `DJANGO_DEBUG=false` the session cookie is `Secure`-only, so signing in
  over plain HTTP silently fails. Set `DJANGO_SECURE_COOKIES=false` for a local
  smoke test.
- A shell variable does **not** override a value in `.env`, because `.env` is
  loaded as `env_file`. Edit `.env`, or pass `-e` to `docker compose run`.

## Configuration

Everything comes from the environment; `.env.example` documents every variable.
Nothing security-relevant has an insecure fallback — with `DJANGO_DEBUG=false`
and no `DJANGO_SECRET_KEY`, the app refuses to start rather than running on a
default key.

The two that shape the statistics:

- **`SOLEIRE_MIN_GROUP_SIZE`** (default `3`) — the privacy floor. A county,
  orientation or size band is published only once that many distinct systems,
  owned by that many distinct contributors, have reported into it. Raising it
  hardens anonymity and hides more of the long tail.
- **`SOLEIRE_STATS_CACHE_SECONDS`** (default `300`) — how long the public
  aggregates are memoised. `0` disables caching.

The cache lives in PostgreSQL, not in each worker's memory. Local memory is the
Django default and is wrong here: gunicorn runs several workers, so each would
hold a private copy, two visitors could see different figures, and no process
could invalidate another's entries. The TTL is only a backstop in any case —
saving a reading bumps a version namespace that retires every cached aggregate
at once (`globalstats/signals.py`), so a contributor never sees numbers that
predate their own submission. Set `DJANGO_CACHE_URL=redis://…` for a larger
deployment.

`DATABASE_URL` is honoured and takes precedence over the discrete `POSTGRES_*`
variables, for platforms that inject one. Only `postgres://` URLs are accepted:
silently falling back to SQLite would hide the misconfiguration until the first
PostgreSQL-specific query failed.

Set `POSTGRES_SCHEMA` to keep the tables in a named schema instead of `public`.
The entrypoint runs `manage.py ensure_schema` first, because `migrate` cannot
create the schema its own `search_path` already points at.

## How the statistics work

**Specific yield — kWh generated per kWp installed — is the headline metric.**
Raw kWh totals mostly measure how many people from a county happened to sign up.
Yield is the only figure that puts a 2 kWp Galway bungalow and a 12 kWp Wicklow
barn on the same footing.

Two units appear, and the distinction matters:

- **kWh/kWp per month** — most tables. Total energy over total capacity across
  the selected months, so each system counts in proportion to its size.
- **kWh/kWp per year** — computed only from systems that filed all twelve
  months of a year. Never a monthly average multiplied by twelve, which would
  badly flatter anyone who only recorded the summer.

Alongside the mean, medians and quartiles come from PostgreSQL's
`percentile_cont` (see `globalstats/aggregates.py`). Where mean and median
diverge, a few unusual systems are pulling the average and the median is the
more honest number.

Readings implying more than 250 kWh/kWp in a single month are excluded from
every aggregate — physically impossible in Ireland, and almost always watt-hours
entered as kilowatt-hours. They stay in the contributor's own records, and the
About page publishes how many were excluded.

### What the site publishes

| Page | Question it answers |
| --- | --- |
| `/` | What does Irish solar actually produce? |
| `/stats/counties/` | Which counties yield most per kWp, by month or year |
| `/stats/trends/` | Seasonality, and whether one year genuinely beat another |
| `/stats/systems/` | Does orientation, array size or a battery change yield? |
| `/me/systems/<id>/benchmark/` | How does my roof compare with my county? |
| `/about/` | Methodology, privacy stance, data-quality report |

Aggregates are downloadable as CSV (`/data/counties.csv`, `/data/monthly.csv`)
and JSON (`/api/stats/<dataset>/` — `summary`, `annual`, `counties`,
`provinces`, `monthly`, `year-on-year`, `orientation`, `size-bands`, `battery`,
`seasons`, `annual-counties`). Suppression is applied before anything leaves the
database, so the exports carry exactly what the pages show.

## Anonymity

An account exists for one reason: so a contributor can correct or delete their
own figures, and so one person cannot stuff the dataset. It is built to hold
nothing about the person.

**Contributors do not choose a username.** Given a username box people type a
name they already use somewhere else, and that one field would tie a household
to its electricity profile. The site issues a handle instead — two words and
four digits, like `bright-heron-4712`, drawn with `secrets` from curated word
lists (39 million combinations) and derived from nothing about the person. The
handle is held in the session and supplied by the server at save time; the
read-only input in the form exists only so browser password managers store it,
and whatever is posted back is discarded. **There is no email field anywhere.**

Passwords are hashed with **Argon2id** (`argon2-cffi`, first in
`PASSWORD_HASHERS`), at Django's defaults of 100 MB memory cost, time cost 2,
parallelism 8. Registration will not complete until the contributor ticks a box
confirming they have saved their handle and password, because there is no
recovery path: no email address, no reset, no support route. That is stated on
the registration form, on a dedicated page shown immediately after sign-up, and
on the sign-in page.

Contributors can export everything they have given, or delete the account and
every reading with it, from their own dashboard.

Enforced in code:

- Public aggregates are suppressed below `SOLEIRE_MIN_GROUP_SIZE`, counting
  **distinct contributors as well as distinct systems** — three arrays on one
  roof are still one household and do not unlock a county.
- Suppressed buckets are shown as withheld rather than omitted, so the reader
  can see that data exists but is being protected.
- The national headline is suppressed on the same threshold as everything else.
  With two contributors, publishing a national total would hand each of them the
  other's output by subtraction while every county row sat dutifully hidden.
  Participation counts stay visible — knowing four people have signed up
  identifies nobody.
- No public page, export or API response contains a handle, a system id, or
  anything finer-grained than a county. There is a test that asserts exactly
  this against every public endpoint.
- The admin lists systems by an opaque `PV-000123` reference. It does not show
  or search usernames, and only a superuser can see which account owns a system.

Stated plainly on the About page and repeated here: threshold suppression
defeats casual re-identification. It is not a formal privacy guarantee, and
someone diffing snapshots of the site as contributors join could narrow things
down.

## Layout

```
soleir/                    project configuration
  settings.py              environment-driven; fails loudly, never insecurely
  env.py                   dependency-free typed env readers + DATABASE_URL parser
globalstats/
  constants.py             counties, provinces, months, orientations — one source of truth
  identifiers.py           generation of anonymous account handles
  models.py                PVSystem + MonthlyGeneration
  stats.py                 every aggregation, with the anonymity rules applied
  signals.py               retires cached aggregates whenever data changes
  aggregates.py            PostgreSQL percentile_cont wrapper
  forms.py                 contribution forms and query-string validation
  views.py                 public statistics + the contributor area
  admin.py                 deliberately identity-light
  management/commands/     wait_for_db, ensure_schema, seed_demo_data
  tests/                   169 tests
templates/                 base layout, partials, statistics, accounts, contribute
static/                    stylesheet and dependency-free SVG charts
docker/entrypoint.sh       wait for db → ensure schema → migrate → exec
```

## Notes on the data model

The original schema stored county, orientation and both size fields on every
monthly row, so one household could be in Cork in January and Dublin in
February, and "kWh per kWp" had no single answer. Installation facts now live on
`PVSystem` and only the reading lives on `MonthlyGeneration`. A contributor can
register more than one system, which the single-table design could not express.

Month is a small integer rather than a month name, so ordering and range filters
are chronological. Sorting the old `CharField` gave April, August, December,
February.

Migrations `0008`–`0010` are a create / copy / drop sequence: `0009` copies
every legacy row across — repairing the `"Waterfor"` county typo, mapping the
old free-form orientations onto the new codes, and grouping each user's distinct
configurations into separate systems — and only then does `0010` drop the old
table. The whole sequence is reversible; rolling back to `0007` reconstructs the
original rows.

```bash
make migrate                                     # apply everything
docker compose run --rm web python manage.py migrate globalstats 0009   # stop and verify first
```

## Demo data

```bash
make seed
docker compose run --rm web python manage.py seed_demo_data \
    --systems 500 --years 5 --clear --seed 42
```

Models Irish irradiance properly — roughly 870 kWh/kWp a year, with a June peak
around eight times the December floor — and weights counties by population so
the suppression rules actually get exercised: Dublin and Cork publish, Leitrim
does not.

Demo accounts are created with **unusable passwords**, so none of them can sign
in. The command refuses to run when `DJANGO_DEBUG` is false unless
`DJANGO_ALLOW_DEMO_SEED=true` is set explicitly.

## Development

```bash
make test        # 169 tests
make coverage    # with a coverage report
make lint        # ruff check + format --check
make format      # apply fixes
make check       # Django deployment checklist
make ci          # all of the above, as CI runs it
```

CI (`.github/workflows/ci.yml`) runs the suite against a real PostgreSQL 17
service, checks for missing migrations, runs the deployment checklist, and
separately builds the production image and asserts it boots.

The dev container runs as your host uid/gid so files it writes into the bind
mount stay yours. If yours are not 1000, set `DOCKER_UID` / `DOCKER_GID` in
`.env` (`id -u`, `id -g`).

Charts are hand-rolled SVG in `static/js/charts.js` rather than a CDN script:
a site premised on not tracking its contributors should not hand every visitor's
IP to a third party, and the container should work without outbound internet
access. Chart data reaches the page through Django's `json_script` filter, so
nothing is interpolated into executable JavaScript. Every chart sits beside a
real `<table>` carrying the same numbers, which is the accessible representation.
