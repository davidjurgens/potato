# Deploying to Jetstream2 and other OpenStack clouds

```bash
pip install 'potato-annotation[deploy-openstack]'
potato deploy up myproject/config.yaml --provider openstack --cloud jetstream2
```

[Jetstream2](https://jetstream-cloud.org) is an NSF-funded research cloud. With
an ACCESS allocation it costs you nothing, and every instance gets a DNS name,
so the task is served at `https://potato-<name>.<allocation>.projects.jetstream-cloud.org`
with an ordinary 90-day Let's Encrypt certificate.

The same provider works on campus OpenStack clouds and on EGI's federated cloud.
On those, the task is served at the floating IP address with an IP certificate,
as on the other [VM providers](deploy-vps.md).

## Getting access to Jetstream2

1. Request an ACCESS **Explore** allocation (<https://allocations.access-ci.org>)
   and ask for Jetstream2 CPU time. Explore allocations are usually approved
   within days.
2. In Horizon (<https://js2.jetstream-cloud.org>), create an **application
   credential** and download its `clouds.yaml`.
3. Put the file in `~/.config/openstack/clouds.yaml`. The entry name is what
   you pass to `--cloud`; name it `jetstream2` to get the defaults below.

`potato deploy providers --verify` confirms that the credential works.

## What it creates

| | Jetstream2 default | Flag |
|---|---|---|
| Flavor | `m3.small` (2 vCPU, 6 GB) | `--size` |
| Image | `Featured-Ubuntu24` | `--os-image` |
| Network | the project's auto-allocated network | `--network` |
| Floating IP | from the `public` network | |
| Security group | inbound 22/80/443 only | |
| Volume | with `--volume-gb` | |

Images on different clouds log in as different users (`ubuntu`, `exouser`,
`cloud-user`), so cloud-init creates a `potato-deploy` user with the deploy key
and passwordless sudo, and Potato connects as that user.

An `m3.small` uses 2 SUs (service units, the allocation's currency) per hour.
Left running for a year, that is about 17,500 SUs, so destroy the instance when
the study ends.

## Managing the instance

```bash
potato deploy status config.yaml
potato deploy logs config.yaml -f
potato deploy pull config.yaml
potato deploy destroy config.yaml
```

## Troubleshooting

**"No --network given and this project has no auto-allocated network"**: create
a network and router in Horizon or Exosphere and pass `--network <name>`.

**The certificate takes a few minutes**: Jetstream2 publishes the instance's
DNS name a minute or two after the floating IP is attached. Potato waits for it
before configuring Caddy, and the certificate is issued once the name resolves.

## Related

- [Installing and running Potato](installation.md)
- [VM providers](deploy-vps.md)
