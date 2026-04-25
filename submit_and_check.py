"""Submit task and check error details."""
import sys
import time
sys.path.insert(0, "unified-app")

from mcp_server.task_submission_pipe import submit_task_via_pipe

print("Submitting task...")
result = submit_task_via_pipe(
    description="Open Notepad",
    domain="desktop",
    timeout_seconds=10
)

task_id = result.get("task_id")
print(f"Task submitted: {task_id}")
print("Waiting for execution...")
time.sleep(8)

# Check database
import sqlite3
import json
from pathlib import Path

db_path = Path("unified-app/_runtime/orchestrator_history.db")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cursor.execute("""
    SELECT task_id, status, error_message, result_data
    FROM task_history
    WHERE task_id = ?
""", (task_id,))

row = cursor.fetchone()
if not row:
    print("Task not found in database yet")
    exit(1)

task_id, status, error_msg, result_data = row

print("\n" + "=" * 80)
print(f"TASK RESULT: {task_id}")
print("=" * 80)
print(f"Status: {status}")
print(f"Error Message: {error_msg}")

if result_data:
    result = json.loads(result_data)
    print(f"\nResult Keys: {list(result.keys())}")
    
    if 'metadata' in result:
        print("\n✅ METADATA FOUND!")
        metadata = result['metadata']
        if 'health_check_error' in metadata:
            print("\n🎯 HEALTH_CHECK_ERROR FOUND!")
            print(json.dumps(metadata['health_check_error'], indent=2))
        else:
            print("Metadata keys:", list(metadata.keys()))
    
    print(f"\nFull Result:")
    print(json.dumps(result, indent=2))

conn.close()
