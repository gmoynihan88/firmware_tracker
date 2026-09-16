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
