# Isolated Docker test stack

This stack runs the UI, Hub backend, ML service, PostgreSQL, and Redis without
sharing containers, ports, networks, or volumes with the normal development or
production stacks.

## Safety boundary

- Compose project: `cah-isolated-test`
- Network: `cah-isolated-test-net`
- Volumes: `cah_isolated_test_*`
- All published ports bind to `127.0.0.1`
- ML enforcement is forced to shadow mode
- Alert destinations are empty by default
- `.env.test` is ignored by Git

## First run

```bash
git switch ui/central-auth-hub-signal-live
cp .env.test.example .env.test
```

Use separate OAuth test credentials and register these callbacks:

```text
http://localhost:18000/auth/google/callback
http://localhost:18000/oauth/callback
http://localhost:18000/auth/account/change-google/callback
```

Start the core stack:

```bash
bash scripts/test-stack/up.sh
```

Start it with the Dorm and Library applications:

```bash
bash scripts/test-stack/up.sh --with-subsystems
```

Open:

- Admin UI: http://localhost:13000
- Hub API: http://localhost:18000
- Dorm (optional): http://localhost:18001
- Library (optional): http://localhost:18002
- ML health: http://localhost:19000/health

## Seed test users

After the backend is healthy:

```bash
docker compose --env-file .env.test -f docker-compose.test.yml \
  exec hub-backend-test python -m app.seeds.seed_users
```

Only synthetic/test users should be loaded into this database.

## Verify

```bash
bash scripts/test-stack/smoke.sh
docker compose --env-file .env.test -f docker-compose.test.yml ps
docker compose --env-file .env.test -f docker-compose.test.yml logs -f hub-backend-test hub-frontend-test
```

The smoke script checks the Hub, database health, JWKS, frontend, and ML. It
also checks optional subsystems when their profile is running.

## Stop and reset

Stop while preserving test data:

```bash
bash scripts/test-stack/down.sh
```

Delete only isolated test volumes:

```bash
bash scripts/test-stack/down.sh --wipe
```

The wipe command requires typing `yes` and does not target normal development
or production volumes.
