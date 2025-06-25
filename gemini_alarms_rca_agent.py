import json
import logging
import yaml

from typing import Annotated, Literal, Any
from typing import Dict

from google import genai
from langchain_core.messages import HumanMessage
from typing_extensions import TypedDict

from google.genai import types
from langchain_core.messages.tool import ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from multiprocessing import Queue
import time

from anonymizer import AnonymizerSingleton
import netconf_client
from nsp_client import NspClientSingleton
from rag import RagSingleton

from pprint import pprint

with open('config/logger.yaml', 'r') as stream:
    logger_config = yaml.load(stream, Loader=yaml.FullLoader)
    logging.config.dictConfig(logger_config)
    log = logging.getLogger(__name__)

"""
LangGraph LLM instructions
"""
SYSINT = ("system", # 'system' indicates the message is a system instruction.
          "You are the alarms details retrieval agent. Your task is to retrieve details and documentation "
          "for the alarms that have been sent to you. "
          "For each ne-id in the alarms feed: "
          "1) Call lg_get_ne_details to get NE details (vendor, chassis-type, OS-version). Then: "
          "2) Call lg_query_db with the vendor, chassis-type and OS-version to retrieve the reference documentation for that NE; "
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

    # Flag indicating that the order is placed and completed.
    finished: bool


class GenAISingleton:
    __instance = None
    __initialized = False

    # These functions have no body; LangGraph does not allow @tools to update
    # the conversation state, so you will implement a separate node to handle
    # state updates. Using @tools is still very convenient for defining the tool
    # schema, so empty functions have been defined that will be bound to the LLM
    # but their implementation is deferred to the order_node.
    @tool
    def lg_get_ne_details(ne_id: str) -> {}:
        """Retrieves the NE instance vendor, chassis and OS"""

    @tool
    def lg_query_db(query: str) -> str | None:
        """Retrieves relevant reference documentation for an NE instance vendor/chassis/OS"""

    @tool
    def lg_get_cisco_ios_xr_interface_name(ne_id: str, snmp_index: int) -> str:
        """For Cisco IOS-XR routers only. Given an interface SNMP ifindex, retrieves the interface name"""

    def __new__(cls, nsp_client: NspClientSingleton):
        if cls.__instance is None:
            cls.__instance = super(GenAISingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self, nsp_client: NspClientSingleton):
        if not self.__initialized:
            with open('config/conf.yaml', 'r') as stream:
                conf = yaml.load(stream, Loader=yaml.FullLoader)
            GOOGLE_API_KEY = conf['google_gemini_api_key']

            """
            We will use 2 LLM clients: One for LangGraph, and another for the final prompt -> RCA
            """
            self.__langgraph_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash",
                                                          api_key=GOOGLE_API_KEY)
            # Attach the tools to the model so that it knows what it can call
            self.langgraph_tools = [self.lg_get_ne_details, self.lg_query_db, self.lg_get_cisco_ios_xr_interface_name]
            self.__langgraph_llm_with_tools = self.__langgraph_llm.bind_tools(self.langgraph_tools)
            self.__build_graph()
            self.__nsp_client = nsp_client
            self.anonymizer = AnonymizerSingleton()
            self.__rag_client = RagSingleton(self)

            self.__llm = genai.Client(api_key=GOOGLE_API_KEY)

            self.__initialized = True

    def __chatbot_with_tools(self, state: OrderState) -> OrderState:
        """The chatbot with tools. A simple wrapper around the model's own chat interface."""
        # Initialize the order
        defaults = {"order": {"ne_details": {}, "references": {}}, "finished": False}

        new_output = self.__langgraph_llm_with_tools.invoke([SYSINT] + state["messages"])

        # Set up some defaults if not already set, then pass through the provided state,
        # overriding only the "messages" field.
        return defaults | state | {"messages": [new_output]}

    def __tools_node(self, state: OrderState) -> OrderState:
        """The tools node. This is where we call out to the tools"""
        tool_msg = state.get("messages", [])[-1]
        order = state.get("order", {})
        outbound_msgs = []
        flow_completed = False

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

                if response is None:
                    flow_completed = True
                #else:
                    # Inject the RAG as a message Gemini can see in the next turn
                #    outbound_msgs.append(
                #        HumanMessage(content=f"NE documentation for {query}:\n{response}")
                #    )

            elif tool_call["name"] == "lg_get_cisco_ios_xr_interface_name":
                ne_id = tool_call["args"]["ne_id"]
                snmp_index = int(tool_call["args"]["snmp_index"])  # Need to cast to int, because Gemini sends float
                response = netconf_client.get_cisco_ios_xr_interface_name_fn(ne_id, snmp_index)

                ifIndex_to_interface_name_map = {}
                ifIndex_to_interface_name_map[snmp_index] = response
                order["ne_details"][ne_id]['ifIndex_to_interface_name'] = ifIndex_to_interface_name_map

                flow_completed = True

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

        log.debug(f"messages: {outbound_msgs}, order: {order}, finished: {flow_completed}")
        return {"messages": outbound_msgs, "order": order, "finished": flow_completed}

    def __maybe_route_to_tools(self, state: OrderState) -> Literal["tools", "__end__"]:
        """Route from chatbot to tool nodes or exit"""
        if not (msgs := state.get("messages", [])):
            raise ValueError(f"No messages found when parsing state: {state}")

        # Only route based on the last message.
        msg = msgs[-1]

        # When the chatbot returns tool_calls, route to the "tools" node.
        if hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0 and state.get("finished") is False:
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
        # Start a chat
        state = self.__rca_langgraph.invoke({"messages": ["alarms", alarms_feed]})

        config = types.GenerateContentConfig(temperature=1.0,
                                             system_instruction=INSTRUCTIONS)

        # Start a chat with automatic function calling enabled.
        chat = self.__llm.chats.create(model="gemini-2.5-flash",
                                          config=config)

        final_prompt = f"{PROMPT}\n\n{alarms_feed}\n\nNE DETAILS + DOCS:\n{state['order']}"
        log.info(f"final_prompt: {final_prompt}")

        # Invoke. Clean up the text string so that we return proper-JSON-format
        return chat.send_message(final_prompt + alarms_feed).text.strip('`').replace('json', '', 1)


    def drain_queue(self, q: Queue):
        messages = []
        while not q.empty():
            log.info("Receiving messages ...")
            try:
                messages.append(q.get_nowait())
            except:
                log.error("Unable to retrieve messages from q")
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


"""
Test
"""
if __name__ == '__main__':
    my_nsp_client = NspClientSingleton(server='135.121.156.104')
    my_nsp_client.authenticate()  # Get Token
    gen_ai = GenAISingleton(my_nsp_client)

    alarms_feed_1 = \
"""
2025-05-29T16:37:29.565092791Z | sim234_236 | 2001::236 | fdn:app:mdm-ami-cmodel:2001::236:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='38.120.234.226'] | | (ASN 200) VR 1: Group iBGP: Peer 38.120.234.226: received notification: code CEASE subcode CONN_REJECT
2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c2/1'] | | Interface 1/1/c2/1 is not operational
2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | | Interface 1/1/c3/1 is not operational
2025-05-29T16:37:34.741454505Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | | Interface toCE is not operational
2025-05-29T16:37:34.747380091Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/service[service-id='411']/bgp/neighbor[ip-address='10.41.1.2'] | | (ASN 200) VR 7: Group toCE: Peer 10.41.1.2: being disabled because the interface is operationally disabled

"""
    alarms_feed_2 = \
"""
2025-06-23T18:43:04.870104158Z | xrv24.labs.ca.alcatel-lucent.com | 38.120.234.239 | fdn:app:mdm-ami-cmodel:38.120.234.239:equipment:NetworkElement:38.120.234.239 | | Alarm Details 
trapName : IsisAdjacencyChange
isisNotificationSysLevelIndex : 1
isisNotificationCircIfIndex : 12
isisPduLspId : 03 81 20 23 42 36 00 00 
isisAdjState : 4
2025-06-23T18:43:05.123821669Z | xrv24.labs.ca.alcatel-lucent.com | 38.120.234.239 | fdn:app:mdm-ami-cmodel:38.120.234.239:equipment:NetworkElement:38.120.234.239 | | Alarm Details 
trapName : IsisAdjacencyChange
isisNotificationSysLevelIndex : 2
isisNotificationCircIfIndex : 12
isisPduLspId : 03 81 20 23 42 36 00 00 
isisAdjState : 4
2025-06-23T18:43:14.461006551Z | xrv24.labs.ca.alcatel-lucent.com | 38.120.234.239 | fdn:app:mdm-ami-cmodel:38.120.234.239:equipment:NetworkElement:38.120.234.239 | | Alarm Details 
trapName : OspfNeighborDown
ospfRouterId : 38.120.234.239
ospfNbrIpAddr : 10.236.239.1
ospfNbrAddressLessIndex : 0
ospfNbrRtrId : 38.120.234.236
ospfNbrState : 1
2025-06-23T18:43:17.474872323Z | xrv24.labs.ca.alcatel-lucent.com | 38.120.234.239 | fdn:app:mdm-ami-cmodel:38.120.234.239:equipment:NetworkElement:38.120.234.239 | | Alarm Details 
trapName : LspDown
mplsTunnelAdminStatus : 1
mplsTunnelOperStatus : 1
2025-06-23T18:43:17.831869840Z | xrv24.labs.ca.alcatel-lucent.com | 38.120.234.239 | fdn:app:mdm-ami-cmodel:38.120.234.239:equipment:NetworkElement:38.120.234.239 | | Alarm Details:
trapName : PortDown 
ifIndex : 16 
ifAdminStatus : 2
ifOperStatus : 2
"""

    alarms_feed = alarms_feed_2
    rca = gen_ai.prompt_from_feed(alarms_feed)
    print(rca)