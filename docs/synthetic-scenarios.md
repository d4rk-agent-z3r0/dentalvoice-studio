# Synthetic Scenarios

The demo world is defined in one file: `backend/app/demo/catalog.py`. It is the source of truth;
this page summarises it. Load it with `make seed` (idempotent; publishes 28 days of slots).

Everything is invented: clinic names, dentists, callers, every line they speak, and every contact
value (RFC 2606 `example.*` domains and `555-01xx` numbers, enforced by database CHECK
constraints). No real person, practice or recording is represented.

## Clinics

| Clinic | Slug | Timezone | Dentists | Scenarios |
|---|---|---|---|---|
| BrightSmile Dental Studio | `brightsmile` | Europe/London | Dr. Mira Calloway, Dr. Tomas Reyland | A–E |
| Juniper & Vale Dental | `juniper-vale` | America/New_York | Dr. Anika Rourke, Dr. Samuel Whitlow | A |

Both timezones observe daylight saving, so booking tests cover offset changes. The second clinic
exists so that tenant-isolation tests have real data on both sides.

## BrightSmile scenarios

| Code | Persona | Objective | Final state | What it proves |
|---|---|---|---|---|
| A | Ava Lindqvist, new | Routine cleaning | `COMPLETED` | Happy path: all ten fields captured, spoken email normalised |
| B | Marcus Bellweather, returning | Follow-up visit | `COMPLETED` | Existing patient matched by contact value (seeded as a registered patient) |
| C | Elena Fairbanks, new | Check-up | `COMPLETED` | Corrections: email fixed, date changed from Monday to Wednesday during review; history kept |
| D | Jordan Okonkwo-Hale, new | Check-up | `ABANDONED` | Missing date, time and email are never guessed; the call ends honestly |
| E | Noah Brightwater, returning | — | `ESCALATED` | Urgent symptoms stop routine intake; no clinical advice is given |

Each scenario in the catalogue carries the persona, objective, ordered caller clips (with the
transcript the synthetic audio is generated from), the expected state transitions, the expected
extracted fields, missing and corrected fields, and the expected final state. The expectation is
stored with the scenario (`synthetic_scenarios.expected`) and is what the Milestone 3 acceptance
tests assert against.

Relative dates (`next:tuesday`) are resolved against the call date in the clinic's timezone, so
the fixtures never go stale.

## Tests

| Test | What it checks |
|---|---|
| `tests/unit/test_catalog.py` | Unique clip IDs and codes; contact values reserved and canonical; fields consistent with personas; requested services exist; no routable email or phone anywhere in the catalogue; slot generation across a DST change |
| `tests/integration/test_seed.py` | Seed loads everything, a second run changes nothing; scenarios round-trip through the service; returning personas have patient records; slots land in clinic-local hours |
