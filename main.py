import os
import re
import json
import logging
import requests
import uvicorn
from fastapi import FastAPI, Request, Form, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد مكتبات Vonage
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest
from vonage_messages.models import WhatsappText

# ==================================================
# 1. إعدادات اللوج والبيئة
# ==================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
WHATSAPP_FROM = os.getenv("VONAGE_SANDBOX_NUMBER")
WHATSAPP_TO = os.getenv("REPORT_TO_NUMBER") 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==================================================
# 2. تهيئة العملاء
# ==================================================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

try:
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
    auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
    vonage_client = Vonage(auth)
    logger.info("✅ تم تهيئة نظام Vonage")
except Exception as e:
    logger.error(f"❌ خطأ في الإعدادات: {e}")

call_log = {}

# ==================================================
# 3. دالة تقارير Gemini 2.5 Flash
# ==================================================

def generate_ai_report(status_data: dict) -> str:
    """استخدام موديل Gemini 2.5 Flash لصياغة التقرير"""
    # تم تثبيت الموديل على الإصدار 2.5 فلاش كما طلبت
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    بصفتك مساعداً ذكياً، حلل حالة المكالمة التالية واكتب تقريراً مختصراً وودوداً باللغة العربية لإرساله عبر الواتساب:
    - الحالة النهائية: {status_data.get('status')}
    - رقم المستلم: {status_data.get('to')}
    - المدة المسجلة: {status_data.get('duration', 0)} ثانية
    - تفاصيل إضافية: {status_data.get('reason', 'لا يوجد')}
    استخدم الرموز التعبيرية المناسبة.
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            logger.error(f"❌ Gemini Error: {res.json()}")
    except Exception as e:
        logger.error(f"❌ Connection Error with Gemini: {e}")
    
    return f"📢 تحديث: المكالمة للرقم {status_data.get('to')} حالتها الآن {status_data.get('status')}."

def send_whatsapp_report(message_text: str):
    """إرسال التقرير عبر الواتساب"""
    try:
        msg = WhatsappText(
            from_=WHATSAPP_FROM.replace("+", "").strip(),
            to=WHATSAPP_TO.replace("+", "").strip(),
            text=message_text
        )
        vonage_client.messages.send(msg)
        logger.info("✅ تم إرسال التقرير الذكي بنجاح")
    except Exception as e:
        logger.error(f"❌ فشل إرسال الواتساب: {e}")

# ==================================================
# 4. المسارات (Routes)
# ==================================================

@app.post("/call")
async def make_call(background_tasks: BackgroundTasks, phone: str = Form(...)):
    to_num = re.sub(r"\D", "", phone)
    try:
        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=[{"action": "talk", "text": "This is an automated call from your smart system."}]
        )
        response = vonage_client.voice.create_call(call_request)
        call_log[response.uuid] = {"to": to_num, "status": "initiated"}
        
        # إشعار مبدئي
        background_tasks.add_task(send_whatsapp_report, f"📞 جاري الاتصال الآن بالرقم {to_num}...")
        return JSONResponse({"status": "success", "uuid": response.uuid})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/event")
async def voice_event(request: Request, background_tasks: BackgroundTasks):
    """معالجة أحداث المكالمة وإرسال تقرير Gemini عند الانتهاء"""
    data = await request.json()
    status = data.get("status")
    uuid = data.get("uuid")
    
    if uuid:
        call_log[uuid] = {"to": data.get("to"), "status": status}
        
        # عند وصول المكالمة لحالة نهائية
        if status in ["completed", "failed", "busy", "no-answer", "rejected"]:
            ai_report = generate_ai_report(data)
            background_tasks.add_task(send_whatsapp_report, ai_report)
            
    return Response(status_code=200)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

# ==================================================
# 5. دالة الماين (Main)
# ==================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 تشغيل النظام (Gemini 2.5 Flash) على المنفذ {port}")
    # تأكد أن اسم هذا الملف هو main.py لتشغيله بهذا السطر
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
