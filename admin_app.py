import streamlit as st
import firebase_admin
import json
from firebase_admin import credentials, firestore, auth

# -----------------------
# ADMIN CREDENTIALS (HARDCODED EXAMPLE)
# -----------------------
ADMIN_EMAIL = "team@yelloway.io"
ADMIN_PASSWORD = "AlphaTheta@2006"

# -----------------------
# FIREBASE CONFIGURATION
# -----------------------

# Load Firebase credentials from a local JSON file
firebase_creds_str = st.secrets["firebase"]["credentials_json"]

# Parse the JSON string into a dictionary
try:
    firebase_creds = json.loads(firebase_creds_str)
except json.JSONDecodeError as e:
    st.error("Error decoding Firebase credentials: " + str(e))
    firebase_creds = {}

# Initialize Firebase if credentials parsed successfully and not already initialized
if firebase_creds and not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

st.set_page_config(page_title="Admin Dashboard", layout="wide")
st.title("Admin Dashboard")

# -----------------------
# SIMPLE ADMIN LOGIN
# -----------------------
if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False

if not st.session_state["admin_logged_in"]:
    st.subheader("Admin Login")
    admin_email_input = st.text_input("Admin Email")
    admin_password_input = st.text_input("Admin Password", type="password")
    if st.button("Login as Admin"):
        if admin_email_input == ADMIN_EMAIL and admin_password_input == ADMIN_PASSWORD:
            st.session_state["admin_logged_in"] = True
            st.success("Welcome, Admin!")
            st.rerun()
        else:
            st.error("Invalid admin credentials.")
    st.stop()

# -----------------------
# ADMIN DASHBOARD
# -----------------------
st.subheader("User Analytics")
users_ref = db.collection("users")
users = list(users_ref.stream())

if users:
    for user_doc in users:
        user_data = user_doc.to_dict()
        user_id = user_doc.id
        email = user_data.get("email", "No email")
        # Count learning plans
        lp_ref = db.collection("users").document(user_id).collection("learning_plans")
        lp_count = len(list(lp_ref.stream()))
        # Example: If you track time_spent or other usage data
        time_spent = user_data.get("time_spent", "Not recorded")

        st.markdown(f"**User:** {email}  \n**Learning Plans:** {lp_count}  \n**Time Spent:** {time_spent}")
        st.markdown("---")
else:
    st.write("No users found.")

st.subheader("Reported Issues")
reports_ref = db.collection("reports")
reports = list(reports_ref.stream())

if reports:
    for rep in reports:
        rep_data = rep.to_dict()
        st.markdown(f"**From:** {rep_data.get('email', 'Unknown')}  \n**Issue:** {rep_data.get('description', 'No details')}  \n**Date:** {rep_data.get('timestamp', 'N/A')}")
        st.markdown("---")
else:
    st.write("No issues reported yet.")
