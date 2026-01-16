"""
Utility functions for handling Amazon Mechanical Turk APIs.

This module provides wrapper classes for interacting with the MTurk API
via boto3 to manage HITs and assignments.

The MTurk API requires AWS credentials and uses different endpoints for
sandbox (testing) and production environments.

Key API Operations:
- GET account balance
- LIST HITs
- GET HIT details
- LIST assignments for a HIT
- APPROVE/REJECT assignments

For more information, see:
https://docs.aws.amazon.com/mturk/index.html
"""
import os
import json
import logging
from collections import OrderedDict, defaultdict

logger = logging.getLogger(__name__)

# Optional boto3 import - only required if using MTurk API features
try:
    import boto3
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.debug("boto3 not available - MTurk API features will be disabled")


class MTurkBase:
    """
    Base class for MTurk API operations.

    Provides low-level API access to Amazon Mechanical Turk's REST endpoints.
    All methods use AWS credential-based authentication via boto3.

    Attributes:
        client: boto3 MTurk client
        sandbox (bool): Whether using sandbox environment
    """

    # MTurk API endpoints
    SANDBOX_ENDPOINT = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com'
    PRODUCTION_ENDPOINT = 'https://mturk-requester.us-east-1.amazonaws.com'

    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None, sandbox=True):
        """
        Initialize the MTurk API client with AWS credentials.

        Args:
            aws_access_key_id (str, optional): AWS access key ID.
                If not provided, uses environment variable or ~/.aws/credentials
            aws_secret_access_key (str, optional): AWS secret access key.
                If not provided, uses environment variable or ~/.aws/credentials
            sandbox (bool): If True, use sandbox environment for testing.
                Default is True (sandbox mode).
        """
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for MTurk API features. "
                "Install it with: pip install boto3"
            )

        self.sandbox = sandbox
        endpoint_url = self.SANDBOX_ENDPOINT if sandbox else self.PRODUCTION_ENDPOINT

        # Build client kwargs
        client_kwargs = {
            'service_name': 'mturk',
            'region_name': 'us-east-1',
            'endpoint_url': endpoint_url
        }

        # Add credentials if provided explicitly
        if aws_access_key_id:
            client_kwargs['aws_access_key_id'] = aws_access_key_id
        if aws_secret_access_key:
            client_kwargs['aws_secret_access_key'] = aws_secret_access_key

        self.client = boto3.client(**client_kwargs)

        env_type = "SANDBOX" if sandbox else "PRODUCTION"
        logger.info(f"MTurk API client initialized ({env_type})")

    def get_account_balance(self):
        """
        Get the MTurk account balance.

        Returns:
            str: Available balance (e.g., "10000.00" for sandbox, actual balance for production)

        Raises:
            ClientError: If the API request fails
        """
        try:
            response = self.client.get_account_balance()
            balance = response['AvailableBalance']
            logger.debug(f"MTurk account balance: {balance}")
            return balance
        except ClientError as e:
            logger.error(f"Failed to get account balance: {e}")
            raise

    def list_hits(self, max_results=100):
        """
        List all HITs in the account.

        Args:
            max_results (int): Maximum number of HITs to return (default: 100)

        Returns:
            list: List of HIT dictionaries containing:
                - HITId: HIT identifier
                - Title: HIT title
                - HITStatus: Current status
                - MaxAssignments: Total assignments available
                - NumberOfAssignmentsCompleted: Completed count
                - NumberOfAssignmentsPending: Pending count
                - NumberOfAssignmentsAvailable: Available count
        """
        try:
            response = self.client.list_hits(MaxResults=max_results)
            hits = response.get('HITs', [])
            logger.debug(f"Listed {len(hits)} HITs")
            return hits
        except ClientError as e:
            logger.error(f"Failed to list HITs: {e}")
            raise

    def get_hit(self, hit_id):
        """
        Get detailed information about a specific HIT.

        Args:
            hit_id (str): The HIT identifier

        Returns:
            dict: Complete HIT information including:
                - HITId, HITTypeId
                - Title, Description, Question
                - HITStatus: ASSIGNABLE, UNASSIGNABLE, REVIEWABLE, etc.
                - MaxAssignments, Reward, AssignmentDurationInSeconds
                - Creation/Expiration times
        """
        try:
            response = self.client.get_hit(HITId=hit_id)
            hit = response.get('HIT', {})
            logger.debug(f"Retrieved HIT {hit_id}: status={hit.get('HITStatus')}")
            return hit
        except ClientError as e:
            logger.error(f"Failed to get HIT {hit_id}: {e}")
            raise

    def list_assignments_for_hit(self, hit_id, assignment_statuses=None, max_results=100):
        """
        Get assignments for a specific HIT.

        Args:
            hit_id (str): The HIT identifier
            assignment_statuses (list, optional): Filter by status.
                Valid values: 'Submitted', 'Approved', 'Rejected'
            max_results (int): Maximum number of assignments to return

        Returns:
            list: List of assignment dictionaries containing:
                - AssignmentId: Assignment identifier
                - WorkerId: Worker's MTurk ID
                - HITId: Associated HIT ID
                - AssignmentStatus: Submitted, Approved, or Rejected
                - AcceptTime, SubmitTime
                - Answer: Worker's submitted answer (XML format)
        """
        try:
            params = {
                'HITId': hit_id,
                'MaxResults': max_results
            }
            if assignment_statuses:
                params['AssignmentStatuses'] = assignment_statuses

            response = self.client.list_assignments_for_hit(**params)
            assignments = response.get('Assignments', [])
            logger.debug(f"Listed {len(assignments)} assignments for HIT {hit_id}")
            return assignments
        except ClientError as e:
            logger.error(f"Failed to list assignments for HIT {hit_id}: {e}")
            raise

    def approve_assignment(self, assignment_id, requester_feedback=""):
        """
        Approve an assignment.

        Args:
            assignment_id (str): The assignment identifier
            requester_feedback (str, optional): Feedback message to worker

        Returns:
            dict: Empty dict on success

        Raises:
            ClientError: If approval fails (e.g., already approved/rejected)
        """
        try:
            response = self.client.approve_assignment(
                AssignmentId=assignment_id,
                RequesterFeedback=requester_feedback,
                OverrideRejection=False
            )
            logger.info(f"Approved assignment {assignment_id}")
            return response
        except ClientError as e:
            logger.error(f"Failed to approve assignment {assignment_id}: {e}")
            raise

    def reject_assignment(self, assignment_id, requester_feedback):
        """
        Reject an assignment.

        Args:
            assignment_id (str): The assignment identifier
            requester_feedback (str): Required feedback explaining rejection

        Returns:
            dict: Empty dict on success

        Raises:
            ClientError: If rejection fails
        """
        try:
            response = self.client.reject_assignment(
                AssignmentId=assignment_id,
                RequesterFeedback=requester_feedback
            )
            logger.info(f"Rejected assignment {assignment_id}")
            return response
        except ClientError as e:
            logger.error(f"Failed to reject assignment {assignment_id}: {e}")
            raise

    def get_assignment(self, assignment_id):
        """
        Get detailed information about a specific assignment.

        Args:
            assignment_id (str): The assignment identifier

        Returns:
            dict: Complete assignment information
        """
        try:
            response = self.client.get_assignment(AssignmentId=assignment_id)
            assignment = response.get('Assignment', {})
            logger.debug(f"Retrieved assignment {assignment_id}")
            return assignment
        except ClientError as e:
            logger.error(f"Failed to get assignment {assignment_id}: {e}")
            raise


class MTurkHIT(MTurkBase):
    """
    High-level HIT management class for MTurk.

    Extends MTurkBase to provide HIT-specific functionality including:
    - Assignment tracking and status management
    - Batch approval/rejection
    - Worker tracking

    Attributes:
        hit_id (str): MTurk HIT identifier
        hit_info (dict): Cached HIT information
        assignments (OrderedDict): Mapping of assignment IDs to assignment data
        worker_status (defaultdict): Mapping of status to worker IDs
    """

    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None,
                 hit_id=None, sandbox=True):
        """
        Initialize HIT management with configuration.

        Args:
            aws_access_key_id (str, optional): AWS access key ID
            aws_secret_access_key (str, optional): AWS secret access key
            hit_id (str, optional): MTurk HIT identifier to manage
            sandbox (bool): Whether to use sandbox environment (default: True)
        """
        super().__init__(aws_access_key_id, aws_secret_access_key, sandbox)

        self.hit_id = hit_id
        self.hit_info = None
        self.assignments = OrderedDict()
        self.worker_status = defaultdict(set)

        if hit_id:
            try:
                self.hit_info = self.get_hit(hit_id)
                logger.info(f"Initialized MTurkHIT for HIT {hit_id}")
            except ClientError as e:
                logger.warning(f"Could not fetch HIT info: {e}")

    def get_basic_hit_info(self):
        """
        Extract basic HIT information for display or logging.

        Returns:
            dict: Basic HIT information including:
                - HITId, Title, HITStatus
                - MaxAssignments, Reward
                - NumberOfAssignmentsCompleted/Pending/Available
        """
        if not self.hit_info:
            return {}

        keys = [
            'HITId', 'Title', 'HITStatus', 'MaxAssignments', 'Reward',
            'NumberOfAssignmentsCompleted', 'NumberOfAssignmentsPending',
            'NumberOfAssignmentsAvailable'
        ]
        return {key: self.hit_info.get(key) for key in keys if key in self.hit_info}

    def refresh_assignments(self):
        """
        Refresh local assignment data from MTurk API.

        Fetches current assignment data from the API and updates local state:
        - Updates assignments mapping
        - Rebuilds worker status dictionary grouped by assignment status
        """
        if not self.hit_id:
            logger.warning("No HIT ID set, cannot refresh assignments")
            return

        try:
            # Get all assignments regardless of status
            assignments = self.list_assignments_for_hit(self.hit_id)

            self.assignments = OrderedDict()
            self.worker_status = defaultdict(set)

            for assignment in assignments:
                assignment_id = assignment['AssignmentId']
                self.assignments[assignment_id] = assignment
                worker_id = assignment['WorkerId']
                status = assignment['AssignmentStatus']
                self.worker_status[status].add(worker_id)

            logger.info(f"Refreshed {len(assignments)} assignments for HIT {self.hit_id}")
        except ClientError as e:
            logger.error(f"Failed to refresh assignments: {e}")

    def get_pending_assignments(self):
        """
        Get assignments pending review (submitted but not approved/rejected).

        Returns:
            list: List of assignment dictionaries with 'Submitted' status
        """
        return self.list_assignments_for_hit(
            self.hit_id,
            assignment_statuses=['Submitted']
        )

    def get_approved_assignments(self):
        """
        Get approved assignments.

        Returns:
            list: List of assignment dictionaries with 'Approved' status
        """
        return self.list_assignments_for_hit(
            self.hit_id,
            assignment_statuses=['Approved']
        )

    def get_rejected_assignments(self):
        """
        Get rejected assignments.

        Returns:
            list: List of assignment dictionaries with 'Rejected' status
        """
        return self.list_assignments_for_hit(
            self.hit_id,
            assignment_statuses=['Rejected']
        )

    def auto_approve_all(self, feedback="Thank you for your work!"):
        """
        Approve all pending (submitted) assignments.

        Args:
            feedback (str): Feedback message to send to workers

        Returns:
            int: Number of assignments approved
        """
        pending = self.get_pending_assignments()
        approved_count = 0

        for assignment in pending:
            try:
                self.approve_assignment(assignment['AssignmentId'], feedback)
                approved_count += 1
            except ClientError as e:
                logger.warning(f"Failed to approve {assignment['AssignmentId']}: {e}")

        logger.info(f"Auto-approved {approved_count} assignments")
        return approved_count

    def get_worker_ids_by_status(self, status):
        """
        Get worker IDs filtered by assignment status.

        Args:
            status (str): Assignment status ('Submitted', 'Approved', 'Rejected')

        Returns:
            set: Set of worker IDs with the specified status
        """
        self.refresh_assignments()
        return self.worker_status.get(status, set())

    def get_completed_workers(self):
        """
        Get list of workers who have completed (submitted or approved) assignments.

        Returns:
            set: Set of worker IDs
        """
        self.refresh_assignments()
        return (self.worker_status.get('Submitted', set()) |
                self.worker_status.get('Approved', set()))


# Module-level singleton instance
_mturk_hit = None


def init_mturk_hit(config):
    """
    Initialize the global MTurk HIT manager from configuration.

    Args:
        config (dict): Configuration dictionary containing:
            - mturk.config_file_path: Path to MTurk config YAML file

    The MTurk config file should contain:
        - aws_access_key_id: AWS access key (optional, uses env/credentials file)
        - aws_secret_access_key: AWS secret key (optional)
        - sandbox: Whether to use sandbox (default: True)
        - hit_id: Optional HIT ID to manage

    Returns:
        MTurkHIT: Initialized MTurk HIT manager, or None if not configured
    """
    global _mturk_hit

    if not BOTO3_AVAILABLE:
        logger.warning("boto3 not available, MTurk API disabled")
        return None

    mturk_config = config.get('mturk', {})
    if not mturk_config.get('enabled', False):
        logger.debug("MTurk API not enabled in config")
        return None

    config_file_path = mturk_config.get('config_file_path')
    if not config_file_path:
        logger.warning("MTurk enabled but no config_file_path specified")
        return None

    try:
        import yaml
        with open(config_file_path, 'r') as f:
            mturk_settings = yaml.safe_load(f)

        _mturk_hit = MTurkHIT(
            aws_access_key_id=mturk_settings.get('aws_access_key_id'),
            aws_secret_access_key=mturk_settings.get('aws_secret_access_key'),
            hit_id=mturk_settings.get('hit_id'),
            sandbox=mturk_settings.get('sandbox', True)
        )

        logger.info(f"MTurk HIT manager initialized from {config_file_path}")
        return _mturk_hit

    except FileNotFoundError:
        logger.error(f"MTurk config file not found: {config_file_path}")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize MTurk HIT manager: {e}")
        return None


def get_mturk_hit():
    """
    Get the global MTurk HIT manager instance.

    Returns:
        MTurkHIT: The MTurk HIT manager, or None if not initialized
    """
    return _mturk_hit


def clear_mturk_hit():
    """
    Clear the global MTurk HIT manager instance.

    Used primarily for testing to reset state between tests.
    """
    global _mturk_hit
    _mturk_hit = None
