import time
from enum import Enum
import logging
from threading import Thread

from nsp_client import NspClientSingleton

log = logging.getLogger(__name__)

class SubscriptionState(Enum):
    UP = 1,
    DOWN = 2

"""
Monitors the subscription state and expiry time.
"""
class SubscriptionMonitorSingleton(Thread):
    __instance = None
    __initialized = False

    check_subscription_interval = 900  # Every 15 minutes

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(SubscriptionMonitorSingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            super().__init__()
            self.daemon = True
            self.nsp_client = NspClientSingleton.instance
            if self.nsp_client is None:
                log.critical("NSP client has not been initialized")
                return
            self.__initialized = True

    """
    Loop:
        1. Check the subscription state ('stage')
           * Report error if not 'ACTIVE' 
        2. Renew the subscription
        3. Sleep
    """
    def run(self):
        while True:
            log.info("Checking subscription details ...")
            subscription_details_dict = self.nsp_client.get_subscription_details()
            if 'stage' in subscription_details_dict and subscription_details_dict['stage'] != "ACTIVE":
                log.critical("Subscription is not ACTIVE")
            else:
                # Renew the subscription
                self.nsp_client.renew_subscription()

            time.sleep(self.check_subscription_interval)

    def get_subscription_state(self) -> SubscriptionState:
        return SubscriptionState.DOWN

"""
Test
"""
if __name__ == '__main__':
    nsp_c = NspClientSingleton(server='135.121.156.104')
    nsp_c.authenticate()
    nsp_c.create_subscription()
    subscription_monitor = SubscriptionMonitorSingleton()
    subscription_monitor.run()
