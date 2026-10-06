# Deploying to AWS

Potato can run on AWS in three ways. For most studies, use the first one.

| | `--provider aws` (Lightsail) | `--provider aws-ec2` | `--provider aws-ecs` (Express Mode) |
|---|---|---|---|
| What you get | one VM | one VM | a managed container |
| Cost | **$12/month**, flat | about $16/month | about $45–70/month |
| Disk | survives restarts | survives restarts | wiped when the task is replaced; needs `--backup` |
| HTTPS | Let's Encrypt certificate for the IP | Let's Encrypt certificate for the IP | AWS certificate on `*.ecs.<region>.on.aws` |
| Permissions | `lightsail:*` | EC2, plus `ssm:GetParameter` | ECS, IAM, SSM, CloudWatch Logs |
| `deploy logs` / SSH | yes | yes | logs only |

**Use Lightsail unless you have a reason not to.** Its price includes the IPv4
address, a 60 GB SSD and 3 TB of transfer, it needs no VPC, security group or
IAM role, and new AWS accounts get $100–200 of credit that covers several months
of it.

Use EC2 if your institution's AWS account has Lightsail turned off or requires
EC2. Use ECS Express only if you specifically want AWS to run the container for
you and you are prepared for the cost and the backup requirement.

App Runner closed to new customers on 30 April 2026, and Lightsail's container
service has no persistent storage, so neither is offered.

## Credentials

The AWS providers use the same credentials as the `aws` command line tool,
looked up the same way: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, then
`AWS_PROFILE`, then `~/.aws/credentials` and `~/.aws/config`. Single sign-on
works:

```bash
pip install 'potato-annotation[deploy-aws]'
aws sso login --profile lab                       # or: aws configure
potato deploy providers --verify                  # prints who AWS thinks you are
potato deploy up config.yaml --provider aws --aws-profile lab
```

Potato never writes AWS credentials anywhere. The profile name, if you gave
one, is recorded so that `status`, `pull` and `destroy` use the same account.

## Lightsail (`--provider aws`)

```bash
potato deploy up myproject/config.yaml --provider aws --dry-run
potato deploy up myproject/config.yaml --provider aws
```

This creates one instance running Ubuntu 24.04, gives it a static IP, and opens
ports 22, 80 and 443. Port 8000, where Potato itself listens, is never opened;
Caddy forwards to it over the loopback interface. The deploy key is generated
for this deployment only and stored in `.potato/secrets.json`. Your own SSH
keys are not used.

| Flag | Default | |
|---|---|---|
| `--region` | `us-east-1` | Any Lightsail region; the instance goes in zone `a`. |
| `--size` | `small_3_0` | 2 GB, $12/month. `medium_3_0` is 4 GB at $24/month. Smaller bundles are allowed but swap. |
| `--volume-gb` | none | Adds a Lightsail disk ($0.10/GB) and keeps the task on it. |

Without `--volume-gb`, annotations are stored on the instance's own SSD. They
survive restarts and reboots, but not `destroy`, so run `potato deploy pull`
first. The static IP is released on `destroy`, because Lightsail bills for one
that is not attached to an instance.

The certificate is issued for the static IP and lasts about six days, renewing
automatically. `potato deploy status` reports a renewal that fails. To use your
own domain, point an A record at the IP and pass `--domain`.

## EC2 (`--provider aws-ec2`)

```bash
potato deploy up myproject/config.yaml --provider aws-ec2
```

This launches a `t4g.small` (2 vCPU, 2 GB, Graviton) running Ubuntu 24.04 arm64
in the region's default VPC, with a security group allowing 22/80/443 and an
Elastic IP. The AMI is looked up from Canonical's public SSM parameter, so it is
always the current image. The instance requires IMDSv2.

If the region has no default VPC, pass a public subnet with `--subnet
subnet-…`. Use `--size t3.small` for an x86 instance.

`--volume-gb` adds a gp3 EBS volume. The volume is found by its NVMe id, not by
a device name, because on Nitro instances the name the volume is attached as
(`/dev/sdf`) is not the name Linux gives it.

## ECS Express Mode (`--provider aws-ecs`)

```bash
potato deploy up myproject/config.yaml --provider aws-ecs --backup hf --hf-token hf_...
```

This creates an ECS Express service: one 0.5 vCPU / 1 GB Fargate task behind a
load balancer that AWS creates and manages, at an `*.ecs.<region>.on.aws`
address with an AWS certificate. There is no server for you to maintain.

Before choosing it, know these three things:

- **The disk does not last.** The Express API has no setting for a volume, so
  the task's files are lost whenever the task is replaced. Potato refuses to
  deploy without `--backup`, and the backup is restored into each new task
  before the server starts. See [Backups](deploy-backups.md).
- **Deploys are changed to stop-then-start.** By default Express starts the new
  task before stopping the old one. That would leave two tasks, each restoring
  and backing up the same study, and the later write would overwrite the
  earlier one. After creating the service, Potato changes it to stop the old
  task first (`maximumPercent` 100) and reads the setting back. Every later
  `up` checks it again and refuses if it has changed. A redeploy therefore
  takes the task offline for a minute or two.
- **It is the most expensive option here,** mainly because of the load balancer
  and its public IPv4 addresses.

Secrets are stored in SSM Parameter Store as SecureStrings under
`/potato/<name>/` and passed to the container as ECS secrets, not as plain
environment variables. Logs go to the CloudWatch log group `/potato/<name>`
(30-day retention), which `potato deploy logs` reads.

Potato creates two IAM roles on first use, `potato-ecs-task-execution` and
`potato-ecs-express-infrastructure`. They are shared by all your ECS
deployments, and `destroy` leaves them in place.

## Permissions

If your IAM user or role is restricted, these are the actions each provider
calls. Every provider also calls `sts:GetCallerIdentity`, which needs no
permission.

**Lightsail:**

```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Resource": "*", "Action": [
  "lightsail:GetBundles", "lightsail:CreateInstances", "lightsail:GetInstance",
  "lightsail:DeleteInstance", "lightsail:AllocateStaticIp", "lightsail:AttachStaticIp",
  "lightsail:GetStaticIp", "lightsail:ReleaseStaticIp",
  "lightsail:PutInstancePublicPorts", "lightsail:CreateDisk", "lightsail:GetDisk",
  "lightsail:AttachDisk", "lightsail:DeleteDisk", "lightsail:TagResource"]}]}
```

**EC2:**

```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Resource": "*", "Action": [
  "ssm:GetParameter", "ec2:DescribeVpcs", "ec2:DescribeSubnets",
  "ec2:CreateSecurityGroup", "ec2:AuthorizeSecurityGroupIngress",
  "ec2:DeleteSecurityGroup", "ec2:RunInstances", "ec2:DescribeInstances",
  "ec2:TerminateInstances", "ec2:AllocateAddress", "ec2:AssociateAddress",
  "ec2:ReleaseAddress", "ec2:CreateVolume", "ec2:AttachVolume",
  "ec2:DescribeVolumes", "ec2:DeleteVolume", "ec2:CreateTags"]}]}
```

**ECS Express:**

```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Resource": "*", "Action": [
  "ecs:CreateExpressGatewayService", "ecs:UpdateExpressGatewayService",
  "ecs:DescribeExpressGatewayService", "ecs:DeleteExpressGatewayService",
  "ecs:UpdateService", "ecs:DescribeServices",
  "iam:GetRole", "iam:CreateRole", "iam:AttachRolePolicy", "iam:PutRolePolicy",
  "iam:PassRole", "iam:TagRole",
  "ssm:PutParameter", "ssm:GetParameter", "ssm:DeleteParameters",
  "logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:FilterLogEvents",
  "logs:DeleteLogGroup"]}]}
```

## Troubleshooting

**"AWS rejected the credentials"**: the SSO session has expired, or
`AWS_PROFILE` names a profile that does not exist. Run `aws sso login` and try
again.

**"Lightsail does not sell bundle …"**: bundle names change when prices do. The
error lists the bundles that are currently sold; pass one with `--size`.

**"This region has no default VPC"** (EC2): pass `--subnet` with a subnet that
has a route to an internet gateway.

**"This ECS service would start a new task before stopping the old one"**:
Express changed the deployment setting back. Rather than risk two tasks writing
the same study, Potato will not redeploy it. Run `destroy` and `up` (pull
first), or move the task to Lightsail.

**HTTPS does not work for the first few minutes** (Lightsail, EC2): the
certificate is requested once the instance is reachable. `potato deploy status`
reports TLS errors separately from the server being down.

## Related

- [Installing and running Potato](installation.md): choosing where to run
- [Deploying a task](one-command-deploy.md): the full lifecycle
- [Backups](deploy-backups.md)
- [Deploy buttons](deploy-buttons.md): a CloudFormation "Launch Stack" button for Lightsail
