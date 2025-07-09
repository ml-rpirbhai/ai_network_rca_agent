import time
from enum import Enum
import logging
from threading import Thread
import yaml

from nsp_client import NspClient

log = logging.getLogger(__name__)

class SubscriptionState(Enum):
    UP = 1,
    DOWN = 2

"""
1. Instantiates subscription to NSP.
2. Monitors the subscription state and expiry time.
3. Renews token and subscription before expiry time.
"""
class SubscriptionMonitorSingleton(Thread):
    __instance = None
    __initialized = False

    check_subscription_interval = 1800  # Every 30 minutes

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(SubscriptionMonitorSingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            log.info("Initializing ...")
            super().__init__()
            self.daemon = True

            # Load config file
            with open('config/conf.yaml', 'r') as stream:
                config = yaml.load(stream, Loader=yaml.FullLoader)

            nsp_server_ip = config['nsp_server_ip']
            self.nsp_client = self.initialize_nsp_client(nsp_server_ip)

            subscr_details_dict = self.nsp_client.get_subscription_details()
            # Save the topic_id to topic_id.txt for the kafka_client
            log.info("Writing topic_id to config/topic_id.txt ...")
            with open('config/topic_id.txt', 'w') as f:
                f.write(subscr_details_dict['topic_id'])

            self.__initialized = True

    """
    Loop:
        1. Check the subscription state ('stage')
           * Report error if not 'ACTIVE' 
        2. Renew:
          a. Token ("refresh")
          b. Subscription
        3. Sleep
    """
    def run(self):
        while True:
            log.info("Checking subscription details ...")
            subscription_details_dict = self.nsp_client.get_subscription_details()
            if 'stage' in subscription_details_dict and subscription_details_dict['stage'] != "ACTIVE":
                error_msg = "Subscription is not ACTIVE"
                log.critical(error_msg)
                raise RuntimeError(error_msg)

            # Refresh the token
            self.nsp_client.refresh_auth_token()

            # Renew the subscription
            self.nsp_client.renew_subscription()

            time.sleep(self.check_subscription_interval)

    def initialize_nsp_client(self, nsp_server_ip) -> NspClient:
        nsp_client = NspClient(server=nsp_server_ip)
        nsp_client._authenticate()  # Get token
        nsp_client.create_subscription()  # Subscribe to NSP-FAULT-YANG
        return nsp_client


    def get_subscription_state(self) -> SubscriptionState:
        return SubscriptionState.DOWN

"""
Test
"""
if __name__ == '__main__':
    subscription_monitor = SubscriptionMonitorSingleton()
    subscription_monitor.run()
