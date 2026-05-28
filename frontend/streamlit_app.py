import streamlit as st
import requests
import uuid
import time
from typing import Dict, Any, Union

# --- 1. CONFIGURATION ---
BACKEND_URL = "http://backend:8000"

st.set_page_config(
    page_title="Jira AI Intelligence",
    page_icon=":material/auto_awesome:",
    layout="wide"
)

# --- 2. CSS INJECTION: MINIMALIST STYLING ENHANCEMENTS ---
st.markdown("""
    <style>
    /* 1. INCREASE FONT SIZE FOR TABS (General / Cron Jobs) */
    button[data-baseweb="tab"] p { 
        font-size: 1.35rem !important; 
        font-weight: 600 !important; 
    }
    
    /* 2. INCREASE GLOBAL FONT SIZE FOR READABILITY */
    .stMarkdown p, .stMarkdown li, label, .stSelectbox div { 
        font-size: 1.08rem !important; 
    }

    /* 3. ACTION BUTTONS STYLING */
    .stButton > button { 
        border-radius: 8px; 
        font-weight: 500; 
        height: 2.8rem; 
    }
    
    /* 4. FIX CHAT INPUT BORDER FOCUS (CHANGE RED TO JIRA BLUE) */
    [data-testid="stChatInput"] { 
        border-color: rgba(128,128,128,0.3) !important; 
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: #0052CC !important;
        box-shadow: 0 0 0 1px #0052CC !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. SESSION STATE INITIALIZATION ---
if "session_id" not in st.session_state: 
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state: 
    st.session_state.messages = []
if "is_processing" not in st.session_state: 
    st.session_state.is_processing = False
if "temp_jobs" not in st.session_state: 
    st.session_state.temp_jobs = []
if "is_loaded" not in st.session_state: 
    st.session_state.is_loaded = False

# --- 4. DATA LOADER ---
def load_saved_jobs():
    """Fetches the current cron job configurations from the Qdrant backend."""
    try:
        res = requests.get(f"{BACKEND_URL}/api/v1/scheduler/jobs", timeout=3)
        if res.status_code == 200:
            st.session_state.temp_jobs = res.json()
            st.session_state.is_loaded = True
    except Exception:
        pass # Silent fail during initial boot if backend is unavailable

if not st.session_state.is_loaded:
    load_saved_jobs()

# --- 5. TABS ROUTER ---
general_tab, cron_tab = st.tabs(["💬 General", "⏰ Cron Jobs"])

# ==========================================
# PAGE 1: GENERAL (NATIVE CHAT UI & WORKFLOWS)
# ==========================================
with general_tab:
    st.markdown("### 🤖 Jira AI Intelligence Assistant")
    
    # 5-Column Layout for evenly distributed Workflow Buttons
    c1, c2, c3, c4, c5 = st.columns(5)
    
    with c1:
        if st.button("📊 Sync Sheet Dashboard", use_container_width=True):
            with st.spinner("Syncing Dashboard..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/gsheet-report")
                    if res.status_code == 200:
                        count = res.json().get('synced_count', 0)
                        st.toast(f"Dashboard synced: {count} items updated.", icon="📊")
                    else:
                        st.error(f"Sync failed: {res.status_code}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

    with c2:
        if st.button("🧠 Sync Knowledge Base", use_container_width=True):
            with st.spinner("Updating Vector Store..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/sync-knowledge-base")
                    if res.status_code == 200:
                        count = res.json().get('synced', 0)
                        st.toast(f"Knowledge Base synced: {count} vectors updated.", icon="🧠")
                    else:
                        st.error(f"Sync failed: {res.status_code}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

    with c3:
        if st.button("🔄 Sync APG Status", use_container_width=True):
            with st.spinner("Matching Statuses..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/sync-status")
                    if res.status_code == 200:
                        count = res.json().get('synced_count', 0)
                        st.toast(f"Status sync complete: {count} tickets moved.", icon="🔄")
                    else:
                        st.error(f"Sync failed: {res.status_code}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

    with c4:
        if st.button("📋 Automate Assignment", use_container_width=True):
            with st.spinner("AI evaluating unassigned tickets..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/auto-assign")
                    if res.status_code == 200:
                        count = res.json().get('notified', 0)
                        st.toast(f"Auto-assignment complete: {count} recommendations dispatched.", icon="🤖")
                    else:
                        st.error(f"Assignment failed: {res.status_code}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

    with c5:
        if st.button("🧹 Clear Chat History", use_container_width=True):
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.is_processing = False
            st.toast("Chat history cleared gracefully.", icon="🧹")
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # MAIN CHAT CONTAINER (Scrollable height)
    chat_box = st.container(height=550, border=True)
    
    with chat_box:
        # Render historical messages using native Streamlit UI
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        # Handle AI Generation Logic
        if st.session_state.is_processing and st.session_state.messages[-1]["role"] == "user":
            with st.chat_message("assistant"):
                placeholder = st.empty()
                
                # Minimalist loading state
                with st.spinner("Agent is thinking..."):
                    full_response = ""
                    try:
                        # Request AI response from Backend
                        payload = {"message": st.session_state.messages[-1]["content"], "session_id": st.session_state.session_id}
                        response = requests.post(f"{BACKEND_URL}/api/v1/chat", json=payload, timeout=60)
                        
                        if response.status_code == 200:
                            raw_answer = response.json().get("reply", "No insights generated.")
                            # Simulate typewriter typing effect
                            for char in raw_answer:
                                full_response += char
                                placeholder.markdown(full_response + "▌")
                                time.sleep(0.003)
                            placeholder.markdown(full_response)
                            st.session_state.messages.append({"role": "assistant", "content": raw_answer})
                        else:
                            placeholder.markdown(f"**Error:** API returned status code {response.status_code}")
                    except Exception as ex:
                        placeholder.empty()
                        st.error(f"Connection lost: {ex}")
                    finally:
                        st.session_state.is_processing = False
                        st.rerun()

    # ANCHORED CHAT INPUT (Fixed at bottom)
    if user_prompt := st.chat_input("Ask me about Jira tickets or project status...", disabled=st.session_state.is_processing):
        st.session_state.is_processing = True
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        st.rerun()

# ==========================================
# PAGE 2: CRON JOBS MANAGEMENT (ALIGNED WITH BACKEND SCHEMAS)
# ==========================================
with cron_tab:
    st.markdown("### 📅 Enterprise Operations Scheduler")

    # Core metadata map for system tasks
    JOBS_METADATA: Dict[str, Dict[str, str]] = {
        "sync_gsheet_report": {"title": "Synchronize Google Sheets Dashboard", "placeholder": "project = 'AIO Development' AND sprint in openSprints()"},
        "sync_jira_to_qdrant": {"title": "Synchronize Knowledge Base (Jira -> Qdrant)", "placeholder": "project = 'AIO Development' AND created >= -8h ORDER BY created DESC"},
        "auto_issue_assignment": {"title": "Automate AI Issue Assignment", "placeholder": "project = 'APG' AND status = 'TO DO' AND created >= -8h"},
        "sync_apg_status_from_ad": {"title": "Synchronize Cross-Project Statuses", "placeholder": "project = 'AIO Development' AND status = 'Done' AND updated >= -8h"}
    }

    col_form, col_queue = st.columns([1, 1])

    with col_form:
        with st.container(border=True):
            st.markdown("##### ➕ Configure New Task")
            
            selected_job_key = st.selectbox(
                "Select Target Task:",
                options=list(JOBS_METADATA.keys()),
                format_func=lambda k: JOBS_METADATA[k]["title"]
            )
            
            # Fetch safe placeholder representation
            current_metadata = JOBS_METADATA.get(selected_job_key, {})
            placeholder_text = current_metadata.get("placeholder", "")
            
            custom_jql = st.text_area(
                "Custom JQL (Optional):", 
                placeholder=f"Default: {placeholder_text}"
            )

            st.markdown("##### 🕒 Timing Configuration")
            is_everyday = st.checkbox("Run Everyday (*)", value=True, key="chk_everyday")
            
            # Weekdays mapping (0=Monday, 6=Sunday, 7=Every day)
            DAYS_MAP = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}
            DAYS_LIST = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            selected_day_val = 7  # Default to Everyday

            if not is_everyday:
                st.markdown("**Select specific day:**")
                cols = st.columns(7)
                
                # Maintain stateful selection for mutually exclusive weekday checkboxes
                if "selected_day_idx" not in st.session_state:
                    st.session_state.selected_day_idx = 0  # Default to Monday
                    
                for i, day_name in enumerate(DAYS_LIST):
                    with cols[i]:
                        # If a specific checkbox is ticked, update state index and refresh view dynamically
                        if st.checkbox(day_name[:3], value=(st.session_state.selected_day_idx == i), key=f"day_chk_{i}"):
                            if st.session_state.selected_day_idx != i:
                                st.session_state.selected_day_idx = i
                                st.rerun()
                                
                selected_day_val = st.session_state.selected_day_idx

            c_hr, c_min = st.columns(2)
            with c_hr: hour_opt = st.number_input("Hour (0-23)", 0, 23, 10)
            with c_min: min_opt = st.number_input("Minute (0-59)", 0, 59, 0)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Add Task", type="secondary", use_container_width=True):
                # Construct the JSON dict payload to exactly match JobConfig nested schema parameters
                new_job = {
                    "id": str(uuid.uuid4()),
                    "name": selected_job_key,  # Target reflection workflow function name string
                    "custom_jql": custom_jql.strip() if custom_jql.strip() else None,
                    "default_jql": placeholder_text,
                    "scheduler": {
                        "hour": int(hour_opt),
                        "minute": int(min_opt),
                        "day_of_week": int(selected_day_val)
                    }
                }
                st.session_state.temp_jobs.append(new_job)
                st.toast(f"Added '{JOBS_METADATA[selected_job_key]['title']}' to processing queue!", icon="✅")
                st.rerun()

    with col_queue:
        with st.container(height=580, border=True):
            st.markdown("##### 📋 Current Automation Tasks")
            
            if not st.session_state.temp_jobs:
                st.info("No tasks configured. Add tasks from the left panel.")
            else:
                DAYS_REVERSE_MAP = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday", 7: "Everyday"}
                
                for idx, job in enumerate(st.session_state.temp_jobs):
                    # Robust type-safe resolution to prevent Pylance overload/union exceptions
                    if isinstance(job, dict):
                        job_dict: Dict[str, Any] = job
                        job_id = str(job_dict.get("id", ""))
                        job_name = str(job_dict.get("name", ""))
                        jql_display = job_dict.get("custom_jql")
                        sched = job_dict.get("scheduler")
                        
                        if isinstance(sched, dict):
                            sched_dict: Dict[str, Any] = sched
                            h_val = sched_dict.get("hour")
                            m_val = sched_dict.get("minute")
                            d_val = sched_dict.get("day_of_week")
                            
                            hour = int(h_val) if h_val is not None else 10
                            minute = int(m_val) if m_val is not None else 0
                            day_of_week = int(d_val) if d_val is not None else 7
                        else:
                            hour = 10
                            minute = 0
                            day_of_week = 7
                    else:
                        job_id = str(job.id)
                        job_name = str(job.name)
                        jql_display = job.custom_jql
                        sched = job.scheduler
                        
                        hour = int(sched.hour)
                        minute = int(sched.minute)
                        day_of_week = 7 if sched.day_of_week is None else int(sched.day_of_week)

                    # Explicitly retrieve title from metadata in a Pyright compliant manner
                    title = job_name
                    job_meta = JOBS_METADATA.get(job_name)
                    if isinstance(job_meta, dict):
                        meta_title = job_meta.get("title")
                        if isinstance(meta_title, str):
                            title = meta_title

                    day_label = DAYS_REVERSE_MAP.get(day_of_week, "Everyday")

                    with st.expander(f"⏱️ {hour:02d}:{minute:02d} - {title}", expanded=False):
                        st.markdown(f"**Days:** `{day_label}`")
                        st.markdown(f"**JQL:** `{jql_display if jql_display else 'System Default'}`")
                        if st.button("🗑️ Remove", key=f"del_{job_id}_{idx}"):
                            st.session_state.temp_jobs.pop(idx)
                            st.rerun()

    st.divider()
    
    # Bottom Action Buttons for saving the pipeline matrix
    bc1, bc2, bc3 = st.columns([6, 1, 1])
    with bc3:
        if st.button("💾 Save All", type="primary", use_container_width=True):
            with st.toast("Saving to Qdrant & Reloading..."):
                try:
                    # Direct serialization transmission mapping down to FastAPI schema verification layer
                    res_save = requests.post(f"{BACKEND_URL}/api/v1/scheduler/jobs", json=st.session_state.temp_jobs)
                    if res_save.status_code == 200:
                        requests.post(f"{BACKEND_URL}/api/v1/scheduler/reload")
                        st.toast("Successfully saved and hot-reloaded active schedules!", icon="✅")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.toast(f"Failed to save jobs to backend: {res_save.text}", icon="🚨")
                except Exception as e:
                    st.toast(f"Connection error: {e}", icon="❌")