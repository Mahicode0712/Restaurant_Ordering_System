import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

import db
import graph

app = FastAPI(title="Bite & Bytes - Restaurant AI System")

# Enable CORS for flexible UI access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database
db.init_db()

# Create Static Directory if not exists
os.makedirs("static", exist_ok=True)

# Data Schemas
class ChatRequest(BaseModel):
    message: str
    thread_id: str

class DecisionRequest(BaseModel):
    order_id: str
    note: Optional[str] = ""

class StockRequest(BaseModel):
    item_id: str
    qty_diff: int

# API Endpoints

@app.get("/api/menu")
def api_get_menu():
    return db.get_menu()

@app.get("/api/orders/all")
def api_get_all_orders():
    return db.get_all_orders()

@app.get("/api/orders/pending")
def api_get_pending_orders():
    return db.get_pending_orders()

@app.get("/api/analytics")
def api_get_analytics():
    return db.get_analytics()

@app.post("/api/menu/update_stock")
def api_update_stock(req: StockRequest):
    item = db.update_stock(req.item_id, req.qty_diff)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Stock updated successfully", "item": item}

@app.post("/api/chat")
def api_chat(req: ChatRequest):
    thread_id = req.thread_id
    message_text = req.message
    
    config = {"configurable": {"thread_id": thread_id}}
    
    # 1. Retrieve current state
    state = graph.graph.get_state(config)
    
    # Check if there is an active interrupt (waiting for manager decision)
    # If the user sends a message while an order is pending, we warn them that they need to wait for manager approval
    # OR we let them chat. But if they checkout, we pause.
    if state and state.next:
        # Check if the graph is paused at manager_review
        if "manager_review" in state.next:
            # We are waiting for manager decision.
            # However, if the user asks a question like "what is the status", we can answer it?
            # Actually, to make it simple: if paused at manager_review, the user can still talk but the graph won't resume until the manager action.
            # Let's check if the manager review is pending.
            # We can inform the user they have a pending order.
            pass
            
    # 2. Invoke the graph with the new user message
    inputs = {
        "messages": [HumanMessage(content=message_text)]
    }
    
    try:
        # Run graph
        result = graph.graph.invoke(inputs, config)
        
        # 3. Analyze post-execution state
        next_state = graph.graph.get_state(config)
        
        # Get all assistant messages generated in this turn
        messages = next_state.values.get("messages", [])
        cart = next_state.values.get("cart", [])
        current_order = next_state.values.get("current_order", {})
        pending_approval = next_state.values.get("pending_approval", False)
        order_id = next_state.values.get("order_id", "")
        
        # Extract messages from the latest turn
        # We look for messages after the user's latest message
        latest_reply_content = ""
        agent_responses = []
        
        # Iterate backwards to find the user message we just sent, and collect everything after it
        user_index = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage) and messages[i].content == message_text:
                user_index = i
                break
                
        if user_index != -1:
            for msg in messages[user_index+1:]:
                # Collect AIMessages and ToolMessages
                if isinstance(msg, AIMessage) and msg.content:
                    agent_responses.append(msg.content)
                elif isinstance(msg, ToolMessage):
                    # We can log tool messages or show them if helpful
                    pass
        else:
            # Fallback if indices mismatch: return last AI message
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    agent_responses.append(msg.content)
                    break
            agent_responses.reverse()
            
        latest_reply_content = "\n\n".join(agent_responses) if agent_responses else "I've updated your session."
        
        # Is the graph now paused waiting for manager approval?
        is_waiting_approval = False
        if next_state.next and "manager_review" in next_state.next:
            is_waiting_approval = True
            
        return {
            "reply": latest_reply_content,
            "cart": cart,
            "current_order": current_order,
            "pending_approval": pending_approval,
            "order_id": order_id,
            "waiting_for_approval": is_waiting_approval,
            "chat_history": _serialize_messages(messages)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph execution failed: {str(e)}")

@app.post("/api/orders/approve")
def api_approve_order(req: DecisionRequest):
    order_id = req.order_id
    note = req.note
    
    # We find the thread_id associated with this order_id
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    thread_id = order["customer_thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    
    # Resume the graph run using Command(resume=...)
    from langgraph.types import Command
    try:
        # Resume manager_review node
        graph.graph.invoke(
            Command(resume={"action": "approve", "note": note}), 
            config
        )
        
        # Get updated state
        next_state = graph.graph.get_state(config)
        messages = next_state.values.get("messages", [])
        
        return {
            "message": "Order approved and payment processed.",
            "order": db.get_order(order_id),
            "chat_history": _serialize_messages(messages)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resume graph: {str(e)}")

@app.post("/api/orders/reject")
def api_reject_order(req: DecisionRequest):
    order_id = req.order_id
    note = req.note
    
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    thread_id = order["customer_thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    
    # Resume the graph run using Command(resume=...)
    from langgraph.types import Command
    try:
        graph.graph.invoke(
            Command(resume={"action": "reject", "note": note}), 
            config
        )
        
        next_state = graph.graph.get_state(config)
        messages = next_state.values.get("messages", [])
        
        return {
            "message": "Order rejected by manager.",
            "order": db.get_order(order_id),
            "chat_history": _serialize_messages(messages)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resume graph: {str(e)}")

def _serialize_messages(messages):
    serialized = []
    for msg in messages:
        role = "user"
        if isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, ToolMessage):
            role = "tool"
            
        serialized.append({
            "role": role,
            "content": msg.content
        })
    return serialized

# Serve Frontend SPA
@app.get("/", response_class=HTMLResponse)
def serve_home():
    # If static/index.html exists, read and serve it
    static_file = os.path.join("static", "index.html")
    if os.path.exists(static_file):
        with open(static_file, "r") as f:
            return f.read()
    return """
    <html>
        <body>
            <h1>Bite & Bytes System Server is Running</h1>
            <p>Frontend file static/index.html is missing. Please implement the frontend page.</p>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
