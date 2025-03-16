import streamlit as st
import openai
import json
import re
import requests
import datetime
import firebase_admin
from firebase_admin import credentials, auth, firestore
from typing import Dict, Any, List

# -----------------------
# 1. CONFIGURATION & INITIAL SETUP
# -----------------------
st.set_page_config(page_title="AI Learning Plan Generator", layout="wide")

def rerun():
    st.rerun()

# Load API keys from secrets
OPENAI_API_KEY = st.secrets["openai"]["api_key"]
openai.api_key = OPENAI_API_KEY
SERPAPI_API_KEY = st.secrets["serpapi"]["api_key"]

# Load Firebase service account credentials from secrets
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

# Load Firebase Web configuration (for client-side usage if needed)
firebase_web_config_str = st.secrets["firebase_web"]["credentials_json"]
if isinstance(firebase_web_config_str, str):
    firebase_web_config = json.loads(firebase_web_config_str)
else:
    firebase_web_config = firebase_web_config_str

# -----------------------
# 2. HELPER FUNCTIONS
# -----------------------
def extract_json(text: str) -> str:
    try:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)
    except Exception as e:
        st.error(f"Error extracting JSON: {e}")
    return ""

def clean_gpt_response(response_text: str) -> str:
    if response_text.startswith("```"):
        lines = response_text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response_text = "\n".join(lines)
    return response_text

def link_is_valid(url: str) -> bool:
    try:
        if "youtube.com" in url or "youtu.be" in url:
            if "watch?v=" not in url and "youtu.be/" not in url:
                return False
            return True
        r = requests.head(url, timeout=3, allow_redirects=True)
        if r.status_code == 200:
            return True
        r = requests.get(url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def serpapi_search(query: str, num_results: int = 3) -> List[Dict[str, str]]:
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": num_results
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        results_list = []
        if "organic_results" in data:
            for item in data["organic_results"][:num_results]:
                link_url = item.get("link")
                title = item.get("title", "Resource")
                if link_url and link_is_valid(link_url):
                    res_type = "video" if ("youtube.com" in link_url or "youtu.be" in link_url) else "article"
                    results_list.append({
                        "name": title[:70],
                        "link": link_url,
                        "type": res_type
                    })
        return results_list
    except Exception as e:
        st.error(f"SerpAPI error: {e}")
        return []

# -----------------------
# 3. THEME CSS (STRICT BLACK & WHITE)
# -----------------------
def get_theme_css() -> str:
    return """
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;700&display=swap');
        body {
            font-family: 'Instrument Sans', sans-serif;
            background-color: #FFFFFF;
            color: #262730;
        }
        .stButton > button {
            width: 100%;
            padding: 10px;
            font-size: 16px;
            background-color: #000000;
            color: #FFFFFF;
            border-radius: 6px;
            border: none;
            transition: background-color 0.2s ease-in-out;
        }
        .stButton > button:hover {
            background-color: #000000;
        }
        .sidebar-divider {
            border-bottom: 0.3px solid #000000;
            margin: 15px 0;
        }
        .plan-container {
            background: #0F1116;
            color: #ffffff;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1, h2, h3, h4, h5 {
            color: #ffffff;
        }
        a, a:visited {
            color: #CBCBCB;
            text-decoration: underline;
        }
        a:hover {
            color: #262730;
        }
        .small-muted {
            font-size: 0.9em;
            color: #CBCBCB;
            margin-bottom: 10px;
        }
        .icon {
            vertical-align: middle;
            font-size: 20px;
            margin-right: 5px;
            color: #CBCBCB;
        }
    </style>
    """
st.markdown(get_theme_css(), unsafe_allow_html=True)

# -----------------------
# 4. GPT LEARNING PLAN GENERATION
# -----------------------
def generate_learning_plan(goal: str, timeline: str, learning_style: List[str],
                           background_level: str, weekly_time: int,
                           topics: str, primary_objective: str, future_goals: str,
                           challenges: str, additional_info: str, courses_option: str) -> Dict[str, Any]:
    prompt = f"""
You are an advanced learning coach. A user wants to learn about {goal}.
They are interested in the following topics: {topics}.
Their primary objective is: {primary_objective}.
Their future goals are: {future_goals}.
Their current expertise level is {background_level} and they face these challenges: {challenges}.
Additional info: {additional_info}.
They can dedicate {weekly_time} hours per week and have a timeline of {timeline}.
They indicated a preference for {courses_option} courses.
Please produce a detailed, step-by-step learning guide that begins with an overall study blueprint and then breaks the plan into diversified weekly sections.
Return the response as valid JSON using this exact schema:
{{
    "goal": string,
    "timeline": string,
    "learning_style": [string],
    "background_level": string,
    "weekly_time": number,
    "weeks": [
        {{
            "week_number": number,
            "objective": string,
            "resources": [
                {{
                    "name": string,
                    "link": string,
                    "type": string
                }}
            ],
            "action_items": [
                {{
                    "description": string,
                    "due_by": string
                }}
            ]
        }}
    ]
}}
No extra text.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You create detailed, personalized learning plans with a clear study blueprint and diversified weekly topics."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1700,
            temperature=0.2
        )
        plan_text = response["choices"][0]["message"]["content"]
        plan_text = clean_gpt_response(plan_text)
        try:
            plan_dict = json.loads(plan_text)
        except Exception:
            extracted = extract_json(plan_text)
            if not extracted:
                st.error("Failed to extract JSON from GPT response.")
                st.write("Raw GPT Response:", plan_text)
                return {}
            plan_dict = json.loads(extracted)
    except Exception as e:
        st.error("Error calling OpenAI API: " + str(e))
        return {}

    resource_mapping = {
        "Videos": "video",
        "Articles": "article",
        "Hands-on Projects": "project",
        "Podcasts": "podcast",
        "Books": "book",
        "Courses": "course"
    }
    desired_types = [resource_mapping[x] for x in learning_style if x in resource_mapping]
    for week in plan_dict.get("weeks", []):
        for rtype in desired_types:
            if not any(r.get("type", "").lower() == rtype for r in week.get("resources", [])):
                query = f"{goal} {week.get('objective', '')} {rtype}"
                fallback = serpapi_search(query, num_results=1)
                if fallback:
                    week["resources"].extend(fallback)
    return plan_dict

# -----------------------
# 5. SESSION STATE INITIALIZATION
# -----------------------
if "user" not in st.session_state:
    st.session_state["user"] = None
if "email" not in st.session_state:
    st.session_state["email"] = None
if "create_plan" not in st.session_state:
    st.session_state["create_plan"] = False
if "selected_plan" not in st.session_state:
    st.session_state["selected_plan"] = None
if "loading" not in st.session_state:
    st.session_state["loading"] = False

# -----------------------
# 6. AUTHENTICATION FUNCTIONS (Using Firebase Auth REST API for demonstration)
# -----------------------
def sign_up(email: str, password: str, confirm_password: str, phone: str):
    if password != confirm_password:
        st.error("Passwords do not match. Please try again.")
        return None
    if len(password) < 6:
        st.error("Password must be at least 6 characters long.")
        return None
    if "@" not in email or "." not in email:
        st.error("Please enter a valid email address.")
        return None
    try:
        # For demonstration, we store the password in plain text in Firestore.
        # In production, use Firebase Authentication's secure methods.
        user_data = {
            "email": email,
            "phone": phone,
            "password": password,
            "time_spent": 0,
            "created_at": datetime.datetime.utcnow().isoformat()
        }
        user_ref = db.collection("users").document(email)
        if user_ref.get().exists:
            st.error("A user with this email already exists. Please log in.")
            return None
        user_ref.set(user_data)
        st.success(f"Account created for {email}. Please log in.")
        return email
    except Exception as e:
        st.error(f"Sign-up error: {e}")
        return None

def log_in(email: str, password: str):
    try:
        user_doc = db.collection("users").document(email).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            stored_password = user_data.get("password", "")
            if password == stored_password:
                st.session_state["user"] = email
                st.session_state["email"] = email
                st.success(f"Welcome back, {email}!")
                rerun()
            else:
                st.error("Incorrect password. Please try again.")
        else:
            st.error("User not found. Please sign up first.")
    except Exception as e:
        st.error(f"Login error: {e}")

# -----------------------
# 7. REPORT ISSUE FUNCTIONALITY
# -----------------------
def report_issue(description: str):
    report_data = {
        "email": st.session_state.get("email", "unknown"),
        "description": description,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    db.collection("reports").add(report_data)
    st.success("Thank you for reporting the issue!")

# -----------------------
# 8. AUTHENTICATION UI
# -----------------------
if not st.session_state["user"]:
    st.markdown("<h1><i class='material-icons icon'>school</i> AI Learning Plan Generator</h1>", unsafe_allow_html=True)
    st.markdown("<p class='small-muted'>Sign up or log in to create and view your personalized learning plans.</p>", unsafe_allow_html=True)
    auth_option = st.radio("Choose an option:", ["Login", "Sign Up"])
    email = st.text_input("Email", key="auth_email")
    password = st.text_input("Password", type="password", key="auth_password")
    if auth_option == "Sign Up":
        confirm_password = st.text_input("Confirm Password", type="password", key="auth_confirm_password")
        phone = st.text_input("Phone Number (e.g. +1234567890)", key="auth_phone")
        if st.button("Create Account"):
            sign_up(email, password, confirm_password, phone)
    else:
        if st.button("Login"):
            log_in(email, password)
    st.stop()

# -----------------------
# 9. SIDEBAR (with plan limit check, short titles, and delete icon)
# -----------------------
st.sidebar.markdown("<h2><i class='material-icons icon'>folder</i> Your Learning Plans</h2>", unsafe_allow_html=True)

user_ref = db.collection("users").document(st.session_state["user"])
learning_plans_ref = user_ref.collection("learning_plans")
existing_plans = list(learning_plans_ref.stream())
if len(existing_plans) >= 5:
    st.sidebar.error("Plan limit reached (5 plans maximum). Please delete an existing plan to create a new one.")

if st.sidebar.button("Create New Learning Plan") and len(existing_plans) < 5:
    st.session_state["create_plan"] = True
    st.session_state["selected_plan"] = None
    rerun()

st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
st.sidebar.subheader("Saved Learning Plans")

def load_saved_plans():
    return learning_plans_ref.stream()

for doc in load_saved_plans():
    plan_data = doc.to_dict()
    full_title = plan_data.get("title", "Unnamed Plan")
    short_title_words = full_title.split()[:3]
    short_title = " ".join(short_title_words)
    if len(full_title.split()) > 3:
        short_title += "..."
    plan_id = doc.id
    col1, col2 = st.sidebar.columns([4,1])
    with col1:
        if st.button(short_title, key=f"view_{plan_id}"):
            st.session_state["selected_plan"] = json.loads(plan_data["plan"])
            st.session_state["create_plan"] = False
            rerun()
    with col2:
        if st.button("🗑", key=f"del_{plan_id}"):
            learning_plans_ref.document(plan_id).delete()
            st.rerun()
            
st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
if st.sidebar.button("Logout"):
    st.session_state["user"] = None
    st.session_state["email"] = None
    st.session_state["create_plan"] = False
    st.session_state["selected_plan"] = None
    rerun()

# -----------------------
# 10. MAIN CONTENT AREA
# -----------------------
st.markdown("<h1><i class='material-icons icon'>dashboard</i> AI Learning Plan Generator</h1>", unsafe_allow_html=True)

if st.session_state["selected_plan"]:
    plan = st.session_state["selected_plan"]
    st.subheader(f"Learning Plan: {plan.get('goal', 'No Title')}")
    st.markdown(f"<p class='small-muted'><strong>Duration:</strong> {plan.get('timeline', 'N/A')}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-muted'><strong>Learning Styles:</strong> {', '.join(plan.get('learning_style', []))}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-muted'><strong>Background Level:</strong> {plan.get('background_level', 'N/A')}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-muted'><strong>Weekly Time Available:</strong> {plan.get('weekly_time', 'N/A')}</p>", unsafe_allow_html=True)
    
    for week in plan.get("weeks", []):
        with st.container():
            st.markdown(
                f"""
                <div class="plan-container">
                    <h3><i class='material-icons icon'>date_range</i> Week {week.get('week_number', '?')}: {week.get('objective', 'No Objective')}</h3>
                    <h4><i class='material-icons icon'>link</i> Resources</h4>
                """,
                unsafe_allow_html=True,
            )
            for resource in week.get("resources", []):
                resource_name = resource.get("name", "Unknown Resource")
                link = resource.get("link", "#")
                resource_type = resource.get("type", "Unknown")
                st.markdown(f"- [{resource_name}]({link}) ({resource_type})")
            st.markdown("<h4><i class='material-icons icon'>assignment</i> Action Items</h4>", unsafe_allow_html=True)
            for action in week.get("action_items", []):
                if isinstance(action, dict):
                    st.markdown(f"- **{action.get('description', '')}** (Due by {action.get('due_by', 'N/A')})")
    
    st.markdown("<h4>Rate this Learning Plan</h4>", unsafe_allow_html=True)
    rating = st.slider("Your Rating (1-5)", 1, 5, 3)
    if st.button("Submit Rating"):
        plan_id = None
        for doc in load_saved_plans():
            data = doc.to_dict()
            if data.get("title", "") == plan.get("goal", ""):
                plan_id = doc.id
                break
        if plan_id:
            learning_plans_ref.document(plan_id).update({"rating": rating})
            st.success("Thank you for your feedback!")
    
    st.markdown("<h4>Report an Issue</h4>", unsafe_allow_html=True)
    issue_text = st.text_area("Describe any issue or feedback you have:")
    if st.button("Submit Issue"):
        if issue_text.strip():
            report_issue(issue_text)
        else:
            st.error("Please provide details about the issue before submitting.")
            
elif st.session_state["create_plan"]:
    st.markdown("<h2><i class='material-icons icon'>create</i> Create a New Learning Plan</h2>", unsafe_allow_html=True)
    st.markdown("<p class='small-muted'>Answer the questions below to help us create a tailored learning plan. We will also ask about course preferences (if you select 'Courses') and gather details about your learning style and personality.</p>", unsafe_allow_html=True)
    
    subject = st.text_input("1. What do you want to learn?", placeholder="e.g., Finance")
    topics = st.text_input("2. What specific topics are you interested in?", placeholder="e.g., Investment strategies, valuation, corporate finance")
    primary_objective = st.text_input("3. What is your primary objective?", placeholder="e.g., Career advancement, personal growth")
    background_level = st.selectbox("4. What is your current expertise level?", ["Beginner", "Intermediate", "Advanced"])
    learning_style = st.multiselect("5. What are your preferred learning methods?", 
                                    ["Videos", "Articles", "Hands-on Projects", "Podcasts", "Books", "Courses"], 
                                    default=["Videos", "Articles"])
    weekly_time = st.slider("6. How many hours can you dedicate per week?", min_value=1, max_value=40, value=5)
    timeline = st.selectbox("7. What is your timeline?", ["4 weeks", "8 weeks", "12 weeks", "Self-paced"])
    future_goals = st.text_input("8. What are your career or personal goals after learning this?", placeholder="e.g., Get a job in finance, launch a startup")
    challenges = st.text_area("9. What challenges or obstacles do you face?", placeholder="e.g., Limited time, difficulty understanding complex topics")
    additional_info = st.text_area("10. Any additional information about your learning style or personality?", placeholder="e.g., Prefer structured blueprints, need hands-on practice")
    
    courses_option = ""
    if "Courses" in learning_style:
        courses_option = st.radio("11. Course recommendations: Do you prefer free or paid courses?", ["Free", "Paid", "Both"], index=2)
    else:
        courses_option = "N/A"

    personality = st.selectbox("12. How would you describe your learning personality?", 
                                 ["Visual Learner", "Auditory Learner", "Kinesthetic Learner", "Read/Write Learner", "Mixed"])
    motivation = st.slider("13. On a scale of 1 to 10, how motivated are you to invest time and resources in your learning journey?", 1, 10, 7)
    
    existing_plans = list(learning_plans_ref.stream())
    if len(existing_plans) >= 5:
        st.error("You have reached the maximum of 5 learning plans. Please delete an existing plan to create a new one.")
    else:
        if st.button("Generate Learning Plan"):
            if not subject:
                st.error("Please specify what you want to learn.")
            else:
                st.session_state["loading"] = True
                rerun()
        if st.session_state["loading"]:
            with st.spinner("Generating your tailored learning plan..."):
                combined_additional_info = f"Personality: {personality}. Motivation level: {motivation}. Additional info: {additional_info}"
                plan_data = generate_learning_plan(
                    goal=subject,
                    timeline=timeline,
                    learning_style=learning_style,
                    background_level=background_level,
                    weekly_time=weekly_time,
                    topics=topics,
                    primary_objective=primary_objective,
                    future_goals=future_goals,
                    challenges=challenges,
                    additional_info=combined_additional_info,
                    courses_option=courses_option
                )
                if plan_data and plan_data.get("weeks"):
                    st.session_state["selected_plan"] = plan_data
                    st.session_state["create_plan"] = False
                    st.session_state["loading"] = False
                    new_plan_ref = learning_plans_ref.document()
                    new_plan_ref.set({
                        "title": plan_data["goal"],
                        "plan": json.dumps(plan_data),
                        "rating": None
                    })
                    st.success("Learning plan generated and saved!")
                    rerun()
                else:
                    st.session_state["loading"] = False
                    st.error("Plan generation failed or returned empty. Please try again.")
else:
    st.write("No learning plan selected. Please create a new plan or select an existing one from the sidebar.")
