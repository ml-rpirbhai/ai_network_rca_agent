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

    def instantiate_consumer(self, c_name: str) -> 'MessageBus._Consumer':
        consumer = MessageBus._Consumer(self, c_name)
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
        def __init__(self, bus: 'MessageBus', c_name: str):
            self.bus = bus
            self.c_name = c_name
            self.redis_client = redis.Redis(decode_responses=True)

            # Create the consumer group (it may already exist)
            try:
                self.redis_client.xgroup_create(self.bus.name, self.bus.name, id='0', mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    log.debug(f"Group {self.bus.name} already exists. Continuing ...")
                else:
                    raise

        def consume(self):
            resp = self.redis_client.xreadgroup(groupname=self.bus.name,
                                                consumername=self.c_name,
                                                streams={self.bus.name: '>'},
                                                block=5000)  # block for 5 seconds

            msgs = []
            if resp:
                for _, messages in resp:
                    for msg_id, msg in messages:
                        log.debug(f"[Consumer] Received msg ID {msg_id}: {msg}")
                        # Acknowledge message
                        self.redis_client.xack(self.bus.name, self.bus.name, msg_id)

                        msgs.append(msg)

            return msgs

if __name__ == "__main__":
    b = MessageBus("my_bus")
    p = b.get_producer()
    payload = {'message': 'Hello'}
    p.publish(payload)
    c = b.instantiate_consumer('alarms_c_1')
    c.consume()
