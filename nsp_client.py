import requests
from requests.auth import HTTPBasicAuth

from datetime import datetime, timezone
import inspect
import json
import logging
import pytz
import time

from kafka_client import Client as KafkaClient
from redis_client import RedisClient

log = logging.getLogger(__name__)

class NspClientSingleton:
    instance = None
    initialized = False

    """
    Though not desirable, we must provide defaults for all args for unpickling. 
    Therefore, we must also protect from server=None 
    """
    def __new__(cls, server=None, username='admin', password='NokiaNsp1!'):
        if cls.instance is None:
            cls.instance = super(NspClientSingleton, cls).__new__(cls)
        return cls.instance

    def __init__(self, server=None, username='admin', password='NokiaNsp1!'):
        if server is None:
            log.exception("Error: server=None")
            return

        if not self.initialized:
            self.server_url = f"https://{server}"
            self.username = username
            self.password = password
            self.token = None
            self.headers_dict = {
                "Content-Type": "application/json"
            }
            self.subscription_id = None
            self.redis_client = RedisClient()
            self.initialized = True

    """
    Get token
    """
    def authenticate(self) -> str:
        url = f"{self.server_url}/rest-gateway/rest/api/v1/auth/token"

        data = {
            "grant_type": "client_credentials"
        }

        response = requests.post(
            url,
            verify=False,  # Skip certificate verification
            auth=HTTPBasicAuth(self.username, self.password),
            headers=self.headers_dict,
            json=data)

        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.token_expires_at_ux_time = response.json().get("expires_in") + time.time()
            self.headers_dict["Authorization"] = f"Bearer {self.token}"
            log.debug(f"Access token: {self.token}")
        else:
            log.critical(f"Failed to get token: {response.status_code}, {response.text}")

        return self.token

    """
    Create subscription
    Params: token: If left as None, use self.token
    """
    def create_subscription(self, token=None) -> None:
        url = f"{self.server_url}/nbi-notification/api/v1/notifications/subscriptions"
        headers_dict = self.headers_dict
        if token != None:  # For testing purpose only
            self.token = token
            headers_dict["Authorization"] = f"Bearer {self.token}"

        # Subscription filter
        data = {
            "categories": [{"name": "NSP-FAULT-YANG",
                            "advancedFilter": "{\"includeAlarmDetailsOnChangeEvent\":true}",
                            "propertyFilter": "nsp-model-notification = 'object-modification' or "
                                              "nsp-model-notification = 'object-creation'"
                            }]
        }

        response = requests.post(
            url,
            verify=False,  # Skip certificate verification
            headers=headers_dict,
            json=data)

        if response.status_code == 201:
            log.debug(f"Response: {response.text}")
            json_response = json.loads(response.text)
            json_response_data = json_response['response']['data']
            self.subscription_id = json_response_data['subscriptionId']
            log.debug(f"subscriptionId: {self.subscription_id}, stage: {json_response_data['stage']}, expiresAt: {json_response_data['expiresAt']}")
        else:
            log.critical(f"Failed: {response.status_code}, {response.text}")

    def renew_subscription(self):
        url = f"{self.server_url}/nbi-notification/api/v1/notifications/subscriptions/{self.subscription_id}/renewals"
        headers_dict = self.headers_dict

        response = requests.post(
            url,
            verify=False,  # Skip certificate verification
            headers=headers_dict)

        if response.status_code == 201:
            log.debug(f"Response: {response.text}")
            json_response = json.loads(response.text)
            json_response_data = json_response['response']['data']
            log.info(f"expiresAt: {json_response_data}")
        else:
            log.critical(f"Failed: {response.status_code}, {response.text}")

    """
    Get subscription details
    Params: subscription_id: If left as None, use self.subscription_id. Is not None only when testing.
            token:           If left as None, use self.token. Is not None only when testing.
    Returns: subscription_details_dict
    """
    def get_subscription_details(self, subscription_id=None, token=None) -> {}:
        subscription_details_dict = {}  # Keys: 'topic_id', 'subscription_id', 'expires_at_unix_time'

        if subscription_id != None: # For testing purpose only
            self.subscription_id = subscription_id
        url = f"{self.server_url}/nbi-notification/api/v1/notifications/subscriptions/{self.subscription_id}"
        headers_dict = self.headers_dict
        if token != None:  # For testing purpose only
            self.token = token
            headers_dict["Authorization"] = f"Bearer {self.token}"

        if self.subscription_id is not None and self.token is not None:
            response = requests.get(
                url,
                verify=False,  # Skip certificate verification
                headers=headers_dict)

            if response.status_code == 200:
                log.debug(f"Response: {response.text}")
                json_response = json.loads(response.text)
                json_response_data = json_response['response']['data']
                subscription_details_dict['subscription_id'] = self.subscription_id
                subscription_details_dict['topic_id'] = json_response_data['topicId']
                subscription_details_dict['expires_at_unix_time'] = json_response_data['expiresAt'] // 1000  # Divide by 1000 and discard the remainder
                subscription_details_dict['stage'] = json_response_data['stage']
                log.debug(subscription_details_dict)
            else:
                log.error(f"Failed:{response.status_code}, {response.text}")

        return subscription_details_dict


    """
    * Called by Gemini Agent *
    From L3VPN interface, get:
    1. Port parent,
    2. Primary IPv4 address/prefix and/or IPv6 address/prefix
    Params: site_id:  str
            svc_name: str
            if_name:  str
    Returns: {}. Keys: 1. 'port_id': str e.g. '1/1/c2/1',
                       2. 'ip_addr': str[] e.g. ['10.41.1.1/30', 'FC10:41:1::1/126']
    """
    def get_l3vpn_interface_details(self, ne_id: str, svc_name: str, if_name: str) -> {}:
        args = [ne_id, svc_name, if_name]
        # Check redis
        if_details = self.redis_client.get_return_value('get_l3vpn_interface_details', args)

        if if_details is None:
            url = f"{self.server_url}/restconf/data/nsp-service-intent:intent-base/intent={svc_name},vprn/intent-specific-data/vprn:vprn/site-details/site={ne_id},{svc_name}/interface-details/interface={if_name}"

            log.debug(f"Request: {url}")
            response = requests.get(
                url,
                verify=False,  # Skip certificate verification
                headers=self.headers_dict)

            if_details = {}
            if response.status_code == 200:
                log.debug(f"Response: {response.text}")
                response_dict = json.loads(response.text)
                if_details['port_id'] = response_dict['vprn:interface']['sap']['port-id']
                ipv4_and_ipv6_addr = []
                if_primary_ipv4_address_ctx = response_dict['vprn:interface']['ipv4']['primary']
                ipv4_and_ipv6_addr.append(if_primary_ipv4_address_ctx['address'] + '/' + str(if_primary_ipv4_address_ctx['prefix-length']))
                #TODO: IPv6
                if_details['ip_addr'] = ipv4_and_ipv6_addr

                # Store in redis
                self.redis_client.store_call('get_l3vpn_interface_details', args, if_details)

            else:
                log.error(f"Failed:{response.status_code}, {response.text}")

        return if_details

    """
    * Called by Gemini Agent *
    """
    def get_ne_details(self, ne_id: str) -> {}:
        args = [ne_id]
        # Check redis
        ne_details = self.redis_client.get_return_value('get_ne_details', args)

        if ne_details is None:
            url = f"{self.server_url}/restconf/operations/nsp-inventory:find"
            data = f'{{"nsp-inventory:input": {{"xpath-filter": "/nsp-equipment:network/network-element[ne-id=\'{ne_id}\']", "depth": "2"}}}}'

            log.debug(f"Request: {url}, Data: {data}")
            response = requests.post(
                url,
                data=data,
                verify=False,  # Skip certificate verification
                headers=self.headers_dict)

            ne_details = {}
            if response.status_code == 200:
                log.debug(f"Response: {response.text}")
                response_dict = json.loads(response.text)
                ne_data = response_dict['nsp-inventory:output']['data'][0]
                ne_details['version'] = ne_data['version']
                ne_details['product'] = ne_data['product']
                ne_details['type'] = ne_data['type']
                ne_details['mgmt_ip_addr'] = ne_data['ip-address']
            else:
                log.error(f"Failed:{response.status_code}, {response.text}")

        return ne_details


    def unixtime_ms_to_currenttime(self, unixtime_ms) -> str:
        # Convert to seconds
        unixtime_s = unixtime_ms / 1000

        # Convert to UTC datetime
        utc_datetime = datetime.fromtimestamp(unixtime_s, tz=timezone.utc)

        # Convert to local time (Eastern Time)
        eastern_timezone = pytz.timezone("America/Toronto")
        local_datetime = utc_datetime.astimezone(eastern_timezone)

        return local_datetime.strftime("%d-%m-%Y %H:%M:%S %Z%z")


"""
Test
"""
if __name__ == '__main__':
    nsp_client = NspClientSingleton(server='135.121.156.104')
    nsp_client.authenticate()  # Get Token
    #nsp_client.create_subscription()  # Subscribe to NSP-FAULT-YANG
    #_, topic_id = nsp_client.get_subscription_details()  # Get Subscription details
    #subscription_details_dict = nsp_client.get_subscription_details(subscription_id='57225cac-b276-416a-a240-fdaa413afe29',
    #                                                                token='eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI5dTJXbjUyQktmWU9lb1ktYlE4eFVhcm02RUxoTVJpRkJpZHlpQ3h5R3ZrIn0.eyJleHAiOjE3NDc5MTg1MzEsImlhdCI6MTc0NzkxNDkzMSwianRpIjoiMDEwOGRkMzItYmE0ZC00ODFlLWJhZWEtNTk0ZDU4MGEzYzJmIiwiaXNzIjoiaHR0cHM6Ly8xMzUuMTIxLjE1Ni4xMDQvYXV0aC9yZWFsbXMvTm9raWEiLCJhdWQiOlsiTlNQIiwiYWNjb3VudCJdLCJzdWIiOiJjNDA1N2MwMS00YTBjLTRlYzYtODI1Zi04ZDlmYWYwZWQwMGMiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJOU1AtT1NTIiwic2Vzc2lvbl9zdGF0ZSI6ImQ3Y2Y5MzIwLTA0YzUtNDYwYS1hMDRmLWJhNDYyYWIwYjFkNyIsImFsbG93ZWQtb3JpZ2lucyI6WyIvKiJdLCJyZWFsbV9hY2Nlc3MiOnsicm9sZXMiOlsib2ZmbGluZV9hY2Nlc3MiLCJkZWZhdWx0LXJvbGVzLW5va2lhIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJOU1AiOnsicm9sZXMiOlsiU3lzdGVtQWRtaW4iXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoiZW1haWwgbWVtYmVyc2hpcCBwcm9maWxlIiwic2lkIjoiZDdjZjkzMjAtMDRjNS00NjBhLWEwNGYtYmE0NjJhYjBiMWQ3IiwiZ3JvdXBfbWVtYmVyc2hpcCI6WyJhZG1pbiJdLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsImF1dGhfc291cmNlIjoiTlNQIiwicHJlZmVycmVkX3VzZXJuYW1lIjoiYWRtaW4ifQ.pBzjfFXJkROw_zzMltkQ8dajpqCZWM7QAvzh2YfORhtMk6tkMp-OO-l_yhAWDjHDN0xCXI5mCqo026QKSgBt9REPG9IRIcym3UFPQA1bUoXB2zzE9jYezaKbNydo69H3UrhcXzRzzJt4Ake8GCUJt_h-SCP8mKYnhSvsoGDrQjJzb4NQIQTSo9WqjgCuoM-mDMWyOtzqxzSdqZor7O_umxerDA2M34NacSBaEjLOWDeYEWunH5Yf7Bn0kgTKgyKlsdn9LijgBDVWLOdJegV7fyW-vZKgLiFgmHjHSL9dMRY5ZcGT9LRhdmx7dfraUun8g19qTL686_V3DL1aPoXTFg')
    #nsp_client.renew_subscription()
    #kafka_client = KafkaClient(server='135.121.156.104', topic_id=subscription_details_dict['topic_id'])
    #kafka_client.connect()
    print(nsp_client.get_l3vpn_interface_details('2001::225', '411', 'toCE'))
    #print(nsp_client.get_ne_details('38.120.234.239'))
    #print(nsp_client.get_ne_details('2001::225'))

