# Deploying to Hetzner, Vultr or Linode

These three providers rent ordinary virtual machines. Potato sets each one up
the same way it does [DigitalOcean](deploy-digitalocean.md): a deploy key
generated for that deployment, a firewall that allows only 22/80/443, Docker,
Caddy with a Let's Encrypt certificate for the machine's IP address, and Potato
running as a systemd service. `deploy logs`, `deploy pull` over SSH and
`--volume-gb` work on all three.

| | `--provider hetzner` | `--provider vultr` | `--provider linode` |
|---|---|---|---|
| Default size | `cx23`: 2 vCPU, 4 GB | `vc2-1c-2gb`: 1 vCPU, 2 GB | `g6-standard-1`: 1 vCPU, 2 GB |
| Monthly | about €6 (€5.49 plus €0.50 for IPv4) | $10 | $12 |
| Default region | `nbg1` (Nuremberg) | `ewr` (New Jersey) | `us-east` (Newark) |
| Token variable | `HCLOUD_TOKEN` | `VULTR_API_KEY` | `LINODE_TOKEN` |
| Billed | in euros | in dollars | in dollars |

```bash
export HCLOUD_TOKEN=...
potato deploy up myproject/config.yaml --provider hetzner
```

## Hetzner

The cheapest of the three, even after Hetzner's two price rises in 2026, and it
has the most memory for the price. It bills in euros, from a company based in
Germany, and some institutions' purchasing rules don't allow that.

The `cx` server types are sold only in the European locations. In the US
locations (`ash`, `hil`), pass a `cpx` type with `--size`; if you don't, Potato
stops before creating anything and lists the locations that sell the type you
asked for.

Create the token in the Hetzner Cloud console, under the project's Security
section, with read and write permission.

## Vultr

The API key needs your machine's IP address added to its access-control list in
the Vultr dashboard, or every request returns 401. Block storage is attached
after the instance starts, and the setup waits for the device to appear before
it formats and mounts it.

## Linode

Linode requires a root password when a machine is created, even when SSH keys
are supplied. Potato generates one, stores it in `.potato/secrets.json`, and
turns off password login over SSH, so the password cannot be used to log in.
The token needs read and write access to Linodes, Firewalls and Volumes.

## Related

- [DigitalOcean](deploy-digitalocean.md): the same setup, documented in full
- [Installing and running Potato](installation.md)
- [Getting annotations back](deploy-pull.md)
