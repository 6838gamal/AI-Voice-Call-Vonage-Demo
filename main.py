import os
import re
import logging
import requests
import uvicorn
from fastapi import FastAPI, Request, Form, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيرادات Vonage
from vonage import Vonage, Auth, HttpClientOptions
from vonage_voice import CreateCallRequest
from vonage_messages.models import WhatsappText

# --- الإعدادات ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER", "14157386102")
REPORT_TO_NUMBER = os.getenv("REPORT_TO_NUMBER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- تهيئة عملاء Vonage بشكل منفصل ---

# 1. عميل الرسائل (يستخدم Sandbox API)
msg_options = HttpClientOptions(api_host="messages-sandbox.nexmo.com")
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
vonage_msg_client = Vonage(auth=auth, http_client_options=msg_options)

# 2. عميل الصوت (يستخدم السيرفر الافتراضي الرسمي)
vonage_voice_client = Vonage(auth=auth) 

call_log = {}

# --- الوظائف الذكية ---

def generate_ai_report(status_data: dict) -> str:
    """صياغة تقرير احترافي باستخدام Gemini 2.5 Flash"""
    # ملاحظة: تأكد من صحة إصدار الموديل في رابط الـ API الخاص بك
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"حلل حالة مكالمة Vonage التالية واكتب تقرير واتساب عربي مختصر وذكي: {status_data}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
    return f"📢 تحديث مكالمة: {status_data.get('status')} للرقم {status_data.get('to')}"

def send_whatsapp(to_number: str, message_text: str):
    """إرسال عبر Sandbox"""
    clean_to = to_number.replace("+", "").strip()
    clean_from = SANDBOX_NUMBER.replace("+", "").strip()
    try:
        msg = WhatsappText(from_=clean_from, to=clean_to, text=message_text)
        # نستخدم عميل الرسائل المخصص للـ Sandbox
        vonage_msg_client.messages.send(msg)
        logger.info(f"✅ WhatsApp Sent to {clean_to}")
    except Exception as e:
        logger.error(f"❌ Vonage Message Error: {e}")

# --- المسارات ---

@app.post("/call")
async def make_call(background_tasks: BackgroundTasks, phone: str = Form(...)):
    to_num = re.sub(r"\D", "", phone)
    try:
        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=[{"action": "talk", "text": "Testing smart notification system"}]
        )
        # نستخدم عميل الصوت الرسمي
        response = vonage_voice_client.voice.create_call(call_request)
        call_log[response.uuid] = {"to": to_num, "status": "initiated"}
        
        background_tasks.add_task(send_whatsapp, REPORT_TO_NUMBER, f"📞 جاري طلب الرقم {to_num}")
        return {"status": "success", "uuid": response.uuid}
    except Exception as e:
        logger.error(f"❌ Voice Error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/event")
async def voice_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    status = data.get("status")
    if status in ["completed", "failed", "busy", "no-answer"]:
        report = generate_ai_report(data)
        background_tasks.add_task(send_whatsapp, REPORT_TO_NUMBER, report)
    return Response(status_code=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
