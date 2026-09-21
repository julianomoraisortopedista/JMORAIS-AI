# PostgreSQL Tamper Resistance and Concurrency — ST-20

## Runtime and local test environment

Python 3.12 is the only supported application runtime. The isolated integration
database is PostgreSQL 16, started with `docker-compose.postgres-test.yml`. Its
credentials are local test-only defaults; callers select the database through
`JMORAIS_TEST_POSTGRES_URL`.

The database uses a tmpfs volume. Teardown is `docker compose -f
docker-compose.postgres-test.yml down -v`; recreating the service provides a clean
database. Alembic is the production schema authority.

## Append-only enforcement

Migration `006_tamper_concurrency` installs PostgreSQL triggers on every scientific
or governance history table. `UPDATE` and `DELETE` fail with SQLSTATE `55000`.
No destructive downgrade is supplied because silently removing these controls or
history would violate the platform invariant.

## Concurrency strategy

Each logical stream is serialized by a transaction-scoped advisory lock derived
from its table namespace and owner identifier. Inside that transaction, the adapter
reads the last committed position and hash, validates the caller's previous hash,
and inserts the next position. Unique `(stream owner, stream position)` constraints
are the final collision barrier.

GovernedEvidence version allocation follows the same pattern: lock by package,
read `max(stream_version)` in the transaction, then insert the next version. A
unique package/version constraint prevents duplicates.

Stale event writers fail with a typed `ConcurrencyConflict`. The application must
reload history, rebuild the immutable event with the current previous hash, and
retry. Repositories never modify an already constructed event to hide a race.

## Transaction ownership

Repository `append` operations own one short atomic transaction. They do not commit
partway through an event chain. Advisory locks are automatically released on commit
or rollback. Integrity, uniqueness, and foreign-key errors roll back the complete
append. Read methods never commit.

## Database boundary invariants

- positive, unique stream positions;
- positive, unique GovernedEvidence versions per package;
- unique immutable event identifiers;
- exact previous-hash linkage enforced before insert;
- foreign-key protection for package version history;
- database-level rejection of historical update and deletion;
- replay exclusively from committed PostgreSQL rows after reconnect.

No patient data, payloads, credentials, or secrets are included in structured
infrastructure exceptions.
