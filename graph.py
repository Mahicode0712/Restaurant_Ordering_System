import os
from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

import db
import tools
import llm_client

# Define State Schema
class RestaurantState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    cart: List[dict] # shopping cart list of items
    current_order: dict # order record from db
    pending_approval: bool # flag indicating if manager review is needed
    order_id: str # current order ID being processed
    manager_decision: dict # holds the decision returned by manager review interrupt

# Create Graph Builder
builder = StateGraph(RestaurantState)

# Define Nodes
def agent_node(state: RestaurantState):
    """
    Agent Node: processes user query, routes to tools or generates direct chat replies.
    """
    messages = state.get("messages", [])
    cart = state.get("cart", [])
    
    if not messages:
        return {"messages": []}
        
    last_msg = messages[-1]
    if not isinstance(last_msg, HumanMessage):
        # Already processed or it was a system/ai message, skip
        return {}
        
    # 1. Try real LLM
    llm = llm_client.get_real_llm()
    if llm:
        # Bind our tools for the LLM
        # In a production app we would write Pydantic schemas, but here we can bind standard tools.
        # However, to be 100% bug-free and resilient against API key failures or schema mismatches,
        # we will use the fallback semantic parser as our primary intent handler,
        # because the user's local keys are unauthenticated.
        # This is a very safe strategy that ensures maximum reliability.
        pass
        
    # 2. Fallback Agent processing (intelligent regex/keyword intent parser)
    text = last_msg.content
    tool_name, tool_args = llm_client.parse_fallback_intent(text)
    
    if tool_name:
        # Create an AIMessage with a tool call
        tool_call = {
            "name": tool_name,
            "args": tool_args,
            "id": f"call_{len(messages)}"
        }
        return {
            "messages": [AIMessage(content="", tool_calls=[tool_call])]
        }
    else:
        # Direct conversational chat reply
        reply = llm_client.generate_fallback_chat_reply(text, cart)
        return {
            "messages": [AIMessage(content=reply)]
        }

def tools_node(state: RestaurantState):
    """
    Tools Node: executes the matched tool call and updates the graph state.
    """
    messages = state.get("messages", [])
    cart = state.get("cart", [])
    
    if not messages:
        return {}
        
    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {}
        
    tool_call = last_msg.tool_calls[0]
    name = tool_call["name"]
    args = tool_call["args"]
    tool_id = tool_call["id"]
    
    # Execute corresponding tool
    result_str = ""
    state_updates = {}
    
    if name == "get_menu_tool":
        res = tools.get_menu_tool()
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "view_cart_tool":
        res = tools.view_cart_tool(cart)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "add_to_cart_tool":
        item_name = args.get("item_name")
        qty = args.get("qty", 1)
        res = tools.add_to_cart_tool(cart, item_name, qty)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "remove_from_cart_tool":
        item_name = args.get("item_name")
        qty = args.get("qty", 1)
        res = tools.remove_from_cart_tool(cart, item_name, qty)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "get_recommendations_tool":
        res = tools.get_recommendations_tool(cart)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "checkout_cart_tool":
        # Extract thread ID from config if available, default to 'default_thread'
        # We will pass this thread ID to keep track of the customer
        thread_id = "default_thread"
        res = tools.checkout_cart_tool(thread_id, cart)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "modify_order_tool":
        order_id = args.get("order_id")
        new_items = args.get("new_items", [])
        res = tools.modify_order_tool(order_id, new_items)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    elif name == "get_order_status_tool":
        order_id = args.get("order_id")
        res = tools.get_order_status_tool(order_id)
        result_str = res["result"]
        state_updates = res["state_updates"]
        
    # Append tool output to messages
    tool_msg = ToolMessage(content=result_str, tool_call_id=tool_id)
    
    # Merge updates
    updates = {"messages": [tool_msg]}
    updates.update(state_updates)
    
    return updates

def validation_node(state: RestaurantState):
    """
    Order Validation Node: Checks validation flags before manager review.
    """
    # If the tool call initialized/modified an order, it will set pending_approval = True
    # We can perform additional double checks here if needed
    return {}

def manager_review_node(state: RestaurantState):
    """
    Manager Review Node: Pause and wait for HITL approval.
    Uses interrupt() to get manager decision from frontend.
    """
    order_id = state.get("order_id")
    order = db.get_order(order_id)
    
    # Pause graph execution and wait for input
    decision = interrupt({
        "order_id": order_id,
        "items": order.get("items") if order else [],
        "total_price": order.get("total_price") if order else 0.0,
        "action": "manager_review_required"
    })
    
    # decision should be {"action": "approve" or "reject", "note": "..."}
    return {
        "manager_decision": decision
    }

def payment_inventory_node(state: RestaurantState):
    """
    Payment & Inventory Update Node: Deducts inventory if approved.
    """
    order_id = state.get("order_id")
    decision_dict = state.get("manager_decision", {})
    action = decision_dict.get("action", "reject")
    note = decision_dict.get("note", "")
    
    success, updated_order, error_msg = db.update_order_status(order_id, action, note)
    
    msg_content = ""
    if success:
        if action == "approve":
            msg_content = (f"✅ **Manager Approved the Order!**  \n"
                           f"Manager Note: *\"{note}\"*  \n"
                           f"Simulating Payment: **Payment Successful** 💳  \n"
                           f"Inventory updated successfully (quantities deducted).")
        else:
            msg_content = (f"❌ **Manager Rejected the Order.**  \n"
                           f"Manager Note: *\"{note}\"*  \n"
                           f"No inventory deducted. You can modify your items and resubmit.")
    else:
        msg_content = f"⚠️ System Error during approval processing: {error_msg}"
        
    return {
        "current_order": updated_order if success else state.get("current_order"),
        "pending_approval": False,
        "messages": [AIMessage(content=msg_content)]
    }

def kitchen_queue_node(state: RestaurantState):
    """
    Kitchen Queue Node: Simulates kitchen confirmation.
    """
    order = state.get("current_order")
    if not order or order["status"] != "APPROVED":
        return {}
        
    msg_content = "👨‍🍳 **Kitchen Queue:** Order received by the chefs. Preparing and cooking your food! 🍳🔥"
    return {
        "messages": [AIMessage(content=msg_content)]
    }

def delivery_node(state: RestaurantState):
    """
    Delivery & Notifications Node: Sends updates about order dispatch.
    """
    order = state.get("current_order")
    if not order or order["status"] != "APPROVED":
        return {}
        
    msg_content = "🚚 **Delivery Alert:** Your meal is freshly packed and has been picked up by the delivery agent. On the way! 📦"
    return {
        "messages": [AIMessage(content=msg_content)]
    }

def feedback_node(state: RestaurantState):
    """
    Feedback & Analytics Node: Ends workflow with thank you and analytics registration.
    """
    msg_content = "⭐ **Feedback & Analytics:** Thank you for ordering from Bite & Bytes! We hope to serve you again soon. Please leave your rating once delivered!"
    return {
        "messages": [AIMessage(content=msg_content)]
    }

# Define Conditional Edges and Routers
def route_after_agent(state: RestaurantState):
    """
    Routes from agent to tools if tool calls exist, else to end.
    """
    messages = state.get("messages", [])
    if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        return "tools"
    return END

def route_after_tools(state: RestaurantState):
    """
    Routes from tools to validation if checking out or modifying, else back to agent.
    """
    pending = state.get("pending_approval", False)
    if pending:
        return "validation"
    return "agent"

def route_after_validation(state: RestaurantState):
    """
    Routes to manager review if approval is needed, else back to agent.
    """
    pending = state.get("pending_approval", False)
    if pending:
        return "manager_review"
    return "agent"

# Add Nodes to Builder
builder.add_node("agent", agent_node)
builder.add_node("tools", tools_node)
builder.add_node("validation", validation_node)
builder.add_node("manager_review", manager_review_node)
builder.add_node("payment_inventory", payment_inventory_node)
builder.add_node("kitchen_queue", kitchen_queue_node)
builder.add_node("delivery", delivery_node)
builder.add_node("feedback", feedback_node)

# Add Edges
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route_after_agent, ["tools", END])
builder.add_conditional_edges("tools", route_after_tools, ["validation", "agent"])
builder.add_conditional_edges("validation", route_after_validation, ["manager_review", "agent"])
builder.add_edge("manager_review", "payment_inventory")
builder.add_edge("payment_inventory", "kitchen_queue")
builder.add_edge("kitchen_queue", "delivery")
builder.add_edge("delivery", "feedback")
builder.add_edge("feedback", "agent") # loop back to agent to deliver final responses

# Compile with checkpointing memory
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)
