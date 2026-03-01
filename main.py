import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# التحديث ليتوافق مع Vonage v4.0+
from vonage import Vonage
from vonage_utils import Auth
from vonage_voice import CreateCallRequest
from google.genai import Client as GeminiClient

# =========================
# Configuration & ENV
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
# نصيحة: ضع محتوى ملف الـ .key في متغير بيئي اسمه VONAGE_PRIVATE_KEY
PRIVATE_KEY = os.getenv("VONAGE_PRIVATE_KEY", "").replace('\\n', '\n') 
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
RENDER_URL = os.getenv("RENDER_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# =========================
# Initialize Clients
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# إعداد المصادقة باستخدام النص مباشرة أو المسار
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_client = Vonage(auth)
gemini = GeminiClient(api_key=GEMINI_API_KEY)

# مخزن الجلسات (سياق المحادثة)
chat_sessions = {}
call_log = []

# =========================
# AI & NCCO Logic
# =========================
def get_ai_response(session_id: str, text: str):
    try:
        if session_id not in chat_sessions:
            chat_sessions[session_id] = gemini.chats.create(model="gemini-2.0-flash")
        
        response = chat_sessions[session_id].send_message(text)
        return response.text
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "I'm sorry, I'm having trouble thinking. Can you repeat that?"

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
                "endOnSilence": 1.5,
                "maxDuration": 60
            },
            "eventUrl": [f"{RENDER_URL}/event"],
            "eventMethod": "POST"
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
    speech_results = data.get("speech", {}).get("results", [])
    call_uuid = data.get("uuid")

    if speech_results:
        user_input = speech_results[0].get("text")
        ai_reply = get_ai_response(call_uuid, user_input)
    else:
        ai_reply = "I didn't hear anything. Are you still there?"

    return JSONResponse(generate_ncco(ai_reply))

@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if text == "call" and sender:
        to_num = sender if sender.startswith("+") else f"+{sender}"
        ncco = generate_ncco("Hello! This is your AI assistant. How can I help you?")
        
        call_req = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=ncco
        )
        vonage_client.voice.create_call(call_req)
        call_log.append({"to": to_num, "status": "Connected"})
        
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
