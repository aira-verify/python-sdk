"""Offline mode — queue authorize calls locally, sync when ready.

Offline mode queues POST/PUT/DELETE requests to local disk. GET requests
(like reading an authorization status) are not available offline. When you
call sync(), the queued authorize calls are flushed to the API and you get
back the real responses in FIFO order.

Note: in offline mode authorize() does NOT return a real action_id
(because it's queued, not yet sent). You cannot call notarize() for an
action until after sync() has flushed the authorize to the backend and
given you the real ID.
"""
from aira import Aira

aira = Aira(api_key="aira_live_xxx", offline=True)

# Queue authorize calls locally — no network calls yet.
aira.authorize(action_type="scan_completed", details="Scanned batch #1", agent_id="scanner")
aira.authorize(action_type="scan_completed", details="Scanned batch #2", agent_id="scanner")
aira.authorize(action_type="classification_done", details="Classified 142 docs", agent_id="scanner")

print(f"Queued: {aira.pending_count} actions")

# Flush when back online — backend creates the actions and returns real IDs.
results = aira.sync()
print(f"Synced: {len(results)} actions")
for r in results:
    print(f"  action_id: {r.get('action_id', '<error>')}")
