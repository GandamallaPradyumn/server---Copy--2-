import pysqlite3
import sys

# Override the standard library sqlite3 with pysqlite3
sys.modules["sqlite3"] = pysqlite3

from security_headers import apply_security_headers
apply_security_headers()

import streamlit as st
import json
st.set_page_config(page_title="TGSRTC AI DASHBOARD", layout="wide")
import pandas as pd
from auth import (
    authenticate_user,
    create_user,
    ensure_admin_exists,
    get_role_by_userid,
    get_connection,
    get_depot_by_userid,
    fetch_depot_names,
    invalidate_session,
    sanitize_input
)
from captcha_utils import render_captcha, generate_captcha
from Etl_main import run_etl_dashboard
from forecast import forecast
from insert import insert
from Input_Data_DM import user_sheet
from Input_Data_RM import RM_sheet
from Input_Data_tgsrtc import corporation_dashboard
from driver_dashboard_DM import driver_depot_dashboard_ui_DM
from driver_dashboard_RM import driver_depot_dashboard_ui_RM
from driver_depot_dashboard_ui import driver_depot_dashboard_ui
from admin import admin
from depot_dashboard_dm import depot_DM
from depot_dashboard_rm import depot_RM
from str_hrs import str_hrs
from depot_UI import depot_ui
from action_plan import action_dm
from action_plan_rm import action_rm
from Action_plan_tgsrtc import action_plan_corporation
from Ratios_DM import prod_ratios_DM
from Ratios_RM import prod_ratios_RM
from Ratios_tgsrtc import ProdRatiosDashboard   
from eight_ratios_DM import eight_ratios_DM
#from app_ui_dm import absdmmain
#from app_ui_admin import absadminmain
from eight_ratios_RM import eight_ratios_RM
from eight_ratios_tgsrtc import eight_ratios_dashboard
from train_kms_hrs import train
from kms_hrs import kms_hrs
from depot_list import depotlist
from pending import pending_depot
import base64
from edit_sheet import edit
from dynamic_scheduling_master.app import render_dynamic_scheduling

with open("config.json") as f:
    config = json.load(f)

logo_path = config["logo_path"]

# Inject custom CSS for sidebar logout button
st.markdown("""
<style>
    .reportview-container .main .block-container{
        padding-top: 2rem;
    }
    .css-1lcbmhc, .css-1qxt0v6 { 
        position: relative;
    }
    #logout-button-container {
        position: absolute;
        bottom: 10px;
        left: 10px;
        width: calc(100% - 20px);
    }
    #logout-button-container button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# Ensure default admin exists
ensure_admin_exists()

# Session state init
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.userid = ""
    st.session_state.user_role = None
    st.session_state.user_depot = None
    st.session_state.user_region = None   # 👈 NEW

# ------------------- LOGIN SCREEN -------------------
if not st.session_state.logged_in:
    # Centered login layout
    with open(logo_path, "rb") as img_file:
        b64_img = base64.b64encode(img_file.read()).decode()

    # Display centered logo with heading
    st.markdown(f"""
        <div style="text-align: center; background-color: #19bc9c; border-radius: 100px 20px;">
            <br>
            <img src="data:image/png;base64,{b64_img}" width="150" height="150">
            <h1 style="color: white;">Telangana State Road Transport Corporation</h1>
        </div>
    """, unsafe_allow_html=True)

    # Styling
    st.markdown("""<style>
        .stTextInput>div>div>input {
            background-color: #e4e4e4;
            color: black;
        }
        .login-btn button {
            background-color: #F63366 !important;
            color: white !important;
            font-weight: bold;
        }
        .stButton button:disabled {
            background-color: #cccccc !important;
            color: #666666 !important;
            cursor: not-allowed !important;
            opacity: 0.65 !important;
        }
    </style>""", unsafe_allow_html=True)

    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            def sync_userid():
                st.session_state["persistent_userid"] = st.session_state.get("login_userid", "")

            def sync_password():
                st.session_state["persistent_password"] = st.session_state.get("login_password", "")

            userid_raw = st.text_input("User ID *", key="login_userid", on_change=sync_userid, max_chars=30, help="Enter your assigned User ID")
            userid = sanitize_input(userid_raw) if userid_raw else ""
            user_depot_display = None
            role = None
            if userid:
                user_depot_display = get_depot_by_userid(userid)
                role = get_role_by_userid(userid)
            password = st.text_input("Password *", type="password", key="login_password", on_change=sync_password, max_chars=30, help="Enter your password")

            st.text_input("Role", value=role if role else "(Role will appear here)", disabled=True)
            st.text_input("Depot/Region", value=user_depot_display if user_depot_display else "(Depot/Region will appear here)", disabled=True)
            captcha_valid = render_captcha()

    # Determine if all 3 mandatory fields (User ID, Password, CAPTCHA) are filled
    uid_check = userid_raw.strip() if userid_raw else ""
    pwd_check = password.strip() if password else ""
    captcha_check = st.session_state.get("captcha_input_value", "").strip()
    is_form_complete = bool(uid_check and pwd_check and captcha_check)

    login_col = st.columns([1, 2, 1])[1]
    with login_col:
        login_clicked = st.button("🔐 Login", key="login_button", disabled=not is_form_complete)

    if login_clicked:
        final_userid = userid if userid else sanitize_input(st.session_state.get("persistent_userid", "")) or sanitize_input(st.session_state.get("login_userid", ""))
        final_password = password if password else st.session_state.get("persistent_password", "") or st.session_state.get("login_password", "")
        print(f"[DEBUG LOGIN] userid_raw={repr(userid_raw)}, userid={repr(userid)}, password={repr(password)}, final_userid={repr(final_userid)}, final_password={repr(final_password)}, pers_uid={repr(st.session_state.get('persistent_userid'))}, pers_pwd={repr(st.session_state.get('persistent_password'))}", flush=True)
        if not captcha_valid:
            generate_captcha()
            st.error("⚠️ Please complete the CAPTCHA security check correctly before logging in.")
        else:
            is_valid, depot_from_db, auth_msg = authenticate_user(final_userid, final_password)
            if is_valid:
                st.session_state.logged_in = True
                st.session_state.userid = final_userid

                role_from_db = get_role_by_userid(final_userid)
                st.session_state.user_role = role_from_db

                if role_from_db == "Depot Manager(DMs)":
                    st.session_state.user_depot = depot_from_db
                    st.session_state.user_region = None
                elif role_from_db == "Regional Manager(RMs)":
                    st.session_state.user_region = depot_from_db   # store region name here
                    st.session_state.user_depot = None
                else:
                    st.session_state.user_depot = None
                    st.session_state.user_region = None

                # Clear login credentials state
                st.session_state.pop("persistent_userid", None)
                st.session_state.pop("persistent_password", None)
                st.session_state.pop("login_userid", None)
                st.session_state.pop("login_password", None)
                st.session_state["captcha_input_value"] = ""
                st.session_state["captcha_solved"] = False

                st.rerun()
            else:
                generate_captcha()
                st.error(auth_msg)

# ------------------- MAIN APP AFTER LOGIN -------------------
else:
    # Welcome banner
    st.markdown(f"""
    <style>
    @keyframes fadeout {{
        0%   {{ opacity: 1; }}
        80%  {{ opacity: 1; }}
        100% {{ opacity: 0; display: none; }}
    }}
    #welcome {{
        padding: 1rem;
        background-color: #2ecc71;
        color: white;
        text-align: center;
        border-radius: 8px;
        font-size: 18px;
        font-weight: bold;
        animation: fadeout 2s forwards;
        animation-delay: 0s;
    }}
    </style>
    <div id="welcome">👋 Welcome, {st.session_state.userid}</div>
    """, unsafe_allow_html=True)

    # Sidebar logout
    with st.sidebar:
        st.markdown('<div id="logout-button-container">', unsafe_allow_html=True)
        if st.button("Logout"):
            invalidate_session(st.session_state.userid)
            st.session_state.logged_in = False
            st.session_state.userid = ""
            st.session_state.user_role = None
            st.session_state.user_depot = None
            st.session_state.user_region = None
            st.session_state.user_zone = None
            st.session_state.pop("session_token", None)

            # Clear stored login form credentials & reset CAPTCHA state
            st.session_state.pop("persistent_userid", None)
            st.session_state.pop("persistent_password", None)
            st.session_state.pop("login_userid", None)
            st.session_state.pop("login_password", None)
            st.session_state["captcha_input_value"] = ""
            st.session_state["captcha_solved"] = False
            generate_captcha()

            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # ------------------- ADMIN -------------------
    if st.session_state.userid == "admin":
        menu = ["ADD NEW USER", "ADD DEPOT CATEGORY", "INPUT SHEET EDIT","UPLOAD DATA","ABSENTEEISM","INSERT PASSENGERS","DYNAMIC SCHEDULING"]
        admin_task = st.sidebar.selectbox("Select screen", menu)
        st.markdown("---")

        if admin_task == "ADD NEW USER":
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.subheader("👤 ADD NEW USER")

                new_userid = st.text_input("🆕 New User ID", key="new_userid")
                new_password = st.text_input("🔑 New Password", type="password", key="new_password")

                roles = ["Select Role", "Depot Manager(DMs)", "Regional Manager(RMs)", "Executive Director(EDs)", "TGSRTC Corporation"]
                role = st.selectbox("🎭 Role", roles, index=0, key="role")

                depot_name = None
                region_name = None
                zone_name = None

                if role == "Depot Manager(DMs)":
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT depot_name FROM TS_ADMIN ORDER BY depot_name")
                    depot_names = [row[0] for row in cursor.fetchall()]
                    cursor.close(); conn.close()
                    if depot_names:
                        depot_options = ["Select Depot"] + depot_names
                        depot_name = st.selectbox("🏢 Depot Name", depot_options, index=0, key="depot_name")
                    else:
                        st.warning("⚠️ No depots found in TS_ADMIN.")

                elif role == "Regional Manager(RMs)":
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT region FROM TS_ADMIN ORDER BY region")
                    region_names = [row[0] for row in cursor.fetchall()]
                    cursor.close(); conn.close()
                    if region_names:
                        region_options = ["Select Region"] + region_names
                        region_name = st.selectbox("🏙️ Region", region_options, index=0, key="region_name")
                    else:
                        st.warning("⚠️ No regions found in TS_ADMIN.")
                elif role == "Executive Director(EDs)":
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT zone FROM TS_ADMIN ORDER BY zone")
                    zone_names = [row[0] for row in cursor.fetchall()]
                    cursor.close(); conn.close()
                    if zone_names:
                        zone_options = ["Select Zone"] + zone_names
                        zone_name = st.selectbox("🏙️ Zone", zone_options, index=0, key="zone_name")
                    else:
                        st.warning("⚠️ No zones found in TS_ADMIN.")

                if st.button("➕ Create New User"):
                    if not new_userid or not new_password:
                        st.warning("⚠️ Please fill both fields.")
                    elif role == "Select Role":
                        st.warning("⚠️ Please select a role.")
                    elif role == "Depot Manager(DMs)":
                        if depot_name == "Select Depot" or depot_name is None:
                            st.warning("⚠️ Please select a valid depot.")
                        elif create_user(new_userid, new_password, depot_name, role):
                            st.success(f"✅ Depot Manager '{new_userid}' created successfully!")
                        else:
                            st.error(f"❌ User ID '{new_userid}' already exists.")
                    elif role == "Regional Manager(RMs)":
                        if region_name == "Select Region" or region_name is None:
                            st.warning("⚠️ Please select a valid region.")
                        elif create_user(new_userid, new_password, region_name, role):
                            st.success(f"✅ Regional Manager '{new_userid}' created successfully!")
                        else:
                            st.error(f"❌ User ID '{new_userid}' already exists.")
                    else:
                        if create_user(new_userid, new_password, None, role):
                            st.success(f"✅ User '{new_userid}' created successfully!")
                        else:
                            st.error(f"❌ User ID '{new_userid}' already exists.")

            # Show existing users
            st.markdown("---")
            st.subheader("📋 Existing Users")

            def fetch_all_users():
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT userid, depot, role FROM users ORDER BY depot, userid")
                    rows = cursor.fetchall()
                    df = pd.DataFrame(rows, columns=["User ID", "Depot/Region", "Role"])
                    return df
                except Exception as e:
                    st.error(f"Error fetching user data: {e}")
                    return pd.DataFrame()
                finally:
                    cursor.close(); conn.close()

            user_df = fetch_all_users()
            if not user_df.empty:
                st.dataframe(user_df, use_container_width=True)
            else:
                st.info("ℹ️ No users found.")

        elif admin_task == "ADD DEPOT CATEGORY":
            admin()
        elif admin_task == "INPUT SHEET EDIT":
            edit()
            depotlist()
            pending_depot()
        elif admin_task == "UPLOAD DATA":
            run_etl_dashboard()
        elif admin_task == "ABSENTEEISM":
            #absadminmain()
            pass
        elif admin_task == "INSERT PASSENGERS":
            insert()
        elif admin_task == "DYNAMIC SCHEDULING":
            from dynamic_scheduling_master.buttons import render_operations_controls
            render_operations_controls()
            st.markdown("---")
            from dynamic_scheduling_master.app import render_dynamic_scheduling
            render_dynamic_scheduling()
    # ------------------- OTHER ROLES -------------------
    else:
        role = st.session_state.user_role

        if role == "Depot Manager(DMs)":
            menu = [
                "Daily Depot Input Sheet",
"Dynamic Scheduling",
                "Productivity Budget 8 Ratios (Rural/Urban)",
                "Productivity Budget vs. Actual 8 Ratios",
                "Action Plan For KPI",
                "Depot Dashboard",
                "Driver Dashboard",
                "Absenteeism Forecast",
                "Passenger Forecast",
                "Kms & Hrs Prediction"
                #"DRIVER PRODUCTIVITY IMPROMENT",
                #"drivers performance report"
            ]

            selection = st.sidebar.selectbox("Select Screen", menu)

            if selection == "Daily Depot Input Sheet":
                user_sheet(st.session_state.user_depot, role)

            elif selection == "Productivity Budget 8 Ratios (Rural/Urban)":
                prod_ratios_DM()

            elif selection == "Productivity Budget vs. Actual 8 Ratios":
                eight_ratios_DM()
            elif selection == "Dynamic Scheduling":
                render_dynamic_scheduling()

            elif selection == "Depot Dashboard":
                depot_DM()
                str_hrs()

            elif selection == "Action Plan For KPI":
                 action_dm()

            elif selection == "Driver Dashboard":

                # ✅ Correct session values
                user_depot = st.session_state.user_depot
                role = st.session_state.user_role

                # Load dashboard
                obj = driver_depot_dashboard_ui_DM(user_depot, role)
                obj.parameters()

                tab1, tab2 = st.tabs(["#Driver Performance", "Driver Performance in Depot"])

                with tab1:
                    try:
                        obj.driver_ui()
                    except Exception as e:
                        st.error(f"{e}")

                with tab2:
                    try:
                        obj.driver_depot_ui()
                    except Exception as e:
                        st.error(f"{e}")
            elif selection == "Absenteeism Forecast":
                #absdmmain()
                pass
            elif selection == "Passenger Forecast":
                forecast()
            elif selection == "KMS & HRS PREDICTION":
                kms_hrs()
           # elif selection == "drivers performance report":
               # render_depot_table()
                

        elif role == "Regional Manager(RMs)":

            menu = [
                "Dynamic Scheduling",
                "Daily Depot Input Sheet",
                "Productivity Budget 8 Ratios (Rural/Urban)",
                "Productivity Budget vs. Actual 8 Ratios",
                "Depot Dashboard",
                "Driver Dashboard",   # 👈 Added (missing earlier)
                "action plan for kpi"
            ]

            selection = st.sidebar.selectbox("Select Screen", menu)
            if selection == "Dynamic Scheduling":
              render_dynamic_scheduling()

            elif selection == "Daily Depot Input Sheet":
                RM_sheet(st.session_state.user_region, role)   # 👈 region passed

            elif selection == "Productivity Budget 8 Ratios (Rural/Urban)":
                prod_ratios_RM(st.session_state.user_region)

            elif selection == "Productivity Budget vs. Actual 8 Ratios":
                eight_ratios_RM()
	    
            elif selection == "action plan for kpi":
                action_rm()

            elif selection == "Depot Dashboard":
                depot_RM()

            elif selection == "Driver Dashboard":

                # ✅ Correct session values
                user_region = st.session_state.user_region
                role = st.session_state.user_role  # (FIXED)

                # Pass region & role correctly
                obj = driver_depot_dashboard_ui_RM(
                    user_depot=None,          # RM doesn't have single depot
                    user_region=user_region,  # correct region
                    role=role
                )

                obj.parameters()

                tab1, tab2 = st.tabs(["Driver Performance", "Driver Performance in Depot"])

                with tab1:
                    try:
                        obj.driver_ui()
                    except Exception as e:
                        st.error(f"{e}")

                with tab2:
                    try:
                        obj.driver_depot_ui()
                    except Exception as e:
                        st.error(f"{e}")


        elif role == "Executive Director(EDs)":
            menu = ["Corporate Dashboard", "All Regions Overview", "AI Executive Tools"]
            selection = st.sidebar.selectbox("Select Screen", menu)
            if selection == "Corporate Dashboard":
                st.info("All Regions Overview")
               #ED_sheet(st.session_state.user_zone, role)
            elif selection == "All Regions Overview":
                st.info("All Regions Overview")
            elif selection == "AI Executive Tools":
                st.info("AI Tools for EDs")

        elif role == "TGSRTC Corporation":
            menu = ["Input Sheet", "Productivity Budget 8 Ratios (Rural/Urban)", "Productivity Budget vs. Actual 8 Ratios", "Driver Dashboard", "Depot Dashboard", "Action Plan"]
            selection = st.sidebar.selectbox("Select Screen", menu)
            
            if selection == "Input Sheet":
                # Show corporation-level productivity dashboard
                corporation_dashboard()

            elif selection == "Productivity Budget 8 Ratios (Rural/Urban)":
                ProdRatiosDashboard()

            elif selection == "Productivity Budget vs. Actual 8 Ratios":
                eight_ratios_dashboard()

            elif selection == "Driver Dashboard":
                # Default values if not set (prevents errors)
                user_region = st.session_state.get("user_region", "HYDERABAD")
                role = st.session_state.get("user_role", "TGSRTC Corporation")  # small fix here too
                obj = driver_depot_dashboard_ui(user_region=user_region, role=role)
                obj.parameters()
                tab1, tab2 = st.tabs(["Driver Performance", "Driver Performance in Depot"])
                with tab1:
                    obj.driver_ui()
                with tab2:
                    obj.driver_depot_ui()

            elif selection == "Depot Dashboard":
                depot_ui()

            elif selection == "Action Plan":
                action_plan_corporation()
