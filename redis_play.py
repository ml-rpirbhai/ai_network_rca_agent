import json
import redis
from typing import Optional


class RedisCache:
    def __init__(self, host='localhost', port=6379, db=0, default_ttl=3600):
        self.client = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)
        self.default_ttl = default_ttl  # seconds

    def get(self, key: str) -> Optional[dict]:
        value = self.client.get(key)
        return json.loads(value) if value else None

    def get_keys(self) -> list:
        return r.keys("*")

    def show_all(self):
        all_keys = r.keys("*")

        for key in all_keys:
            value = r.get(key)
            print(f"{key.decode()}: {value.decode()}")

    def set(self, key: str, value: dict, ttl: Optional[int] = None):
        value_str = json.dumps(value)
        self.client.setex(key, ttl or self.default_ttl, value_str)

    def delete(self, key: str):
        self.client.delete(key)

    def exists(self, key: str) -> bool:
        return self.client.exists(key) == 1


if __name__ == '__main__':
    # Test server is available/up
    r = redis.Redis()
    print(r.ping())  # Should print True
    """
    True
    """

    c = RedisCache()
    # Add
    #c.set("my_key", {"val": 42})
    print(c.get("my_key"))
    """
    {'val': 42}
    """

    # Exists
    print(c.exists("my_key"))
    """
    True
    """

    # Delete
    #c.delete("my_key")

    #print(c.exists("my_key"))
    """
    False
    """

    c.show_all()

    print(c.get_keys())




