import os
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage

load_dotenv()

# We look for GEMINI_API_KEY or GOOGLE_API_KEY in the environment
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

def get_real_llm():
    if not api_key or api_key.startswith("AQ.Ab8RN6Dummy") or "Dummy" in api_key:
        return None
    try:
        # Create the model using langchain_google_genai
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
            temperature=0.2
        )
        return llm
    except Exception as e:
        print("Failed to initialize Gemini LLM:", e)
        return None

def parse_fallback_intent(user_message):
    """
    Parses the last user message using regex/keywords to determine intent and return a tool call if matched,
    or None if it should be handled as natural conversation.
    Returns: (tool_name, tool_args) or (None, None)
    """
    text = user_message.lower().strip()
    
    # 1. Menu Tool
    if any(k in text for k in ["show menu", "view menu", "get menu", "what do you have", "what's on the menu", "food list", "menu list"]):
        return "get_menu_tool", {}
        
    # 2. View Cart Tool
    if any(k in text for k in ["view cart", "show cart", "what's in my cart", "check cart", "see cart", "my cart"]):
        return "view_cart_tool", {}
        
    # 3. Checkout Tool
    if any(k in text for k in ["checkout", "place order", "order now", "confirm order", "buy now"]):
        return "checkout_cart_tool", {}
        
    # 4. Recommendation Tool
    if any(k in text for k in ["recommend", "what goes well", "what else should i get", "any suggestions", "suggest food", "recommendations"]):
        return "get_recommendations_tool", {}
        
    # 5. Order Status Tool
    status_match = re.search(r"(?:status of|where is|track|check|info on)\s+(ord_[a-f0-9]+)", text)
    if status_match:
        return "get_order_status_tool", {"order_id": status_match.group(1)}
    status_match_simple = re.search(r"status\b.*?(ord_[a-f0-9]+)?", text)
    if status_match_simple and status_match_simple.group(1):
        return "get_order_status_tool", {"order_id": status_match_simple.group(1)}
        
    # 6. Modify Order Tool
    modify_match = re.search(r"(?:modify|edit|change|update)\s+(ord_[a-f0-9]+)", text)
    if modify_match:
        order_id = modify_match.group(1)
        # We need to extract the new items. For simplicity, we search for common patterns like "add 2 fries"
        # Since modify_order takes a list of items, we can parse them
        items = parse_items_from_text(text)
        if items:
            return "modify_order_tool", {"order_id": order_id, "new_items": items}
        return None, None # Let natural language ask which items to change
        
    # 7. Add to Cart Tool
    # Look for "add 2 classic burger", "add burger_classic", "i want 1 coke", "give me 3 French Fries"
    # Matches patterns like: add 2 classic burger, add a classic burger, add fries
    add_match = re.search(r"(?:add|want|get|order|give me|buy)\s+(\d+|a|an)?\s*([a-zA-Z\s]+?)(?:\s*(?:to cart|to my cart|\.|$))", text)
    if add_match:
        qty_str = add_match.group(1)
        qty = 1
        if qty_str:
            if qty_str.isdigit():
                qty = int(qty_str)
            elif qty_str in ["a", "an"]:
                qty = 1
        item_raw = add_match.group(2).strip()
        # Clean up item_raw from words like "of", "portion of", etc.
        item_raw = re.sub(r"^(?:of|portion of|cup of|can of|bottle of)\s+", "", item_raw)
        
        # Match against our known menu items
        item_id = match_menu_item(item_raw)
        if item_id:
            return "add_to_cart_tool", {"item_name": item_id, "qty": qty}
            
    # 8. Remove from Cart Tool
    # Match patterns like: remove classic burger, remove 2 fries
    remove_match = re.search(r"(?:remove|delete|discard|take off|take away)\s+(\d+|a|an)?\s*([a-zA-Z\s]+?)(?:\s*(?:from cart|from my cart|\.|$))", text)
    if remove_match:
        qty_str = remove_match.group(1)
        qty = 1
        if qty_str and qty_str.isdigit():
            qty = int(qty_str)
        item_raw = remove_match.group(2).strip()
        item_id = match_menu_item(item_raw)
        if item_id:
            return "remove_from_cart_tool", {"item_name": item_id, "qty": qty}

    return None, None

def match_menu_item(text):
    """
    Matches user input string to a valid menu item_id.
    """
    text = text.lower().strip()
    # Direct mapping mapping keywords to item_ids
    mappings = {
        "classic beef burger": "burger_classic",
        "classic burger": "burger_classic",
        "beef burger": "burger_classic",
        "burger": "burger_classic",
        "cheese burger": "burger_cheese",
        "cheeseburger": "burger_cheese",
        "french fries": "sides_fries",
        "fries": "sides_fries",
        "onion rings": "sides_rings",
        "rings": "sides_rings",
        "coca cola": "drinks_coke",
        "coke": "drinks_coke",
        "cola": "drinks_coke",
        "lemonade": "drinks_lemon",
        "lemon juice": "drinks_lemon",
        "lemon": "drinks_lemon",
        "chocolate brownie": "desserts_brownie",
        "brownie": "desserts_brownie",
        "vanilla ice cream": "desserts_icecream",
        "ice cream": "desserts_icecream",
        "icecream": "desserts_icecream"
    }
    return mappings.get(text) or mappings.get(text.replace("burgers", "burger").replace("friess", "fries"))

def parse_items_from_text(text):
    """
    Parses items and quantities from text, returns a list of {"item_id": str, "qty": int}
    """
    # Matches patterns like "2 fries and 1 coke" or "add burger_classic"
    # Let's find all pairs of (number, word)
    items = []
    pairs = re.findall(r"(\d+)\s+([a-zA-Z\s]+?)(?:and|,|$)", text)
    for qty_str, name in pairs:
        item_id = match_menu_item(name.strip())
        if item_id:
            items.append({"item_id": item_id, "qty": int(qty_str)})
            
    # If no numbers found, look for single item additions
    if not items:
        item_id = match_menu_item(text)
        if item_id:
            items.append({"item_id": item_id, "qty": 1})
            
    return items

def generate_fallback_chat_reply(user_message, cart):
    """
    Generates natural language replies when no tool calls are matched.
    """
    text = user_message.lower().strip()
    
    # Greetings
    if any(k in text for k in ["hi", "hello", "hey", "greetings", "good morning", "good evening"]):
        return ("👋 Hello! Welcome to the **Bite & Bytes Restaurant**. I am your conversational assistant!\n\n"
                "You can ask me to **show the menu**, **add items to your cart** (e.g., *'add 2 fries to cart'*), "
                "**view your cart**, **checkout**, or **check your order status**.\n\n"
                "What can I get started for you today? 🍔")
                
    # Thank you
    if any(k in text for k in ["thanks", "thank you", "great", "awesome", "perfect"]):
        return "You're very welcome! Let me know if you need anything else. 😊"
        
    # Recommendations request (explicitly handled if get_recommendations_tool not run)
    if "recommend" in text or "suggest" in text:
        return "I highly recommend pairing our **Classic Beef Burger** with crispy **French Fries** and a refreshing **Lemonade**! Or you can ask for suggestions and I'll analyze your current cart."

    # General help
    return ("I'm not sure I understood that request. Here is what I can do:\n"
            "- **Show menu**: *'Show me the menu'* 📋\n"
            "- **Add to cart**: *'Add 2 cheeseburgers to cart'* 🛒\n"
            "- **Remove from cart**: *'Remove 1 fries'* ❌\n"
            "- **View cart**: *'What is in my cart?'* 🛍️\n"
            "- **Checkout**: *'Checkout and place order'* 💳\n"
            "- **Check order status**: *'Track order ord_xxxxxxx'* 📍\n\n"
            "How can I help you?")
