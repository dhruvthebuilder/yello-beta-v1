import streamlit as st
import openai
import json
import re
import requests
import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Dict, Any, List
import os

# -----------------------
# 1. CONFIGURATION & INITIAL SETUP
# -----------------------
st.set_page_config(page_title="Yello - Personalised Learning Plan Generator", layout="wide")

def rerun():
    st.rerun()

# Set Pinecone API key in environment.
os.environ["PINECONE_API_KEY"] = st.secrets["pinecone"]["api_key"]

# Load API keys from secrets.
OPENAI_API_KEY = st.secrets["openai"]["api_key"]
SERPAPI_API_KEY = st.secrets["serpapi"]["api_key"]

# Create a global OpenAI client instance using the new API interface.
openai_client = OPENAI_API_KEY

# -----------------------
# 2. FIREBASE INITIALIZATION
# -----------------------
firebase_creds_str = st.secrets["firebase"]["credentials_json"]
if isinstance(firebase_creds_str, str):
    firebase_creds = json.loads(firebase_creds_str)
else:
    firebase_creds = firebase_creds_str

if firebase_creds and not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# (Optional) Load Firebase Web configuration if needed.
firebase_web_config_str = st.secrets["firebase_web"]["credentials_json"]
if isinstance(firebase_web_config_str, str):
    firebase_web_config = json.loads(firebase_web_config_str)
else:
    firebase_web_config = firebase_web_config_str

# -----------------------
# 3. INITIALIZE PINECONE & CURATED CONTENT
# -----------------------
import pinecone
from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key=st.secrets["pinecone"]["api_key"])
pinecone_cloud = st.secrets["pinecone"].get("cloud", "aws")
pinecone_region = st.secrets["pinecone"].get("region", "us-east-1")
spec = ServerlessSpec(cloud=pinecone_cloud, region=pinecone_region)

index_name = "learning-plan-index"
if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=1536,  # Must match your embedding model's dimension
        metric="cosine",
        spec=spec
    )

curated_document = """
High Quality Learning Plan Guidelines:

1. **Define Clear Objectives:**  
   Determine what you want to learn, why you want to learn it, and what the end goal looks like.

2. **Break Down Topics:**  
   Divide your learning into smaller, manageable topics and arrange them in a logical order.

3. **Weekly Structure:**  
   Create a blueprint that allocates specific topics and action items for each week, including resource recommendations.

4. **Mix Learning Methods:**  
   Use a combination of videos, articles, projects, and interactive activities to reinforce understanding.

5. **Set Measurable Milestones:**  
   Establish clear milestones and action items with deadlines to track progress.

6. **Review and Iterate:**  
   Periodically review your plan, update it based on progress, and adjust methods as needed.
"""

from langchain.text_splitter import CharacterTextSplitter
splitter = CharacterTextSplitter(chunk_size=500, chunk_overlap=50)
docs = splitter.split_text(curated_document)

# -----------------------
# 4. EMBEDDINGS & VECTORSTORE SETUP
# -----------------------
from langchain_openai import OpenAIEmbeddings
embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model="text-embedding-ada-002")

from langchain_pinecone import Pinecone as LC_Pinecone
vectorstore = LC_Pinecone.from_existing_index(
    index_name=index_name,
    embedding=embeddings,
    namespace="curated_learning"
)

# -----------------------
# 5. HELPER FUNCTIONS
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
            return "watch?v=" in url or "youtu.be/" in url
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

def retrieve_context_for_goal(goal: str) -> str:
    results = serpapi_search(f"overview of {goal}", num_results=1)
    if results:
        return results[0].get("name", "")
    return ""

def get_youtube_videos(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    youtube_api_key = st.secrets["youtube"]["api_key"]
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": youtube_api_key
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        videos = []
        for item in data.get("items", []):
            title = item["snippet"]["title"]
            video_id = item["id"]["videoId"]
            video_link = f"https://www.youtube.com/watch?v={video_id}"
            videos.append({"title": title, "link": video_link})
        return videos
    except Exception as e:
        st.error(f"YouTube API error: {e}")
        return []

def score_videos_with_gpt(videos: List[Dict[str, str]], topic: str) -> str:
    video_list_str = "\n".join([f"{i+1}. {v['title']} - {v['link']}" for i, v in enumerate(videos)])
    prompt = f"Here is a list of videos:\n{video_list_str}\n\nFor the topic '{topic}', please return only the link of the video that is most relevant."
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert at evaluating video relevance."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0.2,
        )
        result = response.choices[0].message.content.strip()
        url_match = re.search(r'(https?://[^\s]+)', result)
        if url_match:
            return url_match.group(1)
    except Exception as e:
        st.error(f"Error scoring videos with GPT: {e}")
    return ""

def add_best_youtube_videos(plan: Dict[str, Any]) -> Dict[str, Any]:
    for week in plan.get("weeks", []):
        topic = week.get("objective", "")
        if topic:
            videos = get_youtube_videos(topic, max_results=10)
            if videos:
                best_video = score_videos_with_gpt(videos, topic)
                if best_video:
                    week["resources"].append({
                        "name": f"Best Video for {topic}",
                        "link": best_video,
                        "type": "video"
                    })
    return plan


def report_issue(plan_id: str, description: str):
    report_data = {
        "email": st.session_state.get("email", "unknown"),
        "plan_id": plan_id,
        "description": description,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    db.collection("reports").add(report_data)
    st.success("Issue reported successfully!")

# New: Validate resource links; if a link is broken, try to update it.
def validate_links_in_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    for week in plan.get("weeks", []):
        for resource in week.get("resources", []):
            if not link_is_valid(resource["link"]):
                fallback = serpapi_search(f"{resource.get('name', '')} {resource.get('type', '')}", num_results=1)
                if fallback and fallback[0].get("link"):
                    new_link = fallback[0]["link"]
                    if link_is_valid(new_link):
                        resource["link"] = new_link
    return plan

# -----------------------
# 6. THEME CSS
# -----------------------
def get_theme_css() -> str:
    return """
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;700&display=swap');
        body { font-family: 'Instrument Sans', sans-serif; background-color: #FFFFFF; color: #262730; }
        .stButton > button { width: 100%; padding: 10px; font-size: 16px; background-color: #000000; color: #FFFFFF; border-radius: 6px; border: none; transition: background-color 0.2s ease-in-out; }
        .stButton > button:hover { background-color: #000000; }
        .sidebar-divider { border-bottom: 0.3px solid #000000; margin: 15px 0; }
        .small-muted { font-size: 0.9em; color: #CBCBCB; margin-bottom: 10px; }
        .icon { vertical-align: middle; font-size: 20px; margin-right: 5px; color: #CBCBCB; }
        .week-box { background-color: #000; color: #fff; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
    </style>
    """
st.markdown(get_theme_css(), unsafe_allow_html=True)

# -----------------------
# 7. DISPLAY WEEK WITH PROGRESS (CHECKLIST, GAMIFIED INSIGHTS, & UPDATED FORMAT)
# -----------------------
def display_week_with_progress(week: Dict[str, Any], week_index: int, weekly_time: int):
    week_key = f"week_{week_index}_progress"
    plan_id = st.session_state["selected_plan_id"]
    
    # Get document safely (fallback to empty dict).
    plan_doc = learning_plans_ref.document(plan_id).get().to_dict() or {}
    progress = plan_doc.get("progress", {})
    if week_key in progress:
        st.session_state[week_key] = progress[week_key]
    else:
        if week_key not in st.session_state:
            st.session_state[week_key] = {}
    
    st.markdown("<div class='week-box'>", unsafe_allow_html=True)
    st.markdown(f"### Week {week.get('week_number', '?')}: {week.get('objective', 'No Objective')}")
    st.markdown(f"**Estimated Time: {weekly_time} hrs**")
    
    if "detailed_overview" in week:
        st.markdown(f"**Detailed Overview:** {week['detailed_overview']}")
    if "outcomes" in week:
        st.markdown(f"**Outcomes:** {week['outcomes']}")
    if "gamified_insights" in week:
        st.markdown(f"**Gamified Insight:** {week['gamified_insights']}")
    
    resources = week.get("resources", [])
    actions = week.get("action_items", [])
    max_len = max(len(resources), len(actions))
    
    tasks = []
    for i in range(max_len):
        resource = resources[i] if i < len(resources) else None
        action = actions[i] if i < len(actions) else None
        if resource and action:
            resource_name = resource.get("name", "Resource")
            resource_link = resource.get("link", "#")
            action_desc = action.get("description", "")
            due_date = action.get("due_by", "N/A")
            if resource_name in action_desc:
                combined_text = action_desc.replace(resource_name, f"[{resource_name}]({resource_link})")
            else:
                combined_text = f"{action_desc} [{resource_name}]({resource_link})"
            combined_text += f" (Due by {due_date})"
            item_id = f"combined_{week_index}_{i}"
            tasks.append((item_id, combined_text))
        elif resource:
            resource_name = resource.get("name", "Resource")
            resource_link = resource.get("link", "#")
            item_id = f"resource_{week_index}_{i}"
            tasks.append((item_id, f"[{resource_name}]({resource_link})"))
        elif action:
            action_desc = action.get("description", "")
            due_date = action.get("due_by", "N/A")
            item_id = f"action_{week_index}_{i}"
            tasks.append((item_id, f"{action_desc} (Due by {due_date})"))
    
    st.markdown("#### Checklist")
    for (item_id, label) in tasks:
        if item_id not in st.session_state[week_key]:
            st.session_state[week_key][item_id] = False
        new_value = st.checkbox(label, value=st.session_state[week_key][item_id], key=f"{week_key}_{item_id}")
        st.session_state[week_key][item_id] = new_value

    total_items = len(tasks)
    completed_items = sum(1 for v in st.session_state[week_key].values() if v)
    completion_pct = (completed_items / total_items * 100) if total_items > 0 else 0
    st.progress(completion_pct / 100.0)
    st.write(f"{completion_pct:.0f}% Completed")
    
    for resource in week.get("resources", []):
        if resource.get("type", "").lower() == "video" and "Best Video for" in resource.get("name", ""):
            st.video(resource.get("link"))
            break
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Update Firestore with progress.
    plan_ref = learning_plans_ref.document(plan_id)
    current_doc = plan_ref.get().to_dict() or {}
    progress = current_doc.get("progress", {})
    progress[week_key] = st.session_state[week_key]
    plan_ref.update({"progress": progress})

# -----------------------
# 8. LEARNING PLAN GENERATION WITH RAG (PINECONE RETRIEVAL)
# -----------------------
def generate_learning_plan(goal: str, topics: List[str], background_level: str, weekly_time: int, timeline: str) -> Dict[str, Any]:
    retrieval_query = f"learning plan guidelines for {goal}, topics: {', '.join(topics)}, expertise: {background_level}"
    context_docs = vectorstore.similarity_search(retrieval_query, k=3)
    context_text = "\n\n".join([doc.page_content if hasattr(doc, "page_content") else doc for doc in context_docs])
    extra_context = retrieve_context_for_goal(goal)
    
    content_pref = st.session_state.get("content_preference", "Outcome-Focused")
    
    prompt = f"""
Context: {context_text}
Extra Context: {extra_context}
Content Preference: {content_pref}

You are an advanced learning coach. A user wants to learn about {goal}.
They are interested in the following topics: {', '.join(topics)}.
Their current expertise level is: {background_level}.
They can dedicate {weekly_time} hours per week, with a timeline of {timeline}.

For each week, provide:
- An objective.
- A detailed_overview that comprehensively explains the plan for the week.
- Detailed outcomes describing what the user will achieve by the end of the week.
- Gamified insights (e.g., "better than 80% of your peers").

Also, include relevant resources and action items.

Return the response as valid JSON using this exact schema:
{{
    "goal": string,
    "timeline": string,
    "background_level": string,
    "weekly_time": number,
    "weeks": [
        {{
            "week_number": number,
            "objective": string,
            "detailed_overview": string,
            "outcomes": string,
            "gamified_insights": string,
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
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You create detailed, personalized learning plans with clear weekly outcomes, detailed overviews, and gamified insights."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1700,
            temperature=0.2
        )
        plan_text = response.choices[0].message.content
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
    
    plan_dict = add_best_youtube_videos(plan_dict)
    
    desired_types = ["video", "article"]
    for week in plan_dict.get("weeks", []):
        for rtype in desired_types:
            if not any(r.get("type", "").lower() == rtype for r in week.get("resources", [])):
                query = f"{goal} {week.get('objective', '')} {rtype}"
                fallback = serpapi_search(query, num_results=1)
                if fallback:
                    week["resources"].extend(fallback)
    # Validate resource links before returning.
    plan_dict = validate_links_in_plan(plan_dict)
    return plan_dict

# New: Validate resource links in the plan.
def validate_links_in_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    for week in plan.get("weeks", []):
        for resource in week.get("resources", []):
            if not link_is_valid(resource["link"]):
                query = f"{resource.get('name', '')} {resource.get('type', '')}"
                fallback = serpapi_search(query, num_results=1)
                if fallback and fallback[0].get("link"):
                    new_link = fallback[0]["link"]
                    if link_is_valid(new_link):
                        resource["link"] = new_link
    return plan

# -----------------------
# 9. SESSION STATE INITIALIZATION
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
if "selected_plan_id" not in st.session_state:
    st.session_state["selected_plan_id"] = None
if "submitted_ratings" not in st.session_state:
    st.session_state["submitted_ratings"] = {}

# -----------------------
# 10. AUTHENTICATION FUNCTIONS & UI
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

if not st.session_state["user"]:
    st.markdown("<h1><i class='material-icons icon'>school</i> Yello Personalised Learning Plan Generator</h1>", unsafe_allow_html=True)
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
# 11. SIDEBAR (Plan Management & Content Preference)
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
    col1, col2 = st.sidebar.columns([4, 1])
    with col1:
        if st.button(short_title, key=f"view_{plan_id}"):
            st.session_state["selected_plan"] = json.loads(plan_data.get("plan", "{}"))
            st.session_state["selected_plan_id"] = plan_id
            st.session_state["create_plan"] = False
            rerun()
    with col2:
        # Delete button with trash icon emoji
        if st.button("🗑️", key=f"del_{plan_id}", help="Delete Plan"):
            learning_plans_ref.document(plan_id).delete()
            rerun()
            
st.sidebar.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
if st.sidebar.button("Logout"):
    st.session_state.clear()
    rerun()

# -----------------------
# 12. MAIN CONTENT AREA (Plan Viewer / Creator)
# -----------------------
st.markdown("<h1><i class='material-icons icon'>dashboard</i> Yello Personalised Learning Plan Generator</h1>", unsafe_allow_html=True)

if st.session_state.get("selected_plan_id"):
    doc = learning_plans_ref.document(st.session_state["selected_plan_id"]).get()
    if doc.exists:
        st.session_state["selected_plan"] = json.loads(doc.to_dict().get("plan", "{}"))

if st.session_state["selected_plan"]:
    plan = st.session_state["selected_plan"]
    plan_id = st.session_state["selected_plan_id"]
    st.subheader(f"Learning Plan: {plan.get('goal', 'No Title')}")
    st.markdown(f"<p class='small-muted'><strong>Duration:</strong> {plan.get('timeline', 'N/A')}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-muted'><strong>Background Level:</strong> {plan.get('background_level', 'N/A')}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-muted'><strong>Weekly Time Available:</strong> {plan.get('weekly_time', 'N/A')} hrs</p>", unsafe_allow_html=True)
    
    weekly_time_val = plan.get("weekly_time", 0)
    for idx, week in enumerate(plan.get("weeks", [])):
        display_week_with_progress(week, idx, weekly_time_val)
    
    if plan.get("rating") is None:
        rating = st.slider("Your Rating (1-5)", 1, 5, 3, key=f"rating_{plan_id}")
        if st.button("Submit Rating", key=f"submit_rating_{plan_id}"):
            learning_plans_ref.document(plan_id).update({"rating": rating})
            st.session_state["selected_plan"]["rating"] = rating
            st.success("Thank you for your feedback!")
            rerun()
    else:
        st.write(f"Rating submitted: {plan.get('rating')}/5")
    
    st.markdown("### Report an Issue")
    issue_key = f"issue_{plan_id}"
    issue_text = st.text_area("Describe any issue or feedback you have:", key=issue_key, value="")
    if st.button("Submit Issue", key=f"submit_issue_{plan_id}"):
        if issue_text.strip():
            report_issue(plan_id, issue_text)
            st.success("Issue reported. To submit a new issue, please clear the previous input and enter new one.")
            if issue_key in st.session_state:
                st.session_state.pop(issue_key)
            rerun()
        else:
            st.error("Please provide details about the issue before submitting.")
            
elif st.session_state["create_plan"]:
    st.markdown("<h2><i class='material-icons icon'>create</i> Create a New Learning Plan</h2>", unsafe_allow_html=True)
    st.markdown("<p class='small-muted'>Answer the questions below to generate your personalized plan. You will receive detailed weekly outcomes, a comprehensive overview for each week, and gamified insights on your progress.</p>", unsafe_allow_html=True)
    
    subject = st.text_input("What do you want to learn?", placeholder="e.g., Data Science")
    topics = st.multiselect("Which topics interest you?", 
                            ["Finance", "Data Science", "Programming", "Marketing", "Health", "Art"],
                            default=["Data Science"])
    background_level = st.selectbox("What is your current expertise level?", ["Beginner", "Intermediate", "Advanced"])
    weekly_time = st.slider("How many hours per week can you dedicate?", 1, 40, 5)
    timeline = st.selectbox("What is your timeline?", ["4 weeks", "8 weeks", "12 weeks", "Self-paced"])
    
    if st.button("Generate Learning Plan"):
        if not subject:
            st.error("Please specify what you want to learn.")
        else:
            st.session_state["loading"] = True
            rerun()
    if st.session_state["loading"]:
        with st.spinner("Generating your tailored learning plan..."):
            plan_data = generate_learning_plan(subject, topics, background_level, weekly_time, timeline)
            if plan_data and plan_data.get("weeks"):
                st.session_state["selected_plan"] = plan_data
                new_plan_ref = learning_plans_ref.document()
                st.session_state["selected_plan_id"] = new_plan_ref.id
                st.session_state["create_plan"] = False
                st.session_state["loading"] = False
                new_plan_ref.set({
                    "title": plan_data["goal"],
                    "plan": json.dumps(plan_data),
                    "rating": None,
                    "progress": {}
                })
                st.success("Learning plan generated and saved!")
                rerun()
            else:
                st.session_state["loading"] = False
                st.error("Plan generation failed or returned empty. Please try again.")
else:
    st.write("No learning plan selected. Create a new plan or select one from the sidebar.")
