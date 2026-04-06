"""
A LangGraph baristabot that interacts with a human and tools"
     (__start__)
         |
     (chatbot)
     c >   c >
    < c   < |
(human)  (tools)
  c
(_end__)

The tools add_to_order(), get_order(), place_order(), confirm_order() are not available yet. So, the chatbot hallucinates them.
(See interactions at the end of the code)
"""

from typing import Annotated
from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from langchain_core.tools import tool

from PIL import Image
import io
import matplotlib.pyplot as plt

from pprint import pprint

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


@tool
def get_menu() -> str:
    """Provide the latest up-to-date menu."""
    # Note that this is just hard-coded text, but you could connect this to a live stock
    # database, or you could use Gemini's multi-modal capabilities and take live photos of
    # your cafe's chalk menu or the products on the counter and assmble them into an input.

    return """
    MENU:
    Coffee Drinks:
    Espresso
    Americano
    Cold Brew

    Coffee Drinks with Milk:
    Latte
    Cappuccino
    Cortado
    Macchiato
    Mocha
    Flat White

    Tea Drinks:
    English Breakfast Tea
    Green Tea
    Earl Grey

    Tea Drinks with Milk:
    Chai Latte
    Matcha Latte
    London Fog

    Other Drinks:
    Steamer
    Hot Chocolate

    Modifiers:
    Milk options: Whole, 2%, Oat, Almond, 2% Lactose Free; Default option: whole
    Espresso shots: Single, Double, Triple, Quadruple; default: Double
    Caffeine: Decaf, Regular; default: Regular
    Hot-Iced: Hot, Iced; Default: Hot
    Sweeteners (option to add one or more): vanilla sweetener, hazelnut sweetener, caramel sauce, chocolate sauce, sugar free vanilla sweetener
    Special requests: any reasonable modification that does not involve items not on the menu, for example: 'extra hot', 'one pump', 'half caff', 'extra foam', etc.

    "dirty" means add a shot of espresso to a drink that doesn't usually have it, like "Dirty Chai Latte".
    "Regular milk" is the same as 'whole milk'.
    "Sweetened" means add some regular sugar, not a sweetener.

    Soy milk has run out of stock today, so soy is not available.
"""

# Define the tools and create a "tools" node.
tools = [get_menu]
tool_node = ToolNode(tools)

# Attach the tools to the model so that it knows what it can call.
llm_with_tools = llm.bind_tools(tools)


def maybe_exit_human_node(state: OrderState) -> Literal["chatbot", "__end__"]:
    """Route to the chatbot, unless it looks like the user is exiting."""
    if state.get("finished", False):
        return END
    else:
        return "chatbot"


def maybe_route_to_tools(state: OrderState) -> Literal["tools", "human"]:
    """Route between human or tool nodes, depending if a tool call is made."""
    if not (msgs := state.get("messages", [])):
        raise ValueError(f"No messages found when parsing state: {state}")

    # Only route based on the last message.
    msg = msgs[-1]

    # When the chatbot returns tool_calls, route to the "tools" node.
    if hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0:
        return "tools"
    else:
        return "human"


def chatbot_with_tools(state: OrderState) -> OrderState:
    """The chatbot with tools. A simple wrapper around the model's own chat interface."""
    defaults = {"order": [], "finished": False}

    if state["messages"]:
        new_output = llm_with_tools.invoke([BARISTABOT_SYSINT] + state["messages"])
    else:
        new_output = AIMessage(content=WELCOME_MSG)

    # Set up some defaults if not already set, then pass through the provided state,
    # overriding only the "messages" field.
    return defaults | state | {"messages": [new_output]}


graph_builder = StateGraph(OrderState)

# Add the nodes, including the new tool_node.
graph_builder.add_node("chatbot", chatbot_with_tools)
graph_builder.add_node("human", human_node)
graph_builder.add_node("tools", tool_node)

# Chatbot may go to tools, or human.
graph_builder.add_conditional_edges("chatbot", maybe_route_to_tools)
# Human may go back to chatbot, or exit.
graph_builder.add_conditional_edges("human", maybe_exit_human_node)

# Tools always route back to chat afterwards.
graph_builder.add_edge("tools", "chatbot")

graph_builder.add_edge(START, "chatbot")
graph_with_menu = graph_builder.compile()

img_bytes = graph_with_menu.get_graph().draw_mermaid_png()
img = Image.open(io.BytesIO(img_bytes))
plt.imshow(img)
plt.axis('off')
plt.show()

# The default recursion limit for traversing nodes is 25 - setting it higher means
# you can try a more complex order with multiple steps and round-trips (and you
# can chat for longer!)
config = {"recursion_limit": 100}

# Remember that you have not implemented ordering yet, so this will loop forever,
# unless you input `q`, `quit` or one of the other exit terms defined in the
# `human_node`.
# Uncomment this line to execute the graph:
state = graph_with_menu.invoke({"messages": []}, config)

# Things to try:
# - I'd love an espresso drink, what have you got?
# - What teas do you have?
# - Can you do a long black? (this is on the menu as an "Americano" - see if it can
#   figure it out)
# - 'q' to exit.


pprint(state)
"""
Interaction:
Model: Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?
User: What's available in your menu?
Model: We have a wide variety of drinks!

For coffee, we have Espresso, Americano, and Cold Brew, as well as milk-based drinks like Latte, Cappuccino, Cortado, Macchiato, Mocha, and Flat White.

If you prefer tea, we offer English Breakfast, Green Tea, and Earl Grey, along with Chai Latte, Matcha Latte, and London Fog (all available with milk).

For other options, we have Steamer and Hot Chocolate.

You can customize your drinks with milk options (Whole, 2%, Oat, Almond, 2% Lactose Free), different amounts of espresso shots, caffeine levels (Decaf, Regular), and temperatures (Hot, Iced). We also have several sweeteners available.

What sounds good to you today?
User: Do you have anything to eat?
Model: I only have access to the drink menu. Sorry about that! Would you like to order a drink?
User: Can I have a tall black coffee?
Model: We don't have sizes, but I can offer you an Americano or a Cold Brew. Which of those would you prefer for your black coffee?
User: Hot please
Model: Okay, so you'd like a hot Americano?
User: Yes
Model: 
User: And a glass of water please
Model: I am sorry, I can only create orders for items on the menu. I cannot add a water to your order. Would you like an Americano?
User: Yes
Model: 
User: To be clear, I only want one Americano. Is that what you have in your order?
Model: 
User: q
{'finished': True,
 'messages': [AIMessage(content='Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?', additional_kwargs={}, response_metadata={}, id='5fecb2ed-d10d-48d2-a0ec-c3d0be541643'),
              HumanMessage(content="What's available in your menu?", additional_kwargs={}, response_metadata={}, id='bbf9f6b1-c1cb-4fdf-a208-c874109113c2'),
              AIMessage(content='', additional_kwargs={'function_call': {'name': 'get_menu', 'arguments': '{}'}}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--537a7c1c-62c3-4fd8-888b-504a3b679f12-0', tool_calls=[{'name': 'get_menu', 'args': {}, 'id': '4d6e8142-0115-4b2c-80bd-f13fba053a05', 'type': 'tool_call'}], usage_metadata={'input_tokens': 359, 'output_tokens': 3, 'total_tokens': 362, 'input_token_details': {'cache_read': 0}}),
              ToolMessage(content='\n    MENU:\n    Coffee Drinks:\n    Espresso\n    Americano\n    Cold Brew\n\n    Coffee Drinks with Milk:\n    Latte\n    Cappuccino\n    Cortado\n    Macchiato\n    Mocha\n    Flat White\n\n    Tea Drinks:\n    English Breakfast Tea\n    Green Tea\n    Earl Grey\n\n    Tea Drinks with Milk:\n    Chai Latte\n    Matcha Latte\n    London Fog\n\n    Other Drinks:\n    Steamer\n    Hot Chocolate\n\n    Modifiers:\n    Milk options: Whole, 2%, Oat, Almond, 2% Lactose Free; Default option: whole\n    Espresso shots: Single, Double, Triple, Quadruple; default: Double\n    Caffeine: Decaf, Regular; default: Regular\n    Hot-Iced: Hot, Iced; Default: Hot\n    Sweeteners (option to add one or more): vanilla sweetener, hazelnut sweetener, caramel sauce, chocolate sauce, sugar free vanilla sweetener\n    Special requests: any reasonable modification that does not involve items not on the menu, for example: \'extra hot\', \'one pump\', \'half caff\', \'extra foam\', etc.\n\n    "dirty" means add a shot of espresso to a drink that doesn\'t usually have it, like "Dirty Chai Latte".\n    "Regular milk" is the same as \'whole milk\'.\n    "Sweetened" means add some regular sugar, not a sweetener.\n\n    Soy milk has run out of stock today, so soy is not available.\n', name='get_menu', id='a19e21b1-35be-405b-b9a7-4e869be8b00b', tool_call_id='4d6e8142-0115-4b2c-80bd-f13fba053a05'),
              AIMessage(content='We have a wide variety of drinks!\n\nFor coffee, we have Espresso, Americano, and Cold Brew, as well as milk-based drinks like Latte, Cappuccino, Cortado, Macchiato, Mocha, and Flat White.\n\nIf you prefer tea, we offer English Breakfast, Green Tea, and Earl Grey, along with Chai Latte, Matcha Latte, and London Fog (all available with milk).\n\nFor other options, we have Steamer and Hot Chocolate.\n\nYou can customize your drinks with milk options (Whole, 2%, Oat, Almond, 2% Lactose Free), different amounts of espresso shots, caffeine levels (Decaf, Regular), and temperatures (Hot, Iced). We also have several sweeteners available.\n\nWhat sounds good to you today?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--48ebb8d5-8c19-4548-a264-1bed11748cb0-0', usage_metadata={'input_tokens': 685, 'output_tokens': 158, 'total_tokens': 843, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Do you have anything to eat?', additional_kwargs={}, response_metadata={}, id='8177f595-6dfd-4341-abee-65e114029c59'),
              AIMessage(content='I only have access to the drink menu. Sorry about that! Would you like to order a drink?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--8a5c5bca-ffa4-4d14-a256-de9c1b9cbf29-0', usage_metadata={'input_tokens': 849, 'output_tokens': 21, 'total_tokens': 870, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Can I have a tall black coffee?', additional_kwargs={}, response_metadata={}, id='dceb860b-074f-4b21-8c40-be8809c8af3c'),
              AIMessage(content="We don't have sizes, but I can offer you an Americano or a Cold Brew. Which of those would you prefer for your black coffee?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--3ed4696f-08bf-4098-8b4a-cf66ead1c43c-0', usage_metadata={'input_tokens': 878, 'output_tokens': 30, 'total_tokens': 908, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Hot please', additional_kwargs={}, response_metadata={}, id='12929fd8-756c-4af5-b44b-68ca11c4c5f2'),
              AIMessage(content="Okay, so you'd like a hot Americano?", additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--296acc0f-4ecf-4dd8-a50a-b8d6132b1175-0', usage_metadata={'input_tokens': 910, 'output_tokens': 12, 'total_tokens': 922, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Yes', additional_kwargs={}, response_metadata={}, id='e1bb700b-2f4a-4f50-ab07-63b537435e8e'),
              AIMessage(content='', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'MALFORMED_FUNCTION_CALL', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--93fab781-5729-47c5-9878-59f8daa4b949-0', usage_metadata={'input_tokens': 922, 'output_tokens': 0, 'total_tokens': 922, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='And a glass of water please', additional_kwargs={}, response_metadata={}, id='8f9d5b09-58c4-4b3f-a700-ff5117d60844'),
              AIMessage(content='I am sorry, I can only create orders for items on the menu. I cannot add a water to your order. Would you like an Americano?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--6553c2f7-80f4-469f-91f6-574879442da1-0', usage_metadata={'input_tokens': 928, 'output_tokens': 31, 'total_tokens': 959, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Yes', additional_kwargs={}, response_metadata={}, id='7f88eb91-a112-40de-814d-dba907407376'),
              AIMessage(content='', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'MALFORMED_FUNCTION_CALL', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--a5fa4989-fa0c-4b39-bc7b-9a6420f1ac26-0', usage_metadata={'input_tokens': 959, 'output_tokens': 0, 'total_tokens': 959, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='To be clear, I only want one Americano. Is that what you have in your order?', additional_kwargs={}, response_metadata={}, id='dc811f35-f7a2-4a70-9072-d1a9df0a672b'),
              AIMessage(content='', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'MALFORMED_FUNCTION_CALL', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--1b6f02ad-0694-4ee8-8bbf-8bdbf8c78cae-0', usage_metadata={'input_tokens': 978, 'output_tokens': 0, 'total_tokens': 978, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='q', additional_kwargs={}, response_metadata={}, id='8aace94c-911c-4a0b-96a5-c5663ac2a7c9')],
 'order': []}
"""
