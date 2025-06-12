import json
import logging.config
from multiprocessing import Queue
import re
import ssl
import yaml

from kafka import KafkaConsumer

with open('config/logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(config)
    log = logging.getLogger(__name__)

class Client:
    log = None

    def __init__(self, server, topic_id):
        # Configuration
        ssl_context = ssl._create_unverified_context()
        consumer_config = {
            'bootstrap_servers': server + ':9192',
            'security_protocol': 'SSL',
            'ssl_cafile': 'C:\\Users\\rpirbhai\\tls.crt',  # Specify ca-cert
            #'ssl_cafile': 'C:\\Users\\rpirbhai\\nsp24_11',
            'ssl_context': ssl_context,
            'group_id': 'test-group',
            'auto_offset_reset': 'earliest'
        }

        # Create the consumer
        self.consumer = KafkaConsumer(topic_id, **consumer_config)

    def connect(self, queue:Queue=None):
        try:
            log.info("Waiting for messages ...")
            for message in self.consumer:
                log.debug(message)
                # convert from bytes to dict
                msg_dict = json.loads(message.value.decode('utf-8'))

                # Print the message as formatted JSON
                log.debug(json.dumps(msg_dict, indent=2))

                # Print just the fields we want to see
                msg_feed = self.__post_filter_and_data_extractor(msg_dict)
                if msg_feed is not None:
                    log.debug(msg_feed)
                    if queue is not None:
                        # Put the message on the queue
                        log.info("Putting message on multiprocessing.queue:")
                        queue.put(msg_feed)

        except KeyboardInterrupt:
            log.critical("Consumer stopped.")
        finally:
            self.consumer.close()


    """
    Extract only the messages and fields that we care about
    format:
    |time|object|additional-text|
    """
    def __post_filter_and_data_extractor(self, message: dict):
        if message is not None:
            if 'nsp-model-notification:object-creation' in message:
                event_time = message['nsp-model-notification:object-creation']['event-time']
                message_body = message['nsp-model-notification:object-creation']['tree']['/nsp-fault:alarms/alarm-list/alarm']
                return ' | '.join((event_time,
                                   message_body.get('ne-name'),
                                   message_body.get('ne-id'),
                                   message_body['resource'],
                                   message_body['additional-text']))
            elif 'nsp-model-notification:object-modification' in message:
                if 'tree' in message['nsp-model-notification:object-modification']:
                    event_time = message['nsp-model-notification:object-modification']['event-time']
                    message_body = message['nsp-model-notification:object-modification']['tree']['/nsp-fault:alarms/alarm-list/alarm']
                    RESOURCE_BGP_NEIGHBOR_REGEXP = '.+bgp/neighbor.+'
                    bgp_neighbor_match = re.search(RESOURCE_BGP_NEIGHBOR_REGEXP, message_body['resource'])
                    if bgp_neighbor_match:
                        return ' | '.join((event_time,
                                           message_body.get('ne-name'),
                                           message_body.get('ne-id'),
                                           message_body['resource'],
                                           message_body['additional-text']))

"""
External method to initialize Kafka client to work around Pickling error with multiprocessing.Process(target=kafka_client.connect(), ...).
"""
def run_client(server='135.121.156.104', topic_id='ns-eg-ea01c78a-4f66-473d-bd3c-8862278cf92a', queue:Queue=None):
    client = Client(server=server, topic_id=topic_id)
    client.connect(queue)

"""
Test
"""
if __name__ == '__main__':
    json_msg = """{
    "nsp-model-notification:object-creation": {
        "schema-nodeid": "/nsp-fault:alarms/alarm-list/alarm",
        "instance-id": "/nsp-fault:alarms/alarm-list/alarm[alarm-fdn='fdn:model:fm:Alarm:52516']",
        "context": "NSP-Yang",
        "tree": {
            "/nsp-fault:alarms/alarm-list/alarm": {
                "@": {
                    "nsp-model:schema-nodeid": "/nsp-fault:alarms/alarm-list/alarm",
                    "nsp-model:identifier": "/nsp-fault:alarms/alarm-list/alarm[alarm-fdn='fdn:model:fm:Alarm:52516']"
                },
                "node-time-offset": -1,
                "number-of-occurrences-since-clear": 0,
                "probable-cause-string": "equipmentMalfunction",
                "alarm-type-id": "communicationsAlarm",
                "last-changed": null,
                "acknowledged": false,
                "cleared-by": "N/A",
                "original-severity": "major",
                "is-cleared": false,
                "was-acknowledged": false,
                "admin-state": "unlocked",
                "root-cause-resource": null,
                "ne-id": "2001::225",
                "acknowledged-by": "N/A",
                "frequency": 1,
                "last-time-severity-changed": null,
                "last-raised": "2025-05-12T12:04:56.488Z",
                "user-text": "N/A",
                "ne-name": "sim234_225",
                "source-type": "mdm",
                "affected-object-type": "/openconfig-network-instance:network-instances/network-instance/interfaces/interface",
                "time-created": "2025-05-12T12:04:56.488Z",
                "source-system": "fdn:app:mdm-ami-cmodel",
                "alarm-type-qualifier": "LinkDown",
                "impacted-resource": null,
                "additional-text": "Interface toSR233 is not operational",
                "last-time-de-escalated": null,
                "number-of-occurrences-since-ack": 0,
                "resource": "fdn:app:mdm-ami-cmodel:2001::225:/openconfig-network-instance:network-instances/network-instance/interfaces/interface:/router[router-name='Base']/interface[interface-name='toSR233']",
                "perceived-severity": "major",
                "last-time-acknowledged": null,
                "number-of-occurrences": 1,
                "previous-severity": "indeterminate",
                "impact-count": 0,
                "alarm-fdn": "fdn:model:fm:Alarm:52516",
                "last-time-escalated": null,
                "affected-object-name": "interface=toSR233",
                "implicitly-cleared": true,
                "alt-resource": "2001::225:fm:Alarm:/router[router-name='Base']/interface[interface-name='toSR233']/linkDown",
                "last-time-cleared": null,
                "is-root-cause": null
            }
        },
        "event-time": "2025-05-12T11:57:09.394813609Z"
    }
}"""

    client = Client(server='135.121.156.104', topic_id='ns-eg-787391e9-d9c0-47dc-99bc-d87e3bbcc5d7')
    #print(client.post_filter_and_data_extractor(message=json.loads(json_msg)))
    client.connect()

    #run_client(server='135.121.156.104', topic_id='ns-eg-ea01c78a-4f66-473d-bd3c-8862278cf92a')