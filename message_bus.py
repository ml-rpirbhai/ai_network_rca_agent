import logging
import redis

log = logging.getLogger(__name__)

class MessageBus:
    buses = {}

    def __init__(self, bus_name:str):
        self.name = bus_name
        MessageBus.buses[bus_name] = self
        self.producer = MessageBus._Producer(self)  # Instantiate producer
        self.consumers = {}

    def get_producer(self) -> 'MessageBus._Producer':
        return self.producer

    def instantiate_consumer(self, c_group: str, c_name: str) -> 'MessageBus._Consumer':
        consumer = MessageBus._Consumer(self, c_group, c_name)
        self.consumers[c_name] = consumer
        return consumer

    class _Producer:
        def __init__(self, bus: 'MessageBus'):
            self.bus = bus
            self.redis_client = redis.Redis(decode_responses=True)

        def publish(self, message):
            message_id = self.redis_client.xadd(self.bus.name, message)
            log.debug(f"Sent: {message}, ID: {message_id}")


    class _Consumer:
        def __init__(self, bus: 'MessageBus', c_group: str, c_name: str):
            self.bus = bus
            self.c_group = c_group
            self.c_name = c_name
            self.redis_client = redis.Redis(decode_responses=True)

        def consume(self):
            consumer_group = self.c_group
            stream = self.bus.name

            # Create the consumer group if it doesn't exist
            try:
                self.redis_client.xgroup_create(stream, consumer_group, id='0', mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    print("[Consumer] Group already exists, continuing...")
                else:
                    raise

            while True:
                resp = self.redis_client.xreadgroup(groupname=consumer_group,
                                                    consumername=self.c_name,
                                                    streams={stream: '>'},
                                                    block=5000)  # block for 5 seconds

                if resp:
                    for stream_name, messages in resp:
                        for msg_id, msg in messages:
                            print(f"[Consumer] Received alarm ID {msg_id}: {msg}")
                            # Acknowledge message
                            self.redis_client.xack(stream, consumer_group, msg_id)

if __name__ == "__main__":
    b = MessageBus("my_bus")
    p = b.get_producer()
    payload = {'message': 'Hello'}
    p.publish(payload)
    c = b.instantiate_consumer('alarms_group', 'alarms_c_1')
    c.consume()
