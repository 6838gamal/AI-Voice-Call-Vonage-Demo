import os
import uvicorn
import re
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد الأدوات اللازمة من Vonage v4
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest
from google.genai import Client as GeminiClient

# =========================
# Configuration & ENV
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
RENDER_URL = os.getenv("RENDER_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# قراءة المفتاح الخاص من ملف
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
gemini = GeminiClient(api_key=GEMINI_API_KEY)

chat_sessions = {}
call_log = []

# =========================
# Helpers
# =========================

def clean_num(number: str):
    return re.sub(r'\D', '', str(number))

def get_ai_response(session_id: str, text: str):
    try:
        if session_id not in chat_sessions:
            chat_sessions[session_id] = gemini.chats.create(
                model="gemini-2.0-flash",
                config={'system_instruction': 'You are a concise AI phone assistant.'}
            )
        response = chat_sessions[session_id].send_message(text)
        return response.text
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "Sorry, I am having trouble. Can you repeat?"

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

@app.post("/event")
async def voice_event(req: Request):
    data = await req.json()
    call_uuid = data.get("uuid")
    status = data.get("status")

    if status in ["completed", "disconnected"]:
        chat_sessions.pop(call_uuid, None)
        return JSONResponse({"status": "ok"})

    speech_results = data.get("speech", {}).get("results", [])
    ai_reply = get_ai_response(call_uuid, speech_results[0].get("text")) if speech_results else "Are you there?"
    
    return JSONResponse(generate_ncco(ai_reply))

@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if text == "call" and sender:
        to_num = clean_num(sender)
        from_num = clean_num(VOICE_FROM_NUMBER)
        
        # الحل النهائي: استخدام CreateCallRequest بشكل رسمي
        try:
            call_params = CreateCallRequest(
                to=[{"type": "phone", "number": to_num}],
                from_={"type": "phone", "number": from_num},
                ncco=generate_ncco("Hello! This is your AI assistant.")
            )
            
            # تمرير الكائن كـ params كما تطلب المكتبة في اللوج
            vonage_client.voice.create_call(call_params)
            
            call_log.append({"to": to_num, "status": "Initiated"})
            print(f"✅ Success: Calling {to_num}")
        except Exception as e:
            print(f"❌ Final Error: {e}")
        
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
