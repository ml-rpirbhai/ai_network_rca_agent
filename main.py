import logging.config
import time
import yaml

from nsp_client import NspClientSingleton
from subscription_monitor import SubscriptionMonitorSingleton

# Suppress HTTPS warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

with open('config/logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
logging.config.dictConfig(config)
log = logging.getLogger(__name__)

if __name__ == '__main__':
    print("Initializing main ...")
    log.info("Initializing main ...")
    nsp_server_ip = '135.121.156.104'

    # Initialize NSP Client
    nsp_c = NspClientSingleton(server=nsp_server_ip)
    nsp_c.authenticate()  # Get Token
    nsp_c.create_subscription()  # Subscribe to NSP-FAULT-YANG

    # Initialize the Monitor Thread
    subscr_monitor = SubscriptionMonitorSingleton()
    subscr_monitor.start()

    #Loop forever. In the future we will add health-checks here
    while True:
        time.sleep(5)

    print("Main exited")
    log.info("Main exited")
