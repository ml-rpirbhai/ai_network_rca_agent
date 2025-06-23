"""
A LangGraph baristabot that interacts with a human and tools"
                 (__start__)
                     |
       -----c(    chatbot     )
      |      c >    c >    c >
      |     < c    < |     < |
      |  (human)  (tools)  (ordering)
      |    c
      ->(_end__)

The tools add_to_order(), get_order(), place_order(), confirm_order() are available.
The chatbot naturally exits after the order has been confirmed and placed.
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

# The default recursion limit for traversing nodes is 25 - setting it higher means
# you can try a more complex order with multiple steps and round-trips (and you
# can chat for longer!)
config = {"recursion_limit": 100}


from collections.abc import Iterable
from random import randint

from langchain_core.messages.tool import ToolMessage

# These functions have no body; LangGraph does not allow @tools to update
# the conversation state, so you will implement a separate node to handle
# state updates. Using @tools is still very convenient for defining the tool
# schema, so empty functions have been defined that will be bound to the LLM
# but their implementation is deferred to the order_node.


@tool
def add_to_order(drink: str, modifiers: Iterable[str]) -> str:
    """Adds the specified drink to the customer's order, including any modifiers.

    Returns:
      The updated order in progress.
    """


@tool
def confirm_order() -> str:
    """Asks the customer if the order is correct.

    Returns:
      The user's free-text response.
    """


@tool
def get_order() -> str:
    """Returns the users order so far. One item per line."""


@tool
def clear_order():
    """Removes all items from the user's order."""


@tool
def place_order() -> int:
    """Sends the order to the barista for fulfillment.

    Returns:
      The estimated number of minutes until the order is ready.
    """


def order_node(state: OrderState) -> OrderState:
    """The ordering node. This is where the order state is manipulated."""
    tool_msg = state.get("messages", [])[-1]
    order = state.get("order", [])
    outbound_msgs = []
    order_placed = False

    for tool_call in tool_msg.tool_calls:

        if tool_call["name"] == "add_to_order":

            # Each order item is just a string. This is where it assembled as "drink (modifiers, ...)".
            modifiers = tool_call["args"]["modifiers"]
            modifier_str = ", ".join(modifiers) if modifiers else "no modifiers"

            order.append(f'{tool_call["args"]["drink"]} ({modifier_str})')
            response = "\n".join(order)

        elif tool_call["name"] == "confirm_order":

            # We could entrust the LLM to do order confirmation, but it is a good practice to
            # show the user the exact data that comprises their order so that what they confirm
            # precisely matches the order that goes to the kitchen - avoiding hallucination
            # or reality skew.

            # In a real scenario, this is where you would connect your POS screen to show the
            # order to the user.

            print("Your order:")
            if not order:
                print("  (no items)")

            for drink in order:
                print(f"  {drink}")

            response = input("Is this correct? ")

        elif tool_call["name"] == "get_order":

            response = "\n".join(order) if order else "(no order)"

        elif tool_call["name"] == "clear_order":

            order.clear()
            response = None

        elif tool_call["name"] == "place_order":

            order_text = "\n".join(order)
            print("Sending order to kitchen!")
            print(order_text)

            # TODO(you!): Implement cafe.
            order_placed = True
            response = randint(1, 5)  # ETA in minutes

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

    return {"messages": outbound_msgs, "order": order, "finished": order_placed}


def maybe_exit_human_node(state: OrderState) -> Literal["chatbot", "__end__"]:
    """Route to the chatbot, unless it looks like the user is exiting."""
    if state.get("finished", False):
        return END
    else:
        return "chatbot"


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


def maybe_route_to_tools(state: OrderState) -> str:
    """Route between chat and tool nodes if a tool call is made."""
    if not (msgs := state.get("messages", [])):
        raise ValueError(f"No messages found when parsing state: {state}")

    msg = msgs[-1]

    if state.get("finished", False):
        # When an order is placed, exit the app. The system instruction indicates
        # that the chatbot should say thanks and goodbye at this point, so we can exit
        # cleanly.
        return END

    elif hasattr(msg, "tool_calls") and len(msg.tool_calls) > 0:
        # Route to `tools` node for any automated tool calls first.
        if any(
                tool["name"] in tool_node.tools_by_name.keys() for tool in msg.tool_calls
        ):
            return "tools"
        else:
            return "ordering"

    else:
        return "human"

# Auto-tools will be invoked automatically by the ToolNode
auto_tools = [get_menu]
tool_node = ToolNode(auto_tools)

# Order-tools will be handled by the order node.
order_tools = [add_to_order, confirm_order, get_order, clear_order, place_order]

# The LLM needs to know about all of the tools, so specify everything here.
llm_with_tools = llm.bind_tools(auto_tools + order_tools)


graph_builder = StateGraph(OrderState)

# Nodes
graph_builder.add_node("chatbot", chatbot_with_tools)
graph_builder.add_node("human", human_node)
graph_builder.add_node("tools", tool_node)
graph_builder.add_node("ordering", order_node)

# Chatbot -> {ordering, tools, human, END}
graph_builder.add_conditional_edges("chatbot", maybe_route_to_tools)
# Human -> {chatbot, END}
graph_builder.add_conditional_edges("human", maybe_exit_human_node)

# Tools (both kinds) always route back to chat afterwards.
graph_builder.add_edge("tools", "chatbot")
graph_builder.add_edge("ordering", "chatbot")

graph_builder.add_edge(START, "chatbot")
graph_with_order_tools = graph_builder.compile()

img_bytes = graph_with_order_tools.get_graph().draw_mermaid_png()
img = Image.open(io.BytesIO(img_bytes))
plt.imshow(img)
plt.axis('off')
plt.show()

# Uncomment this line to execute the graph:
state = graph_with_order_tools.invoke({"messages": []}, config)

# Things to try:
# - Order a drink!
# - Make a change to your order.
# - "Which teas are from England?"
# - Note that the graph should naturally exit after placing an order.

pprint(state)
"""
Interaction:
Model: Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?
User: What's on the menu?
Model: Here is the menu:

Coffee Drinks: Espresso, Americano, Cold Brew

Coffee Drinks with Milk: Latte, Cappuccino, Cortado, Macchiato, Mocha, Flat White

Tea Drinks: English Breakfast Tea, Green Tea, Earl Grey

Tea Drinks with Milk: Chai Latte, Matcha Latte, London Fog

Other Drinks: Steamer, Hot Chocolate

Modifiers:
Milk options: Whole, 2%, Oat, Almond, 2% Lactose Free
Espresso shots: Single, Double, Triple, Quadruple
Caffeine: Decaf, Regular
Hot-Iced: Hot, Iced
Sweeteners: vanilla sweetener, hazelnut sweetener, caramel sauce, chocolate sauce, sugar free vanilla sweetener
Special requests: any reasonable modification that does not involve items not on the menu.
User: Do you have any European teas?
Model: We have English Breakfast Tea and Earl Grey. Are either of those what you were looking for?
User: OK. A large English tea with 1 sugar and 2 cream
Model: I can add an English Breakfast Tea to your order with sugar as a sweetener. However, we only have milk options (Whole, 2%, Oat, Almond, 2% Lactose Free). Which milk would you like? We do not have cream. Also, we do not have sizes, so I will assume the default size.
User: Almond milk please
Model: OK. I have added an English Breakfast Tea with almond milk and sugar to your order. Anything else?
User: No thanks
Your order:
  English Breakfast Tea (Almond, sugar)
Is this correct? Yes
Model: OK, so just the English Breakfast Tea with almond milk and sugar. Is that correct?
User: Yes
Sending order to kitchen!
English Breakfast Tea (Almond, sugar)
{'finished': True,
 'messages': [AIMessage(content='Welcome to the BaristaBot cafe. Type `q` to quit. How may I serve you today?', additional_kwargs={}, response_metadata={}, id='18b20c09-cba0-4bf2-8b81-05444d5d8c3c'),
              HumanMessage(content="What's on the menu?", additional_kwargs={}, response_metadata={}, id='bcf7d5ed-f34d-4edb-b7f9-cb78f46ea02d'),
              AIMessage(content='', additional_kwargs={'function_call': {'name': 'get_menu', 'arguments': '{}'}}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--f8aea264-8509-4810-828e-3623b4d997e3-0', tool_calls=[{'name': 'get_menu', 'args': {}, 'id': 'b7b74239-7f84-4505-b84b-c2521679394e', 'type': 'tool_call'}], usage_metadata={'input_tokens': 484, 'output_tokens': 3, 'total_tokens': 487, 'input_token_details': {'cache_read': 0}}),
              ToolMessage(content='\n    MENU:\n    Coffee Drinks:\n    Espresso\n    Americano\n    Cold Brew\n\n    Coffee Drinks with Milk:\n    Latte\n    Cappuccino\n    Cortado\n    Macchiato\n    Mocha\n    Flat White\n\n    Tea Drinks:\n    English Breakfast Tea\n    Green Tea\n    Earl Grey\n\n    Tea Drinks with Milk:\n    Chai Latte\n    Matcha Latte\n    London Fog\n\n    Other Drinks:\n    Steamer\n    Hot Chocolate\n\n    Modifiers:\n    Milk options: Whole, 2%, Oat, Almond, 2% Lactose Free; Default option: whole\n    Espresso shots: Single, Double, Triple, Quadruple; default: Double\n    Caffeine: Decaf, Regular; default: Regular\n    Hot-Iced: Hot, Iced; Default: Hot\n    Sweeteners (option to add one or more): vanilla sweetener, hazelnut sweetener, caramel sauce, chocolate sauce, sugar free vanilla sweetener\n    Special requests: any reasonable modification that does not involve items not on the menu, for example: \'extra hot\', \'one pump\', \'half caff\', \'extra foam\', etc.\n\n    "dirty" means add a shot of espresso to a drink that doesn\'t usually have it, like "Dirty Chai Latte".\n    "Regular milk" is the same as \'whole milk\'.\n    "Sweetened" means add some regular sugar, not a sweetener.\n\n    Soy milk has run out of stock today, so soy is not available.\n', name='get_menu', id='782df62f-ac40-464b-b5e1-c1ec16f0ac8a', tool_call_id='b7b74239-7f84-4505-b84b-c2521679394e'),
              AIMessage(content='Here is the menu:\n\nCoffee Drinks: Espresso, Americano, Cold Brew\n\nCoffee Drinks with Milk: Latte, Cappuccino, Cortado, Macchiato, Mocha, Flat White\n\nTea Drinks: English Breakfast Tea, Green Tea, Earl Grey\n\nTea Drinks with Milk: Chai Latte, Matcha Latte, London Fog\n\nOther Drinks: Steamer, Hot Chocolate\n\nModifiers:\nMilk options: Whole, 2%, Oat, Almond, 2% Lactose Free\nEspresso shots: Single, Double, Triple, Quadruple\nCaffeine: Decaf, Regular\nHot-Iced: Hot, Iced\nSweeteners: vanilla sweetener, hazelnut sweetener, caramel sauce, chocolate sauce, sugar free vanilla sweetener\nSpecial requests: any reasonable modification that does not involve items not on the menu.', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--86fb2484-dc8a-4018-9712-211a66902d42-0', usage_metadata={'input_tokens': 810, 'output_tokens': 161, 'total_tokens': 971, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Do you have any European teas?', additional_kwargs={}, response_metadata={}, id='5ee1c39d-9c9b-4f32-ab44-7859910c5710'),
              AIMessage(content='We have English Breakfast Tea and Earl Grey. Are either of those what you were looking for?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--6765cc94-9b05-44b1-84df-21bc3beab064-0', usage_metadata={'input_tokens': 977, 'output_tokens': 20, 'total_tokens': 997, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='OK. A large English tea with 1 sugar and 2 cream', additional_kwargs={}, response_metadata={}, id='d0697b4f-133b-485d-8086-8e4a850b2f3d'),
              AIMessage(content='I can add an English Breakfast Tea to your order with sugar as a sweetener. However, we only have milk options (Whole, 2%, Oat, Almond, 2% Lactose Free). Which milk would you like? We do not have cream. Also, we do not have sizes, so I will assume the default size.', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--c68e6738-76a0-448c-a372-0b445b69225e-0', usage_metadata={'input_tokens': 1010, 'output_tokens': 69, 'total_tokens': 1079, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Almond milk please', additional_kwargs={}, response_metadata={}, id='5e56db32-9bb3-456c-9b21-187d2125a269'),
              AIMessage(content='', additional_kwargs={'function_call': {'name': 'add_to_order', 'arguments': '{"modifiers": ["Almond", "sugar"], "drink": "English Breakfast Tea"}'}}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--8035106f-2615-4e90-99e4-e727209fa6a5-0', tool_calls=[{'name': 'add_to_order', 'args': {'modifiers': ['Almond', 'sugar'], 'drink': 'English Breakfast Tea'}, 'id': 'ef38a574-3af6-4f06-8c56-e1912bf8c1a8', 'type': 'tool_call'}], usage_metadata={'input_tokens': 1081, 'output_tokens': 12, 'total_tokens': 1093, 'input_token_details': {'cache_read': 0}}),
              ToolMessage(content='English Breakfast Tea (Almond, sugar)', name='add_to_order', id='3af70e91-43f9-4df7-bd81-4009ec0285b8', tool_call_id='ef38a574-3af6-4f06-8c56-e1912bf8c1a8'),
              AIMessage(content='OK. I have added an English Breakfast Tea with almond milk and sugar to your order. Anything else?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--00704e76-0307-40b8-a449-969097667dbf-0', usage_metadata={'input_tokens': 1107, 'output_tokens': 22, 'total_tokens': 1129, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='No thanks', additional_kwargs={}, response_metadata={}, id='8e24b6b1-fbc1-41d1-b34a-f27286cfd345'),
              AIMessage(content='', additional_kwargs={'function_call': {'name': 'confirm_order', 'arguments': '{}'}}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--7d13c64c-e788-4810-8d7d-d296049e2e9a-0', tool_calls=[{'name': 'confirm_order', 'args': {}, 'id': 'a3254673-d276-4089-8e38-687847925279', 'type': 'tool_call'}], usage_metadata={'input_tokens': 1130, 'output_tokens': 3, 'total_tokens': 1133, 'input_token_details': {'cache_read': 0}}),
              ToolMessage(content='Yes', name='confirm_order', id='f59b407f-b1fe-4c7c-a27e-6455b7df7c47', tool_call_id='a3254673-d276-4089-8e38-687847925279'),
              AIMessage(content='OK, so just the English Breakfast Tea with almond milk and sugar. Is that correct?', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--1f6ec17f-09ae-403b-b51e-ba8a8f1a860f-0', usage_metadata={'input_tokens': 1138, 'output_tokens': 19, 'total_tokens': 1157, 'input_token_details': {'cache_read': 0}}),
              HumanMessage(content='Yes', additional_kwargs={}, response_metadata={}, id='cfad41ec-2aec-4abc-8cfe-c3742203c8d8'),
              AIMessage(content='', additional_kwargs={'function_call': {'name': 'place_order', 'arguments': '{}'}}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--eedb2856-d746-4555-9f29-67233b1d190e-0', tool_calls=[{'name': 'place_order', 'args': {}, 'id': '8369d2a4-9cee-4f8b-8bb2-149c26263a4f', 'type': 'tool_call'}], usage_metadata={'input_tokens': 1157, 'output_tokens': 3, 'total_tokens': 1160, 'input_token_details': {'cache_read': 0}}),
              ToolMessage(content='3', name='place_order', id='d6ef2c66-0812-41cd-8fa8-936fa1d56cd3', tool_call_id='8369d2a4-9cee-4f8b-8bb2-149c26263a4f'),
              AIMessage(content='OK. Your order has been placed and will be ready in approximately 3 minutes. Thank you!', additional_kwargs={}, response_metadata={'prompt_feedback': {'block_reason': 0, 'safety_ratings': []}, 'finish_reason': 'STOP', 'model_name': 'gemini-2.0-flash', 'safety_ratings': []}, id='run--7ceffed9-5ea1-4e56-9c30-a98b671785f0-0', usage_metadata={'input_tokens': 1165, 'output_tokens': 21, 'total_tokens': 1186, 'input_token_details': {'cache_read': 0}})],
 'order': ['English Breakfast Tea (Almond, sugar)']}
"""

pprint(state["order"])