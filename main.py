import logging.config
from multiprocessing import Process, Queue
import yaml

from gemini_alarms_rca_agent import GenAISingleton
import kafka_client
from nsp_client import NspClientSingleton
from subscription_monitor import SubscriptionMonitorSingleton

# Suppress HTTPS warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

with open('config/logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
logging.config.dictConfig(config)
log = logging.getLogger(__name__)


def run_genai_agent(nsp_client: NspClientSingleton, queue: Queue):
    log.info("RCA agent process starting...")
    gen_ai = GenAISingleton(nsp_client)
    gen_ai.prompt_bulk_from_queue(queue)


if __name__ == '__main__':
    print("Initializing main ...")
    log.info("Initializing main ...")

    # Initialize NSP Client
    nsp_server_ip = '135.121.156.104'
    nsp_client = NspClientSingleton(server=nsp_server_ip)
    nsp_client.authenticate()  # Get Token
    nsp_client.create_subscription()  # Subscribe to NSP-FAULT-YANG
    subscription_details_dict = nsp_client.get_subscription_details()  # Get Subscription details

    # Kafka -> GenAI Queue
    nsp_kafka_to_ai = Queue()
    nsp_kafka_client_process = Process(target=kafka_client.run_client, args=(nsp_server_ip, subscription_details_dict['topic_id'], nsp_kafka_to_ai))
    ai_agent_process = Process(target=run_genai_agent, args=(nsp_client, nsp_kafka_to_ai,))

    # Initialize Kafka Client
    nsp_kafka_client_process.start()
    # Initialize GenAI
    ai_agent_process.start()

    # Initialize the Monitor Thread
    subscr_monitor = SubscriptionMonitorSingleton(nsp_client)
    subscr_monitor.start()

    nsp_kafka_client_process.join()
    ai_agent_process.join()
    #subscr_monitor.join()

    print("Main exited")
    log.info("Main exited")
