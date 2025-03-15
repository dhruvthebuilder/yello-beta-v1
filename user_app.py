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

def rerun():
    st.rerun()

# Replace with your own keys
OPENAI_API_KEY = st.secrets["openai"]["api_key"]
SERPAPI_API_KEY = st.secrets["serpapi"]["api_key"]
openai.api_key = OPENAI_API_KEY

firebase_creds = st.secrets["firebase"]
if isinstance(firebase_creds, str):
    firebase_creds = json.loads(firebase_creds)
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS)
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.set_page_config(page_title="AI Learning Plan Generator", layout="wide")

# -----------------------
# 2. HELPER FUNCTIONS
# -----------------------

def extract_json(text: str) -> str:
    """Extract a JSON object from text using regex."""
    try:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)
    except Exception as e:
        st.error(f"Error extracting JSON: {e}")
    return ""

def link_is_valid(url: str) -> bool:
    """
    Check if a URL returns a 200 status.
    For YouTube, the URL must contain 'watch?v=' or 'youtu.be/'.
    """
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
    """
    Use SerpAPI to fetch real links from Google Search.
    Returns a list of dictionaries with keys: 'name', 'link', and 'type'.
    """
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
    """
    Returns CSS using only black (#000000) and white (#FFFFFF).
    - Background: White
    - Text: Black
    - Buttons: Black background, white text.
    """
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
            color: #fffff;
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
def generate_learning_plan(goal: str, timeline: str, learning_style: list,
                           background_level: str, weekly_time: int,
                           topics: str, primary_objective: str, future_goals: str,
                           challenges: str, additional_info: str) -> Dict[str, Any]:
    """
    Generate a tailored learning plan using GPT.
    The prompt includes extra questions for a more personalized plan.
    Validates resource links and falls back to SerpAPI if needed.
    """
    prompt = f"""
You are an expert learning coach. A user wants to learn about {goal}.
The user is interested in the following topics: {topics}.
Their primary objective is: {primary_objective}.
They aim to achieve: {future_goals}.
They mention the following challenges: {challenges}.
Additional information: {additional_info}.
They are at a {background_level} level and prefer these learning styles: {', '.join(learning_style)}.
They can dedicate about {weekly_time} hours per week and their timeline is {timeline}.

Provide a structured weekly learning plan where each week includes:
- A clear objective.
- 2-3 suggested resources with direct links and resource types (video, article, podcast, project).
  * If "Podcasts" is in the user's learning style, include at least one resource of type "podcast".
  * If "Hands-on Projects" is in the user's learning style, include a detailed hands-on project description as a resource of type "project".
- 2-3 action items with short due-by estimates.

Return your answer strictly in JSON format with the structure:
{{
    "goal": "...",
    "timeline": "...",
    "learning_style": [...],
    "background_level": "...",
    "weekly_time": ...,
    "weeks": [
        {{
            "week_number": 1,
            "objective": "...",
            "resources": [
                {{
                    "name": "...",
                    "link": "...",
                    "type": "..."
                }}
            ],
            "action_items": [
                {{
                    "description": "...",
                    "due_by": "..."
                }}
            ]
        }}
    ]
}}
    """
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1400,
        temperature=0.7,
    )
    plan_text = response["choices"][0]["message"]["content"]
    try:
        plan_dict = json.loads(plan_text)
    except Exception:
        extracted = extract_json(plan_text)
        if not extracted:
            return {}
        try:
            plan_dict = json.loads(extracted)
        except Exception:
            return {}

    plan_dict.setdefault("goal", goal)
    plan_dict.setdefault("timeline", timeline)
    plan_dict.setdefault("learning_style", learning_style)
    plan_dict.setdefault("background_level", background_level)
    plan_dict.setdefault("weekly_time", weekly_time)

    # Validate resource links
    for week in plan_dict.get("weeks", []):
        valid_resources = []
        for r in week.get("resources", []):
            link_url = r.get("link", "")
            if link_url and link_is_valid(link_url):
                valid_resources.append(r)
        week["resources"] = valid_resources

    # Fallback: for each week, if a desired resource type is missing, use SerpAPI
    resource_mapping = {
        "Videos": "video",
        "Articles": "article",
        "Hands-on Projects": "project",
        "Podcasts": "podcast",
        "Books": "book"
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
# 6. AUTHENTICATION FUNCTIONS
# -----------------------
def sign_up(email: str, password: str):
    """
    Create a user in Firebase Auth and write user details to Firestore.
    """
    try:
        user = auth.create_user(email=email, password=password)
        db.collection("users").document(user.uid).set({
            "email": email,
            "time_spent": 0,
            "created_at": datetime.datetime.utcnow().isoformat()
        })
        st.success(f"Account created for {email}. You can now log in.")
        return user.uid
    except Exception as e:
        st.error(f"Sign-up error: {e}")
        return None

def log_in(email: str, password: str):
    """
    Log in an existing user and set session state.
    """
    try:
        user_rec = auth.get_user_by_email(email)
        if user_rec:
            st.session_state["user"] = user_rec.uid
            st.session_state["email"] = email
            st.success(f"Welcome back, {email}!")
            rerun()
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
        if st.button("Create Account"):
            sign_up(email, password)
    else:
        if st.button("Login"):
            log_in(email, password)
    st.stop()

# -----------------------
# 9. SIDEBAR
# -----------------------
st.sidebar.markdown("<h2><i class='material-icons icon'>folder</i> Your Learning Plans</h2>", unsafe_allow_html=True)
if st.sidebar.button("Create New Learning Plan"):
    st.session_state["create_plan"] = True
    st.session_state["selected_plan"] = None
    rerun()
st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
st.sidebar.subheader("Saved Learning Plans")
user_ref = db.collection("users").document(st.session_state["user"])
learning_plans_ref = user_ref.collection("learning_plans")
def load_saved_plans():
    return learning_plans_ref.stream()
for doc in load_saved_plans():
    plan_data = doc.to_dict()
    plan_key = f"plan_{doc.id}"
    plan_title = plan_data.get("title", "Unnamed Plan")
    if st.sidebar.button(plan_title, key=plan_key):
        st.session_state["selected_plan"] = json.loads(plan_data["plan"])
        st.session_state["create_plan"] = False
        rerun()
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

# If a plan is selected, display it.
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
    with st.expander("Report an Issue"):
        with st.form("report_form"):
            issue_text = st.text_area("Describe the issue:")
            submitted = st.form_submit_button("Submit Report")
            if submitted and issue_text:
                db.collection("reports").add({
                    "email": st.session_state.get("email", "unknown"),
                    "description": issue_text,
                    "timestamp": datetime.datetime.utcnow().isoformat()
                })
                st.success("Thank you for reporting the issue!")
                
# If the user is creating a new plan, ask additional detailed questions.
elif st.session_state["create_plan"]:
    st.markdown("<h2><i class='material-icons icon'>create</i> Create a New Learning Plan</h2>", unsafe_allow_html=True)
    st.markdown("<p class='small-muted'>Please answer the following questions to help us tailor your learning plan.</p>", unsafe_allow_html=True)
    
    # Basic questions
    subject = st.text_input("1. What do you want to learn?", placeholder="e.g., Web Development")
    topics = st.text_input("2. What specific topics are you interested in?", placeholder="e.g., Front-end frameworks, APIs")
    primary_objective = st.text_input("3. What is your primary objective?", placeholder="e.g., Career advancement, Personal interest")
    background_level = st.selectbox("4. What is your current expertise level?", ["Beginner", "Intermediate", "Advanced"])
    learning_style = st.multiselect("5. What are your preferred learning methods?", 
                                    ["Videos", "Articles", "Hands-on Projects", "Podcasts", "Books"], 
                                    default=["Videos", "Articles"])
    weekly_time = st.slider("6. How many hours can you dedicate per week?", min_value=1, max_value=40, value=5)
    timeline = st.selectbox("7. What is your timeline?", ["4 weeks", "8 weeks", "12 weeks", "Self-paced"])
    future_goals = st.text_input("8. What are your career or personal goals after learning this?", placeholder="e.g., Get a job as a developer")
    challenges = st.text_area("9. What challenges or obstacles do you face?", placeholder="e.g., Limited time, difficult concepts")
    additional_info = st.text_area("10. Any additional information you'd like to share?", placeholder="e.g., Specific interests, learning preferences")
    
    if st.button("Generate Learning Plan"):
        if not subject:
            st.error("Please specify what you want to learn.")
        else:
            st.session_state["loading"] = True
            rerun()
    if st.session_state["loading"]:
        with st.spinner("Generating your tailored learning plan..."):
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
                additional_info=additional_info
            )
            if plan_data and plan_data.get("weeks"):
                st.session_state["selected_plan"] = plan_data
                st.session_state["create_plan"] = False
                st.session_state["loading"] = False
                new_plan_ref = learning_plans_ref.document()
                new_plan_ref.set({
                    "title": plan_data["goal"],
                    "plan": json.dumps(plan_data)
                })
                st.success("Learning plan generated and saved!")
                rerun()
            else:
                st.session_state["loading"] = False
                st.error("Plan generation failed or returned empty. Please try again.")
else:
    st.write("No learning plan selected. Please create a new plan or select an existing one from the sidebar.")
