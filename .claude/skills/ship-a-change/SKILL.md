---
name: ship-a-change
description: Take a change from branch to verified in production — PR, merge, the deploy the merge triggers, and the checks that prove the running task is the new code. Use when merging anything, when a deploy needs verifying, or when production looks wrong after a change.
---

# Shipping a change

Five changes went out on 2026-09-16 with the loop below. The loop is short; what makes
it worth writing down is that **merging is deploying**, that Terraform does not deploy,
and that a deploy which looks broken is usually a deploy working as designed.

```
checkout main -> branch -> PR -> CI green -> merge
                                               |
                          merge fires deploy.yml automatically
                                               |
                          ~6 min, one task, brief outage
                                               |
                          verify: image == merge SHA, counts, endpoints
```

## Branch and PR

```bash
git checkout main && git pull --ff-only
git checkout -b some-branch
git log --oneline main..HEAD   # must print nothing
```

**Check out main first.** Branching from whatever branch you are on has stacked PRs
twice in this repo, and it is invisible until review shows unrelated commits.

Merging is the user's call, every time. Approval to merge one PR is not approval for
the next one.

```bash
gh pr checks 219            # all green before merging, read it rather than assuming
gh pr merge 219 --squash --delete-branch
```

Squash matches the history: every recent commit on main ends with `(#NNN)`.

## Merging is deploying

`.github/workflows/deploy.yml` fires on push to main under these paths:

```
src/**  templates/**  static/**  alembic/**
Dockerfile  docker-entrypoint.sh  requirements.txt  .github/workflows/deploy.yml
```

So a merge touching any of those **is** a production deploy, whether or not anyone
said the word. There is one Fargate Spot task, and the service stops the old one
before starting the new, so every deploy is a brief outage. Say so before merging.

Docs- and test-only changes do not deploy. A PR that touches `README.md`,
`docs/**` and `tests/**` ships nothing and needs no production check.

**Never cancel a running deploy.** The workflow sets `concurrency: deploy-production`
with `cancel-in-progress: false` for a reason recorded in its own comment: the service
stops the old task before starting the new one, so an interrupted deploy leaves
nothing running at all.

The job takes about 6 minutes: checkout, assume the deploy role, log in to ECR, build
and push, register a task definition revision, update the service, wait for the
service to settle, report what is running.

```bash
gh run watch <run-id> --exit-status --interval 20
```

## Verify that the new code is actually running

A green workflow is not proof. Check the image the service is running, and check it
is the **merge SHA** rather than a tag:

```bash
C=firmware-tracker-production
aws ecs describe-services --cluster $C --services $C \
  --query 'services[0].{status:status,desired:desiredCount,running:runningCount,pending:pendingCount,taskDef:taskDefinition}' --output json

TD=$(aws ecs describe-services --cluster $C --services $C --query 'services[0].taskDefinition' --output text)
aws ecs describe-task-definition --task-definition "$TD" \
  --query 'taskDefinition.containerDefinitions[0].{image:image,command:command}' --output json
```

What each field has to say:

| Check | Pass | Why it matters |
|---|---|---|
| `image` | ends in the merge SHA | `:latest` means a Terraform-authored revision is running, not your code |
| `desired`/`running`/`pending` | 1 / 1 / 0 | pending>0 means it is still rolling; running=0 means it failed to start |
| `uptime_seconds` from `/health` | small | proves a *fresh* task, not the old one that survived |
| an owner-only route | 401 | proves the auth middleware is still closed after the change |

```bash
for p in /health /health/ready /catalog /scrape-status; do
  printf "%-16s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 https://firmware.gregmoynihan.dev$p)"
done
curl -s https://firmware.gregmoynihan.dev/health
```

`/catalog` 200 and `/scrape-status` 401 together are the useful pair: the public
catalogue still serves, and the owner-only page is still owner-only.

## Terraform does not deploy

`infra/service.tf` carries `ignore_changes = [task_definition]` on the service. Two
consequences, both of which have caused wasted time here:

- **`terraform apply` alone ships no code.** It can change the task definition family
  all it likes; the service keeps pointing where it pointed.
- **Terraform's own revision carries `image = ":latest"`** and must never be deployed
  directly. `deploy.yml` builds each new revision from the family's **latest ACTIVE**
  revision, which is how an infrastructure change eventually reaches production: apply
  it, then merge any app change (or run the workflow manually) to carry it out.

To ship an infra change with no app change, use `workflow_dispatch` rather than an
empty commit.

## When production looks wrong, read the deploy log before theorising

On 2026-09-16 the site went down right after a merge. I announced I had caused it,
then theorised that Terraform had deregistered the running revision. Both were wrong:
that revision stayed `ACTIVE` the whole time, and the outage was the merge triggering
a deploy — the documented, expected brief gap while one task is replaced.

The order that would have answered it in thirty seconds:

```bash
gh run list --workflow=deploy.yml --limit 5     # is a deploy running right now?
aws ecs describe-services --cluster $C --services $C \
  --query 'services[0].events[:5]' --output json
aws ecs list-task-definitions --family-prefix firmware-tracker-production --status ACTIVE
```

A deploy in flight explains an outage completely. Check that before forming a theory,
and before claiming responsibility for one.
