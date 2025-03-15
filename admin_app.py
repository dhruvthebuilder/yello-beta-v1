import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth

# -----------------------
# ADMIN CREDENTIALS (HARDCODED EXAMPLE)
# -----------------------
ADMIN_EMAIL = "team@yelloway.io"
ADMIN_PASSWORD = "AlphaTheta@2006"

# -----------------------
# FIREBASE CONFIGURATION
# -----------------------
FIREBASE_CREDENTIALS = {
    "type": "service_account",
    "project_id": "yello-beta-a5931",
    "private_key_id": "9c390f09655d7bb61868084b4d0e444b4dab026a",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCf5Crre16+Oy3/\npWP8o8m33NV1VU47R+6upMeA+A8yAtndDn8M4YbZl6h0X/aGGS+1B1PbKUmoxT9g\nDNKps8ffaziGAq6vSdS9uV5ZQcBQ2/LUybUTgvD9TIjGiNzg58GxCFWo+boynMl0\nm5iTmCJv7MSlSoyC3eKBbbn0NqLwoh22WpGgz4q9f2CTpZs/50GOLwga+2GXzxBH\nz6zmLWaqHhXkcfWwhhr+FfJv7TWyVFBa0dG9AEeXjwfXZ071loXZBzkpdLmlBRK4\nmU+5cfUd6dLXRcQ23vYx6lMsEdUyPoP53K9tF5YSIBNNHvMOfnNMcBrQkMZWUBad\nC86DV2hpAgMBAAECggEAJ6AKkfrsZz0v4Goq7i7iPD6OqSo3veHNEXuVVM1FKMoD\nl7DyxCy1OIJJFXQ92oxt4hGbktY34stlciajY7rCF0jRhIawJ5Fm15ETxI+Su4dS\n9jC5/0ildETuJbO/973/5uGPpxWis03fcFZqWPOsXywgrO0dhwY5zwU0P0V2GqfS\nHyhKGfciB8U3fp5YrTV30PA1FDDrh6yYNqEljbjLzksWfffjGmFLRj+pk3tqGMpd\nK5iTsV83YfFlp+0PhfLaaWxnXvqDyVxfBYoQRRwEjp/EpTwcTM4SqD8PCpRSLf9i\nPEGIffw5C7rd92k3c7NtBQFe4jQjUtJ0z3NfrELH/QKBgQDaQfmbCfq1VIEZ9VK/\nnALA6XWbMO4mgAWAkf0UmR0NY+u1Fss8UkKP+OtBpi8aebbbDGVX4vFa/5fVi+Sg\nrWIWFtoXMYehYj+XztO6uy4BSu1kkWJItvSEfSgmPfYOqkZr7sMYcCWdGIavAowy\n0K8QhJiUL831xUlgKoyZY6qh/QKBgQC7imA14XzU1BZSAEg40cboxIgHDQ0GwRRX\nXrODfFL+Sp2gCPgM17ruw7Fq8Os4LScjerXr8NfuWDhkz38ssSImrKD6Rit10TZy\neF0sscC9hLcpO2wyOmVvOPYnTw/R7AMzzT0EvdDMHROYHqho7hOnoylwIngGOXLw\nd9RS0CAl3QKBgQCYL0KdUXMH9xliAUYmpuDgpKjFgnO8Uq4DfUgLkcvJJ3AWQAOM\nVwtkmjtn9jmH63COAnGzu2FxgyDa3QWY5+yp3FtLqtSYugn/j07hOF0Wt6kZ46m1\nbCTJMP/K0o98oEwkPEK7Co+fn5dh9pPNZud6zAob4c1p3puQO3r4BZ/X/QKBgBN+\n/iN7zntdlPhvWRK3FCOMksuQ2sLR/ahbivPnT8Vpwlsps4e6QY+ivmXsp7dOUlxI\n3HKrtfbsKuin/YOK4o78sTtzYf88gZmC08TasbvB+TyLFeNe2L6oQEaz3GQpUefn\ntSkyBmvBthDBVyaZYWey+ZLTsoCLJlzDSEpXoo/tAoGANlji99POGurr8rewGDRC\nmWUSp4BkS3p5XiPSfW7fxg8S/YT5b+BCWCbgP06/y3vS5MwyGQBg9uXGrMNkYmKr\nDh4uWHHwhGlAVHTdunVlecbpjyAj30sgcRAqcfL0xG/vzaFoYqBXMJVY4ljF020I\ns1qhlzONJYAYc6IedUfo1iw=\n-----END PRIVATE KEY-----\n",
    "client_email": "firebase-adminsdk-fbsvc@yello-beta-a5931.iam.gserviceaccount.com",
    "client_id": "113842839715709948130",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40yello-beta-a5931.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
  }

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS)
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
