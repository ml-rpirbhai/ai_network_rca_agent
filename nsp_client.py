import requests
from requests.auth import HTTPBasicAuth

from datetime import datetime, timezone
import json
import logging
import pytz
import time

log = logging.getLogger(__name__)

class NspClientSingleton:
    instance = None
    initialized = False

    def __new__(cls, username='admin', password='NokiaNsp1!'):
        if cls.instance is None:
            cls.instance = super(NspClientSingleton, cls).__new__(cls)
        return cls.instance

    def __init__(self, server=None, username='admin', password='NokiaNsp1!'):
        if not self.initialized:
            self.server_url = f"https://{server}"
            self.username = username
            self.password = password
            self.token = None
            self.headers_dict = {
                "Content-Type": "application/json"
            }
            self.subscription_id = None
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
        else:
            log.error(f"Failed:{response.status_code}, {response.text}")

        return if_details

    def get_ne_details(self, ne_id: str) -> {}:
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
    print(nsp_client.get_ne_details('38.120.234.239'))


