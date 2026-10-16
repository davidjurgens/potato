# Deploy Buttons

A deploy button sets up a copy of a task from its git repository in one click.
Use one when other people (collaborators, students, another lab) should be able
to run your task in their own accounts. `potato deploy button` writes the files
each host reads into your repository and prints the badge to put in your
README:

```bash
potato deploy button studies/pilot/config.yaml --target heroku --backup hf
git add app.json heroku.yml Dockerfile.potato .dockerignore studies/pilot/potato.deploy.yaml
git commit -m "Add a Deploy to Heroku button" && git push
```

Your own `config.yaml` is never changed. The command writes a copy beside it,
`potato.deploy.yaml`, with deployment settings applied (debug off, sessions
persisted) and the backup configured, and the generated files point at the
copy.

No secrets are written. Heroku and Render generate the session key and the
admin key when someone deploys. The AWS template generates them on the
instance.

The backup destination is not written either. Each person who deploys the
button names their own HuggingFace dataset or S3 bucket, along with its
credentials, and `potato.deploy.yaml` reads them from the environment. Their
annotations go to storage they own, and a new deployment restores only from
that storage.

## Settings each deployer supplies

| Backup | Setting | Required |
|---|---|---|
| `--backup hf` | `POTATO_BACKUP_HF_REPO`: their dataset, as `<account>/<name>`. It is created, private, if it does not exist | yes |
| | `HF_TOKEN`: a token with write access to that dataset | yes |
| `--backup s3` | `POTATO_BACKUP_S3_BUCKET`: their bucket | yes |
| | `POTATO_BACKUP_S3_REGION`: the bucket's region | no |
| | `POTATO_BACKUP_S3_ENDPOINT`: an S3-compatible endpoint (R2, MinIO); empty for AWS | no |
| | `POTATO_S3_ACCESS_KEY_ID`, `POTATO_S3_SECRET_ACCESS_KEY` | yes |

Heroku asks for these as config vars and Render as Blueprint environment
variables. Neither has a default. The AWS template takes them as stack
parameters (`HfBackupRepo`, `HfToken`, `S3Bucket`, `S3Region`, `S3Endpoint`,
`S3AccessKeyId`, `S3SecretAccessKey`). CloudFormation will not create the
stack without the dataset or bucket. If one is missing on a running server,
the server logs an error naming the variable and backs up nothing.

The S3 key prefix, `potato/<name>` unless you pass `--s3-prefix`, is written
into the files. It is a path inside the deployer's bucket.

`--hf-backup-repo`, `--hf-token`, `--s3-bucket`, `--s3-region` and
`--s3-endpoint` are ignored by `button`, and the command says so. Through
2.11.1 `--hf-backup-repo` was written into `potato.deploy.yaml`, so every
deployment backed up to the author's dataset and a new deployment restored the
author's annotators from it. Regenerate a button made with 2.11.1 or earlier
with `--force` and commit the result.

## Targets

| `--target` | Files | What the person clicking needs |
|---|---|---|
| `heroku` | `app.json`, `heroku.yml`, `Dockerfile.potato` | a Heroku account and their own backup storage |
| `render` | `render.yaml`, `Dockerfile.potato` | a Render account and their own backup storage |
| `aws` | `potato-lightsail.cfn.yaml` | an AWS account and their own backup storage; the repository must be public |
| `railway` | none (the command prints the steps) | a Railway account |

The Heroku and Render buttons deploy onto disks that do not last, and nobody
pulls from an AWS button's instance, so all three require `--backup`.

### AWS: "Launch Stack"

CloudFormation reads templates only from S3, so there is one more step:

```bash
potato deploy button config.yaml --target aws --backup hf
aws s3 cp potato-lightsail.cfn.yaml s3://my-bucket/ --acl public-read
potato deploy button config.yaml --target aws --backup hf \
    --template-url https://my-bucket.s3.amazonaws.com/potato-lightsail.cfn.yaml --force
```

The stack creates a Lightsail instance ($12/month) and a static IP. The
instance clones your public repository, generates its secrets, waits for the
static IP to stop changing, and starts Potato with a certificate for that IP.
The stack's `URL` output is the address to give annotators. It is ready a few
minutes after the stack completes. The admin key is on the instance; read it
from Lightsail's browser SSH with `sudo grep ADMIN /opt/potato/potato.env`.

## Before you push

The command checks two things and prints a warning for each problem it finds:

- **`.dockerignore`.** Heroku and Render build an image from your repository,
  and `.potato/` (the admin key and deploy secrets), `annotation_output/` and
  the SQLite databases must not be built into it. If the repository has no
  `.dockerignore`, the command writes one. If one exists but is missing
  entries, the command lists them for you to add.
- **`.gitignore`.** A button deploys from your pushed repository, so the same
  files must not be committed. Any that `git check-ignore` does not report as
  ignored are listed.

## Options

`--dry-run` prints the files without writing them. Existing files are not
replaced unless you pass `--force`. `--image` pins a specific Potato image tag.

## Related

- [Backups](deploy-backups.md)
- [Heroku](deploy-heroku.md), [Render](deploy-render.md), [AWS](deploy-aws.md),
  [Railway](deploy-railway.md)
