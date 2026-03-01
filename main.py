import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# التحديث: استيراد Vonage فقط
from vonage import Vonage, Auth
from google import genai

# =========================
# Configuration & ENV
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
# تأكد أن المفتاح الخاص يبدأ بـ -----BEGIN PRIVATE KEY-----
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

# إعداد Vonage بدون مكتبات إضافية
client = Vonage(Auth(
    application_id=APP_ID,
    private_key=PRIVATE_KEY,
))

# إعداد Gemini (التحديث لنسخة Google GenAI الحديثة)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

chat_sessions = {}
call_log = []

# =========================
# Logic
# =========================

def get_ai_response(session_id: str, text: str):
    try:
        if session_id not in chat_sessions:
            # إضافة تعليمات النظام لجعل الردود مناسبة للمكالمات الهاتفية (قصيرة ومباشرة)
            chat_sessions[session_id] = gemini_client.chats.create(
                model="gemini-2.0-flash",
                config={'system_instruction': 'You are a concise phone assistant. Keep answers brief.'}
            )
        
        response = chat_sessions[session_id].send_message(text)
        return response.text
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "I'm sorry, I'm having trouble. Can you repeat that?"

def generate_ncco(text: str):
    return [
        {
            "action": "talk",
            "text": text,
            "language": "en-US",
            "style": 1, # تحسين جودة الصوت
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 1.0,
                "saveAudio": False
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
    
    # معالجة حالة انتهاء المكالمة لتنظيف الذاكرة
    status = data.get("status")
    call_uuid = data.get("uuid")
    
    if status in ["completed", "disconnected"]:
        if call_uuid in chat_sessions:
            del chat_sessions[call_uuid]
        return JSONResponse({"status": "cleaned"})

    speech_results = data.get("speech", {}).get("results", [])
    
    if speech_results:
        user_input = speech_results[0].get("text")
        ai_reply = get_ai_response(call_uuid, user_input)
    else:
        # إذا لم يتكلم المستخدم أو لم يفهم النظام
        return JSONResponse(generate_ncco("Are you still there? I didn't catch that."))

    return JSONResponse(generate_ncco(ai_reply))

@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if text == "call" and sender:
        to_num = sender if sender.startswith("+") else f"+{sender}"
        
        # إنشاء المكالمة باستخدام الكائن الموحد
        response = client.voice.create_call({
            'to': [{'type': 'phone', 'number': to_num}],
            'from': {'type': 'phone', 'number': VOICE_FROM_NUMBER},
            'ncco': generate_ncco("Hello! This is your AI assistant. How can I help you?")
        })
        
        call_log.append({"to": to_num, "status": "Initiated", "uuid": response['uuid']})
        
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
