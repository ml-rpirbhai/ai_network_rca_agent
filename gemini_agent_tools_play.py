from google import genai
from google.genai import types

from nsp_client import NspClient
from rag import RagSingleton

GOOGLE_API_KEY=''
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

nsp_client = NspClient(server='135.121.156.104')
rag_instance = RagSingleton(genai_client)

tools = [nsp_client.get_l3vpn_interface_details,
         nsp_client.get_ne_details,
         RagSingleton.instance.query_db]

instruction = """You are a helpful chatbot that can interact with NSP to retrieve details about network objects. 
You will take the user's questions and retrieve the required information using the tools available. 
Once you have the information you need, you will answer the user's question using the data returned.

Use nsp_client.get_l3vpn_interface_details to retrieve the port-parent and IP addresses of an L3VPN interface.
Use nsp_client.get_ne_details to retrieve an NE instance's vendor, chassis and OS details.
Use RagSingleton.instance.query_db to retrieve useful references information about how to interpret an NE instance's vendor or OS type/version alarms: 
  Simply provide the vendor, OS type and version in the query (don't provide any other details)."""

# Start a chat with automatic function calling enabled.
chat = genai_client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction=instruction,
        tools=tools,
    ),
)

#resp = chat.send_message("What is the parent port of the L3 interface 'toCE' on L3VPN service-instance '411' on site '2001::225'?")
#resp = chat.send_message("What is the IPv6 address of the L3 interface 'toCE' on L3VPN service-instance '411' on site '2001::225'?")
#resp = chat.send_message("Is PE-CE eBGP peer 10.41.1.2 configured on L3VPN service-instance '411' on site '2001::225' interface 'toCE'?")
alarms_feed = """2025-05-29T16:37:34.736748113Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c2/1'] | Interface 1/1/c2/1 is not operational
                 2025-05-29T16:37:34.741454505Z | sim234_225 | 2001::225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | Interface toCE is not operational
              """

#message = """Did interface toCE fail because port 1/1/c2/1 failed?
#             You can assume that service-name = service-id.
#             Description of alarms (by column): | time-detected | ne-name | ne-id | object-fdn | additional-text |
#             Alarms:
#          """

message = "What is the relevant reference information for these alarms?"
          
resp = chat.send_message(message + alarms_feed)
print(f"\n{resp.text}")
