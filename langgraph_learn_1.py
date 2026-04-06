"""
A simple LangGraph baristabot that replies to hardcoded messages"
(__start__)
    |
(chatbot)
"""

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages

from pprint import pprint

from IPython.display import Image, display
from PIL import Image
import io
import matplotlib.pyplot as plt

GOOGLE_API_KEY=''

class OrderState(TypedDict):
    """State representing the customer's order conversation."""

    # The chat conversation. This preserves the conversation history
    # between nodes. The `add_messages` annotation indicates to LangGraph
    # that state is updated by appending returned messages, not replacing
    # them.
    messages: Annotated[list, add_messages]

    # The customer's in-progress order.
    order: list[str]

    # Flag indicating that the order is placed and completed.
    finished: bool


# The system instruction defines how the chatbot is expected to behave and includes
# rules for when to call different functions, as well as rules for the conversation, such
# as tone and what is permitted for discussion.
BARISTABOT_SYSINT = (
    "system",  # 'system' indicates the message is a system instruction.
    "You are a BaristaBot, an interactive cafe ordering system. A human will talk to you about the "
    "available products you have and you will answer any questions about menu items (and only about "
    "menu items - no off-topic discussion, but you can chat about the products and their history). "
    "The customer will place an order for 1 or more items from the menu, which you will structure "
    "and send to the ordering system after confirming the order with the human. "
    "\n\n"
    "Add items to the customer's order with add_to_order, and reset the order with clear_order. "
    "To see the contents of the order so far, call get_order (this is shown to you, not the user) "
    "Always confirm_order with the user (double-check) before calling place_order. Calling confirm_order will "
    "display the order items to the user and returns their response to seeing the list. Their response may contain modifications. "
    "Always verify and respond with drink and modifier names from the MENU before adding them to the order. "
    "If you are unsure a drink or modifier matches those on the MENU, ask a question to clarify or redirect. "
    "You only have the modifiers listed on the menu. "
    "Once the customer has finished ordering items, Call confirm_order to ensure it is correct then make "
    "any necessary updates and then call place_order. Once place_order has returned, thank the user and "
    "say goodbye!"
    "\n\n"
    "If any of the tools are unavailable, you can break the fourth wall and tell the user that "
    "they have not implemented them yet and should keep reading to do so.",
)

# This is the message with which the system opens the conversation.
WELCOME_MSG = "Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?"

from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI

# Try using different models. The Gemini 2.0 flash model is highly
# capable, great with tools, and has a generous free tier. If you
# try the older 1.5 models, note that the `pro` models are better at
# complex multi-tool cases like this, but the `flash` models are
# faster and have more free quota.
# Check out the features and quota differences here:
#  - https://ai.google.dev/gemini-api/docs/models/gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GOOGLE_API_KEY)


def chatbot(state: OrderState) -> OrderState:
    """The chatbot itself. A simple wrapper around the model's own chat interface."""
    message_history = [BARISTABOT_SYSINT] + state["messages"]
    return {"messages": [llm.invoke(message_history)]}


# Set up the initial graph based on our state definition.
graph_builder = StateGraph(OrderState)

# Add the chatbot function to the app graph as a node called "chatbot".
graph_builder.add_node("chatbot", chatbot)

# Define the chatbot node as the app entrypoint.
graph_builder.add_edge(START, "chatbot")

chat_graph = graph_builder.compile()

#img_bytes = chat_graph.get_graph().draw_mermaid_png()
#img = Image.open(io.BytesIO(img_bytes))
#plt.imshow(img)
#plt.axis('off')
#plt.show()

user_msg = "Hello, what can you do?"
state = chat_graph.invoke({"messages": [user_msg]})

# The state object contains lots of information. Uncomment the pprint lines to see it all.
print(state)
"""
output:
{'messages': [HumanMessage(content='Hello, what can you do?', additional_kwargs={}, response_metadata={}, id='e9370f8a-fa52-4e18-8430-f81b64b54209'), AIMessage(content="Hi there! I'm BaristaBot, and I can take your coffee order. I know all about our menu items and can answer any questions you have about them. Once you're ready, I'll put together your order and send it to the kitchen. What can I get for you today?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--b9cd48f9-3923-4749-ba78-03ce5a9bd068-0', usage_metadata={'input_tokens': 323, 'output_tokens': 64, 'total_tokens': 387, 'input_token_details': {'cache_read': 0}})]}
"""

# Note that the final state now has 2 messages. Our HumanMessage, and an additional AIMessage.
#for msg in state["messages"]:
#    print(f"{type(msg).__name__}: {msg.content}")

user_msg = "Oh great, what kinds of latte can you make?"

state["messages"].append(user_msg)
state = chat_graph.invoke(state)

pprint(state)
for msg in state["messages"]:
    print(f"{type(msg).__name__}: {msg.content}")
"""
output:
{'messages': [HumanMessage(content='Hello, what can you do?', additional_kwargs={}, response_metadata={}, id='e9370f8a-fa52-4e18-8430-f81b64b54209'),
              AIMessage(content="Hi there! I'm BaristaBot, and I can take your coffee order. I know all about our menu items and can answer any questions you have about them. Once you're ready, I'll put together your order and send it to the kitchen. What can I get for you today?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--b9cd48f9-3923-4749-ba78-03ce5a9bd068-0', usage_metadata={'input_tokens': 323, 'output_tokens': 64, 'total_tokens': 387, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Oh great, what kinds of latte can you make?', additional_kwargs={}, response_metadata={}, id='7b27d429-2f62-44e6-a2e7-c5523a92f3ef'),
              AIMessage(content="We have a few delicious lattes on our menu! There's the classic Latte, the sweet Vanilla Latte, the rich Caramel Latte, the chocolatey Mocha Latte, and the spicy Cinnamon Latte. Do any of those sound good?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--041ab331-780e-4445-aadf-f12f2cbd67f3-0', usage_metadata={'input_tokens': 397, 'output_tokens': 48, 'total_tokens': 445, 'input_token_details': {'cache_read': 0}})]}
HumanMessage: Hello, what can you do?
AIMessage: Hi there! I'm BaristaBot, and I can take your coffee order. I know all about our menu items and can answer any questions you have about them. Once you're ready, I'll put together your order and send it to the kitchen. What can I get for you today?
HumanMessage: Oh great, what kinds of latte can you make?
AIMessage: We have a few delicious lattes on our menu! There's the classic Latte, the sweet Vanilla Latte, the rich Caramel Latte, the chocolatey Mocha Latte, and the spicy Cinnamon Latte. Do any of those sound good?
"""
