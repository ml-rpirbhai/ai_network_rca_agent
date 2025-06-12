import json
import logging
import yaml

from google import genai
from google.genai import types
from google.api_core import retry

from multiprocessing import Queue
import time

from anonymizer import AnonymizerSingleton
from nsp_client import NspClientSingleton
from rag import RagSingleton

with open('config/logger.yaml', 'r') as stream:
    logger_config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(logger_config)
    log = logging.getLogger(__name__)

with open('config/conf.yaml', 'r') as stream:
    conf = yaml.load(stream, Loader=yaml.FullLoader)
    GOOGLE_API_KEY = conf['google_gemini_api_key']


class GenAISingleton:
    __instance = None
    __initialized = False

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(GenAISingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            log.info(f"genai.__version__: {genai.__version__}")
            self.is_retriable = lambda e: (isinstance(e, genai.errors.APIError) and e.code in {429, 503})
            self.__client = genai.Client(api_key=GOOGLE_API_KEY)
            nsp_client_instance = NspClientSingleton.instance
            self.anonymizer = AnonymizerSingleton()
            rag_instance = RagSingleton(self)
            self.tools = [nsp_client_instance.get_l3vpn_interface_details,
                          nsp_client_instance.get_ne_details,
                          rag_instance.query_db]

            self.__initialized = True

    def get_model_details(self):
        print("Supported models:")
        for m in self.__client.models.list():
            print(m.name)

    def prompt_from_feed(self, alarms_feed) -> json:
        genai.models.Models.generate_content = retry.Retry(predicate=self.is_retriable)(genai.models.Models.generate_content)
        instructions = ("""You are the network alarms RCA agent. Your task is to identify the root-cause FDN (or FDNs if there are multiple root-causes)
                           from the list of alarms that were sent to your prompt.
                           Use the tools to verify the association between each alarmed object and other alarmed objects in the alarm-feed. 
                           e.g. if alarms were raised for failures on 
                           1) ne-id '2001::255' -> Port '1/1/1, and 
                           2) L3VPN service '411' -> ne-id '2001::255' -> interface 'toCE', and
                           3) L3VPN service '411' -> ne-id '2001::255' -> PE-CE eBGP peer '10.41.1.2':
                           You can correlate: 
                           a) The root-cause of the service-interface failure to the port failure by using a tool to determine whether the service-interface is configured on the port; and
                           b) The root-cause of the eBGP peer failure to the port failure by using a tool to determine whether the peer IP is on the interface's subnet. 
                           Tools:
                           * Use nsp_client_instance.get_l3vpn_interface_details to retrieve the port-parent and IP addresses of an L3VPN interface. 
                             ** If the service-name is not available, you can assume that service-name = service-id. 
                           * Use nsp_client_instance.get_ne_details to retrieve an NE instance's vendor, chassis and OS details.
                           * Use rag_instance.query_db to retrieve useful references information about how to interpret an NE instance's vendor/OS/version alarms: 
                             ** Simply provide the vendor, OS type and version in the query (don't provide any other details).                     
                        """
                        )

        config = types.GenerateContentConfig(temperature=1.0,
                                             system_instruction=instructions,
                                             tools=self.tools)

        prompt = ("""Which of the following alarms is the root-cause failure?                
                     Description of alarms (by column): | time-detected | ne-name | ne-id | object-fdn | additional-text |
                     Respond with either the root-cause object-fdns or 'indeterminate'.
                     The root-cause is 'indeterminate' if none of the alarms in the feed is a equipment failure or configuration error.
                     If there are multiple equipment failures and you cannot determine which one may be the root-cause, return multiple Object_FDNs.                         
                     Explain your reasoning. 
                     Respond **only** with a valid JSON object. Do not include any other text in your response.
                     Use double quotes (") for all keys and string values, like this:
                     {
                       "reasoning": "your reasoning here",
                       "root_cause_fdns": ["fdn:..."]
                     }                       

                     EXAMPLE:
                     2025-05-12T18:32:01.672731026Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='10.1.1.1'] | (ASN 200) VR 1: Group iBGP: Peer 10.1.1.1: received notification: code CEASE subcode CONN_REJECT
                     2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/2/1'] | Interface 1/1/2/1 is not operational
                     2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/3/1'] | Interface 1/1/3/1 is not operational
                     2025-05-12T18:32:02.760893587Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='100'] | Interface toCE is not operational
                     JSON RESPONSE:
                     {
                        "reasoning": "<your reasoning here>",
                        "root_cause_fdns": [fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/2/1'], fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/3/1']]
                     }
    
                     EXAMPLE: 
                     2025-05-12T18:32:01.672731026Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='10.1.1.1'] | (ASN 200) VR 1: Group iBGP: Peer 10.1.1.1: received notification: code CEASE subcode CONN_REJECT 
                     2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/2/1'] | Interface 1/1/2/1 is not operational 
                     2025-05-12T18:32:02.760893587Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='100'] | Interface toCE is not operational 
                     JSON RESPONSE:
                     {
                        "reasoning": "<your reasoning here>",
                        "root_cause_fdns": [fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/2/1']]
                     }    
                     """
                  )

        # Start a chat with automatic function calling enabled.
        chat = self.__client.chats.create(model="gemini-2.0-flash",
                                          config=config)

        # Clean up the text string so that we return proper-JSON-format
        return chat.send_message(prompt + alarms_feed).text.strip('`').replace('json', '', 1)

    def drain_queue(self, q: Queue):
        messages = []
        while not q.empty():
            log.info("Receiving messages ...")
            try:
                messages.append(q.get_nowait())
            except:
                break
        return messages

    def prompt_bulk_from_queue(self, queue: Queue):
        while True:
            log.info("Waiting ...")
            time.sleep(5)
            alarms_list = self.drain_queue(queue)
            if len(alarms_list) > 0:
                alarms_feed = '\n'.join(alarms_list)
                print(alarms_feed)
                log.info(f"alarms_feed:\n{alarms_feed}")

                # Anonymize the data we send to AI
                ai_alarms_list = self.anonymize_alarms(alarms_list)
                ai_alarms_feed = '\n'.join(ai_alarms_list)
                ai_response_json = self.prompt_from_feed(ai_alarms_feed)
                ai_response_dict = json.loads(ai_response_json)

                # Restore the AI's response to well-known
                wellknown_response = self.ai_response_to_wellknown(ai_response_dict)

                # Only print to stdout if gen_ai identified a root-cause
                if ai_response_dict['root_cause_fdns'][0] != 'indeterminate':
                    print(wellknown_response)
                log.info(f"\n{wellknown_response}")
                # Strip the unicode special chars
                #log.info(wellknown_response.encode("ascii", errors="ignore").decode())


    def anonymize_alarms(self, alarms_list:[]):
        anonymized_alarms_feed = []
        for alarm in alarms_list:
            anonymized_alarms_feed.append(self.anonymizer.anonymize_string(alarm))
        return anonymized_alarms_feed

    def ai_response_to_wellknown(self, json_response:json):
        return f"🚨root_cause_fdns={[self.anonymizer.restore_anonymized_string(fdn) for fdn in json_response['root_cause_fdns']]}🚨\n💡reasoning={self.anonymizer.restore_anonymized_string(json_response['reasoning'])}💡"




"""
Test
"""
if __name__ == '__main__':
    my_nsp_client = NspClientSingleton(server='135.121.156.104')
    my_nsp_client.authenticate()  # Get Token
    gen_ai = GenAISingleton()

    alarms_feed_1 = \
"""
2025-05-29T16:37:29.565092791Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='38.120.234.226'] | (ASN 200) VR 1: Group iBGP: Peer 38.120.234.226: received notification: code CEASE subcode CONN_REJECT
2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c2/1'] | Interface 1/1/c2/1 is not operational
2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | Interface 1/1/c3/1 is not operational
2025-05-29T16:37:34.741454505Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | Interface toCE is not operational
2025-05-29T16:37:34.747380091Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/service[service-id='411']/bgp/neighbor[ip-address='10.41.1.2'] | (ASN 200) VR 7: Group toCE: Peer 10.41.1.2: being disabled because the interface is operationally disabled

"""

    alarms_feed = alarms_feed_1
    rca = gen_ai.prompt_from_feed(alarms_feed)
    print(rca)
    #print(f"{json.loads(rca)}")
