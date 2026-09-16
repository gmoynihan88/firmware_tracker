# Running it

## Adding devices

From the catalogue at `/catalog`: search by product or vendor, split hardware from
software, pick a vendor, or hide what you already track. Filtering, sorting and paging
all happen on the server, so a search covers the whole catalogue rather than the rows
you can see, and the URL carries the view -- a filtered, sorted page is a link you can
send someone. Devices you already track say so instead of offering to add a second copy.

Or in bulk, from what is installed (macOS):

```bash
python scripts/scan_installed_plugins.py --compare   # what matches the database
python scripts/scan_installed_plugins.py --add       # import the matches
```

## Scraping by hand

```bash
curl -X POST http://localhost:8000/api/firmware/scrape-all
curl -X POST http://localhost:8000/api/firmware/scrape/strymon
```

It reports what it could not do, not just what it did:

```json
{
  "new_firmware_versions": 195,
  "devices_without_firmware": ["Hall of Fame 2"],
  "devices_failed": [],
  "devices_not_checked": []
}
```

## Backfilling notifications

For a device whose installed version you recorded *after* its latest was already known — a
scrape only notifies about versions it discovers, so those would otherwise never fire.
Safe to re-run; one notification per device per version:

```bash
curl -X POST http://localhost:8000/api/firmware/reconcile-notifications
```

## Notifications on your phone

```bash
NOTIFY_TRANSPORT=ntfy
NTFY_TOPIC=firmware-tracker-<long random string>
```

Delivery is a side effect: if ntfy is unreachable the notification is still recorded and
the failure logged. The test suite forces the transport off, so `pytest` on a configured
machine cannot push fixture alerts to your phone.

**On public ntfy.sh the topic name is the only secret.** Use a long random one
(`firmware-tracker-$(openssl rand -hex 16)`) and keep it in `.env`, which is gitignored.

## Finding versions a vendor has withdrawn

A version that disappears from a vendor's page simply stops being returned, so without a
last-seen stamp its row looks identical to one confirmed this morning. Comparing it
against the last successful scrape for that vendor separates "withdrawn" from "we stopped
looking":

```sql
WITH last_run AS (
  SELECT scraper_type, MAX(started_at) AS ran_at
  FROM scrape_runs WHERE success = 1 GROUP BY scraper_type
)
SELECT m.name, dm.name, fv.version, date(fv.last_seen_at)
FROM firmware_versions fv
JOIN device_models dm ON dm.id = fv.device_model_id
JOIN manufacturers m ON m.id = dm.manufacturer_id
JOIN last_run lr ON lr.scraper_type = m.slug
WHERE fv.last_seen_at < lr.ran_at;
```

## What the scrapes have been doing

This is what makes a quiet stretch in a device's history readable — a version's first-seen
date cannot tell "the vendor published nothing for eight months" from "the scraper was
broken for eight months":

```bash
curl "http://localhost:8000/api/firmware/runs?limit=20"
curl "http://localhost:8000/api/firmware/runs?scraper_type=yamaha"
```

## Backups

`bash scripts/backup_db.sh` (`list` and `restore` too). Each run writes two files: a `.db`
that restores fastest and is byte-exact, and a `.sql` text dump that diffs, compresses and
can be read without sqlite. SQLite rewrites pages on almost any change, so two binary
snapshots a day apart share very little — one scrape of a single manufacturer moved 3,238
bytes in the `.db` and five lines in the dump.

`backups/` is gitignored, and should stay that way: this database holds your device list,
and git history is permanent. If you want the dumps versioned, put them in a private repo.

## Referential integrity

```bash
python scripts/check_orphans.py          # --fix deletes what it finds, exits 1 on anything
```

It should always find nothing: deletes cascade through the ORM and SQLite is told to
enforce foreign keys. It exists because neither was true for most of this project's life,
and a database outlives the bug that damaged it.

## Health and logs

```bash
curl http://localhost:8000/health        # liveness  -> {"status":"ok","uptime_seconds":2.9}
curl http://localhost:8000/health/ready  # readiness -> {"status":"ok","database":"ok"}
```

`/health` touches nothing, so a failure means the process is wedged or gone. It
deliberately skips the database: if it checked, a slow disk would have the orchestrator
kill and replace tasks, which does not fix a slow disk. `/health/ready` runs a query and
returns **503** with a reason — on a deployment where the database is a file on a network
mount, losing that mount is exactly what this catches.

Logs go to stderr. Docker caps them at 10MB × 3; under systemd journald handles it; if you
run `uvicorn > file &` then nothing rotates it, so set `LOG_FILE` and the app rotates for
you. Access lines for `/health` are dropped by default — a container health check polls it
every 30 seconds, which is 95MB of log a year against about 1MB of actual results.

## CloudFront access logs

Deployed only, and separate from the app's own logs: these are what the edge served,
including the requests that never reached the task because the cache answered them.

```bash
BUCKET=$(terraform -chdir=infra output -raw access_log_bucket)
aws s3 ls "s3://$BUCKET/" --recursive | tail
aws s3 cp "s3://$BUCKET/<key>" - | gunzip | head
```

Objects are gzipped, one JSON record per request, keyed by distribution and hour:
`AWSLogs/<account>/CloudFront/<distribution>.<YYYY-MM-DD-HH>.<hash>.gz`.

**Delivery is not immediate**, though it is quicker than the hour AWS allows for: measured
here, requests at 16:46 UTC were in an object by 16:49. Give it an hour before concluding
anything is wrong, because an empty bucket shortly after an apply means wait.

One trap worth knowing. A **zero-byte `AWSLogs/<account>/CloudFront/` prefix marker
appears immediately**, long before any log does. It is not a log, and counting objects
rather than bytes will tell you delivery works when the bucket holds nothing else -- which
is exactly how the first check written for this reported success against an empty bucket.
Its one use is diagnostic: only the delivery service creates it, so if it is there, the
bucket policy is letting that service write and any problem lies further along.

They expire after two years (`access_log_retention_days`). At roughly 300 requests a day
that is a couple of hundred megabytes, so pennies a month. Worth knowing before tuning
it: these records carry visitor IP addresses, so the case for a shorter window is a
privacy one rather than a cost one.

What these add over CloudFront's own metrics is per-URL and per-viewer detail: which
pages a visitor actually opened, and which addresses are working on `/login`. Request
counts, error rates and cache hit ratio are already in CloudWatch for free, which is
where to look first.
