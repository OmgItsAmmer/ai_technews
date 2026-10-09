# Fly.io Deployment Runbook

Two Fly apps, both configured to **sleep when idle** and wake on the next request:

| App                                                | Folder          | Config                                        | Public?      | Reached at                   |
| -------------------------------------------------- | --------------- | --------------------------------------------- | ------------ | ---------------------------- |
| `ainews` (core Django app + Celery + Redis)      | repo root       | [fly.toml](../../fly.toml)                       | Yes          | `https://ainews.fly.dev`   |
| `ainews-ai` (Antix AI service: API + arq worker) | `ai_service/` | [ai_service/fly.toml](../../ai_service/fly.toml) | No (private) | `http://ainews-ai.flycast` |

Pushes to `main` deploy automatically via [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml).

## How sleeping works

- Both apps use `auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0`. Fly's proxy stops a machine after a few idle minutes and starts it on the next request (cold start of a few seconds).
- Fly only auto-stops machines that sit behind its **proxy**. The AI app is private, so Django calls it over **Flycast** (`ainews-ai.flycast`), which goes through the proxy. The older `.internal` address bypasses the proxy, so the AI machine would never sleep or wake. That is why `AI_SERVICE_URL` is `http://ainews-ai.flycast`.
- The AI app runs its API and arq worker in **one** machine (`sh -c 'antix-ai worker & exec antix-ai serve ...'`). A separate always-polling worker machine would never let the app sleep.
- Core Redis runs inside the same machine (supervisord), so it is wiped on every sleep. That is fine: it only holds Celery broker/cache data.

**Known caveat:** background work that continues after the triggering request has returned (a long fetch run, AI indexing) does not count as traffic. If the machine goes idle mid-job, Fly may stop it and the job is cut off. If you see half-finished fetches, set `min_machines_running = 1` on `ainews` for the fetch window, or make the trigger endpoint stay open until the run finishes.

## Prerequisites

- Fly CLI: `fly version`. Install from https://fly.io/docs/flyctl/install/ if missing.
- Logged in: `fly auth login`.
- A Neon Postgres database for the core app (`DATABASE_URL`) and one for the AI service (`AI_DATABASE_URL`, needs the `pgvector` extension; the AI migrations create it).
- A Redis reachable from Fly for the AI service (`AI_REDIS_URL`), for example a free Upstash Redis in the same region.
- OpenAI (or compatible) API keys.

## First-time setup (once)

Run from the repo root unless noted. Rename the apps in both `fly.toml` files if `ainews` / `ainews-ai` are taken.

### 1. Create the apps

```bash
fly apps create ainews-core
fly apps create ainews-ai
```

### 2. Set secrets

Generate one shared key for service-to-service auth (24+ chars) and reuse it in both apps:

```bash
# bash / git-bash
export AI_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Core app:

```bash
fly secrets set -a ainews --stage \
  SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  DATABASE_URL="postgresql://USER:PASSWORD@ep-xxxx.neon.tech/neondb?sslmode=require" \
  OPENAI_API_KEY="sk-..." \
  CRON_SECRET="long-random-string" \
  AI_SERVICE_KEY="$AI_KEY"
```

AI service (full list in [ai_service/.env.example](../../ai_service/.env.example)):

```bash
fly secrets set -a ainews-ai --stage \
  AI_DATABASE_URL="postgresql://USER:PASSWORD@ep-yyyy.neon.tech/neondb?sslmode=require" \
  AI_SERVICE_KEY="$AI_KEY" \
  AI_REDIS_URL="rediss://default:PASSWORD@HOST:6379" \
  AI_FAST__PROVIDER=openai AI_FAST__MODEL=gpt-4o-mini AI_FAST__API_KEY="sk-..." \
  AI_STRONG__PROVIDER=openai AI_STRONG__MODEL=gpt-4o AI_STRONG__API_KEY="sk-..." \
  AI_EMBED_PROVIDER=openai AI_EMBED_MODEL=text-embedding-3-small AI_EMBED_DIM=1536 AI_EMBED_API_KEY="sk-..."
```

`--stage` stores the secrets without restarting anything; they apply on the first deploy.

### 3. Deploy the AI service first, private

```bash
cd ai_service
fly config validate
fly deploy --no-public-ips          # runs `antix-ai migrate` as the release command
fly ips allocate-v6 --private -a ainews-ai   # gives it the Flycast address
cd ..
```

Check it: `fly status -a ainews-ai` and `fly logs -a ainews-ai`.

### 4. Deploy the core app

```bash
fly config validate
fly deploy                          # runs `python manage.py migrate --noinput` first
fly open -a ainews
```

### 5. Seed data (first deploy only)

```bash
fly ssh console -a ainews -C "python manage.py seed_sources"
fly ssh console -a ainews -C "python manage.py createsuperuser"
```

### 6. Smoke test

```bash
curl -i https://ainews.fly.dev/                     # app responds (wakes the machine)
fly logs -a ainews-ai                               # open Ask AI in the UI and watch it wake
curl -X POST -H "X-Cron-Secret: <CRON_SECRET>" https://ainews.fly.dev/internal/trigger-fetch/
```

## CI/CD with GitHub Actions

[deploy.yml](../../.github/workflows/deploy.yml) runs on every push to `main` (and manually via **Actions > Deploy to Fly.io > Run workflow**, which deploys both apps):

1. `changes` detects what was touched. `ai_service/**` means AI; any other file outside `ai_service/` and `docs/` means core. Docs-only pushes deploy nothing.
2. `test-core` / `test-ai` run the test suites. A failing suite blocks that app's deploy.
3. `deploy-ai` runs first (when AI changed), then `deploy-core`, so Django never points at an older AI API than it expects.
4. Runs are serialized (`concurrency: fly-deploy`) so two pushes never deploy at once.

### One-time GitHub setup

Create one deploy token per app (scoped to that app only):

```bash
fly tokens create deploy -a ainews      # copy output
fly tokens create deploy -a ainews-ai   # copy output
```

In GitHub: **Settings > Secrets and variables > Actions**

| Type     | Name                   | Value                                                  |
| -------- | ---------------------- | ------------------------------------------------------ |
| Secret   | `FLY_API_TOKEN_CORE` | token for `ainews`                                   |
| Secret   | `FLY_API_TOKEN_AI`   | token for `ainews-ai`                                |
| Secret   | `CRON_SECRET`        | same as the Fly secret (used by `trigger-fetch.yml`) |
| Variable | `FLY_APP_URL`        | `https://ainews.fly.dev`                             |

Then protect `main` (Settings > Branches) and require the `CI Pipeline` and `ai-service` checks, so only reviewed, passing code reaches the deploy.

## Day-to-day operations

```bash
fly status -a ainews                  # machine state (started / stopped)
fly logs -a ainews                    # live logs
fly logs -a ainews-ai
fly deploy                            # manual deploy of core (from repo root)
fly deploy --no-public-ips            # manual deploy of AI (from ai_service/)
fly releases -a ainews                # release history
fly secrets list -a ainews
fly ssh console -a ainews             # shell into the machine
fly machine start <id> -a ainews      # wake manually
```

Rollback: `fly releases -a <app>` to find the last good image, then `fly deploy -a <app> --image <image-ref>`.

## Troubleshooting

| Symptom                                           | Likely cause / fix                                                                                                                            |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `DisallowedHost` / 400 on the site              | Add your domain to `ALLOWED_HOSTS` in `fly.toml` (`[env]`) and redeploy.                                                                |
| Ask AI times out on the first question after idle | AI machine is cold-starting.`AI_SERVICE_TIMEOUT` defaults to 60s; raise it if needed.                                                       |
| Ask AI always fails, AI logs show nothing         | Flycast address missing. Run `fly ips list -a ainews-ai`; it needs a private v6. Also check `AI_SERVICE_KEY` matches in both apps.        |
| AI machine never sleeps                           | Something is hitting it (check `fly logs`), or `min_machines_running` was changed. `.internal` URLs bypass the proxy; use `.flycast`. |
| Release command fails on deploy                   | Read `fly logs`; usually a missing secret (`DATABASE_URL` / `AI_DATABASE_URL`) or a migration error. The old version keeps running.     |
| Fetch run stops half way                          | Machine went idle mid-job. See the caveat above.                                                                                              |
| GitHub deploy fails with `unauthorized`         | Token expired or wrong app. Recreate with `fly tokens create deploy -a <app>` and update the secret.                                        |
| Deploy skipped on a push                          | Only `docs/` changed, or the push was not to `main`. Use the manual **Run workflow** button.                                        |

## Cost notes

Stopped machines cost only for their root-filesystem storage, not CPU or RAM. Remember the always-on pieces are external: Neon, Redis (Upstash), and the OpenAI usage itself.
