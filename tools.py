import db
import json

def get_menu_tool():
    menu_items = db.get_menu()
    if not menu_items:
        return {
            "result": "The menu is currently empty.",
            "state_updates": {}
        }
        
    lines = ["### 📋 Menu"]
    current_cat = None
    for item in menu_items:
        if item["category"] != current_cat:
            current_cat = item["category"]
            lines.append(f"\n**{current_cat}**:")
        lines.append(f"- **{item['name']}** - ${item['price']:.2f} (Stock: {item['available_qty']})  \n  *{item['description']}*")
        
    return {
        "result": "\n".join(lines),
        "state_updates": {}
    }

def add_to_cart_tool(cart, item_name, qty):
    # Match item by ID or name
    is_ok, item_id, name, stock, price, reason = db.check_item_availability(item_name, qty)
    if not is_ok:
        return {
            "result": f"❌ Cannot add to cart: {reason}",
            "state_updates": {}
        }
        
    # Check if item is already in the cart
    updated_cart = list(cart)
    found = False
    
    # Calculate how much is already in the cart for stock validation
    qty_in_cart = 0
    for it in updated_cart:
        if it["item_id"] == item_id:
            qty_in_cart = it["qty"]
            
    if qty_in_cart + qty > stock:
        return {
            "result": f"❌ Cannot add {qty} more of '{name}' to cart. You already have {qty_in_cart} in cart, and live stock is {stock}.",
            "state_updates": {}
        }
        
    for it in updated_cart:
        if it["item_id"] == item_id:
            it["qty"] += qty
            found = True
            break
            
    if not found:
        updated_cart.append({
            "item_id": item_id,
            "name": name,
            "price": price,
            "qty": qty
        })
        
    # Calculate cart total
    subtotal = sum(it["price"] * it["qty"] for it in updated_cart)
    
    result_msg = f"🛒 Added {qty}x **{name}** to your cart.\n\n"
    result_msg += _format_cart_summary(updated_cart, subtotal)
    
    return {
        "result": result_msg,
        "state_updates": {"cart": updated_cart}
    }

def remove_from_cart_tool(cart, item_name, qty):
    item_id = None
    # Match item
    item_db = db.get_item_by_id(item_name)
    if not item_db:
        item_db = db.get_item_by_name(item_name)
    if item_db:
        item_id = item_db["item_id"]
    else:
        # Fallback to fuzzy substring match in cart
        for it in cart:
            if item_name.lower() in it["name"].lower():
                item_id = it["item_id"]
                break
                
    if not item_id:
        return {
            "result": f"❌ Item '{item_name}' was not found in your cart.",
            "state_updates": {}
        }
        
    updated_cart = []
    removed_qty = 0
    removed_name = ""
    
    for it in cart:
        if it["item_id"] == item_id:
            removed_name = it["name"]
            if it["qty"] <= qty:
                removed_qty = it["qty"]
                # Skip adding it to updated_cart to remove it completely
                continue
            else:
                removed_qty = qty
                updated_cart.append({
                    "item_id": it["item_id"],
                    "name": it["name"],
                    "price": it["price"],
                    "qty": it["qty"] - qty
                })
        else:
            updated_cart.append(dict(it))
            
    if removed_qty == 0:
        return {
            "result": f"❌ Item '{item_name}' was not found in your cart.",
            "state_updates": {}
        }
        
    subtotal = sum(it["price"] * it["qty"] for it in updated_cart)
    result_msg = f"❌ Removed {removed_qty}x **{removed_name}** from your cart.\n\n"
    result_msg += _format_cart_summary(updated_cart, subtotal)
    
    return {
        "result": result_msg,
        "state_updates": {"cart": updated_cart}
    }

def view_cart_tool(cart):
    if not cart:
        return {
            "result": "🛒 Your shopping cart is empty.",
            "state_updates": {}
        }
        
    subtotal = sum(it["price"] * it["qty"] for it in cart)
    return {
        "result": _format_cart_summary(cart, subtotal),
        "state_updates": {}
    }

def checkout_cart_tool(thread_id, cart):
    if not cart:
        return {
            "result": "❌ Cannot checkout: Your cart is empty. Please add items to your cart first.",
            "state_updates": {}
        }
        
    # Check feasibility
    items_to_check = [{"item_id": it["item_id"], "qty": it["qty"]} for it in cart]
    success, order_id, order_details, error_msg = db.create_order(thread_id, items_to_check)
    
    if not success:
        return {
            "result": f"❌ Checkout failed: {error_msg}",
            "state_updates": {"pending_approval": False}
        }
        
    return {
        "result": (f"🎉 **Order Placed Successfully!**\n\n"
                   f"**Order ID:** `{order_id}`  \n"
                   f"**Total:** ${order_details['total_price']:.2f}  \n"
                   f"**Status:** `PENDING_APPROVAL` ⏳\n\n"
                   f"Your order has been sent to the manager queue for approval. "
                   f"You can check its status at any time by asking: *'What is the status of my order?'*"),
        "state_updates": {
            "cart": [], # Clear cart on checkout
            "current_order": order_details,
            "pending_approval": True,
            "order_id": order_id
        }
    }

def modify_order_tool(order_id, new_items):
    """
    Modifies an order.
    new_items: list of {"item_id": str, "qty": int} or {"name": str, "qty": int}
    """
    if not order_id:
        return {
            "result": "❌ Please specify the Order ID you want to modify.",
            "state_updates": {}
        }
        
    success, updated_order, error_msg = db.modify_order(order_id, new_items)
    if not success:
        return {
            "result": f"❌ Modification failed: {error_msg}",
            "state_updates": {}
        }
        
    return {
        "result": (f"🔄 **Order Modified successfully!**\n\n"
                   f"**Order ID:** `{order_id}`  \n"
                   f"**New Total:** ${updated_order['total_price']:.2f}  \n"
                   f"**Status Reset to:** `PENDING_APPROVAL` ⏳\n\n"
                   f"Because the order was modified, it has been resubmitted for manager approval. "
                   f"Any previously deducted inventory has been correctly handled."),
        "state_updates": {
            "current_order": updated_order,
            "pending_approval": True,
            "order_id": order_id
        }
    }

def get_order_status_tool(order_id):
    if not order_id:
        return {
            "result": "❌ Please specify an Order ID.",
            "state_updates": {}
        }
        
    order = db.get_order(order_id)
    if not order:
        return {
            "result": f"❌ Order `{order_id}` not found.",
            "state_updates": {}
        }
        
    lines = [
        f"📋 **Order Status Details**",
        f"**Order ID:** `{order['order_id']}`",
        f"**Status:** `{order['status']}`",
        f"**Total Price:** ${order['total_price']:.2f}",
        f"**Placed At:** {order['created_at']}"
    ]
    if order["manager_note"]:
        lines.append(f"**Manager Note:** *\"{order['manager_note']}\"*")
        
    lines.append("\n**Items Ordered:**")
    for it in order["items"]:
        lines.append(f"- {it['qty']}x **{it['name']}** (${it['price']:.2f} each)")
        
    return {
        "result": "\n".join(lines),
        "state_updates": {"current_order": order}
    }

def get_recommendations_tool(cart):
    all_items = db.get_menu()
    cart_item_ids = {it["item_id"] for it in cart}
    
    recommendations = []
    # Simple recommendation engine logic:
    # If burger in cart -> recommend fries, soft drink, chocolate brownie
    # If desserts in cart -> recommend ice cream, hot brownie
    # If empty -> recommend best-selling Classic Burger and French Fries
    has_burger = any("burger" in it["item_id"] for it in cart)
    has_fries = any("fries" in it["item_id"] for it in cart)
    has_drinks = any("drinks" in it["item_id"] for it in cart)
    
    candidates = []
    if not cart:
        candidates = ["burger_classic", "sides_fries", "drinks_lemon"]
    elif has_burger and not has_fries:
        candidates = ["sides_fries", "drinks_coke"]
    elif has_burger and has_fries and not has_drinks:
        candidates = ["drinks_lemon", "drinks_coke"]
    elif has_drinks and not has_burger:
        candidates = ["burger_classic", "desserts_brownie"]
    else:
        # Default fallback: anything not currently in the cart
        candidates = ["desserts_brownie", "burger_cheese", "sides_rings"]
        
    for item in all_items:
        if item["item_id"] in candidates and item["item_id"] not in cart_item_ids:
            recommendations.append(item)
            
    # Cap at 3 recommendations
    recommendations = recommendations[:3]
    
    if not recommendations:
        # Just return top items
        recommendations = [item for item in all_items if item["item_id"] not in cart_item_ids][:2]
        
    lines = ["⭐️ **Recommendations for You**"]
    for item in recommendations:
        lines.append(f"- **{item['name']}** - ${item['price']:.2f}  \n  *{item['description']}*")
        
    return {
        "result": "\n".join(lines),
        "state_updates": {}
    }

def _format_cart_summary(cart, subtotal):
    if not cart:
        return "🛒 Your shopping cart is empty."
    lines = ["**Your Cart Details:**"]
    for it in cart:
        lines.append(f"- {it['qty']}x **{it['name']}** (${it['price']:.2f} each) = ${it['price']*it['qty']:.2f}")
    lines.append(f"\n**Subtotal:** **${subtotal:.2f}**")
    return "\n".join(lines)
