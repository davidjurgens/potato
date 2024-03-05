"""
Utility functions for handling prolific apis

"""
import os.path
import pandas as pd
import requests
from collections import OrderedDict, defaultdict
import time
import json

# The base wrapper of prolific apis
class ProlificBase(object):
    def __init__(self, token):
        self.headers = {
            'Authorization': f'Token {token}',
        }

    # list all the studies
    def list_all_studies(self):
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

    # get the information of a prolific study using the study id
    def get_study_by_id(self, study_id):
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

    #get all submissions, might be super slow when you have a long list of submissions
    def get_submissions(self):
        url = 'https://api.prolific.com/api/v1/submissions/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            print('You currently have %s submissions'%len(data['results']))
            return data['results']
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    # get the list of submissions from a study
    def get_submissions_from_study(self, study_id = None):
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
        #print(len(data))
        #print(data.keys())


    # get the status of a specific submission
    def get_submission_from_id(self, submission_id):
        url = f'https://api.prolific.com/api/v1/submissions/{submission_id}/'
        response = requests.get(url, headers=self.headers)
        if response.status_code == 200:
            data = response.json()  # If the response contains JSON data
            return data
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None

    # get the list of recent submissions from a study
    def get_recent_study_submissions(self, study_id):
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

    #get study status
    def get_study_status(self, study_id = None):
        if study_id == None:
            study_id = self.study_id
        data = self.get_study_by_id(study_id)
        if data:
            return data['status']
        else:
            return None

    #pause study based on the given study id, if id not given, use the study id
    #in the current object
    def pause_study(self, study_id = None):
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

    #start study based on the given study id, if id not given, use the study id
    #in the current object
    def start_study(self, study_id = None):
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
    def __init__(self, token, study_id, saving_dir, max_concurrent_sessions = 30, workload_checker_period = 60):
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

    #get the basic study information and return them as a dict
    def get_basic_study_info(self):
        keys = ['id', 'name', 'internal_name',
                'reward', 'average_reward_per_hour', 'external_study_url', 'status', 'total_available_places', 'places_taken']
        return {key:self.study_info[key] for key in keys}

    #update the submission status
    def update_submission_status(self):
        submission_data = self.get_submissions_from_study()
        with open(self.submission_info_path, "wt") as f:
            for v in submission_data:
                f.writelines(json.dumps(v) + "\n")
        self.user_status_dict = defaultdict(set)
        for v in submission_data:
            self.sessions[v['id']] = v
            #self.user2session[v['participant_id']] = v['id']
            self.user_status_dict[v['status']].add(v['participant_id'])

    # return a full list of usernames who have returned/timed-out the task or who have been rejected
    def get_dropped_users(self):
        return list(self.user_status_dict['RETURNED'] | self.user_status_dict['TIMED-OUT'] | self.user_status_dict['REJECTED'])

    # return the amount of ACTIVE session/users
    def get_concurrent_sessions_count(self):
        return len(self.user_status_dict['ACTIVE'])


    # periodically check the amount of active users, if the amount of active users is below 20% of the
    # max_concurrent_sessions resume the study on prolific
    def workload_checker(self):
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
    '''
    
    def update_active_session_status(self):
        updated_active_session_ids = []
        for sess_id in self.session_status_sets['active']:
            status = self.get_submission_from_id(sess_id)['status']
            self.sessions[sess_id] = status
            if status != 'ACTIVE':
                self.session_status_dict[status].append(sess_id)
            else:
                updated_active_session_ids.append(sess_id)
        self.session_status_sets['active'] = updated_active_session_ids
    '''

    def update_session_status(self, sess_id):
        status = self.get_submission_from_id(sess_id)['status']
        self.sessions[sess_id]['status'] = status

    def add_new_user(self, user):
        status = self.get_submission_from_id(user['SESSION_ID'])['status']
        self.sessions[user['SESSION_ID']] = {'username':user['PROLIFIC_PID'], 'status':status}
        self.session_status_dict[status].append(user['SESSION_ID'])

'''

prolific = ProlificStudy(token = 'yRB91_ngkHclqd36bhXCGWwl5fqU4iVlXX-2i61cfNoh7Tpvh4tH8R6IAxEBsYrkMnyc4X8tEpmmJhHXiHiRkFZYIm_Jr-pCoXFqyrIHX30qUuT5RMcIc7rG',
                         study_id='6498cf2053b6c5b98075f52c', saving_dir='../')
prolific.list_all_studies()

#print(prolific.get_submissions_from_study())
print(prolific.get_study_status())
#prolific.start_study()
#prolific.pause_study()

#prolific.get_study_by_id('651d90aa31f42a08bce57feb')
#prolific.get_recent_study_submissions('651d90aa31f42a08bce57feb')
#print(prolific.get_submission_from_id('651db6a7718107d07e95639d')['status'])
start_time = time.time()
print(prolific.initialize_submission_info())
end_time = time.time()
execution_time = end_time - start_time
print(execution_time)


start_time = time.time()
for sess_id in tqdm(prolific.sessions):
    prolific.get_submission_from_id(sess_id)
end_time = time.time()
execution_time = end_time - start_time
print(execution_time)

'''