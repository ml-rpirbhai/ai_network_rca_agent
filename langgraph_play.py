from nsp_client import NspClientSingleton
from rag import RagSingleton

from typing import Annotated, Literal, Any

from langchain_core.tools import tool
from langchain_core.messages.ai import AIMessage

from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
from typing import Dict, Tuple

from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langchain_core.messages.tool import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from PIL import Image
import io
import matplotlib.pyplot as plt

from pprint import pprint


GOOGLE_API_KEY='***REMOVED***'


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


SYSINT = ("system", # 'system' indicates the message is a system instruction.
          "You are the network alarms RCA agent. Your task is to identify the root-cause FDN " 
          "(or FDNs if there are multiple root-cause failures) from the list of alarms that have been  sent to you. "
          "For each ne-id in the alarms feed: "
          "1) Call lg_get_ne_details to get NE details (vendor, OS type, and OS version). Then: "
          "2) Call lg_query_db with the vendor, OS type, and OS version to retrieve the reference documentation for that NE; "
          "lg_query_db may return None if there is no documentation for that particular NE vendor/chassis/OS. "
          )

prompt = ("""You are the network alarms RCA agent. Your task is to identify the root-cause FDN
             (or FDNs if there are multiple root-cause failures) from the list of alarms that have been  sent to you.
             Which of the alarms is the root-cause failure?                
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

alarms_feed = """Description of alarms (by column): | time-detected | ne-name | ne-id | object-fdn | additional-text |
                 2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c2/1'] | Interface 1/1/c2/1 is not operational
                 2025-05-29T16:37:34.741454505Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | Interface toCE is not operational
              """

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash",
                             google_api_key=GOOGLE_API_KEY)


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


tools = [lg_get_ne_details, lg_query_db]

# Attach the tools to the model so that it knows what it can call
llm_with_tools = llm.bind_tools(tools)

def chatbot_with_tools(state: OrderState) -> OrderState:
    """The chatbot with tools. A simple wrapper around the model's own chat interface."""
    # Initialize the order
    defaults = {"order": {"ne_details": {}, "references": {}}, "finished": False}

    new_output = llm_with_tools.invoke([SYSINT] + [alarms_feed] + state["messages"])

    # Set up some defaults if not already set, then pass through the provided state,
    # overriding only the "messages" field.
    return defaults | state | {"messages": [new_output]}


# Initialize nsp_client
nsp_client = NspClientSingleton(server='135.121.156.104')
nsp_client.authenticate()
rag_client = RagSingleton()

def tools_node(state: OrderState) -> OrderState:
    """The tools node. This is where we call out to the tools"""
    tool_msg = state.get("messages", [])[-1]
    order = state.get("order", {})
    outbound_msgs = []
    flow_completed = False

    for tool_call in tool_msg.tool_calls:

        if tool_call["name"] == "lg_get_ne_details":

            print(tool_call)
            ne_id = tool_call["args"]["ne_id"]
            response = nsp_client.get_ne_details(ne_id)
            # Update the order record ne_details
            order["ne_details"][ne_id] = response

        elif tool_call["name"] == "lg_query_db":

            print(tool_call)
            query = tool_call["args"]["query"]
            response = rag_client.query_db(query)
            order["references"][query] = response
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

    return {"messages": outbound_msgs, "order": order, "finished": flow_completed}



def maybe_route_to_tools(state: OrderState) -> Literal["tools", "__end__"]:
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


# Define the LangGraph and transitions
graph_builder = StateGraph(OrderState)
graph_builder.add_node("chatbot", chatbot_with_tools)
graph_builder.add_node("tools", tools_node)

graph_builder.set_entry_point("chatbot")
# Chatbot may go to tools, or exit.
graph_builder.add_conditional_edges("chatbot", maybe_route_to_tools)
# Tools always return to chatbot
graph_builder.add_edge("tools", "chatbot")

rca_langgraph = graph_builder.compile()

img_bytes = rca_langgraph.get_graph().draw_mermaid_png()
img = Image.open(io.BytesIO(img_bytes))
plt.imshow(img)
plt.axis('off')
plt.show()

state = rca_langgraph.invoke({"messages": []})
pprint(state["order"])

final_prompt = f"{prompt}\n\n{alarms_feed}\n\nNE DETAILS + DOCS:\n{pprint(state['order'])}"
print(final_prompt)
final_output = llm.invoke([final_prompt])
print(final_output.content)
