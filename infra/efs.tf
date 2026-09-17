# The database lives on EFS so it survives a task being replaced, which on Spot is a
# routine event rather than an exception.
#
# SQLite over NFS is only safe with exactly one writer, which is why the service runs a
# single task and the deployment stops the old one before starting the new. The app's
# own scheduler is in-process, so a second task would also double every scrape.

resource "aws_efs_file_system" "data" {
  creation_token = local.name
  encrypted      = true

  # Elastic throughput bills per request rather than per provisioned MB/s, which suits
  # a database that is idle between scrapes.
  throughput_mode = "elastic"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  lifecycle_policy {
    transition_to_primary_storage_class = "AFTER_1_ACCESS"
  }

  tags = {
    Name = local.name
  }

  # creation_token is ForceNew, and it is derived from project and environment. So
  # renaming either -- or standing up a second workspace, which is the documented way to
  # make a staging environment -- plans a destroy-and-create of the file system holding
  # the entire database. Terraform prints it, but a skimmed plan or an -auto-approve
  # discards it in silence. The state bucket already carries this guard, and for a
  # weaker reason: state can be rebuilt by importing, whereas this cannot be rebuilt at
  # all.
  lifecycle {
    prevent_destroy = true
  }
}

# Daily backups, which were simply absent.
#
# EFS created through the API -- which is what Terraform does -- has automatic backups
# OFF by default; only the console enables them for you. That distinction is easy to
# read past, so it was verified against the live file system rather than assumed:
# `aws efs describe-backup-policy --file-system-id fs-03a653f5a3c083092` returned
# PolicyNotFound, meaning the file holding every scraped version, every device and the
# whole firmware history had no copy anywhere.
#
# What made this worth fixing ahead of everything else is that the alternatives are not
# recovery. docker-entrypoint.sh runs `alembic upgrade head` unattended on every task
# start, including every Spot restart, so a bad migration reaches production with no
# human in the loop. scripts/backup_db.sh reads a relative path on a developer laptop
# and has never run against this file system, though outputs.tf claims otherwise.
#
# AWS Backup's default plan keeps 35 daily recovery points. At this size that is cents a
# month, against a database that is otherwise unrecoverable.
#
# **These recovery points cannot be restored.** Automatic EFS backups go to the
# AWS-managed vault `aws/efs/automatic-backup-vault`, whose resource policy denies
# StartRestoreJob and StartCopyJob to `Principal: *` -- an explicit Deny that beats
# administrator, and that cannot be removed because deleting the policy is denied too. A
# restore drill on 2026-09-17 established this from the API rather than from the docs;
# the reasoning above was right that the database needed backups and wrong about what
# this resource delivers. backup.tf is the restorable path, and the comment there
# carries the measured policy.
#
# Left ENABLED deliberately, for now. It costs cents, it is a second copy of the bytes
# even if reaching them means an AWS support case, and the conservative order is to
# prove the new vault restores before switching anything off. Once backup.tf has a
# recovery point that has actually been restored, this should go to DISABLED.
resource "aws_efs_backup_policy" "data" {
  file_system_id = aws_efs_file_system.data.id

  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_security_group" "efs" {
  name        = "${local.name}-efs"
  description = "EFS mount targets: NFS from the task only."
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name}-efs"
  }
}

# The only thing that may mount the file system is the task's security group. EFS in a
# public subnet is otherwise reachable from anywhere in the VPC.
resource "aws_vpc_security_group_ingress_rule" "efs_from_app" {
  security_group_id            = aws_security_group.efs.id
  description                  = "NFS from the Firmware Tracker task"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "app_efs" {
  security_group_id            = aws_security_group.app.id
  description                  = "NFS to the EFS mount targets"
  referenced_security_group_id = aws_security_group.efs.id
  from_port                    = 2049
  to_port                      = 2049
  ip_protocol                  = "tcp"
}

resource "aws_efs_mount_target" "data" {
  count = length(aws_subnet.public)

  file_system_id  = aws_efs_file_system.data.id
  subnet_id       = aws_subnet.public[count.index].id
  security_groups = [aws_security_group.efs.id]
}

# The access point pins every file to the container's own user. The image creates
# `tracker` as uid 10001 and runs as it (see the Dockerfile), and without this the task
# would arrive as root against a directory it may not own.
resource "aws_efs_access_point" "data" {
  file_system_id = aws_efs_file_system.data.id

  posix_user {
    uid = 10001
    gid = 10001
  }

  root_directory {
    path = "/firmware-tracker"

    creation_info {
      owner_uid   = 10001
      owner_gid   = 10001
      permissions = "0755"
    }
  }

  tags = {
    Name = local.name
  }
}
