import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# التحديث ليتوافق مع Vonage v4.0+
from vonage import Vonage, Auth
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

# --- منطق قراءة المفتاح الخاص من ملف ---
PRIVATE_KEY_PATH = "private.key"  # اسم الملف الذي تريده

if os.path.exists(PRIVATE_KEY_PATH):
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
    print(f"✅ Private key loaded from: {PRIVATE_KEY_PATH}")
else:
    # محاولة بديلة في حال لم يجد الملف (من المتغير البيئي)
    PRIVATE_KEY = os.getenv("VONAGE_PRIVATE_KEY", "").replace('\\n', '\n').strip()
    if not PRIVATE_KEY:
        print(f"❌ ERROR: {PRIVATE_KEY_PATH} NOT FOUND AND NO ENV KEY SET!")

# =========================
# Initialize Clients
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# إعداد المصادقة
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_client = Vonage(auth)
gemini = GeminiClient(api_key=GEMINI_API_KEY)

# مخزن الجلسات
chat_sessions = {}
call_log = []

# =========================
# AI & NCCO Logic
# =========================
def get_ai_response(session_id: str, text: str):
    try:
        if session_id not in chat_sessions:
            # تعليمات النظام ليكون الرد مناسباً للهاتف (قصير ومباشر)
            chat_sessions[session_id] = gemini.chats.create(
                model="gemini-2.0-flash",
                config={'system_instruction': 'You are a helpful phone assistant. Be concise and friendly.'}
            )
        
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
            "style": 1,
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 1.2,
                "maxDuration": 45
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
    call_uuid = data.get("uuid")
    status = data.get("status")

    # تنظيف الذاكرة عند انتهاء المكالمة
    if status in ["completed", "disconnected"]:
        if call_uuid in chat_sessions:
            del chat_sessions[call_uuid]
        return JSONResponse({"status": "ok"})

    speech_results = data.get("speech", {}).get("results", [])

    if speech_results:
        user_input = speech_results[0].get("text")
        ai_reply = get_ai_response(call_uuid, user_input)
    else:
        # إذا لم يتحدث المستخدم لفترة
        ai_reply = "I'm still here, did you have another question?"

    return JSONResponse(generate_ncco(ai_reply))

@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if text == "call" and sender:
        to_num = sender if sender.startswith("+") else f"+{sender}"
        ncco = generate_ncco("Hello! This is your AI assistant. How can I help you today?")
        
        try:
            # استخدام الطريقة الموحدة في v4
            response = vonage_client.voice.create_call({
                "to": [{"type": "phone", "number": to_num}],
                "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
                "ncco": ncco
            })
            call_log.append({"to": to_num, "status": "Initiated", "uuid": response['uuid']})
        except Exception as e:
            print(f"Call Dispatch Error: {e}")
        
    return {"status": "ok"}

if __name__ == "__main__":
    # استخدام بورت ريندر التلقائي
    uvicorn.run(app, host="0.0.0.0", port=PORT)
