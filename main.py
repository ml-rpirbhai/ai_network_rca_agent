import logging.config
import time
import yaml

from nsp_client import NspClientSingleton
from subscription_monitor import SubscriptionMonitorSingleton

# Suppress HTTPS warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

with open('config/main_logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
logging.config.dictConfig(config)
log = logging.getLogger(__name__)

if __name__ == '__main__':
    print("Initializing main ...")
    log.info("Initializing ...")

    # Load config file
    with open('config/conf.yaml', 'r') as stream:
        config = yaml.load(stream, Loader=yaml.FullLoader)

    nsp_server_ip = config['nsp_server_ip']

    # Initialize NSP client
    nsp_c = NspClientSingleton(server=nsp_server_ip)
    nsp_c.authenticate()  # Get Token
    nsp_c.create_subscription()  # Subscribe to NSP-FAULT-YANG

    subscr_details_dict = nsp_c.get_subscription_details()
    # Save the topic_id to topic_id.txt for the kafka_client
    log.info("Writing topic_id to config/topic_id.txt ...")
    with open('config/topic_id.txt', 'w') as f:
        f.write(subscr_details_dict['topic_id'])

    # Initialize the subscription-monitor Thread
    subscr_monitor = SubscriptionMonitorSingleton()
    subscr_monitor.start()

    #Loop forever. In the future we will add health-checks here
    while True:
        time.sleep(5)

    print("Main exited")
    log.info("Main exited")
