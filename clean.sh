cd "/mnt/d/code/IOT-EV/gridsense3"
pkill -f "simulator.py"; pkill -f "scheduler.py"; pkill -f "streamlit run app.py"

# Optional: install real acnportal (if it fails, local impl is used)
uv add acnportal 2>/dev/null || echo "acnportal not available; local impl will be used"

# Copy 8 files from /home/z/my-project/download/gridsense_v3/ (scheduler.py,
# ml_module.py, database.py, reset_db.py are unchanged from v2):
#   acn_sessions.json acndata_client.py battery_model.py
#   ev_data.py simulator.py app.py start.sh INTEGRATION.md
