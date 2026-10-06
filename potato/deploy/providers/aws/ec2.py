"""Deploy a Potato task to an EC2 instance (``--provider aws-ec2``).

The same machine as ``--provider aws`` built from EC2 parts, for accounts where
Lightsail is unavailable or an institution requires EC2. It costs a little more
(the public IPv4 address, $3.65/month since February 2024, and the root disk
are billed separately) and needs more permissions: EC2 instances, security
groups, Elastic IPs and volumes, plus ``ssm:GetParameter`` to find the AMI.

Defaults: a ``t4g.small`` (2 vCPU, 2 GB, Graviton) running Ubuntu 24.04 arm64,
in the region's default VPC. The published Potato and Caddy images are
multi-arch, so arm64 needs nothing special.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from potato.deploy.providers.aws._aws import (
    AWSClient,
    caller_identity,
    is_not_found,
    wait_until,
)
from potato.deploy.providers.base import (
    Action,
    DeploySpec,
    ProviderError,
    register_provider,
)
from potato.deploy.providers.vm_base import PUBLIC_PORTS, VMProvider

DEFAULT_REGION = "us-east-1"
DEFAULT_TYPE = "t4g.small"
ROOT_GB = 30
DATA_DEVICE = "/dev/sdf"

# Canonical publishes the current Ubuntu AMI per region and architecture here.
AMI_PARAMETER = ("/aws/service/canonical/ubuntu/server/24.04/stable/current/"
                 "{arch}/hvm/ebs-gp3/ami-id")

# On-demand Linux, us-east-1, USD/month (730 h). Other regions differ by a few
# percent; the plan says "estimated".
TYPE_PRICES = {
    "t4g.small": 12.26, "t4g.medium": 24.53, "t4g.large": 49.06,
    "t3.small": 15.18, "t3.medium": 30.37, "t3.large": 60.74,
}
TYPE_MEMORY_MB = {
    "t4g.micro": 1024, "t4g.small": 2048, "t4g.medium": 4096, "t4g.large": 8192,
    "t3.micro": 1024, "t3.small": 2048, "t3.medium": 4096, "t3.large": 8192,
}
IPV4_PRICE = 3.65
GP3_PRICE_PER_GB = 0.08


def architecture(instance_type: str) -> str:
    """Graviton families carry a `g` after the generation digit: t4g, m7g, c8g."""
    family = instance_type.split(".")[0]
    return "arm64" if len(family) >= 3 and family[2:3] == "g" else "amd64"


def ebs_device_candidates(volume_id: str) -> List[str]:
    """Nitro exposes EBS as NVMe with the volume id in the by-id name."""
    return [f"/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_{volume_id.replace('-', '')}",
            "/dev/xvdf", "/dev/nvme1n1"]


def tag_spec(resource: str, deployment: str) -> Dict[str, Any]:
    return {"ResourceType": resource,
            "Tags": [{"Key": "Name", "Value": f"potato-{deployment}"},
                     {"Key": "potato", "Value": deployment}]}


def ingress_permissions() -> List[Dict[str, Any]]:
    """22/80/443 from anywhere, IPv4 and IPv6. Never 8000."""
    return [{"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
             "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
             "Ipv6Ranges": [{"CidrIpv6": "::/0"}]} for port in PUBLIC_PORTS]


def run_request(spec: DeploySpec, *, image_id: str, instance_type: str,
                security_group: str, user_data: str,
                subnet: Optional[str] = None) -> Dict[str, Any]:
    """The RunInstances call. Pure, so a test can assert it exactly."""
    request: Dict[str, Any] = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "UserData": user_data,
        "SecurityGroupIds": [security_group],
        "BlockDeviceMappings": [{
            "DeviceName": "/dev/sda1",
            "Ebs": {"VolumeSize": ROOT_GB, "VolumeType": "gp3",
                    "DeleteOnTermination": True},
        }],
        # IMDSv2 only: a process on the box cannot reach the metadata service
        # with a plain GET.
        "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
        "TagSpecifications": [tag_spec("instance", spec.name),
                              tag_spec("volume", spec.name)],
    }
    if subnet:
        request["SubnetId"] = subnet
    return request


@register_provider
class EC2Provider(VMProvider):
    """One EC2 instance with an Elastic IP, behind Caddy."""

    name = "aws-ec2"
    summary = "AWS EC2: a t4g.small VM with an Elastic IP, about $16/mo"
    requires = ("boto3", "paramiko")
    install_extra = "deploy-aws"
    ssh_user = "ubuntu"
    server_noun = "instance"
    server_id_key = "instance_id"
    default_region = DEFAULT_REGION
    default_size = DEFAULT_TYPE
    user_data_limit = 16 * 1024
    console_name = "the EC2 console"

    def __init__(self, token: Optional[str] = None, console=None):
        super().__init__(token=token, console=console)
        self.profile: Optional[str] = None
        self.subnet: Optional[str] = None

    def verify_credential(self):
        return caller_identity(self.profile or os.environ.get("AWS_PROFILE"))

    def _profile(self) -> Optional[str]:
        return self.profile or os.environ.get("AWS_PROFILE")

    def _api(self, region: Optional[str] = None) -> AWSClient:
        return AWSClient("ec2", region=region or DEFAULT_REGION, profile=self._profile())

    def _ssm(self, region: str) -> AWSClient:
        return AWSClient("ssm", region=region, profile=self._profile())

    def _bind(self, record) -> None:
        self.profile = self.profile or record.provider_ref.get("aws_profile")

    def memory_mb(self, size: str) -> Optional[int]:
        return TYPE_MEMORY_MB.get(size)

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> Optional[float]:
        if size not in TYPE_PRICES:
            return None
        cost = TYPE_PRICES[size] + IPV4_PRICE + ROOT_GB * GP3_PRICE_PER_GB
        if volume_gb:
            cost += float(volume_gb) * GP3_PRICE_PER_GB
        return round(cost, 2)

    def volume_device_hint(self, spec: DeploySpec) -> str:
        return DATA_DEVICE

    # -- plan ----------------------------------------------------------

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        arch = architecture(size)
        actions = [
            Action("aws.identity", "confirm the credentials with sts:GetCallerIdentity"),
            Action("ssh.keygen", "generate an ed25519 deploy key, delivered by cloud-init"),
            Action("ssm.ami", f"look up the current Ubuntu 24.04 {arch} AMI",
                   {"Name": AMI_PARAMETER.format(arch=arch)}),
            Action("ec2.vpc", "find the default VPC (or use --subnet)"),
            Action("ec2.security_group", "allow inbound 22/80/443 only; never 8000",
                   {"IpPermissions": ingress_permissions()}),
            Action("ec2.instance", f"launch a {size} in {region}",
                   run_request(spec, image_id="<ami>", instance_type=size,
                               security_group="<sg>", user_data="<cloud-init>")),
            Action("state.persist", "record the instance id before anything else can fail"),
            Action("wait.active", "poll until the instance is running"),
            Action("ec2.elastic_ip", "allocate an Elastic IP and associate it"),
        ]
        if spec.volume_gb:
            actions.append(Action("ec2.volume",
                                  f"create a {spec.volume_gb} GB gp3 volume and "
                                  f"attach it at {DATA_DEVICE}"))
        return actions

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store):
        self.profile = spec.extra.get("aws_profile") or self.profile
        self.subnet = spec.extra.get("subnet") or self.subnet
        if existing is not None:
            self._bind(existing)
        return super().create(spec, bundle, existing, store)

    def _check_account(self, api) -> None:
        caller_identity(self._profile())

    def _create_infrastructure(self, api, spec, record, store, *, region, size,
                               public_key, user_data_for: Callable) -> str:
        if self.profile:
            record.provider_ref["aws_profile"] = self.profile
        image_id = self._ssm(region).call(
            "get_parameter", Name=AMI_PARAMETER.format(arch=architecture(size))
        )["Parameter"]["Value"]

        vpc_id = self._vpc(api)
        group = api.call("create_security_group",
                         GroupName=f"potato-{spec.name}-{os.urandom(3).hex()}",
                         Description=f"Potato deployment {spec.name}: 22/80/443",
                         VpcId=vpc_id,
                         TagSpecifications=[tag_spec("security-group", spec.name)])
        record.provider_ref["security_group_id"] = group["GroupId"]
        store.upsert(record)
        api.call("authorize_security_group_ingress", GroupId=group["GroupId"],
                 IpPermissions=ingress_permissions())

        user_data = user_data_for(DATA_DEVICE if spec.volume_gb else None)
        self.console(f"Launching a {size} instance in {region}...")
        result = api.call("run_instances", **run_request(
            spec, image_id=image_id, instance_type=size,
            security_group=group["GroupId"], user_data=user_data,
            subnet=self.subnet))
        instance_id = result["Instances"][0]["InstanceId"]
        # Before anything else can fail: an instance nobody recorded bills forever.
        record.provider_ref["instance_id"] = instance_id
        store.upsert(record)

        self.console("Waiting for the instance to start...")
        if not wait_until(lambda: self._instance(api, instance_id).get("State", {})
                          .get("Name") == "running", timeout=600, interval=5):
            raise ProviderError(f"{instance_id} did not reach running within 10 minutes.")

        address = api.call("allocate_address", Domain="vpc",
                           TagSpecifications=[tag_spec("elastic-ip", spec.name)])
        record.provider_ref["allocation_id"] = address["AllocationId"]
        store.upsert(record)
        api.call("associate_address", AllocationId=address["AllocationId"],
                 InstanceId=instance_id)

        if spec.volume_gb:
            zone = self._instance(api, instance_id)["Placement"]["AvailabilityZone"]
            volume = api.call("create_volume", AvailabilityZone=zone,
                              Size=int(spec.volume_gb), VolumeType="gp3",
                              TagSpecifications=[tag_spec("volume", spec.name)])
            record.provider_ref["volume_id"] = volume["VolumeId"]
            record.provider_ref["volume_devices"] = ebs_device_candidates(volume["VolumeId"])
            store.upsert(record)
            wait_until(lambda: self._volume_state(api, volume["VolumeId"]) == "available",
                       timeout=300, interval=5)
            api.call("attach_volume", Device=DATA_DEVICE, InstanceId=instance_id,
                     VolumeId=volume["VolumeId"])
        return address["PublicIp"]

    def _vpc(self, api) -> Optional[str]:
        if self.subnet:
            subnets = api.call("describe_subnets", SubnetIds=[self.subnet])["Subnets"]
            return subnets[0]["VpcId"]
        vpcs = api.call("describe_vpcs",
                        Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
        if not vpcs:
            raise ProviderError(
                "This region has no default VPC. Pass --subnet <subnet-id> for a "
                "public subnet (one with a route to an internet gateway).")
        return vpcs[0]["VpcId"]

    def _instance(self, api, instance_id: str) -> Dict[str, Any]:
        try:
            reservations = api.call("describe_instances",
                                    InstanceIds=[instance_id])["Reservations"]
        except ProviderError as exc:
            if is_not_found(exc.__cause__ or exc):
                return {}
            raise
        instances = [i for r in reservations for i in r.get("Instances", [])]
        return instances[0] if instances else {}

    def _volume_state(self, api, volume_id: str) -> Optional[str]:
        volumes = api.call("describe_volumes", VolumeIds=[volume_id])["Volumes"]
        return volumes[0]["State"] if volumes else None

    # -- status / destroy ----------------------------------------------

    def status(self, record):
        self._bind(record)
        return super().status(record)

    def logs(self, record, **kwargs):
        self._bind(record)
        return super().logs(record, **kwargs)

    def pull(self, record, dest: str):
        self._bind(record)
        return super().pull(record, dest)

    def destroy(self, record, *, keep_data: bool = False) -> None:
        self._bind(record)
        super().destroy(record, keep_data=keep_data)

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        instance = self._instance(api, record.provider_ref["instance_id"])
        state = (instance.get("State") or {}).get("Name")
        if not instance or state in ("terminated", "shutting-down"):
            return "absent", instance
        return ("active" if state == "running" else state), instance

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        """Instance, then the address, the volume and the security group.

        The group and a detaching volume cannot be deleted while the instance
        still holds them, so each waits on the termination. An unassociated
        Elastic IP bills by the hour; it is always released.
        """
        reference = record.provider_ref
        instance_id = reference.get("instance_id")
        if instance_id:
            self._ignore_missing(lambda: api.call("terminate_instances",
                                                  InstanceIds=[instance_id]))
            self.console(f"Terminating {instance_id}...")
            wait_until(lambda: (self._instance(api, instance_id).get("State") or {})
                       .get("Name") in (None, "terminated"),
                       timeout=600, interval=10)

        if reference.get("allocation_id"):
            self._ignore_missing(lambda: api.call(
                "release_address", AllocationId=reference["allocation_id"]))
            self.console("Released the Elastic IP")

        volume_id = reference.get("volume_id")
        if volume_id and keep_data:
            self.console(f"Kept volume {volume_id}; it bills "
                         f"${GP3_PRICE_PER_GB:.2f}/GB per month until deleted.")
        elif volume_id:
            self._ignore_missing(lambda: api.call("delete_volume", VolumeId=volume_id))
            self.console(f"Deleted volume {volume_id}")

        group = reference.get("security_group_id")
        if group:
            def deleted() -> bool:
                try:
                    api.call("delete_security_group", GroupId=group)
                    return True
                except ProviderError as exc:
                    return is_not_found(exc.__cause__ or exc)
            if wait_until(deleted, timeout=180, interval=10):
                self.console("Deleted the security group")
            else:
                self.console(f"Security group {group} is still in use; remove it "
                             "in the EC2 console once the instance is gone.")

    @staticmethod
    def _ignore_missing(action) -> None:
        try:
            action()
        except ProviderError as exc:
            if not is_not_found(exc.__cause__ or exc):
                raise
