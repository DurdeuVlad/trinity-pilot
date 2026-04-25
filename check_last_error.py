"""Check the last task error to verify error surfacing."""
import sqlite3
import json
from pathlib import Path

db_path = Path("unified-app/_runtime/orchestrator_history.db")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cursor.execute("""
    SELECT task_id, status, error_message, result_data
    FROM task_history
    ORDER BY id DESC
    LIMIT 1
""")

row = cursor.fetchone()
if not row:
    print("No tasks found")
    exit(0)

task_id, status, error_msg, result_data = row

print("=" * 80)
print(f"LAST TASK: {task_id}")
print("=" * 80)
print(f"Status: {status}")
print(f"Error Message: {error_msg}")

if result_data:
    result = json.loads(result_data)
    print(f"\nResult Keys: {list(result.keys())}")
    
    if 'error_details' in result:
        print("\n✅ ERROR_DETAILS FOUND!")
        error_details = result['error_details']
        print(json.dumps(error_details, indent=2))
    else:
        print("\n❌ No error_details in result")
        print(f"Result: {json.dumps(result, indent=2)}")

conn.close()
