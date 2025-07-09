import logging.config
import time
import yaml

with open('config/main_logger.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)
logging.config.dictConfig(config)
log = logging.getLogger(__name__)

if __name__ == '__main__':
    print("Initializing main ...")
    log.info("Initializing ...")

    #Loop forever. In the future we will add health-checks here
    while True:
        time.sleep(5)

    print("Main exited")
    log.info("Main exited")
