import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import json
import datetime
import pandas as pd
import altair as alt
import time

# -----------------------
# 1. CONFIGURATION & INITIAL SETUP
# -----------------------
st.set_page_config(page_title="Admin Dashboard", layout="wide")

# Admin credentials (hard-coded)
ADMIN_EMAIL = "team@yelloway.io"
ADMIN_PASSWORD = "AlphaTheta@2006"

# Function to force a rerun
def rerun():
    st.rerun()

# -----------------------
# 2. ADMIN LOGIN
# -----------------------
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

if not st.session_state["admin_authenticated"]:
    st.title("Admin Login")
    admin_email = st.text_input("Admin Email")
    admin_password = st.text_input("Password", type="password")
    if st.button("Login"):
        if admin_email == ADMIN_EMAIL and admin_password == ADMIN_PASSWORD:
            st.session_state["admin_authenticated"] = True
            st.success("Logged in successfully!")
            rerun()
        else:
            st.error("Invalid admin credentials.")
    st.stop()

# -----------------------
# 3. FIREBASE INITIALIZATION
# -----------------------
# Load Firebase service account credentials from secrets (stored as JSON string)
firebase_creds_str = st.secrets["firebase"]["credentials_json"]
if isinstance(firebase_creds_str, str):
    firebase_creds = json.loads(firebase_creds_str)
else:
    firebase_creds = firebase_creds_str

# Initialize Firebase Admin if not already initialized
if firebase_creds and not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------
# 4. SIDEBAR NAVIGATION
# -----------------------
st.sidebar.title("Admin Navigation")
page = st.sidebar.radio("Select Page", ["Dashboard", "Users", "Learning Plans", "Reported Issues"])

# -----------------------
# 5. DASHBOARD PAGE
# -----------------------
if page == "Dashboard":
    st.title("Admin Dashboard")
    
    with st.spinner("Loading dashboard data..."):
        time.sleep(1)  # Simulate loading delay

        user_docs = list(db.collection("users").stream())
        total_users = len(user_docs)
        total_plans = 0
        all_ratings = []
        signup_dates = []
        for user_doc in user_docs:
            user_data = user_doc.to_dict()
            created_at = user_data.get("created_at")
            if created_at:
                try:
                    dt = datetime.datetime.fromisoformat(created_at)
                    signup_dates.append({"date": dt.date()})
                except Exception:
                    pass
            # Count learning plans for each user
            plans = list(db.collection("users").document(user_doc.id).collection("learning_plans").stream())
            total_plans += len(plans)
            for plan in plans:
                rating = plan.to_dict().get("rating")
                if rating is not None:
                    all_ratings.append(rating)
        
        avg_rating = sum(all_ratings)/len(all_ratings) if all_ratings else None

    # Display key metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Users", total_users)
    col2.metric("Total Learning Plans", total_plans)
    col3.metric("Average Rating", f"{avg_rating:.2f}" if avg_rating is not None else "N/A")
    
    # Bar chart of user signup dates
    if signup_dates:
        df_signup = pd.DataFrame(signup_dates)
        chart = alt.Chart(df_signup).mark_bar().encode(
            x=alt.X("date:T", title="Signup Date"),
            y=alt.Y("count()", title="Number of Users")
        )
        st.altair_chart(chart, use_container_width=True)

# -----------------------
# 6. USERS PAGE
# -----------------------
elif page == "Users":
    st.title("User Details")
    
    with st.spinner("Loading user data..."):
        user_list = []
        for user_doc in db.collection("users").stream():
            data = user_doc.to_dict()
            email = data.get("email", "")
            phone = data.get("phone", "")
            # Count learning plans for each user
            plans = list(db.collection("users").document(user_doc.id).collection("learning_plans").stream())
            num_plans = len(plans)
            user_list.append({"Email": email, "Phone": phone, "Learning Plans": num_plans})
        df_users = pd.DataFrame(user_list)
    
    search_term = st.text_input("Search by Email")
    if search_term:
        df_users = df_users[df_users["Email"].str.contains(search_term, case=False, na=False)]
    st.dataframe(df_users)

# -----------------------
# 7. LEARNING PLANS PAGE
# -----------------------
elif page == "Learning Plans":
    st.title("Learning Plans Overview")
    
    with st.spinner("Loading learning plan data..."):
        plans_list = []
        for user_doc in db.collection("users").stream():
            user_email = user_doc.to_dict().get("email", "")
            for plan_doc in db.collection("users").document(user_doc.id).collection("learning_plans").stream():
                plan_data = plan_doc.to_dict()
                title = plan_data.get("title", "Untitled")
                rating = plan_data.get("rating")
                plans_list.append({"User Email": user_email, "Plan Title": title, "Rating": rating})
        df_plans = pd.DataFrame(plans_list)
    
    search_term = st.text_input("Search Learning Plans by Title")
    if search_term:
        df_plans = df_plans[df_plans["Plan Title"].str.contains(search_term, case=False, na=False)]
    st.dataframe(df_plans)

# -----------------------
# 8. REPORTED ISSUES PAGE
# -----------------------
elif page == "Reported Issues":
    st.title("Reported Issues")
    with st.spinner("Loading reported issues..."):
        issues_list = []
        for report in db.collection("reports").stream():
            data = report.to_dict()
            issues_list.append({
                "User Email": data.get("email", ""),
                "Description": data.get("description", ""),
                "Timestamp": data.get("timestamp", "")
            })
        df_issues = pd.DataFrame(issues_list)
    st.dataframe(df_issues)
