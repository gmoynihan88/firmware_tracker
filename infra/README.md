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
  ssm.tf          SecureString parameters, created empty and set by hand
  iam.tf          execution role -- and no task role, on purpose
  ecs.tf          cluster, capacity providers and the task definition
  service.tf      the service and its Cloud Map registration
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

## What is not here yet

In order, each its own change:

1. **Edge** — VPC Link, API Gateway HTTP API, CloudFront with the managed
   CachingDisabled policy on the default behaviour and a long TTL on `/static/*`
   (assets are content-hashed), and its log bucket.
2. **Deploy** — an OIDC role trusted only by
   `repo:gmoynihan88/firmware_tracker:environment:production`, and workflows that plan
   on a pull request and apply on merge. The repository only allows GitHub-owned
   actions, so `aws-actions/configure-aws-credentials`, `aws-actions/amazon-ecr-login`
   and `hashicorp/setup-terraform` each need adding to the allowlist and pinning to a
   commit SHA first.
3. **Guardrails** — a budget alarm, and a rate limit on `/login` at the edge if the
   app-level throttle proves not to be enough.

A domain is deliberately absent: the first deploy answers on CloudFront's own address,
and ACM plus Route 53 can follow without reworking anything.
