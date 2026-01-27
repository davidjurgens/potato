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

For more information, see: https://docs.prolific.com/reference/
"""
import os.path
import pandas as pd
import requests
from collections import OrderedDict, defaultdict
import time
import json

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
        #self.user_status_dict = {'RESERVED':set(), 'AWAITING REVIEW':set(), 'RETURNED':set(), 'TIMED-OUT':set(), 'ACTIVE': set(), 'APPROVED':set(), 'REJECTED':set()}
        self.study_status = None
        self.status_path = None
        self.max_concurrent_sessions = max_concurrent_sessions # How many users can work on the study at the same time
        self.checker_period = workload_checker_period
        self.workload_checker_remaining_time = workload_checker_period
        self.workload_checker_on = False

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
        with open(self.submission_info_path, "wt") as f:
            for v in submission_data:
                f.writelines(json.dumps(v) + "\n")
        self.user_status_dict = defaultdict(set)
        for v in submission_data:
            self.sessions[v['id']] = v
            #self.user2session[v['participant_id']] = v['id']
            self.user_status_dict[v['status']].add(v['participant_id'])

    def get_dropped_users(self):
        """
        Get list of participants who are no longer active.

        Returns:
            list: Participant IDs who have returned, timed out, or been rejected
        """
        return list(self.user_status_dict['RETURNED'] | self.user_status_dict['TIMED-OUT'] | self.user_status_dict['REJECTED'])

    def get_concurrent_sessions_count(self):
        """
        Get the number of currently active participants.

        Returns:
            int: Number of participants with 'ACTIVE' status
        """
        return len(self.user_status_dict['ACTIVE'])

    def workload_checker(self):
        """
        Monitor study workload and automatically manage study status.

        Periodically checks the number of active participants and automatically:
        - Pauses the study if too many participants are active
        - Resumes the study when active participants drop below threshold

        The threshold is 20% of max_concurrent_sessions. The checker runs
        continuously with the specified checker_period interval.

        This method runs in an infinite loop and should be called in a separate
        thread to avoid blocking the main application.
        """
        if self.workload_checker_on:
            print('Workload checker already in process, time remaining: %s seconds' % self.workload_checker_remaining_time)
            return None
        else:
            print('Workload checker started, checking every %s seconds'%self.checker_period)
            while True:
                self.workload_checker_remaining_time = self.checker_period
                self.workload_checker_on = True
                print(f"\rChecking workload in: {self.checker_period} seconds")
                #time.sleep(self.checker_period)
                for i in range(self.checker_period, 0, -1):
                    #print(f"\rChecking workload in: {i}s", end='', flush=True)
                    self.workload_checker_remaining_time -= 1
                    time.sleep(1)
                self.update_submission_status()
                if self.get_concurrent_sessions_count() < 0.2 * self.max_concurrent_sessions:
                    self.workload_checker_on = False
                    print('current workload: ', self.get_concurrent_sessions_count(), ', resuming study %s'%self.study_id)
                    self.start_study()
                    return None
                else:
                    print('current workload: ', self.get_concurrent_sessions_count(), ', starting another workload checker')

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
        """
        status = self.get_submission_from_id(user['SESSION_ID'])['status']
        self.sessions[user['SESSION_ID']] = {'username':user['PROLIFIC_PID'], 'status':status}
        self.session_status_dict[status].append(user['SESSION_ID'])