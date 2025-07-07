import redis
import json

import logging.config

import yaml

log = logging.getLogger(__name__)

class RedisClient:
    def __init__(self):
        self.redis_client = redis.Redis()
        log.debug("Initialized")

    def store_call(self, func_name:str, args:[], return_value):
        log.debug(f"{func_name}, {args}, {return_value}")
        self.redis_client.set(name=f"{func_name}:{json.dumps(args)}", value=json.dumps(return_value), ex=3600)  # Store for 1 hour

    def get_return_value(self, func_name:str, args:[]) -> str:
        log.debug(f"{func_name}, {args}")
        return self.redis_client.get(f"{func_name}:{json.dumps(args)}")

    def show_all(self):
        all_keys = self.redis_client.keys("*")

        for key in all_keys:
            value = self.redis_client.get(key)
            print(f"{key.decode()}: {value.decode()}")


"""
Test
"""
if __name__ == "__main__":
    with open('config/logger.yaml', 'r') as stream:
        config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(config)

    r = RedisClient()
    r.store_call('get_l3vpn_interface_details', ['2001::225', 'l3vpn_test', 'if_test'], {'port_id': '1/1/1', 'ip_addr': '1.1.1.1/30'})

    r.show_all()