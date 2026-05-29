import streamlit as st
import requests
import uuid
import time
from typing import Dict, Any, Optional

# --- 1. CONFIGURATION ---
BACKEND_URL = "http://backend:8000"

st.set_page_config(
    page_title="Jira AI Intelligence Platform",
    page_icon="🤖",
    layout="wide"
)

# --- 2. CSS INJECTION: ENTERPRISE MODERN STYLING ---
st.markdown("""
    <style>
    /* Tab Navigation Headers */
    button[data-baseweb="tab"] p { 
        font-size: 1.2rem !important; 
        font-weight: 600 !important; 
    }
    
    /* Global Content Adjustments */
    .stMarkdown p, .stMarkdown li, label, .stSelectbox div { 
        font-size: 1.02rem !important; 
    }

    /* Action Buttons Design Blueprint */
    .stButton > button { 
        border-radius: 6px; 
        font-weight: 500; 
        height: 2.6rem; 
    }
    
    /* Fix Chat Input Focus Behavior to Corporate Jira Blue */
    [data-testid="stChatInput"] { 
        border-color: rgba(128,128,128,0.2) !important; 
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

# --- 4. ASYNC DATA LOADER ---
def load_saved_jobs() -> None:
    """Fetches current cron job configurations from the vector storage backend."""
    try:
        res = requests.get(f"{BACKEND_URL}/api/v1/scheduler/jobs", timeout=5)
        if res.status_code == 200:
            st.session_state.temp_jobs = res.json()
            st.session_state.is_loaded = True
    except Exception:
        pass  # Microservice gracefully degrades if backend is bootstrapping

if not st.session_state.is_loaded:
    load_saved_jobs()

# --- 5. CORE ROUTER NAVIGATION ---
general_tab, cron_tab = st.tabs(["💬 Chat Agent", "⏰ Automation Scheduler"])

# ==============================================================================
# TAB 1: DYNAMIC CHAT AGENT & IMMEDIATE WORKFLOW ACTIONS
# ==============================================================================
with general_tab:
    st.markdown("### ⚙️ Operational Telemetry Controls")
    
    # 5-Column Grid Layout for Immediate Workflow Execution
    c1, c2, c3, c4, c5 = st.columns(5)
    
    with c1:
        if st.button("📊 Sync Sheet Dashboard", use_container_width=True):
            with st.spinner("Executing Spreadsheet Sync..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/gsheet-report")
                    data = res.json()
                    if res.status_code == 200 and data.get("status") != "error":
                        metrics = data.get("metrics", {})
                        count = metrics.get("processed_transactions", 0)
                        st.toast(f"GSheet Dashboard Synced: **{count}** records updated.", icon="📊")
                    else:
                        st.error(f"Sync Failed: {data.get('message', res.text)}")
                except Exception as e:
                    st.error(f"Network Connection Lost: {e}")

    with c2:
        if st.button("🧠 Sync Knowledge Base", use_container_width=True):
            with st.spinner("Ingesting Vector Layers..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/sync-knowledge-base")
                    data = res.json()
                    if res.status_code == 200 and data.get("status") != "error":
                        metrics = data.get("metrics", {})
                        count = metrics.get("vector_updates_mapped", 0)
                        st.toast(f"Knowledge Base Up-to-date: **{count}** vectors upserted.", icon="🧠")
                    else:
                        st.error(f"Vector Sync Failed: {data.get('message', res.text)}")
                except Exception as e:
                    st.error(f"Network Connection Lost: {e}")

    with c3:
        if st.button("🔄 Sync APG Status", use_container_width=True):
            with st.spinner("Aligning Ticket Lifecycles..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/sync-status")
                    data = res.json()
                    if res.status_code == 200 and data.get("status") != "error":
                        metrics = data.get("metrics", {})
                        total = metrics.get("total_ad_found", 0)
                        synced = metrics.get("synced_count", 0)
                        st.toast(f"Status Mapping Complete: Moved **{synced}/{total}** tickets to Done.", icon="🔄")
                    else:
                        st.error(f"Status Synchronization Failed: {data.get('message', res.text)}")
                except Exception as e:
                    st.error(f"Network Connection Lost: {e}")

    with c4:
        if st.button("📋 Automate Assignment", use_container_width=True):
            with st.spinner("RAG Agent evaluating candidate expertise..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/workflow/auto-assign")
                    data = res.json()
                    if res.status_code == 200 and data.get("status") != "error":
                        metrics = data.get("metrics", {})
                        notified = metrics.get("developers_notified", 0)
                        skipped = metrics.get("tickets_skipped", 0)
                        st.toast(f"AI Triage Complete: Notified **{notified}**, Skipped **{skipped}** tasks.", icon="🤖")
                    else:
                        st.error(f"Auto-Assignment Engine Aborted: {data.get('message', res.text)}")
                except Exception as e:
                    st.error(f"Network Connection Lost: {e}")

    with c5:
        if st.button("🧹 Clear Conversation Context", use_container_width=True):
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.is_processing = False
            st.toast("Internal session token refreshed. Memory cleared.", icon="🧹")
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # SECURE SCROLLABLE CHAT RUNTIME CONTAINER
    chat_box = st.container(height=520, border=True)
    
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
        if st.session_state.is_processing and st.session_state.messages[-1]["role"] == "user":
            with st.chat_message("assistant"):
                placeholder = st.empty()
                
                with st.spinner("Agent is thinking...", show_time=True):
                    full_response = ""
                    try:
                        payload = {
                            "message": st.session_state.messages[-1]["content"], 
                            "session_id": st.session_state.session_id
                        }
                        response = requests.post(f"{BACKEND_URL}/api/v1/chat", json=payload, timeout=90)
                        
                        if response.status_code == 200:
                            raw_answer = response.json().get("reply", "No data returned.")
                            # Standard low-latency typewriter animation effect loop
                            for char in raw_answer:
                                full_response += char
                                placeholder.markdown(full_response + "▌")
                                time.sleep(0.002)
                            placeholder.markdown(full_response)
                            st.session_state.messages.append({"role": "assistant", "content": raw_answer})
                        else:
                            placeholder.markdown(f"⚠️ **Inference Gateway Error:** Gateway responded with status {response.status_code}")
                    except Exception as ex:
                        placeholder.empty()
                        st.error(f"Inference Route Timeouts: {ex}")
                    finally:
                        st.session_state.is_processing = False
                        st.rerun()

    if user_prompt := st.chat_input("Query enterprise projects, filters, or active metrics...", disabled=st.session_state.is_processing):
        st.session_state.is_processing = True
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        st.rerun()


# ==============================================================================
# TAB 2: SYSTEM CRON SCHEDULER MANAGEMENT ARCHITECTURE
# ==============================================================================
with cron_tab:
    st.markdown("### 📅 Operations Scheduler")

    JOBS_METADATA: Dict[str, Dict[str, str]] = {
        "sync_gsheet_report": {
            "title": "Synchronize Google Sheets Dashboard", 
            "placeholder": "project = 'AIO Development' AND sprint in openSprints()"
        },
        "sync_jira_to_qdrant": {
            "title": "Synchronize Knowledge Base (Jira -> Qdrant)", 
            "placeholder": "project = 'AIO Development' AND created >= -8h ORDER BY created DESC"
        },
        "auto_issue_assignment": {
            "title": "Automate AI Issue Assignment", 
            "placeholder": "project = 'APG' AND status = 'TO DO' AND created >= -8h"
        },
        "sync_apg_status_from_ad": {
            "title": "Synchronize Cross-Project Statuses", 
            "placeholder": "project = 'AIO Development' AND status = 'Done' AND updated >= -8h"
        }
    }

    col_form, col_queue = st.columns([1, 1])

    with col_form:
        with st.container(border=True):
            st.markdown("##### ➕ Configure Automation Task")
            
            selected_job_key = st.selectbox(
                "Select System Target Macro:",
                options=list(JOBS_METADATA.keys()),
                format_func=lambda k: JOBS_METADATA[k]["title"]
            )
            
            current_metadata = JOBS_METADATA.get(selected_job_key, {})
            placeholder_text = current_metadata.get("placeholder", "")
            
            custom_jql = st.text_area(
                "Target JQL Constraints override (Optional):", 
                placeholder=f"System Default: {placeholder_text}"
            )

            st.markdown("##### 🕒 Interval Constraints Configuration")
            is_everyday = st.checkbox("Every Day (*)", value=True, key="chk_everyday")
            
            DAYS_MAP = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}
            DAYS_LIST = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            selected_day_val = 7  # 7 maps to continuous execution boundary

            if not is_everyday:
                st.markdown("**Target Operational Weekday:**")
                cols = st.columns(7)
                
                if "selected_day_idx" not in st.session_state:
                    st.session_state.selected_day_idx = 0
                    
                for i, day_name in enumerate(DAYS_LIST):
                    with cols[i]:
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
                new_job = {
                    "id": str(uuid.uuid4()),
                    "name": selected_job_key, 
                    "custom_jql": custom_jql.strip() if custom_jql.strip() else None,
                    "default_jql": placeholder_text,
                    "scheduler": {
                        "hour": int(hour_opt),
                        "minute": int(min_opt),
                        "day_of_week": int(selected_day_val)
                    }
                }
                st.session_state.temp_jobs.append(new_job)
                st.toast(f"Staged profile: '{JOBS_METADATA[selected_job_key]['title']}'", icon="✅")
                st.rerun()

    with col_queue:
        with st.container(height=570, border=True):
            st.markdown("##### 📋 Registered Task Queue Matrix")
            
            if not st.session_state.temp_jobs:
                st.info("No active pipeline schedules detected within volatile cache boundaries.")
            else:
                DAYS_REVERSE_MAP = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday", 7: "Continuous (Daily)"}
                
                for idx, job in enumerate(st.session_state.temp_jobs):
                    if isinstance(job, dict):
                        job_dict: Dict[str, Any] = job
                        job_id = str(job_dict.get("id", ""))
                        job_name = str(job_dict.get("name", ""))
                        jql_display = job_dict.get("custom_jql")
                        sched = job_dict.get("scheduler")
                        
                        if isinstance(sched, dict):
                            sched_dict: Dict[str, Any] = sched
                            hour = int(sched_dict.get("hour", 10))
                            minute = int(sched_dict.get("minute", 0))
                            day_of_week = int(sched_dict.get("day_of_week", 7))
                        else:
                            hour, minute, day_of_week = 10, 0, 7
                    else:
                        job_id = str(job.id)
                        job_name = str(job.name)
                        jql_display = job.custom_jql
                        sched = job.scheduler
                        hour = int(sched.hour)
                        minute = int(sched.minute)
                        day_of_week = 7 if sched.day_of_week is None else int(sched.day_of_week)

                    title = job_name
                    job_meta = JOBS_METADATA.get(job_name)
                    if isinstance(job_meta, dict):
                        meta_title = job_meta.get("title")
                        if isinstance(meta_title, str):
                            title = meta_title

                    day_label = DAYS_REVERSE_MAP.get(day_of_week, "Continuous (Daily)")

                    with st.expander(f"⏱️ {hour:02d}:{minute:02d} - {title}", expanded=False):
                        st.markdown(f"**Execution Cadence:** `{day_label}`")
                        st.markdown(f"**JQL Filter Mapping:** `{jql_display if jql_display else 'Fallback System Default'}`")
                        if st.button("🗑️ Remove Profile", key=f"del_{job_id}_{idx}"):
                            st.session_state.temp_jobs.pop(idx)
                            st.rerun()

    st.divider()
    
    bc1, bc2, bc3 = st.columns([6, 1, 1])
    with bc3:
        if st.button("💾 Save all", type="primary", use_container_width=True):
            with st.spinner("Committing matrices to Qdrant storage..."):
                try:
                    res_save = requests.post(f"{BACKEND_URL}/api/v1/scheduler/jobs", json=st.session_state.temp_jobs)
                    if res_save.status_code == 200:
                        requests.post(f"{BACKEND_URL}/api/v1/scheduler/reload")
                        st.toast("Active execution states updated and hot-reloaded successfully!", icon="✅")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Storage Sync Refused: {res_save.text}")
                except Exception as e:
                    st.error(f"Failovers hit during upstream commit: {e}")