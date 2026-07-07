import db
import json

def run_tests():
    print("==================================================")
    print("🚀 STARTING AUTOMATED RESTAURANT AGENT TEST SUITE")
    print("==================================================")
    
    # 1. Reset and initialize database
    db.init_db()
    
    # Reset menu stock to default seed values for consistent testing
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE menu SET available_qty = 20 WHERE item_id = 'burger_classic'")
    cursor.execute("UPDATE menu SET available_qty = 30 WHERE item_id = 'sides_fries'")
    cursor.execute("UPDATE menu SET available_qty = 50 WHERE item_id = 'drinks_coke'")
    conn.commit()
    conn.close()
    
    # Fetch initial stock levels
    init_burger = db.get_item_by_id("burger_classic")["available_qty"]
    init_fries = db.get_item_by_id("sides_fries")["available_qty"]
    init_coke = db.get_item_by_id("drinks_coke")["available_qty"]
    
    print(f"Initial Stock: Burger={init_burger}, Fries={init_fries}, Coke={init_coke}\n")
    
    # ==================================================
    # TEST 1: Block Infeasible Request (qty > stock)
    # ==================================================
    print("👉 TEST 1: Requesting quantities larger than available stock")
    infeasible_items = [{"item_id": "burger_classic", "qty": 50}]
    is_feasible, validated, total, reason = db.check_order_feasibility(infeasible_items)
    
    assert not is_feasible, "Test 1 Failed: Infeasible order was marked feasible!"
    print("✅ TEST 1 PASSED: Order correctly blocked. Reason:", reason)
    print("-" * 50)
    
    # ==================================================
    # TEST 2: Happy Path Order Approval
    # ==================================================
    print("👉 TEST 2: Happy Path (Checkout -> Pending -> Approved -> Stock Deducted)")
    thread_id = "test_thread_1"
    items = [
        {"item_id": "burger_classic", "qty": 2},
        {"item_id": "drinks_coke", "qty": 3}
    ]
    
    # Create order (creates as PENDING_APPROVAL)
    success, order_id, order, err = db.create_order(thread_id, items)
    assert success, f"Failed to create order: {err}"
    assert order["status"] == "PENDING_APPROVAL", "Order status must be PENDING_APPROVAL on creation"
    
    # Verify no inventory deducted yet
    stock_burger = db.get_item_by_id("burger_classic")["available_qty"]
    stock_coke = db.get_item_by_id("drinks_coke")["available_qty"]
    assert stock_burger == 20, "Burger stock should not change before approval"
    assert stock_coke == 50, "Coke stock should not change before approval"
    print("  - Order is PENDING_APPROVAL. Stock remains: Burger=20, Coke=50.")
    
    # Manager Approval
    success, updated_order, err = db.update_order_status(order_id, "approve", "Approved by testing suite.")
    assert success, f"Approval failed: {err}"
    assert updated_order["status"] == "APPROVED", "Order status must update to APPROVED"
    
    # Verify inventory is deducted
    stock_burger = db.get_item_by_id("burger_classic")["available_qty"]
    stock_coke = db.get_item_by_id("drinks_coke")["available_qty"]
    assert stock_burger == 18, f"Expected burger stock 18, got {stock_burger}"
    assert stock_coke == 47, f"Expected coke stock 47, got {stock_coke}"
    print(f"  - Order is APPROVED. Stock successfully deducted: Burger={stock_burger}, Coke={stock_coke}.")
    print("✅ TEST 2 PASSED: Stock deducted correctly on approval.")
    print("-" * 50)
    
    # ==================================================
    # TEST 3: Rejection Path (Checkout -> Pending -> Rejected -> No Stock Change)
    # ==================================================
    print("👉 TEST 3: Rejection Path (Checkout -> Pending -> Rejected -> No stock change)")
    items_rej = [{"item_id": "burger_classic", "qty": 1}]
    
    success, order_id_rej, order_rej, err = db.create_order(thread_id, items_rej)
    assert success, f"Failed to create order: {err}"
    
    # Reject Order
    success, updated_order_rej, err = db.update_order_status(order_id_rej, "reject", "Not hungry enough.")
    assert success, f"Rejection failed: {err}"
    assert updated_order_rej["status"] == "REJECTED", "Order status must update to REJECTED"
    
    # Verify stock remains unchanged (Burger=18)
    stock_burger = db.get_item_by_id("burger_classic")["available_qty"]
    assert stock_burger == 18, f"Expected burger stock 18, got {stock_burger}"
    print(f"  - Order is REJECTED. Stock remains unchanged: Burger={stock_burger}.")
    print("✅ TEST 3 PASSED: No stock deducted on rejection.")
    print("-" * 50)
    
    # ==================================================
    # TEST 4: Modify Already Approved Order (Stock Restored -> Feasibility Checked -> Reset to Pending)
    # ==================================================
    print("👉 TEST 4: Modify Approved Order (Restore stock -> Check new items -> Reset to Pending)")
    # Order ID from Test 2 was 'order_id'
    # Original items: 2 Burgers, 3 Cokes (Stock levels currently: Burger=18, Coke=47, Fries=30)
    # New items: 1 Burger, 2 Fries (We remove Coke entirely, reduce Burger to 1, and add 2 Fries)
    new_items = [
        {"item_id": "burger_classic", "qty": 1},
        {"item_id": "sides_fries", "qty": 2}
    ]
    
    success, modified_order, err = db.modify_order(order_id, new_items)
    assert success, f"Modification failed: {err}"
    assert modified_order["status"] == "PENDING_APPROVAL", "Modified order must reset to PENDING_APPROVAL"
    
    # Verify inventory is restored during check-out modification phase:
    # Burger stock: was 18. Restoring old (2) makes it 20. Then new modification proposal checks stock.
    # Note: Because the modification is PENDING approval, the new quantities are NOT deducted yet,
    # but the old quantities are completely restored!
    # So stock should be:
    # Burger: 18 (approved stock) + 2 (restored) = 20
    # Coke: 47 (approved stock) + 3 (restored) = 50
    # Fries: 30 (not modified/deducted yet) = 30
    stock_burger = db.get_item_by_id("burger_classic")["available_qty"]
    stock_coke = db.get_item_by_id("drinks_coke")["available_qty"]
    stock_fries = db.get_item_by_id("sides_fries")["available_qty"]
    
    assert stock_burger == 20, f"Expected burger stock 20, got {stock_burger}"
    assert stock_coke == 50, f"Expected coke stock 50, got {stock_coke}"
    assert stock_fries == 30, f"Expected fries stock 30, got {stock_fries}"
    print(f"  - Order modified. Stock restored to pool: Burger={stock_burger}, Coke={stock_coke}, Fries={stock_fries}.")
    
    # Now, the manager approves the modified order
    success, final_order, err = db.update_order_status(order_id, "approve", "Approve modified order.")
    assert success, f"Approval of modification failed: {err}"
    
    # Verify new inventory is deducted on approval:
    # Burger stock: 20 - 1 = 19
    # Fries stock: 30 - 2 = 28
    # Coke stock: 50 (remains restored!)
    stock_burger = db.get_item_by_id("burger_classic")["available_qty"]
    stock_coke = db.get_item_by_id("drinks_coke")["available_qty"]
    stock_fries = db.get_item_by_id("sides_fries")["available_qty"]
    
    assert stock_burger == 19, f"Expected burger stock 19, got {stock_burger}"
    assert stock_coke == 50, f"Expected coke stock 50, got {stock_coke}"
    assert stock_fries == 28, f"Expected fries stock 28, got {stock_fries}"
    print(f"  - Modified Order APPROVED. Final Stock: Burger={stock_burger}, Coke={stock_coke}, Fries={stock_fries}.")
    print("✅ TEST 4 PASSED: Inventory restoration & modification re-deducted correctly.")
    print("-" * 50)
    
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! The database and state lifecycle logic are 100% correct.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
