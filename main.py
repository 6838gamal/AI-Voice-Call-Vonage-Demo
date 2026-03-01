import os
import uvicorn
import re
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

# --- منطق قراءة المفتاح الخاص من ملف (كما طلبت) ---
PRIVATE_KEY_PATH = "private.key"

if os.path.exists(PRIVATE_KEY_PATH):
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
    print(f"✅ Private key loaded from: {PRIVATE_KEY_PATH}")
else:
    # خطة احتياطية في حال لم يجد الملف (من المتغير البيئي)
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

# إعداد المصادقة باستخدام مكتبة Vonage v4
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_client = Vonage(auth)
gemini = GeminiClient(api_key=GEMINI_API_KEY)

# مخزن الجلسات وسجل المكالمات
chat_sessions = {}
call_log = []

# =========================
# Helper Functions
# =========================

def clean_phone_number(number: str):
    """تنظيف الرقم من أي رموز مثل + ليتوافق مع Regex فوناج v4"""
    if not number:
        return ""
    return re.sub(r'\D', '', str(number))

def get_ai_response(session_id: str, text: str):
    try:
        if session_id not in chat_sessions:
            chat_sessions[session_id] = gemini.chats.create(
                model="gemini-2.0-flash",
                config={'system_instruction': 'You are a helpful and concise phone assistant. Speak briefly.'}
            )
        
        response = chat_sessions[session_id].send_message(text)
        return response.text
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "I'm sorry, I'm having trouble thinking. Can you repeat that?"

def generate_ncco(text: str):
    """إنشاء كائن التحكم في المكالمة (NCCO)"""
    return [
        {
            "action": "talk",
            "text": text,
            "language": "en-US",
            "style": 0,
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 1.2,
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
    call_uuid = data.get("uuid")
    status = data.get("status")

    # تنظيف الذاكرة عند انتهاء المكالمة
    if status in ["completed", "disconnected"]:
        if call_uuid in chat_sessions:
            del chat_sessions[call_uuid]
        return JSONResponse({"status": "cleared"})

    speech_results = data.get("speech", {}).get("results", [])

    if speech_results:
        user_input = speech_results[0].get("text")
        ai_reply = get_ai_response(call_uuid, user_input)
    else:
        ai_reply = "I didn't hear anything. Are you still there?"

    return JSONResponse(generate_ncco(ai_reply))

@app.post("/inbound")
async def inbound(req: Request):
    """تحويل رسالة SMS تحتوي على كلمة call إلى مكالمة هاتفية"""
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if text == "call" and sender:
        target_number = clean_phone_number(sender)
        from_number = clean_phone_number(VOICE_FROM_NUMBER)
        
        ncco_payload = generate_ncco("Hello! This is your AI assistant. How can I help you today?")
        
        try:
            # التعديل الحاسم: استخدام from_ بالشرطة السفلية لـ Pydantic Validation
            vonage_client.voice.create_call(
                to=[{"type": "phone", "number": target_number}],
                from_={"type": "phone", "number": from_number},
                ncco=ncco_payload
            )
            
            call_log.append({"to": target_number, "status": "Connected"})
            print(f"✅ Success! Initiated call to {target_number}")
        except Exception as e:
            # طباعة الخطأ كاملاً للتشخيص
            print(f"❌ Call Dispatch Error: {e}")
        
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
