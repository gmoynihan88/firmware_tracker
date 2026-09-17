# Infrastructure

Terraform for running Firmware Tracker on AWS: one Fargate task behind API Gateway and
CloudFront, at a target of roughly $10 a month.

```
infra/
  bootstrap/      the state bucket, applied once with local state
  versions.tf     Terraform and provider versions, S3 backend (partial)
  providers.tf    us-west-2, plus a us-east-1 alias for CloudFront's certificate
  variables.tf    inputs and the shared tag set
  network.tf      VPC, two public subnets, the task's security group
  ecr.tf          image repository and its lifecycle policy
  efs.tf          file system, mount targets and the access point the task writes as
  logs.tf         CloudWatch log group
  access_logs.tf  CloudFront access log delivery, and the bucket it writes to
  ssm.tf          SecureString parameters, created empty and set by hand
  iam.tf          execution role -- and no task role, on purpose
  ecs.tf          cluster, capacity providers and the task definition
  service.tf      the service and its Cloud Map registration
  edge.tf         VPC Link, HTTP API, route and stage
  cloudfront.tf   the distribution in front of it
  github_oidc.tf  the role GitHub Actions assumes to deploy
  outputs.tf      values the later stacks and the deploy workflow read
```

## Why it is shaped this way

- **No NAT gateway.** A NAT gateway is about $32 a month before it moves a byte, three
  times the budget for the whole stack. The task runs in a public subnet with a public
  IP for outbound scraping, and its security group has no inbound rule: only the VPC
  Link will be allowed in, on port 8000.
- **No load balancer.** An ALB is about $16 a month. CloudFront needs a stable origin,
  and a Fargate task's IP changes on every restart, so the origin is an API Gateway
  HTTP API with a VPC Link to the service. Cheap at this traffic, and it keeps Fargate.
- **No DynamoDB lock table.** Terraform 1.11 locks state with a file in the same
  bucket, which the older DynamoDB pattern predates.
- **Two subnets, one task.** ECS wants more than one availability zone. The service
  still runs a single task: SQLite on EFS allows exactly one writer, and the scheduler
  runs in-process, so a second task would double every scrape.

## First run

The state bucket cannot live in the state it stores, so it is applied on its own.

```bash
cd infra/bootstrap
terraform init
terraform apply -var state_bucket_name=firmware-tracker-tfstate-$(openssl rand -hex 4)

cd ..
cp backend.hcl.example backend.hcl        # gitignored; set the bucket it printed
terraform init -backend-config=backend.hcl
terraform plan
```

`terraform.tfvars` and `backend.hcl` are gitignored, as is all state. Every
account-specific value belongs in those two files, which is what keeps this repository
public without leaking the account.

## The task

0.5 vCPU and 1 GB on **Fargate Spot**, about $6 a month. Spot can reclaim the task with
two minutes' notice; it restarts, and since the database is on EFS that costs a few
seconds of downtime rather than any data. `use_spot = false` moves it to on-demand at
roughly three times the price. 512 MB was the original plan and is too tight: Chromium
renders half the catalogue's pages, and a task killed mid-render fails the scrape.

**Desired count is fixed at 1**, with a validation rule that refuses anything else.
SQLite on EFS allows exactly one writer, and the scheduler runs in the app's own
process, so a second task would double every scrape as well as risk the database. The
deployment stops the old task before starting the new one for the same reason.

**No task role.** A task role is served over the container credential endpoint at
`169.254.170.2`, which no security group can filter, and this app fetches arbitrary
vendor URLs with a browser whose DNS resolution its egress guard cannot see. With no
task role there is nothing there to take. The execution role — used by the ECS agent,
not the app — pulls the image, reads the four SecureString parameters and writes logs.

**Secrets** are created as placeholders and then ignored by Terraform, so real values
never reach state:

```bash
python -m src.auth.hash_password        # prints AUTH_PASSWORD_HASH and SECRET_KEY
aws ssm put-parameter --overwrite --type SecureString \
  --name /firmware-tracker/production/secret_key --value '<value>'
```

`terraform output secret_parameter_names` lists all four.

## The edge

CloudFront -> API Gateway HTTP API -> VPC Link -> Cloud Map -> the task. The API's route
table is a single `$default`, because the app does its own routing and its own
authentication; a per-path table here would be a second thing to keep in step. The
default behaviour caches nothing (a dashboard behind a session cookie must not be shared)
and `/static/*` caches hard, which is safe because every asset URL carries a hash of its
contents.

**The catalogue is public** (`PUBLIC_CATALOG=true`), so the deployment can be linked to
as a demo: `/catalog`, its version-history popup and the read-only device APIs answer
without a password, while the dashboard, notifications, tracked devices and every write
stay behind it. `/catalog*` is cached for 60 seconds with the session cookie in the cache
key, which absorbs a burst of strangers without ever handing an anonymous page to the
logged-in owner.

**The API Gateway URL is public and answers directly, bypassing CloudFront.** HTTP APIs
have no resource policy, and CloudFront's origin access control does not cover API
Gateway, so the options are to accept it, add a Lambda authorizer checking a shared
secret header, or move to an ALB with a CloudFront VPC origin at about $16 a month. It is
accepted here: the app authenticates every request, throttles failed logins, and the
stage caps bursts at 50 requests. Anything added at CloudFront later -- WAF especially --
would want this closed first.

## Cost alarms

Three, because they fail differently. A **monthly budget** at $15 catches drift -- the
realistic failure is $9 quietly becoming $25, not a sudden $50 -- and alerts on forecast
as well as actual, because Cost Explorer lags 8-24 hours and the forecast fires first. A
**daily budget** at $1 catches a spike; it sits near the ~$0.30 run rate rather than far
above it, since a threshold at five times normal lets a steady doubling through forever.
**Anomaly detection** catches a change of shape that no fixed number describes.

Measured run rate on 2026-09-16: about $0.30 a day, and the largest single item is not the
task -- it is the **public IPv4 address at $0.005/hour (~$3.65/month)**, which exists
because the task sits in a public subnet to avoid a $32/month NAT gateway. Fargate Spot
for 0.5 vCPU and 1GB is about $0.10 a day.

`alert_email` and `anomaly_monitor_arn` live in `terraform.tfvars`, gitignored.

## Backups, and why there are two kinds

`aws_efs_backup_policy` (efs.tf) turns on EFS **automatic** backups. Those go to the
AWS-managed vault `aws/efs/automatic-backup-vault`, and a restore drill on 2026-09-17
established that **nothing in this account can restore from it**:

```
Effect: Deny   Principal: *
Action: DeleteBackupVault, DeleteBackupVaultAccessPolicy, DeleteRecoveryPoint,
        StartCopyJob, StartRestoreJob, UpdateRecoveryPointLifecycle
```

An explicit Deny to `Principal: *` beats administrator. The recovery point cannot be
restored, cannot be copied somewhere restorable, and the deny cannot be lifted, because
deleting the policy is itself denied. It was found by trying: `start-restore-job`
returned `AccessDeniedException` naming the resource-based policy.

So backup.tf adds the restorable path — our own vault, a daily plan at 05:00 UTC keeping
35 days, and one role holding **both** the backup and the restore managed policies. A
role that can only take backups produces a vault full of data and no way to use it,
which is the same failure wearing a different hat.

To restore, with the names from `terraform output`:

```bash
VAULT=$(terraform -chdir=infra output -raw backup_vault_name)
ROLE=$(terraform -chdir=infra output -raw backup_role_arn)
aws backup list-recovery-points-by-backup-vault --backup-vault-name "$VAULT" \
  --query 'RecoveryPoints[].{arn:RecoveryPointArn,created:CreationDate,bytes:BackupSizeInBytes}'
```

Then `aws backup start-restore-job` with `--iam-role-arn "$ROLE"` and metadata setting
`newFileSystem: "true"` — **never** pass the recovery point's own `file-system-id`
through unchanged, which restores into the live volume rather than beside it.

**~11MB is the baseline.** A recovery point far below it is a signal, not a saving. And
a backup nobody has restored is a hypothesis: drill it, or it is not a backup.

### The drill, 2026-09-17 — passed

An on-demand backup into this vault was restored to a throwaway file system, mounted
read-only by a one-off Fargate task, and the database opened:

```
integrity_check: ok        manufacturers: 91      device_models: 2045
firmware_versions: 11207   my_devices: 82         scrape_runs: 774
dated_versions: 8646       alembic_version: f2c8d1a94b70
```

91 and 2,045 match what production's public API served at the same moment, so the
counts are a comparison rather than a number that merely looks plausible.

**The restore lands in a recovery directory, even on a brand-new file system**:
`/aws-backup-restore_<timestamp>/firmware-tracker/firmware_tracker.db`. The access point
roots at `/firmware-tracker`, one level below that, so a real recovery cannot just point
the service at the restored volume — move the contents up, or create an access point
matching the restored path. Worth knowing before doing it under pressure.

Three things that cost a cycle each, recorded so the next drill does not repeat them:

- **`"entryPoint": []` does not override an image entrypoint.** ECS reads the empty array
  as "unset" and runs the image's own, which here is `alembic upgrade head` — a migration
  against the evidence. Use a non-empty entrypoint (`["python"]`).
- **`Encrypted: "true"` requires an explicit `KmsKeyId`** in the restore metadata, or the
  job fails after several minutes with `Required key(s) [kmskeyid (String)] missing`.
- **EFS `SizeInBytes` is metered hourly.** The restored file system read 6,144 bytes while
  actually holding 11,153,408. Mount it and look; do not judge a restore by that field.

The mount was `readOnly: true` throughout and the database was copied to `/tmp` before
opening, so the drill could not alter what it was inspecting.

## What is not here yet

In order, each its own change:

1. **CloudFront access logs.** Legacy standard logging needs S3 ACLs enabled on the
   bucket, which new buckets disable; the newer delivery path avoids that and is worth
   doing properly rather than quickly. API Gateway access logs are already on.
2. **An edge rate limit on `/login`**, if the app-level throttle proves not to be
   enough. The stage already caps bursts at 50 requests.
3. **Terraform in CI** — plan on a pull request, apply on merge. That needs a second
   role with much wider permissions than the deploy role, which is a decision worth
   making deliberately rather than by default.

A domain is deliberately absent: the first deploy answers on CloudFront's own address,
and ACM plus Route 53 can follow without reworking anything.
