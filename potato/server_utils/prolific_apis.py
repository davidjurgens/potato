"""
Utility functions for handling Prolific APIs

This module provides wrapper classes for interacting with the Prolific API
(https://api.prolific.com/api/v1/) to manage studies and submissions.

The Prolific API uses token-based authentication and returns JSON responses.
All endpoints require the Authorization header with format: 'Token {your_token}'

Key API Endpoints Used:
- GET /studies/ - List all studies
- GET /studies/{id}/ - Get study details
- GET /submissions/ - List all submissions
- GET /submissions?study={id} - Get submissions for a study
- GET /submissions/{id}/ - Get submission details
- GET /studies/{id}/submissions/ - Get recent submissions for a study
- POST /studies/{id}/transition/ - Change study status (START/PAUSE)

For more information, see: https://docs.prolific.com/api-reference
"""
import os.path
import pandas as pd
import requests
from collections import OrderedDict, defaultdict
import threading
import time
import json
import logging

logger = logging.getLogger(__name__)

# The base wrapper of prolific apis
class ProlificBase(object):
    """
    Base class for Prolific API operations.

    Provides low-level API access to Prolific's REST endpoints.
    All methods use token-based authentication and handle HTTP responses.

    Attributes:
        headers (dict): HTTP headers including Authorization token
    """

    def __init__(self, token):
        """
        Initialize the API client with authentication token.

        Args:
            token (str): Prolific API token for authentication
        """
        self.headers = {
            'Authorization': f'Token {token}',
        }

    def list_all_studies(self):
        """
        Retrieve all studies from Prolific.

        Makes a GET request to /api/v1/studies/ to fetch all studies
        associated with the authenticated account.

        Returns:
            pandas.DataFrame: DataFrame containing study information with columns:
                - id: Study identifier
                - name: Study name
                - study_type: Type of study
                - internal_name: Internal reference name
                - status: Current study status
            None: If the request fails
        """
        url = 'https://api.prolific.com/api/v1/studies/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            studies = pd.DataFrame.from_records(data['results'])
            print('You currently have %s studies'%len(data['results']))
            print(studies[['id','name','study_type','internal_name','status']].to_records())
            return studies
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_study_by_id(self, study_id):
        """
        Retrieve detailed information about a specific study.

        Makes a GET request to /api/v1/studies/{study_id}/ to fetch
        complete study details including configuration and status.

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            dict: Complete study information including:
                - id, name, internal_name
                - reward, average_reward_per_hour
                - external_study_url, status
                - total_available_places, places_taken
                - and other study configuration fields
            None: If the request fails
        """
        if study_id == None:
            study_id = self.study_id
        url = f'https://api.prolific.com/api/v1/studies/{study_id}/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            return data
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_submissions(self):
        """
        Retrieve all submissions across all studies.

        Makes a GET request to /api/v1/submissions/ to fetch all submissions.
        Note: This can be slow for accounts with many submissions.

        Returns:
            list: List of submission dictionaries containing:
                - id: Submission identifier
                - participant_id: Participant's Prolific ID
                - study_id: Associated study ID
                - status: Current submission status
                - and other submission details
            None: If the request fails
        """
        url = 'https://api.prolific.com/api/v1/submissions/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            print('You currently have %s submissions'%len(data['results']))
            return data['results']
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_submissions_from_study(self, study_id = None):
        """
        Retrieve all submissions for a specific study.

        Makes a GET request to /api/v1/submissions?study={study_id} to fetch
        submissions filtered by study ID.

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            list: List of submission dictionaries for the specified study
            None: If the request fails
        """
        if study_id == None:
            study_id = self.study_id
        api_endpoint = 'https://api.prolific.com/api/v1/submissions?study={}'
        url = api_endpoint.format(study_id)
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()['results']
            print('Successfully fetched %s submissions from study %s' % (len(data), study_id))
            return data
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_submission_from_id(self, submission_id):
        """
        Retrieve detailed information about a specific submission.

        Makes a GET request to /api/v1/submissions/{submission_id}/ to fetch
        complete submission details including participant info and status.

        Args:
            submission_id (str): Prolific submission ID

        Returns:
            dict: Complete submission information including:
                - id, participant_id, study_id
                - status: Current submission status
                - started_at, completed_at timestamps
                - and other submission details
            None: If the request fails
        """
        url = f'https://api.prolific.com/api/v1/submissions/{submission_id}/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            return data
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_recent_study_submissions(self, study_id):
        """
        Retrieve recent submissions for a specific study.

        Makes a GET request to /api/v1/studies/{study_id}/submissions/ to fetch
        recent submissions. This endpoint may return a subset of submissions
        compared to get_submissions_from_study().

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            list: List of recent submission dictionaries for the specified study
            None: If the request fails
        """
        if study_id == None:
            study_id = self.study_id
        url = f'https://api.prolific.com/api/v1/studies/{study_id}/submissions/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            print('You currently have %s submissions' % len(data['results']))
            return (data['results'])
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    def get_study_status(self, study_id = None):
        """
        Get the current status of a study.

        Retrieves study information and extracts the status field.

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            str: Study status (e.g., 'ACTIVE', 'PAUSED', 'COMPLETED')
            None: If the request fails
        """
        if study_id == None:
            study_id = self.study_id
        data = self.get_study_by_id(study_id)
        if data:
            return data['status']
        else:
            return None

    def pause_study(self, study_id = None):
        """
        Pause a study to stop new participants from joining.

        Makes a POST request to /api/v1/studies/{study_id}/transition/ with
        action "PAUSE" to change the study status to paused.

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            dict: Response from the transition API call
        """
        if study_id == None:
            study_id = self.study_id
        api_endpoint = 'https://api.prolific.com/api/v1/studies/{}/transition/'
        url = api_endpoint.format(study_id)
        data = {
                  "action": "PAUSE"
        }
        response = requests.post(url, headers=self.headers, json=data)
        data = response.json()
        print(study_id, self.get_study_status(study_id))
        return data

    def start_study(self, study_id = None):
        """
        Start a study to allow new participants to join.

        Makes a POST request to /api/v1/studies/{study_id}/transition/ with
        action "START" to change the study status to active.

        Args:
            study_id (str, optional): Prolific study ID. If None, uses self.study_id

        Returns:
            dict: Response from the transition API call
        """
        if study_id == None:
            study_id = self.study_id
        api_endpoint = 'https://api.prolific.com/api/v1/studies/{}/transition/'
        url = api_endpoint.format(study_id)
        data = {
                  "action": "START"
        }
        response = requests.post(url, headers=self.headers, json=data)
        data = response.json()
        print(study_id, self.get_study_status(study_id))
        return data


# The class to manage the status of a prolific study
class ProlificStudy(ProlificBase):
    """
    High-level study management class for Prolific studies.

    Extends ProlificBase to provide study-specific functionality including:
    - Submission tracking and status management
    - Workload monitoring and automatic study control
    - Local state persistence

    Attributes:
        study_id (str): Prolific study identifier
        study_info (dict): Cached study information
        submission_info_path (str): Path to local submission data file
        sessions (OrderedDict): Mapping of submission IDs to submission data
        user_status_dict (defaultdict): Mapping of status to participant IDs
        max_concurrent_sessions (int): Maximum allowed concurrent participants
        checker_period (int): Seconds between workload checks
        workload_checker_on (bool): Whether workload checker is running
    """

    def __init__(self, token, study_id, saving_dir, max_concurrent_sessions = 30, workload_checker_period = 60):
        """
        Initialize study management with configuration.

        Args:
            token (str): Prolific API token
            study_id (str): Prolific study identifier
            saving_dir (str): Directory to save submission data
            max_concurrent_sessions (int): Maximum concurrent participants (default: 30)
            workload_checker_period (int): Seconds between workload checks (default: 60)
        """
        ProlificBase.__init__(self, token)
        self.study_id = study_id
        self.study_info = self.get_study_by_id(study_id)
        self.submission_info_path = os.path.join(saving_dir, 'submissions.json')
        self.sessions = OrderedDict()
        self.user2session = {}
        # Must exist before the first update_submission_status() call: add_new_user
        # and get_concurrent_sessions_count read it on the login path.
        self.user_status_dict = defaultdict(set)
        self.study_status = None
        self.status_path = None
        self.max_concurrent_sessions = max_concurrent_sessions # How many users can work on the study at the same time
        self.checker_period = workload_checker_period
        self.workload_checker_remaining_time = workload_checker_period
        self.workload_checker_on = False
        self._monitor_thread = None
        self._monitor_stop = threading.Event()
        self._paused_by_monitor = False

    def get_basic_study_info(self):
        """
        Extract basic study information for display or logging.

        Returns:
            dict: Basic study information including:
                - id, name, internal_name
                - reward, average_reward_per_hour
                - external_study_url, status
                - total_available_places, places_taken
        """
        keys = ['id', 'name', 'internal_name',
                'reward', 'average_reward_per_hour', 'external_study_url', 'status', 'total_available_places', 'places_taken']
        return {key:self.study_info[key] for key in keys}

    def update_submission_status(self):
        """
        Refresh local submission data from Prolific API.

        Fetches current submission data from the API and updates local state:
        - Saves submission data to local JSON file
        - Updates sessions mapping
        - Rebuilds user status dictionary grouped by submission status

        The user_status_dict maps submission statuses to sets of participant IDs:
        - 'ACTIVE': Currently working participants
        - 'AWAITING REVIEW': Completed submissions pending review
        - 'APPROVED': Approved submissions
        - 'REJECTED': Rejected submissions
        - 'RETURNED': Participants who returned the study
        - 'TIMED-OUT': Participants who timed out
        """
        submission_data = self.get_submissions_from_study()
        if submission_data is None:
            logger.warning("Could not fetch submissions for study %s; keeping previous status data", self.study_id)
            return
        with open(self.submission_info_path, "wt") as f:
            for v in submission_data:
                f.writelines(json.dumps(v) + "\n")
        self.user_status_dict = defaultdict(set)
        for v in submission_data:
            self.sessions[v['id']] = v
            #self.user2session[v['participant_id']] = v['id']
            self.user_status_dict[v['status']].add(v['participant_id'])
        self.reclaim_dropped_user_assignments()

    def get_dropped_users(self):
        """
        Get list of participants who are no longer active.

        Returns:
            list: Participant IDs who have returned, timed out, or been rejected
        """
        return list(self.user_status_dict['RETURNED'] | self.user_status_dict['TIMED-OUT'] | self.user_status_dict['REJECTED'])

    def get_dropped_users_by_status(self):
        """
        Get dropped participant IDs grouped by Prolific submission status.

        Returns:
            dict: Mapping from RETURNED, TIMED-OUT, and REJECTED to participant IDs.
        """
        return {
            'RETURNED': list(self.user_status_dict['RETURNED']),
            'TIMED-OUT': list(self.user_status_dict['TIMED-OUT']),
            'REJECTED': list(self.user_status_dict['REJECTED']),
        }

    def reclaim_dropped_user_assignments(self):
        """
        Release unannotated Potato assignments for dropped Prolific workers.

        Prolific reports dropped workers as RETURNED, TIMED-OUT, or REJECTED.
        Their participant IDs are also the Potato usernames for url-direct
        Prolific login, so the item state manager can safely reclaim any
        assigned-but-unannotated instances.
        """
        dropped_by_status = self.get_dropped_users_by_status()
        if not any(dropped_by_status.values()):
            return {}

        status_to_reason = {
            'RETURNED': 'prolific_returned',
            'TIMED-OUT': 'prolific_timed_out',
            'REJECTED': 'prolific_rejected',
        }

        try:
            from potato.item_state_management import get_item_state_manager
            manager = get_item_state_manager()
            reclaimed = {}
            for status, user_ids in dropped_by_status.items():
                if not user_ids:
                    continue
                reclaimed.update(
                    manager.reclaim_unannotated_assignments_for_users(
                        user_ids,
                        reason=status_to_reason[status],
                    )
                )
            return reclaimed
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Could not reclaim assignments for dropped Prolific users: %s",
                e,
            )
            return {}

    def get_concurrent_sessions_count(self):
        """
        Get the number of currently active participants.

        Returns:
            int: Number of participants with 'ACTIVE' status
        """
        return len(self.user_status_dict['ACTIVE'])

    def check_workload_once(self):
        """
        Poll submissions once and pause/resume the study based on load.

        - Pauses the study when active participants reach max_concurrent_sessions.
        - Resumes the study when the count drops below 20% of the maximum,
          but only if this monitor was the one that paused it (a study paused
          manually by the researcher is never restarted).

        Returns:
            str or None: 'paused'/'resumed' if a transition was made, else None
        """
        self.update_submission_status()
        active = self.get_concurrent_sessions_count()
        if active >= self.max_concurrent_sessions:
            if not self._paused_by_monitor and self.get_study_status() == 'ACTIVE':
                logger.info("Workload monitor: %d active >= max %d, pausing study %s",
                            active, self.max_concurrent_sessions, self.study_id)
                self.pause_study()
                self._paused_by_monitor = True
                return 'paused'
        elif self._paused_by_monitor and active < 0.2 * self.max_concurrent_sessions:
            logger.info("Workload monitor: %d active < 20%% of max %d, resuming study %s",
                        active, self.max_concurrent_sessions, self.study_id)
            self.start_study()
            self._paused_by_monitor = False
            return 'resumed'
        return None

    def start_workload_monitor(self):
        """
        Start the background workload monitoring thread.

        Polls every checker_period seconds via check_workload_once(). Idempotent:
        calling while a monitor is already running has no effect. Use
        stop_workload_monitor() to terminate.
        """
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            logger.warning("Prolific workload monitor is already running")
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="ProlificWorkloadMonitor",
            daemon=True,
        )
        self._monitor_thread.start()
        self.workload_checker_on = True
        logger.info("Prolific workload monitor started (poll interval: %ss, max concurrent: %s)",
                    self.checker_period, self.max_concurrent_sessions)

    def stop_workload_monitor(self):
        """Stop the workload monitoring thread gracefully (safe if never started)."""
        self._monitor_stop.set()
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
            if self._monitor_thread.is_alive():
                logger.warning("Prolific workload monitor did not stop gracefully")
        self._monitor_thread = None
        self.workload_checker_on = False

    def _monitor_loop(self):
        while not self._monitor_stop.wait(self.checker_period):
            try:
                self.check_workload_once()
            except Exception as e:
                logger.warning("Prolific workload check failed: %s", e)

    def workload_checker(self):
        """Deprecated: use start_workload_monitor(). Kept for backwards compatibility."""
        logger.warning("workload_checker() is deprecated; use start_workload_monitor()")
        self.start_workload_monitor()

    def update_session_status(self, sess_id):
        """
        Update the status of a specific submission.

        Fetches current status from Prolific API and updates local session data.

        Args:
            sess_id (str): Submission ID to update
        """
        status = self.get_submission_from_id(sess_id)['status']
        self.sessions[sess_id]['status'] = status

    def add_new_user(self, user):
        """
        Add a new participant to the local session tracking.

        Fetches current submission status and adds to local state.

        Args:
            user (dict): User data containing 'SESSION_ID' and 'PROLIFIC_PID'

        Returns:
            str or None: The submission status, or None if it could not be fetched
        """
        submission = self.get_submission_from_id(user['SESSION_ID'])
        if not submission:
            logger.warning("Could not fetch Prolific submission %s for participant %s",
                           user.get('SESSION_ID'), user.get('PROLIFIC_PID'))
            return None
        status = submission['status']
        self.sessions[user['SESSION_ID']] = {'username': user['PROLIFIC_PID'], 'status': status}
        self.user2session[user['PROLIFIC_PID']] = user['SESSION_ID']
        self.user_status_dict[status].add(user['PROLIFIC_PID'])
        return status
