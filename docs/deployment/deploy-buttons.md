# Deploy Buttons

A deploy button sets up a copy of a task from its git repository in one click.
Use one when other people (collaborators, students, another lab) should be able
to run your task in their own accounts. `potato deploy button` writes the files
each host reads into your repository and prints the badge to put in your
README:

```bash
potato deploy button studies/pilot/config.yaml --target heroku \
    --backup hf --hf-backup-repo lab/pilot-annotations
git add app.json heroku.yml Dockerfile.potato .dockerignore studies/pilot/potato.deploy.yaml
git commit -m "Add a Deploy to Heroku button" && git push
```

Your own `config.yaml` is never changed. The command writes a copy beside it,
`potato.deploy.yaml`, with deployment settings applied (debug off, sessions
persisted) and the backup configured, and the generated files point at the
copy.

No secrets are written. Heroku and Render generate the session key and the
admin key when someone deploys. The AWS template generates them on the
instance. Backup credentials are asked for at deploy time.

## Targets

| `--target` | Files | What the person clicking needs |
|---|---|---|
| `heroku` | `app.json`, `heroku.yml`, `Dockerfile.potato` | a Heroku account and a backup token |
| `render` | `render.yaml`, `Dockerfile.potato` | a Render account and a backup token |
| `aws` | `potato-lightsail.cfn.yaml` | an AWS account; the repository must be public |
| `railway` | none (the command prints the steps) | a Railway account |

The Heroku and Render buttons deploy onto disks that do not last, and nobody
pulls from an AWS button's instance, so all three require `--backup`. The
person clicking supplies the token or key; `--hf-backup-repo` names the dataset
the backup goes to.

### AWS: "Launch Stack"

CloudFormation reads templates only from S3, so there is one more step:

```bash
potato deploy button config.yaml --target aws --backup hf --hf-backup-repo lab/r
aws s3 cp potato-lightsail.cfn.yaml s3://my-bucket/ --acl public-read
potato deploy button config.yaml --target aws --backup hf --hf-backup-repo lab/r \
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
