import argparse
from enum import Enum
import json
import logging.config

import yaml

from typing import Annotated, Literal, Any
from typing import Dict

from google import genai
from typing_extensions import TypedDict

from google.genai import types
from langchain_core.messages.tool import ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

import time

from anonymizer import AnonymizerSingleton
import netconf_client
from message_bus import MessageBus
from nsp_client import NspClient
from rag import RagSingleton

# Suppress HTTPS warnings
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

with open('config/ai_agent_logger.yaml', 'r') as stream:
    logger_config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(logger_config)
    log = logging.getLogger(__name__)

with open('config/conf.yaml', 'r') as stream:
    config = yaml.load(stream, Loader=yaml.FullLoader)

"""
LangGraph LLM instructions
"""
SYSINT = ("system",  # 'system' indicates the message is a system instruction.
          "You are the alarms details retrieval agent. Your task is to retrieve details and documentation "
          "for the alarms that have been sent to you. "
          "For each ne-id in the alarms feed: "
          "1) Call lg_get_ne_details to get NE details (vendor, chassis-type, OS-version). Then: "
          "2) Call lg_query_db with the vendor, chassis-type and OS-version *values* (from lg_get_ne_details; "
          "pass the vendor, chassis-type, OS-version *values* in order, and separated by a space: "
          "no additional text!) to retrieve the reference documentation for that NE; "
          "lg_query_db may return None if there is no documentation for that particular NE vendor/chassis/OS. "
          "3) For interface alarms on Cisco IOS-XR: Call lg_get_cisco_ios_xr_interface_name to get the Cisco object associated with the SNMP ifIndex. "
          "Description of alarms (by column): time-detected | ne-name | ne-id | object-fdn | object-name | additional-info "
          )

"""
RCA LLM instructions and prompt
"""
INSTRUCTIONS = ("""You are the network alarms RCA agent. Your task is to identify the root-cause FDN
             (or FDNs if there are multiple root-cause failures) from the list of alarms that have been sent to you.
             Respond with either the root-cause object-fdns or 'indeterminate'.
             The root-cause is 'indeterminate' if none of the alarms in the feed is a equipment failure or configuration error.
             If there are multiple equipment failures and you cannot determine which one may be the root-cause, return multiple Object_FDNs. 
             Use your memory to attribute a recent failure to an older root-cause (not more than 5 seconds prior). In other cases, 
             the root-cause may be notified after its side-effects: This may be due to separate router processes notifying the failures.                         
             Explain your reasoning.
             Respond **only** with a valid JSON object. Do not include any other text in your response.
             Use double quotes (") for all keys and string values, like this:
             {
                       "reasoning": "your reasoning here",
                       "root_cause_fdns": ["fdn:..."]
             }       
             
             Description of alarms (by column): time-detected | ne-name | ne-id | object-fdn | object-name | additional-info                 

             EXAMPLE:
             2025-05-12T18:32:01.672731026Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='10.1.1.1'] | | (ASN 200) VR 1: Group iBGP: Peer 10.1.1.1: received notification: code CEASE subcode CONN_REJECT
             2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/2/1'] | | Interface 1/1/2/1 is not operational
             2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/3/1'] | | Interface 1/1/3/1 is not operational
             2025-05-12T18:32:02.760893587Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='100'] | | Interface toCE is not operational
             JSON RESPONSE:
             {
                        "reasoning": "<your reasoning here>",
                        "root_cause_fdns": [fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/2/1'], fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/3/1']]
             }
    
             EXAMPLE: 
             2025-05-12T18:32:01.672731026Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='10.1.1.1'] | | (ASN 200) VR 1: Group iBGP: Peer 10.1.1.1: received notification: code CEASE subcode CONN_REJECT 
             2025-05-12T18:32:02.760383079Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/2/1'] | | Interface 1/1/2/1 is not operational 
             2025-05-12T18:32:02.760893587Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='100'] | | Interface toCE is not operational 
             JSON RESPONSE:
             {
                        "reasoning": "<your reasoning here>",
                        "root_cause_fdns": [fdn:app:mdm-ami-cmodel:m07rjwbp:equipment:Equipment:/port[port-id='1/1/2/1']]
             }                 
             """
          )

PROMPT = ("""Read the 'NE_DETAILS + DOCS:' for instructions on how to interpret some alarms. 
             Which of the following alarms is the root-cause failure?
             Description of alarms (by column): time-detected | ne-name | ne-id | object-fdn | object-name | additional-info""")


class OrderState(TypedDict):
    """Agent finite-state-machine"""

    # This preserves the transition history between nodes. The `add_messages` annotation indicates to LangGraph
    # that state is updated by appending returned messages, not replacing them
    messages: Annotated[list, add_messages]

    # In-progress order
    # {'ne_details' -> {ne_id:str -> {vendor -> str,    # From get_ne_details()
    #                                 os_type -> str,   #
    #                                 version -> str}}, #
    #  'references' -> {query:str -> str}               # From query_db()
    # }
    order: Dict[str, Any]


class GenAISingleton:
    __instance = None
    __initialized = False

    # These functions have no body; LangGraph does not allow @tools to update
    # the conversation state, so you will implement a separate node to handle
    # state updates. Using @tools is still very convenient for defining the tool
    # schema, so empty functions have been defined that will be bound to the LLM
    # but their implementation is deferred to the order_node.
    @tool
    def lg_get_ne_details(self, ne_id: str) -> dict:
        """Retrieves the NE instance vendor, chassis and OS"""

    @tool
    def lg_query_db(self, query: str) -> str | None:
        """Retrieves relevant reference documentation for an NE instance vendor/chassis/OS"""

    @tool
    def lg_get_cisco_ios_xr_interface_name(self, ne_id: str, snmp_index: int) -> str:
        """For Cisco IOS-XR routers only. Given an interface SNMP ifindex, retrieves the interface name"""

    def __new__(cls, nsp_client: NspClient):
        if cls.__instance is None:
            cls.__instance = super(GenAISingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self, nsp_client: NspClient):
        if not self.__initialized:
            print("Initializing gemini_alarms_rca_agent ...")
            log.info("Initializing ...")

            global config  # Tell interpreter to use outer config declaration

            # Initialize message-bus consumer
            bus = MessageBus.get_bus(config['message_bus_name'])
            self.consumer = bus.instantiate_consumer('genai_alarms_consumer')

            GOOGLE_API_KEY = config['google_gemini_api_key']

            """
            We will use 2 LLM clients: One for LangGraph, and another for the final prompt -> RCA
            """
            langgraph_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash",
                                                   api_key=GOOGLE_API_KEY)
            # Attach the tools to the model so that it knows what it can call
            langgraph_tools = [self.lg_get_ne_details, self.lg_query_db, self.lg_get_cisco_ios_xr_interface_name]
            self.__langgraph_llm_with_tools = langgraph_llm.bind_tools(langgraph_tools)
            self.__build_graph()
            self.__nsp_client = nsp_client
            self.anonymizer = AnonymizerSingleton()
            self.__rag_client = RagSingleton(self)

            rca_llm = genai.Client(api_key=GOOGLE_API_KEY)

            """
            Start the RCA chat. We will reuse this chat object for the lifetime of the agent so that the LLM
            can recall/associate recent failures to previous/historical alarms
            """
            config = types.GenerateContentConfig(temperature=1.0,
                                                 system_instruction=INSTRUCTIONS)
            self.__rca_chat = rca_llm.chats.create(model="gemini-2.5-flash",
                                                   config=config)

            self.__initialized = True

    def __chatbot_with_tools(self, state: OrderState) -> OrderState:
        """The chatbot with tools. A simple wrapper around the model's own chat interface."""
        # Initialize the order
        defaults = {"order": {"ne_details": {}, "references": {}}}

        new_output = self.__langgraph_llm_with_tools.invoke([SYSINT] + state["messages"])

        # Set up some defaults if not already set, then pass through the provided state,
        # overriding only the "messages" field.
        return defaults | state | {"messages": [new_output]}

    def __tools_node(self, state: OrderState) -> OrderState:
        """The tools node. This is where we call out to the tools"""
        tool_msg = state.get("messages", [])[-1]
        order = state.get("order", {})
        outbound_msgs = []

        for tool_call in tool_msg.tool_calls:
            #Sleep for 1 sec to avoid hitting rate-limits on Gemini free-tier
            time.sleep(1)
            log.debug(tool_call)

            if tool_call["name"] == "lg_get_ne_details":
                ne_id = tool_call["args"]["ne_id"]
                response = self.__nsp_client.get_ne_details(ne_id)
                # Update the order record ne_details
                ne_details_map = {}
                ne_details_map['ne'] = response
                order["ne_details"][ne_id] = ne_details_map

            elif tool_call["name"] == "lg_query_db":
                query = tool_call["args"]["query"]
                response = self.__rag_client.query_db(query)
                order["references"][query] = response

            elif tool_call["name"] == "lg_get_cisco_ios_xr_interface_name":
                ne_id = tool_call["args"]["ne_id"]
                snmp_index = int(tool_call["args"]["snmp_index"])  # Need to cast to int, because Gemini sends float
                response = netconf_client.get_cisco_ios_xr_interface_name_fn(ne_id, snmp_index)

                ne_details_map = order["ne_details"][ne_id]
                # Get the ifIndex_to_interface_name_map if exists; else insert the key and default to {}
                ifIndex_to_interface_name_map = ne_details_map.setdefault('ifIndex_to_interface_name', {})
                ifIndex_to_interface_name_map[snmp_index] = response


            else:
                raise NotImplementedError(f'Unknown tool call: {tool_call["name"]}')

            # Record the tool results as tool messages.
            outbound_msgs.append(
                ToolMessage(
                    content=response,
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )

        log.debug(f"messages: {outbound_msgs}, order: {json.dumps(order, indent=4)}")
        return {"messages": outbound_msgs, "order": order}

    def __maybe_route_to_tools(self, state: OrderState) -> Literal["tools", "__end__"]:
        """Route from chatbot to tool nodes or exit"""
        if not (msgs := state.get("messages", [])):
            raise ValueError(f"No messages found when parsing state: {state}")

        # Only route based on the last message.
        msg = msgs[-1]

        # When the chatbot returns tool_calls, route to the "tools" node.
        if hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0:
            return "tools"
        else:
            return END

    def __build_graph(self):
        """Define the LangGraph and transitions"""
        graph_builder = StateGraph(OrderState)
        graph_builder.add_node("chatbot", self.__chatbot_with_tools)
        graph_builder.add_node("tools", self.__tools_node)

        graph_builder.set_entry_point("chatbot")
        # Chatbot may go to tools, or exit.
        graph_builder.add_conditional_edges("chatbot", self.__maybe_route_to_tools)
        # Tools always return to chatbot
        graph_builder.add_edge("tools", "chatbot")

        self.__rca_langgraph = graph_builder.compile()

    def prompt_from_feed(self, alarms_feed) -> json:
        # Start a langgraph chat
        state = self.__rca_langgraph.invoke({"messages": ["alarms", alarms_feed]})

        final_prompt = f"{PROMPT}\n\n{alarms_feed}\n\nNE DETAILS + DOCS:\n{state['order']}"
        log.info(f"final_prompt: {final_prompt}")

        # Invoke the RCA chat. Clean up the text string so that we return proper-JSON-format
        return self.__rca_chat.send_message(final_prompt).text.strip('`').replace('json', '', 1)

    def drain_queue(self) -> list:
        messages = None
        log.info("Checking for messages ...")
        try:
            messages = self.consumer.consume()
        except:
            log.error("Unable to retrieve messages from q")

        if messages is not None and messages.__len__() > 0:
            log.info("Received messages")
            # Extract the alarm payload from each message, and return the alarms[]
            return [message['message'] for message in messages]

    def prompt_bulk_from_queue(self):
        keep_looping = True
        while keep_looping:
            log.info("Waiting ...")
            time.sleep(5)
            alarms_list = self.drain_queue()

            if alarms_list is not None and len(alarms_list) > 0:
                alarms_feed = '\n'.join(alarms_list)
                print(alarms_feed)
                log.info(f"alarms_feed:\n{alarms_feed}")


                # Disable anonymizer for now. There is work to do to unanonimize tools calls from LangGraph
                #  e.g. to NSP and subsequently re-anonymize the tools' responses
                """
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
                """

                ai_response_json = self.prompt_from_feed(alarms_feed)
                ai_response_dict = json.loads(ai_response_json)
                # Only print to stdout if gen_ai identified a root-cause
                if ('root_cause_fdns' in ai_response_dict and ai_response_dict['root_cause_fdns'].__len__() > 0 and
                    ai_response_dict['root_cause_fdns'][0] != 'indeterminate'):
                    print(ai_response_dict)
                log.info(f"\n{ai_response_dict}")


    def anonymize_alarms(self, alarms_list:[]):
        anonymized_alarms_feed = []
        for alarm in alarms_list:
            anonymized_alarms_feed.append(self.anonymizer.anonymize_string(alarm))
        return anonymized_alarms_feed

    def ai_response_to_wellknown(self, json_response:json):
        return f"🚨root_cause_fdns={[self.anonymizer.restore_anonymized_string(fdn) for fdn in json_response['root_cause_fdns']]}🚨\n💡reasoning={self.anonymizer.restore_anonymized_string(json_response['reasoning'])}💡"

if __name__ == '__main__':
    my_nsp_client = NspClient(server=config['nsp']['ip'],
                              username=config['nsp']['user'],
                              password=config['nsp']['password'])
    gen_ai = GenAISingleton(my_nsp_client)
    gen_ai.prompt_bulk_from_queue()
