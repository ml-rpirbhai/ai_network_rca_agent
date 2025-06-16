"""
A LangGraph baristabot that interacts with a human"
(__start__)
    |
(chatbot)
  |   >
 <   c
(human)
  c
(_end__)

The chatbot hallucinates the menu.
The tools are not available yet. However, the chatbot hallucinated invoking add_to_order(), get_order(), place_order(), confirm_order()
(See interactions at the end of the code)
"""

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages

from IPython.display import Image, display
from PIL import Image
import io
import matplotlib.pyplot as plt

from pprint import pprint

GOOGLE_API_KEY='AIzaSyBx6vUjcxQheUOvVzUAnWE7ZzgqaqHqT7g'

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

from langchain_core.messages.ai import AIMessage


def human_node(state: OrderState) -> OrderState:
    """Display the last model message to the user, and receive the user's input."""
    last_msg = state["messages"][-1]
    print("Model:", last_msg.content)

    user_input = input("User: ")

    # If it looks like the user is trying to quit, flag the conversation
    # as over.
    if user_input in {"q", "quit", "exit", "goodbye"}:
        state["finished"] = True

    return state | {"messages": [("user", user_input)]}


def chatbot_with_welcome_msg(state: OrderState) -> OrderState:
    """The chatbot itself. A wrapper around the model's own chat interface."""

    if state["messages"]:
        # If there are messages, continue the conversation with the Gemini model.
        new_output = llm.invoke([BARISTABOT_SYSINT] + state["messages"])
    else:
        # If there are no messages, start with the welcome message.
        new_output = AIMessage(content=WELCOME_MSG)

    return state | {"messages": [new_output]}


# Start building a new graph.
graph_builder = StateGraph(OrderState)

# Add the chatbot and human nodes to the app graph.
graph_builder.add_node("chatbot", chatbot_with_welcome_msg)
graph_builder.add_node("human", human_node)

# Start with the chatbot again.
graph_builder.add_edge(START, "chatbot")

# The chatbot will always go to the human next.
graph_builder.add_edge("chatbot", "human");

from typing import Literal


def maybe_exit_human_node(state: OrderState) -> Literal["chatbot", "__end__"]:
    """Route to the chatbot, unless it looks like the user is exiting."""
    if state.get("finished", False):
        return END
    else:
        return "chatbot"


graph_builder.add_conditional_edges("human", maybe_exit_human_node)

chat_with_human_graph = graph_builder.compile()

#img_bytes = chat_with_human_graph.get_graph().draw_mermaid_png()
#img = Image.open(io.BytesIO(img_bytes))
#plt.imshow(img)
#plt.axis('off')
#plt.show()

# The default recursion limit for traversing nodes is 25 - setting it higher means
# you can try a more complex order with multiple steps and round-trips (and you
# can chat for longer!)
config = {"recursion_limit": 100}

# Remember that this will loop forever, unless you input `q`, `quit` or one of the
# other exit terms defined in `human_node`.
# Uncomment this line to execute the graph:
state = chat_with_human_graph.invoke({"messages": []}, config)

# Things to try:
#  - Just chat! There's no ordering or menu yet.
#  - 'q' to exit.

pprint(state)
"""
Interaction #1:
Model: Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?
User: Hello, nice to meet you. What's the weather like today?
Model: I'm sorry, I can only answer questions about the menu items. However, I can tell you about our delicious Caramel Macchiato! It's a layered drink with vanilla syrup, steamed milk, espresso, and caramel drizzle. Did you want to add it to your order?
User: Do you have anything to eat?
Model: Yes, we have a delicious Blueberry Muffin. Would you like to add it to your order?
User: Do you have anything with chocolate?
Model: Yes, we have a Chocolate Croissant. It's a flaky, buttery pastry with a rich chocolate filling. Would you like to add it to your order?
User: Yes please
Model: ```tool_code
add_to_order(item='Chocolate Croissant', quantity=1)
```
User: How much do I owe you? 
Model: ```tool_code
get_order()
```
User: q
{'finished': True,
 'messages': [AIMessage(content='Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?', additional_kwargs={}, response_metadata={}, id='5d5c83ed-7eff-4eb4-a7c6-4bc25513958d'),
              HumanMessage(content="Hello, nice to meet you. What's the weather like today?", additional_kwargs={}, response_metadata={}, id='bb9b1583-0f37-4141-9d08-425a206d5d4c'),
              AIMessage(content="I'm sorry, I can only answer questions about the menu items. However, I can tell you about our delicious Caramel Macchiato! It's a layered drink with vanilla syrup, steamed milk, espresso, and caramel drizzle. Did you want to add it to your order?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--b94ce8a6-eff6-42f2-8cc9-c0e86db80800-0', usage_metadata={'input_tokens': 353, 'output_tokens': 58, 'total_tokens': 411, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Do you have anything to eat?', additional_kwargs={}, response_metadata={}, id='755bcfd8-06c1-445a-b7b0-9e37e2e80cc4'),
              AIMessage(content='Yes, we have a delicious Blueberry Muffin. Would you like to add it to your order?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--0cba9b29-4ce4-4974-8dfd-bb2d63a3f56d-0', usage_metadata={'input_tokens': 417, 'output_tokens': 21, 'total_tokens': 438, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Do you have anything with chocolate?', additional_kwargs={}, response_metadata={}, id='4b89ba83-4740-4302-9b34-a519a11630ad'),
              AIMessage(content="Yes, we have a Chocolate Croissant. It's a flaky, buttery pastry with a rich chocolate filling. Would you like to add it to your order?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--133b3304-c80b-4492-9545-926bb2411f66-0', usage_metadata={'input_tokens': 444, 'output_tokens': 34, 'total_tokens': 478, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Yes please', additional_kwargs={}, response_metadata={}, id='11c35f60-0505-4262-a9cc-59c6524c65ae'),
              AIMessage(content="```tool_code\nadd_to_order(item='Chocolate Croissant', quantity=1)\n```", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--4eafa1a4-c6a0-4a39-a930-9480f8b7920a-0', usage_metadata={'input_tokens': 479, 'output_tokens': 23, 'total_tokens': 502, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='How much do I owe you? ', additional_kwargs={}, response_metadata={}, id='1d1ccf63-86b2-4c1d-bf1c-086760a1ff19'),
              AIMessage(content='```tool_code\nget_order()\n```', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--cc3a057c-1822-4ab9-9bb8-3cb5a4cfff93-0', usage_metadata={'input_tokens': 510, 'output_tokens': 11, 'total_tokens': 521, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='q', additional_kwargs={}, response_metadata={}, id='5f5d5e04-e0e3-4066-b1cd-1116350cca94')]}

"""
"""
Interaction #2:
Model: Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?
User: Can i please order a burger
Model: I'm sorry, we don't serve burgers here. We are a cafe, so we have coffee, tea, and pastries. Would you like to try something from our menu?
User: OK. I will have a tall Americano and a chocolate chip muffin
Model: ```tool_code
add_to_order(item='Americano', size='Tall')
add_to_order(item='Chocolate Chip Muffin')
```
User: Can you repeat my order back to me?
Model: ```tool_code
confirm_order()
```
User: Do you remember what I ordered?
Model: You ordered a Tall Americano and a Chocolate Chip Muffin. Is that correct?
User: Yes
Model: ```tool_code
place_order()
```
User: How much should I pay?
Model: The tools to calculate that aren't implemented yet. You should keep reading to implement the tools.
User: q
{'finished': True,
 'messages': [AIMessage(content='Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?', additional_kwargs={}, response_metadata={}, id='2efdb000-e71d-4e14-a23a-835ecb474e13'),
              HumanMessage(content='Can i please order a burger', additional_kwargs={}, response_metadata={}, id='1b9fa4b3-959b-47c9-a35f-d934f07771ca'),
              AIMessage(content="I'm sorry, we don't serve burgers here. We are a cafe, so we have coffee, tea, and pastries. Would you like to try something from our menu?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--00dd3d91-da79-41e8-b374-6b0c917a6d78-0', usage_metadata={'input_tokens': 344, 'output_tokens': 39, 'total_tokens': 383, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='OK. I will have a tall Americano and a chocolate chip muffin', additional_kwargs={}, response_metadata={}, id='d139e7bc-8c52-474c-a56a-abb43d477633'),
              AIMessage(content="```tool_code\nadd_to_order(item='Americano', size='Tall')\nadd_to_order(item='Chocolate Chip Muffin')\n```", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--72b57510-9c56-491d-8a5d-e9bb8eca33c0-0', usage_metadata={'input_tokens': 395, 'output_tokens': 36, 'total_tokens': 431, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Can you repeat my order back to me?', additional_kwargs={}, response_metadata={}, id='246aeaa8-6768-46aa-90fb-15644ada3ab9'),
              AIMessage(content='```tool_code\nconfirm_order()\n```', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--60e8fa21-7f66-42c4-988d-2d5a6c5b9c15-0', usage_metadata={'input_tokens': 440, 'output_tokens': 11, 'total_tokens': 451, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Do you remember what I ordered?', additional_kwargs={}, response_metadata={}, id='cd8d898b-55e5-40be-ad19-af96da2559a7'),
              AIMessage(content='You ordered a Tall Americano and a Chocolate Chip Muffin. Is that correct?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--69f74035-b293-4ef1-a726-01bf4148d8d7-0', usage_metadata={'input_tokens': 458, 'output_tokens': 17, 'total_tokens': 475, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Yes', additional_kwargs={}, response_metadata={}, id='2e36d7e0-c65c-42f6-bd73-7d34f58ce9dd'),
              AIMessage(content='```tool_code\nplace_order()\n```', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--39ad85a2-79c6-414d-a95a-cdee67abc3c1-0', usage_metadata={'input_tokens': 475, 'output_tokens': 11, 'total_tokens': 486, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='How much should I pay?', additional_kwargs={}, response_metadata={}, id='f5751063-3470-4379-9c1c-bddaee9755e1'),
              AIMessage(content="The tools to calculate that aren't implemented yet. You should keep reading to implement the tools.", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--952bb2c7-8425-4787-9b1c-85175265bfe3-0', usage_metadata={'input_tokens': 492, 'output_tokens': 21, 'total_tokens': 513, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='q', additional_kwargs={}, response_metadata={}, id='1f59e082-a7a9-46cc-8fec-edc3288a1eb8')]}

"""