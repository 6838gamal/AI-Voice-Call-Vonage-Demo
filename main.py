import os
import re
import json
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

# =========================
# Configuration & ENV
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
RENDER_URL = os.getenv("RENDER_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

PRIVATE_KEY_PATH = "private.key"
if os.path.exists(PRIVATE_KEY_PATH):
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
else:
    PRIVATE_KEY = os.getenv("VONAGE_PRIVATE_KEY", "").replace('\\n', '\n').strip()

# =========================
# Initialize Clients
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_client = Vonage(auth)

chat_sessions = {}
call_log = []

# =========================
# Helpers
# =========================
def clean_num(number: str):
    return re.sub(r'\D', '', str(number))

def ask_gemini(text: str, session_id: str):
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    chat_history = chat_sessions[session_id]
    full_prompt = "\n".join(chat_history + [f"You: {text}"])
    data = {"contents":[{"parts":[{"text": full_prompt}]}]}
    GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    try:
        r = requests.post(GEMINI_URL, headers={"Content-Type":"application/json"}, data=json.dumps(data))
        res = r.json()
        reply = res["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        reply = f"Error: {e}"
    
    chat_history.append(f"You: {text}")
    chat_history.append(f"Gemini: {reply}")
    chat_sessions[session_id] = chat_history
    return reply

def generate_ncco(text: str):
    return [
        {
            "action": "talk",
            "text": text,
            "language": "en-US",
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 1.2
            },
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]

# =========================
# Routes
# =========================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/call")
async def call(request: Request, phone: str = Form(...)):
    to_num = clean_num(phone)
    from_num = clean_num(VOICE_FROM_NUMBER)
    
    try:
        call_params = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": from_num},
            ncco=generate_ncco("Hello! This is your AI assistant.")
        )
        vonage_client.voice.create_call(call_params)
        call_log.append({"to": to_num, "status": "Initiated"})
        print(f"✅ Calling {to_num}")
    except Exception as e:
        call_log.append({"to": to_num, "status": f"Error: {e}"})
        print(f"❌ Error calling {to_num}: {e}")
    
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/event")
async def voice_event(req: Request):
    data = await req.json()
    call_uuid = data.get("uuid")
    status = data.get("status")

    if status in ["completed", "disconnected"]:
        chat_sessions.pop(call_uuid, None)
        return JSONResponse({"status": "ok"})

    speech_results = data.get("speech", {}).get("results", [])
    ai_reply = ask_gemini(speech_results[0].get("text") if speech_results else "Are you there?", call_uuid)
    
    return JSONResponse(generate_ncco(ai_reply))

# =========================
# Main
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
