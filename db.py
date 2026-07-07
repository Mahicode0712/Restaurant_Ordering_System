import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "restaurant.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create menu table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS menu (
        item_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        available_qty INTEGER NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT 1,
        category TEXT NOT NULL,
        description TEXT,
        image_url TEXT
    )
    """)
    
    # Create orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        customer_thread_id TEXT NOT NULL,
        items TEXT NOT NULL, -- JSON list of {"item_id": str, "name": str, "price": float, "qty": int}
        status TEXT NOT NULL, -- DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, DELIVERED
        total_price REAL NOT NULL,
        manager_note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    
    conn.commit()
    seed_menu_if_empty()
    conn.close()

def seed_menu_if_empty():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM menu")
    if cursor.fetchone()[0] == 0:
        default_items = [
            ("burger_classic", "Classic Beef Burger", 12.99, 20, 1, "Burgers", "Juicy beef patty, cheddar, lettuce, tomato, special sauce", "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500&auto=format&fit=crop&q=60"),
            ("burger_cheese", "Cheese Burger", 13.99, 15, 1, "Burgers", "Beef patty with extra melted cheddar cheese, pickles, mustard", "https://images.unsplash.com/photo-1571091718767-18b5b1457add?w=500&auto=format&fit=crop&q=60"),
            ("sides_fries", "French Fries", 4.99, 30, 1, "Sides", "Crispy golden fries seasoned with sea salt", "https://images.unsplash.com/photo-1573080496219-bb080dd4f877?w=500&auto=format&fit=crop&q=60"),
            ("sides_rings", "Onion Rings", 5.99, 25, 1, "Sides", "Crispy batter-fried onion rings", "https://images.unsplash.com/photo-1639024471283-2bc7b3c6a267?w=500&auto=format&fit=crop&q=60"),
            ("drinks_coke", "Coca Cola", 2.49, 50, 1, "Drinks", "Chilled classic Coca-Cola can", "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500&auto=format&fit=crop&q=60"),
            ("drinks_lemon", "Lemonade", 3.49, 40, 1, "Drinks", "Freshly squeezed lemon juice with mint", "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?w=500&auto=format&fit=crop&q=60"),
            ("desserts_brownie", "Chocolate Brownie", 6.99, 10, 1, "Desserts", "Warm fudge brownie with chocolate chips", "https://images.unsplash.com/photo-1564355808539-22fda35bed7e?w=500&auto=format&fit=crop&q=60"),
            ("desserts_icecream", "Vanilla Ice Cream", 5.99, 12, 1, "Desserts", "Creamy vanilla bean ice cream", "https://images.unsplash.com/photo-1570197788417-0e82375c9371?w=500&auto=format&fit=crop&q=60")
        ]
        cursor.executemany("""
        INSERT INTO menu (item_id, name, price, available_qty, is_active, category, description, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, default_items)
        conn.commit()
    conn.close()

def get_menu():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM menu WHERE is_active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_item_by_id(item_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM menu WHERE item_id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_item_by_name(name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM menu WHERE LOWER(name) = LOWER(?) AND is_active = 1", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def check_item_availability(item_id_or_name, qty):
    """
    Returns (is_available, item_id, item_name, current_stock, price, reason)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Try by ID first
    cursor.execute("SELECT * FROM menu WHERE item_id = ? AND is_active = 1", (item_id_or_name,))
    row = cursor.fetchone()
    
    # Try by name if not found
    if not row:
        cursor.execute("SELECT * FROM menu WHERE LOWER(name) = LOWER(?) AND is_active = 1", (item_id_or_name,))
        row = cursor.fetchone()
        
    conn.close()
    
    if not row:
        return False, None, None, 0, 0.0, f"Item '{item_id_or_name}' is not on the menu."
        
    item = dict(row)
    if item["available_qty"] >= qty:
        return True, item["item_id"], item["name"], item["available_qty"], item["price"], "Available"
    else:
        return False, item["item_id"], item["name"], item["available_qty"], item["price"], f"Requested {qty} but only {item['available_qty']} available."

def check_order_feasibility(items):
    """
    Validates a list of items against live inventory.
    items: list of {"item_id": str, "qty": int} or {"name": str, "qty": int}
    Returns (is_feasible, validated_items, total_price, error_message)
    """
    validated_items = []
    total_price = 0.0
    for item_req in items:
        identifier = item_req.get("item_id") or item_req.get("name")
        qty = item_req.get("qty", 1)
        
        is_ok, item_id, item_name, stock, price, reason = check_item_availability(identifier, qty)
        if not is_ok:
            return False, [], 0.0, f"Infeasible: {reason}"
            
        validated_items.append({
            "item_id": item_id,
            "name": item_name,
            "price": price,
            "qty": qty
        })
        total_price += price * qty
        
    return True, validated_items, round(total_price, 2), "Feasible"

def create_order(thread_id, items):
    """
    Creates an order in the database with status 'PENDING_APPROVAL'.
    Validates items first.
    Returns (success, order_id, order_details, error_message)
    """
    is_feasible, validated_items, total_price, error_msg = check_order_feasibility(items)
    if not is_feasible:
        return False, None, None, error_msg
        
    import uuid
    order_id = f"ord_{uuid.uuid4().hex[:8]}"
    now_str = datetime.now().isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO orders (order_id, customer_thread_id, items, status, total_price, manager_note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            thread_id,
            json.dumps(validated_items),
            "PENDING_APPROVAL",
            total_price,
            None,
            now_str,
            now_str
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, None, None, f"Database error: {str(e)}"
        
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    order_row = dict(cursor.fetchone())
    conn.close()
    
    return True, order_id, order_row, "Order created successfully"

def get_order(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        return order
    return None

def get_orders_by_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE customer_thread_id = ? ORDER BY created_at DESC", (thread_id,))
    rows = cursor.fetchall()
    conn.close()
    
    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders

def get_all_orders():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders

def get_pending_orders():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE status = 'PENDING_APPROVAL' ORDER BY created_at ASC")
    rows = cursor.fetchall()
    conn.close()
    
    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders

def update_order_status(order_id, decision, manager_note=None):
    """
    Updates the status of the order based on manager decision.
    decision: 'approve' or 'reject'
    If approved, deducts stock.
    Returns (success, updated_order, error_message)
    """
    order = get_order(order_id)
    if not order:
        return False, None, "Order not found."
        
    if order["status"] != "PENDING_APPROVAL":
        return False, None, f"Order status is {order['status']}. Only PENDING_APPROVAL orders can be approved or rejected."
        
    now_str = datetime.now().isoformat()
    new_status = "APPROVED" if decision == "approve" else "REJECTED"
    
    conn = get_connection()
    conn.execute("BEGIN TRANSACTION")
    cursor = conn.cursor()
    
    try:
        if decision == "approve":
            # Check feasibility again just to be 100% safe against double-spending stock
            for item in order["items"]:
                cursor.execute("SELECT available_qty FROM menu WHERE item_id = ?", (item["item_id"],))
                qty_row = cursor.fetchone()
                if not qty_row or qty_row[0] < item["qty"]:
                    conn.rollback()
                    conn.close()
                    return False, None, f"Insufficient stock for '{item['name']}' to approve order."
            
            # Deduct stock
            for item in order["items"]:
                cursor.execute("""
                UPDATE menu 
                SET available_qty = available_qty - ? 
                WHERE item_id = ?
                """, (item["qty"], item["item_id"]))
                
        # Update order status
        cursor.execute("""
        UPDATE orders
        SET status = ?, manager_note = ?, updated_at = ?
        WHERE order_id = ?
        """, (new_status, manager_note, now_str, order_id))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, None, f"Database error during status update: {str(e)}"
        
    conn.close()
    
    updated_order = get_order(order_id)
    return True, updated_order, f"Order {new_status.lower()} successfully."

def modify_order(order_id, new_items):
    """
    Modifies an order's items. Handles inventory restoration if the order was previously APPROVED.
    new_items: list of {"item_id": str, "qty": int} or {"name": str, "qty": int}
    Returns (success, updated_order, error_message)
    """
    order = get_order(order_id)
    if not order:
        return False, None, "Order not found."
        
    old_status = order["status"]
    
    # We only allow modification of PENDING_APPROVAL, APPROVED, or REJECTED orders
    if old_status not in ["PENDING_APPROVAL", "APPROVED", "REJECTED"]:
        return False, None, f"Orders in '{old_status}' status cannot be modified."
        
    conn = get_connection()
    conn.execute("BEGIN TRANSACTION")
    cursor = conn.cursor()
    
    try:
        # Step 1: If previously APPROVED, temporarily restore stock so feasibility check is valid
        if old_status == "APPROVED":
            for item in order["items"]:
                cursor.execute("""
                UPDATE menu 
                SET available_qty = available_qty + ? 
                WHERE item_id = ?
                """, (item["qty"], item["item_id"]))
                
        # Step 2: Perform feasibility check against the (potentially restored) live stock
        # We need to query current stock from within this transaction to avoid race conditions
        validated_items = []
        total_price = 0.0
        
        for item_req in new_items:
            identifier = item_req.get("item_id") or item_req.get("name")
            qty = item_req.get("qty", 1)
            
            cursor.execute("""
            SELECT * FROM menu 
            WHERE (item_id = ? OR LOWER(name) = LOWER(?)) AND is_active = 1
            """, (identifier, identifier))
            row = cursor.fetchone()
            
            if not row:
                conn.rollback()
                conn.close()
                return False, None, f"Item '{identifier}' is not on the menu."
                
            item = dict(row)
            if item["available_qty"] < qty:
                conn.rollback()
                conn.close()
                return False, None, f"Insufficient stock for '{item['name']}'. Requested {qty}, available {item['available_qty']}."
                
            validated_items.append({
                "item_id": item["item_id"],
                "name": item["name"],
                "price": item["price"],
                "qty": qty
            })
            total_price += item["price"] * qty
            
        # Step 3: Update order details and set status to PENDING_APPROVAL
        now_str = datetime.now().isoformat()
        cursor.execute("""
        UPDATE orders
        SET items = ?, status = ?, total_price = ?, manager_note = ?, updated_at = ?
        WHERE order_id = ?
        """, (
            json.dumps(validated_items),
            "PENDING_APPROVAL",
            round(total_price, 2),
            f"Reset to pending due to user modification (previously {old_status}).",
            now_str,
            order_id
        ))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, None, f"Database error during modification: {str(e)}"
        
    conn.close()
    
    updated_order = get_order(order_id)
    return True, updated_order, "Order modified successfully and reset to PENDING_APPROVAL."

def update_stock(item_id, qty_diff):
    """
    Manually add or subtract stock. Useful for replenishment or mock management.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE menu
    SET available_qty = MAX(0, available_qty + ?)
    WHERE item_id = ?
    """, (qty_diff, item_id))
    conn.commit()
    conn.close()
    return get_item_by_id(item_id)

def get_analytics():
    """
    Computes analytics data for the manager dashboard.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Total Revenue (only from APPROVED and DELIVERED orders)
    cursor.execute("SELECT SUM(total_price) FROM orders WHERE status IN ('APPROVED', 'DELIVERED')")
    revenue = cursor.fetchone()[0] or 0.0
    
    # Orders count by status
    cursor.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
    status_counts = {row["status"]: row[1] for row in cursor.fetchall()}
    
    # Popular items calculation
    cursor.execute("SELECT items FROM orders WHERE status IN ('APPROVED', 'DELIVERED')")
    item_sales = {}
    for row in cursor.fetchall():
        items = json.loads(row[0])
        for it in items:
            name = it["name"]
            item_sales[name] = item_sales.get(name, 0) + it["qty"]
            
    popular_items = sorted(item_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    popular_list = [{"name": name, "qty": qty} for name, qty in popular_items]
    
    # Low stock items (stock < 5)
    cursor.execute("SELECT name, available_qty FROM menu WHERE available_qty < 5")
    low_stock = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "revenue": round(revenue, 2),
        "status_counts": status_counts,
        "popular_items": popular_list,
        "low_stock": low_stock
    }

if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
