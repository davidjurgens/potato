"""AWS deploy targets.

Three, because AWS has no single obvious answer:

* ``aws`` (Lightsail) — the default and the one to recommend. A VM with a flat
  monthly price that includes IPv4, an SSD and transfer; only ``lightsail:*``
  permissions; HTTPS from a Let's Encrypt IP certificate.
* ``aws-ec2`` — the same machine built from EC2 parts, for accounts where
  Lightsail is not available or an institution mandates EC2.
* ``aws-ecs`` — ECS Express Mode on Fargate with EFS: no server to manage and a
  real HTTPS hostname, at several times the price.

App Runner closed to new customers on 2026-04-30, and Lightsail Container
Services have no persistent storage, so neither is offered.
"""
