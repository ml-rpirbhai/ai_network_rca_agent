import logging.config
from time import sleep

import yaml

from message_bus import MessageBus

with open('config/test_producer.yaml', 'r') as stream:
    logger_config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(logger_config)
    log = logging.getLogger(__name__)

with open('config/conf.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)


class TestProducer():
    def __init__(self):
        log.info("Initializing ...")
        super().__init__()
        self.test_alarms_list = None
        self.message_bus_producer = None

        # Load the test alarms
        with open('config/test_alarms.txt', 'r') as f:
            test_alarms = f.read()
            self.test_alarms_list = test_alarms.split('\n')

        # Initialize message-bus producer
        bus = MessageBus.get_bus(config['message_bus_name'])
        self.message_bus_producer = bus.instantiate_producer()

    def publish(self):
        log.info("Putting messages on bus ...")
        for message in self.test_alarms_list:
            published_message = {}
            published_message['message'] = message
            self.message_bus_producer.publish(published_message)


if __name__ == "__main__":
    test_p = TestProducer()
    test_p.publish()
