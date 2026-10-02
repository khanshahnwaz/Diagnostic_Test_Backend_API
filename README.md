# EVE Diagnostics API

Backend service for booking diagnostic tests with a simulated payment flow.
Built with FastAPI, SQLAlchemy 2, PostgreSQL and JWT auth.

## Running it

### With Docker (easiest)

```bash
docker compose up --build
```

API is on http://localhost:8000 and the Swagger docs are at http://localhost:8000/docs.
`admin@example.com` is treated as an admin when it signs up (see `ADMIN_EMAILS`).

### Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # point DATABASE_URL at your postgres
uvicorn app.main:app --reload
```

Tables are created on startup, there are no migrations.

### Tests

```bash
pytest
```

Tests run against in-memory SQLite so they need no setup.

### Config

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL | local postgres |
| `JWT_SECRET` | signs access tokens | `change-me` |
| `WEBHOOK_SECRET` | HMAC key shared with the payment provider | `change-me-too` |
| `ADMIN_EMAILS` | comma separated emails that become admin on signup | empty |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | token lifetime | 60 |
| `PAYMENT_SUCCESS_RATE` | chance a simulated payment succeeds | 0.8 |

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/signup` | - | |
| POST | `/auth/login` | - | returns JWT |
| GET | `/auth/me` | user | |
| GET | `/centres` | - | filters: `location`, `test_id`; paginated |
| GET | `/centres/{id}` | - | includes tests and prices |
| POST | `/centres` | admin | |
| POST | `/centres/{id}/tests` | admin | adds a test, or updates its price if the centre already has it |
| GET | `/tests` | - | paginated |
| POST | `/bookings` | user | |
| GET | `/bookings` | user | own bookings, `status` filter, paginated |
| GET | `/bookings/{id}` | user | includes payments |
| POST | `/bookings/{id}/cancel` | user | |
| POST | `/payments/` | user | simulated payment |
| POST | `/payments/webhook/` | HMAC signature | provider callback |
| GET | `/health` | - | |

### Example requests

```bash
# signup + login
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","full_name":"Admin","password":"password123"}'

TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"password123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# admin creates a centre and adds a test
curl -X POST localhost:8000/centres -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Apollo Diagnostics","location":"Ranchi"}'

curl -X POST localhost:8000/centres/1/tests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"CBC","description":"Complete blood count","price":"499.00"}'

# book it
curl -X POST localhost:8000/bookings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-12-01T10:00:00Z"}'

# pay (leave out "outcome" for a random result)
curl -X POST localhost:8000/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id":1,"outcome":"SUCCESS"}'
```

`POST /payments/` body:

- `booking_id` (required)
- `outcome`: `SUCCESS` or `FAILED` to force a result, otherwise it is random
- `async_mode`: if true the payment stays `PENDING` and the result has to come in through the webhook

### Webhook

The body is signed with HMAC-SHA256 using `WEBHOOK_SECRET` and sent in the `X-Signature` header.

```bash
BODY='{"event_id":"evt_123","payment_reference":"pay_xxx","status":"SUCCESS"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "dev-webhook-secret" | awk '{print $2}')

curl -X POST localhost:8000/payments/webhook/ -H 'Content-Type: application/json' \
  -H "X-Signature: $SIG" -d "$BODY"
```

Responses: `{"status": "processed" | "duplicate" | "ignored"}`.

## Database design

```
users 1---* bookings *---1 diagnostic_centres 1---* centre_tests *---1 diagnostic_tests
                |
                1---* payments

webhook_events (standalone, keyed by the provider's event_id)
```

- **users**: email (unique, stored lowercase), bcrypt hash, `is_admin`.
- **diagnostic_centres**: name + location, unique together.
- **diagnostic_tests**: the catalogue of tests, name unique.
- **centre_tests**: join table holding the price. Unique on (centre, test). Price lives here because the same test costs different amounts at different centres.
- **bookings**: user, centre, test, appointment time, amount, status. `amount` is copied from the price at booking time. A partial unique index on (user, centre, test, appointment_at) where status is PENDING or CONFIRMED prevents double booking, while cancelled or failed ones don't block a rebook.
- **payments**: one row per payment attempt, with a unique `reference` that the provider uses. A booking can have several (e.g. a failed one followed by a successful retry).
- **webhook_events**: unique `event_id`, stores the payload and what happened with it.

Money is `NUMERIC(10,2)` / `Decimal`, never float.

### State rules

Booking: `PENDING -> CONFIRMED` on successful payment, `PENDING -> FAILED` on failed payment, `FAILED -> CONFIRMED` on a successful retry, and `PENDING/CONFIRMED/FAILED -> CANCELLED` by the user. Only `PENDING` and `FAILED` bookings can be paid.

Payment: starts `PENDING`, moves once to `SUCCESS` or `FAILED` and then never changes.

## How the webhook stays idempotent

1. Signature is checked on the raw body first.
2. If `event_id` was already stored, return `duplicate` without touching anything.
3. The payment row is locked (`SELECT ... FOR UPDATE`), and the result is only applied if the payment is still `PENDING`. A different event that arrives for an already settled payment is stored as `ignored`.
4. The `webhook_events` insert and the payment/booking update are committed in one transaction. The unique constraint on `event_id` catches two identical events arriving at the same moment.
5. An event for an unknown payment reference returns 404 and is *not* stored, so the provider's retry can succeed later.

## Assumptions

- Signup is open to everyone, admins are picked through the `ADMIN_EMAILS` setting. Only admins manage centres and tests, reading them is public.
- Naive appointment datetimes are treated as UTC. Appointments must be in the future.
- Asking for someone else's booking returns 404 instead of 403 so ids can't be probed.
- A user can retry payment on a `FAILED` booking, but can't start a new payment while one is still `PENDING`.
- If a success webhook arrives for a booking that was cancelled in the meantime, the payment is recorded as `SUCCESS` but the booking stays `CANCELLED` and a warning is logged. A real system would trigger a refund here.
- The simulated provider is just the `/payments/` endpoint. Use `async_mode` plus a manually sent webhook to see the full flow.
- Tests run on SQLite, the schema and queries are plain SQLAlchemy so they also work on Postgres, but row locking (`FOR UPDATE`) only has an effect on Postgres.

## What I'd improve with more time

- Alembic migrations instead of `create_all`.
- Run the test suite against a real Postgres in CI, and add a concurrency test for the webhook.
- Retry handling through a queue (Celery) for webhook processing, plus a reaper for payments stuck in `PENDING`.
- Refresh tokens and token revocation.
- Rate limiting on auth and payment endpoints.
- Appointment slots / capacity per centre instead of free-form times.
- Refunds when a paid booking is cancelled.
- Request ids in logs so a request can be traced across log lines.
