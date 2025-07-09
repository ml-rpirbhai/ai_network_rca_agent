import json
import logging.config
import re
import ssl
import yaml

from kafka import KafkaConsumer
from message_bus import MessageBus
from nsp_client import NspClient

# Suppress HTTPS warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

with open('config/kafka_client_logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(config)
    log = logging.getLogger(__name__)

class KafkaClient:
    def __init__(self, nsp_client: NspClient):
        print("Initializing kafka_client ...")
        log.info("Initializing ...")
        with open('config/conf.yaml', 'r') as stream:
            config = yaml.load(stream, Loader=yaml.FullLoader)

        # Initialize message-bus producer
        bus = MessageBus.get_bus(config['message_bus_name'])
        self.message_bus_producer = bus.instantiate_producer()

        # Initialize Kafka
        ssl_context = ssl._create_unverified_context()
        consumer_config = {
            'bootstrap_servers': nsp_client.server + ':9192',
            'security_protocol': 'SSL',
            'ssl_cafile': 'C:\\Users\\rpirbhai\\tls.crt',  # Specify ca-cert
            'ssl_context': ssl_context,
            'group_id': 'test-group',
            'auto_offset_reset': 'earliest'
        }

        # Create the consumer
        if nsp_client.topic_id is not None:
            self.nsp_kafka_consumer = KafkaConsumer(nsp_client.topic_id, **consumer_config)
        else:
            error_msg = f"topic_id is None. nsp_client subscription must be initiated first"
            log.error(error_msg)
            raise RuntimeError(error_msg)

    def connect(self):
        try:
            log.info("Waiting for messages ...")
            for message in self.nsp_kafka_consumer:
                log.debug(message)
                # convert from bytes to dict
                msg_dict = json.loads(message.value.decode('utf-8'))

                # Print the message as formatted JSON
                log.debug(json.dumps(msg_dict, indent=2))

                # Print just the fields we want to see
                msg_feed = self.__post_filter_and_data_extractor(msg_dict)
                if msg_feed is not None:
                    log.debug(msg_feed)
                    # Put the message on the queue
                    published_message = {}
                    published_message['message'] = msg_feed
                    if isinstance(published_message, dict):
                        log.info("Putting message on bus ...")
                        self.message_bus_producer.publish(published_message)
                    else:
                        log.error(f"Unable to publish message. Payload is not dict: {published_message}")

        except KeyboardInterrupt:
            log.critical("Consumer stopped")
        finally:
            self.nsp_kafka_consumer.close()

    """
    Return: |time|ne-name|ne-id|object-fdn|object-name|additional-info|
    """
    def build_gen_ai_alarm_feed(self, event_time: str, message_body: dict) -> str:
        return ' | '.join((event_time,
                           message_body.get('ne-name', 'null') or 'null',
                           message_body.get('ne-id', 'null') or 'null',
                           message_body['resource'],
                           message_body['affected-object-name'],
                           ' , '.join((message_body['additional-text'], message_body['alt-resource']))))

    """
    Extract only the messages and fields that we care about
    """
    def __post_filter_and_data_extractor(self, message: dict):
        if message is not None:
            if 'nsp-model-notification:object-creation' in message:
                event_time = message['nsp-model-notification:object-creation']['event-time']
                message_body = message['nsp-model-notification:object-creation']['tree']['/nsp-fault:alarms/alarm-list/alarm']
                return self.build_gen_ai_alarm_feed(event_time, message_body)
            elif 'nsp-model-notification:object-modification' in message:
                if 'tree' in message['nsp-model-notification:object-modification']:
                    event_time = message['nsp-model-notification:object-modification']['event-time']
                    message_body = message['nsp-model-notification:object-modification']['tree']['/nsp-fault:alarms/alarm-list/alarm']
                    RESOURCE_BGP_NEIGHBOR_REGEXP = '.+bgp/neighbor.+'
                    bgp_neighbor_match = re.search(RESOURCE_BGP_NEIGHBOR_REGEXP, message_body['resource'])
                    if bgp_neighbor_match:
                        return self.build_gen_ai_alarm_feed(event_time, message_body)

            log.debug("Message did not meet filter criteria. Will not extract")

if __name__ == '__main__':
    my_nsp_client = NspClient(server='135.121.156.104')
    my_nsp_client.create_subscription()
    client = KafkaClient(my_nsp_client)
    client.connect()