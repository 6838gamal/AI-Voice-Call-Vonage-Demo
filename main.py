import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest
from google.genai import Client as GeminiClient

# =========================
# ENV & CONFIG
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
RENDER_URL = os.getenv("RENDER_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# =========================
# APP SETUP
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")
# تأكد من وجود مجلد static و templates في مشروعك
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# =========================
# CLIENTS
# =========================
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
vonage_client = Vonage(auth)
gemini = GeminiClient(api_key=GEMINI_API_KEY)

# لتخزين جلسات الدردشة (الذاكرة)
chat_sessions = {}
call_log = []

# =========================
# AI LOGIC
# =========================
def get_ai_response(user_id: str, text: str):
    try:
        # إنشاء جلسة جديدة إذا لم تكن موجودة لهذا المستخدم/المكالمة
        if user_id not in chat_sessions:
            chat_sessions[user_id] = gemini.chats.create(model="gemini-2.0-flash")
        
        response = chat_sessions[user_id].send_message(text)
        return response.text
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "I'm sorry, I'm having trouble connecting. Could you repeat that?"

# =========================
# CALL CONTROL (NCCO)
# =========================
def generate_ncco(text_to_speak: str):
    return [
        {
            "action": "talk",
            "text": text_to_speak,
            "language": "en-US",
            "bargeIn": True  # يسمح للمستخدم بمقاطعة الرد الآلي
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
# ROUTES
# =========================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/inbound")
async def inbound_whatsapp(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").lower().strip()

    if not sender: return {"ok": False}

    if text == "call":
        to_number = sender if sender.startswith("+") else f"+{sender}"
        # بدء المكالمة
        ncco = generate_ncco("Hello! I am your Gemini assistant. How can I help you today?")
        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_number}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=ncco
        )
        vonage_client.voice.create_call(call_request)
        call_log.append({"to": to_number, "status": "Initiated"})
    else:
        # رد واتساب عادي
        reply = get_ai_response(sender, text)
        print(f"WhatsApp Reply to {sender}: {reply}")
        # هنا يمكنك إضافة كود vonage_client.messages.send_message لإرسال الرد
    
    return {"ok": True}

@app.post("/event")
async def voice_event(req: Request):
    data = await req.json()
    
    # استخراج النص المنطوق من المستخدم
    speech_results = data.get("speech", {}).get("results", [])
    call_uuid = data.get("uuid") # معرف فريد للمكالمة

    if speech_results:
        user_text = speech_results[0].get("text")
        print(f"User said: {user_text}")
        ai_text = get_ai_response(call_uuid, user_text)
    else:
        ai_text = "I didn't catch that. Could you say it again?"

    return JSONResponse(generate_ncco(ai_text))

@app.get("/status")
async def status():
    return {"active_sessions": len(chat_sessions), "total_calls": len(call_log)}

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
