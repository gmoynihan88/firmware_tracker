# A backup you can actually restore from.
#
# `aws_efs_backup_policy` in efs.tf turns on EFS *automatic* backups, and those land in
# the AWS-managed vault `aws/efs/automatic-backup-vault`. That vault carries a resource
# policy AWS writes and this account cannot remove:
#
#   Effect: Deny   Principal: *
#   Action: DeleteBackupVault, DeleteBackupVaultAccessPolicy, DeleteRecoveryPoint,
#           StartCopyJob, StartRestoreJob, UpdateRecoveryPointLifecycle
#
# An explicit Deny to `Principal: *` beats every Allow, administrator included. So from
# that vault nobody can restore, nobody can copy a recovery point somewhere restorable,
# and nobody can lift the deny by deleting the policy. Measured, not assumed: a restore
# of the 2026-09-17 recovery point returned AccessDeniedException naming the
# resource-based policy, and `get-backup-vault-access-policy` prints the statement above.
#
# That is the whole reason this file exists. The recovery point created by #216 is real
# -- COMPLETED, 11,153,589 bytes -- and it is not a backup, because a backup is defined
# by whether you can get the data back. A drill is what turned that from an assumption
# into a fact, which is the argument for running one before you need it.
#
# Everything below is the restorable path: our own vault, our own plan, and a role that
# can both take a backup and put one back.

resource "aws_backup_vault" "data" {
  name = local.name

  # Deleting the vault destroys every recovery point in it, and unlike the automatic
  # vault nothing else stops that here -- the AWS-managed deny that makes restores
  # impossible is also what makes those recovery points undeletable. Ours are deletable
  # by design, so the guard has to be explicit.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = local.name
  }
}

# One role for both directions. Backup and restore are separate managed policies, and a
# role that can only take backups is how you arrive at a vault full of data and no way
# to use it -- a second version of the failure this file is about.
data "aws_iam_policy_document" "backup_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backup" {
  name               = "${local.name}-backup"
  description        = "Assumed by AWS Backup to back up and to restore the EFS file system."
  assume_role_policy = data.aws_iam_policy_document.backup_assume.json
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "backup_restores" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

resource "aws_backup_plan" "data" {
  name = local.name

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.data.name

    # 05:00 UTC, the same hour the automatic plan used. The task is idle then and a
    # scrape is not mid-write, which matters for SQLite on NFS.
    schedule = "cron(0 5 ? * * *)"

    # An hour to start and two to finish. The file is ~11MB, so these are generous by
    # orders of magnitude; they exist so a job that cannot start fails visibly rather
    # than queueing forever.
    start_window      = 60
    completion_window = 120

    lifecycle {
      # 35 days, matching what the automatic plan kept. At ~11MB a point that is a few
      # cents a month in total.
      delete_after = 35
    }
  }
}

resource "aws_backup_selection" "data" {
  name         = local.name
  iam_role_arn = aws_iam_role.backup.arn
  plan_id      = aws_backup_plan.data.id

  resources = [aws_efs_file_system.data.arn]
}
