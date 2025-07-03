import json
import logging.config
import re
import ssl
import yaml

from kafka import KafkaConsumer
from message_bus import MessageBus
from nsp_client import NspClientSingleton

with open('config/kafka_client_logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(config)
    log = logging.getLogger(__name__)

class Client:
    def __init__(self, server, topic_id):
        with open('config/conf.yaml', 'r') as stream:
            config = yaml.load(stream, Loader=yaml.FullLoader)

        # Initialize message-bus producer
        bus = MessageBus(config['message_bus_name'])
        self.message_bus_producer = bus.get_producer()

        bus = MessageBus("alarms_bus")
        self.message_bus_producer = bus.get_producer()

        # Initialize Kafka
        ssl_context = ssl._create_unverified_context()
        consumer_config = {
            'bootstrap_servers': server + ':9192',
            'security_protocol': 'SSL',
            'ssl_cafile': 'C:\\Users\\rpirbhai\\tls.crt',  # Specify ca-cert
            'ssl_context': ssl_context,
            'group_id': 'test-group',
            'auto_offset_reset': 'earliest'
        }

        # Create the consumer
        self.nsp_kafka_consumer = KafkaConsumer(topic_id, **consumer_config)

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
                    log.info("Putting message on bus")
                    self.message_bus_producer.publish(msg_feed)

        except KeyboardInterrupt:
            log.critical("Consumer stopped.")
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
    client = Client(server='135.121.156.104', topic_id='ns-eg-787391e9-d9c0-47dc-99bc-d87e3bbcc5d7')
    client.connect()