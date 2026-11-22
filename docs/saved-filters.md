# Saved filters on the Accounts list

*Built for ADR 0042, step BR-pre (2026-11-21). Batch research (BR1 onward) starts from a saved filter or from
ticked rows, so saved filters come first. They are useful on their own.*

## What it is, in plain words

On the Accounts page you can already narrow the list (search text, status, segment, country, lifecycle stage).
A **saved filter** remembers one such combination under a name, for example "Hyderabad enterprise". Choosing it
later applies the same conditions again in one click.

A saved filter stores **only the conditions**, never a list of accounts. Applying it is exactly the same as typing
the conditions on the list, so the usual rules still decide what you see: you only ever get the accounts you are
allowed to read.

## Who can do what

| | Sales agent | Sales manager / tenant admin |
|---|---|---|
| Save a filter for themselves | yes | yes |
| See their own filters | yes | yes |
| See filters shared by the organisation | yes | yes |
| Share a filter with the organisation | no | yes (managers and administrators) |
| Rename, change or delete their own | yes | yes |
| Change someone else's shared filter | no | no |
| Stop sharing or delete someone else's **shared** filter | no | tenant administrators only |

A private filter belongs to its owner alone: for everybody else it does not exist (the API answers "not found",
also to an administrator). People who may not read accounts (for example portal customers) get a refusal.

Limits: 50 saved filters per person, 50 shared per organisation. Names are unique per person (capitals ignored)
and a shared name is unique across the organisation.

## On screen

*Accounts* page, under the filter form:

- the **saved filters** as small buttons; the one that matches what you are looking at is highlighted;
- **Save this filter**, shown only when the list has at least one condition and it is not already saved
  (a dialog asks for a name; managers also see "Share with everyone in my organisation");
- **Delete** next to your own filters (after a confirmation). Nothing else is changed by deleting.

Filters are shown as plain text; a name can never act as a link or markup. "(shared)" marks your own shared
filters, "(team)" a colleague's shared filter, "(partly shown)" a filter that holds a condition this screen has no
box for (for example one made by another tool); that condition is still stored but not part of the address.

## What a filter may hold (API)

`POST /api/v1/saved-filters` takes a name, `params` and `shared`. The server accepts only these conditions, with
the same values the list endpoint accepts: `q`, `status`, `segment`, `lifecycle_stage`, `account_type`,
`industry`, `country`, `owner_id`, `min_value` together with `value_currency`. It refuses anything else - in
particular `archived`, `limit`, `offset`, a tenant id or any made-up key - so a saved filter can never widen a
list, page it or reach another organisation. The owner, the organisation and the record type come from the
signed-in person, never from the request.

Endpoints (all need permission to read accounts): `GET /saved-filters`, `POST /saved-filters`,
`GET /saved-filters/{id}`, `PATCH /saved-filters/{id}` (with the `version` you saw: a stale one is a 409),
`DELETE /saved-filters/{id}`.

## For other modules

`app/modules/saved_filters/api.py` offers `filter_params(session, principal, filter_id)`: the parameters of a
filter the person may use, else "not found". Batch research (ADR 0042) resolves a saved filter through it, then
runs the normal account search as the person.

## Storage and audit

One table, `saved_filters` (migration 0074): tenant-owned, row-level security enabled and forced, a check that
the record type is `account` and that the name is 1-80 characters, unique names as above. Visibility (own or shared)
is applied in the SQL of every query. Creating, changing and deleting a filter is written to the audit log with the
kind of change and the names of the conditions - never the values.

## Tests

- Pure rules: `backend/tests/test_saved_filter_rules.py` (34 tests).
- API with the real database: `backend/tests/db/test_saved_filters_api.py` (26 tests: roles, sharing, private
  filters look missing, an administrator's limited rights, stale versions, limits, bad parameters, server fields
  that a client cannot choose, tenant isolation, made-up ids).
- Screen: `frontend/src/lib/saved-filters.test.tsx` (20 tests) and the journey `frontend/e2e/saved-filters.spec.ts`.
