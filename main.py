import os
import re
import logging
import requests
import uvicorn
from fastapi import FastAPI, Request, Form, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# استيرادات Vonage الحديثة
from vonage import Vonage, Auth, HttpClientOptions
from vonage_voice import CreateCallRequest
from vonage_messages.models import WhatsappText

# ==================================================
# 1. الإعدادات واللوج
# ==================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

# الإعدادات من ملف البيئة أو Render
APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# رقم الساند بوكس (متغير من الإعدادات)
SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER", "14157386102")

# رقمك الشخصي الثابت (مباشرة لضمان عدم حدوث أخطاء NoneType)
MY_FIXED_NUMBER = "967774440982" 

# ==================================================
# 2. تهيئة FastAPI والملفات الثابتة
# ==================================================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# سطر الـ Static لملفات CSS/JS
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================================================
# 3. تهيئة عملاء Vonage
# ==================================================
try:
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
    
    auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
    
    # عميل الرسائل (Sandbox)
    msg_options = HttpClientOptions(api_host="messages-sandbox.nexmo.com")
    vonage_msg_client = Vonage(auth=auth, http_client_options=msg_options)
    
    # عميل الصوت (الرسمي)
    vonage_voice_client = Vonage(auth=auth)
    
    logger.info("✅ تم تهيئة نظام Vonage بنجاح")
except Exception as e:
    logger.error(f"❌ خطأ في تحميل مفاتيح Vonage: {e}")

# مخزن مؤقت لحالات المكالمات (للعرض في الويب)
call_log = {}

# ==================================================
# 4. وظائف الذكاء الاصطناعي والتقارير
# ==================================================

def generate_ai_report(status_data: dict) -> str:
    """استخدام موديل Gemini 2.5 Flash لصياغة التقرير الذكي"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    أنت مساعد ذكي. قم بتحليل بيانات المكالمة التالية وصغ تقرير واتساب عربي مختصر واحترافي:
    - الحالة: {status_data.get('status')}
    - الرقم المطلوب: {status_data.get('to')}
    - المدة: {status_data.get('duration', 0)} ثانية
    - السبب: {status_data.get('detail', 'لا يوجد')}
    استخدم الرموز التعبيرية واجعل النص سهل القراءة.
    """
    
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=12)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"❌ Gemini Error: {e}")
    
    return f"📢 تحديث مكالمة: {status_data.get('status')} للرقم {status_data.get('to')}"

def send_whatsapp_fixed(message_text: str):
    """إرسال من رقم الساند بوكس المتغير إلى رقمك الثابت مباشرة"""
    try:
        msg = WhatsappText(
            from_=SANDBOX_NUMBER, 
            to=MY_FIXED_NUMBER, 
            text=message_text
        )
        vonage_msg_client.messages.send(msg)
        logger.info(f"📤 تم إرسال التقرير للرقم {MY_FIXED_NUMBER}")
    except Exception as e:
        logger.error(f"❌ فشل إرسال الواتساب: {e}")

# ==================================================
# 5. المسارات (Routes)
# ==================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/call")
async def make_call(background_tasks: BackgroundTasks, phone: str = Form(...)):
    # تنظيف الرقم من أي رموز غير رقمية
    to_num = re.sub(r"\D", "", phone)
    
    try:
        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=[{"action": "talk", "text": "This is a smart notification call."}]
        )
        response = vonage_voice_client.voice.create_call(call_request)
        call_uuid = response.uuid
        
        # تسجيل الحالة مبدئياً
        call_log[call_uuid] = {"to": to_num, "status": "initiated"}
        
        # إشعار البدء الفوري
        background_tasks.add_task(send_whatsapp_fixed, f"📞 بدأت الآن محاولة اتصال للرقم: {to_num}")
        
        return JSONResponse({"status": "success", "uuid": call_uuid})
    except Exception as e:
        logger.error(f"❌ فشل إنشاء المكالمة: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/event")
async def voice_event(request: Request, background_tasks: BackgroundTasks):
    """استلام أحداث المكالمة ومعالجتها بذكاء عبر Gemini 2.5"""
    try:
        data = await request.json()
        status = data.get("status")
        uuid = data.get("uuid")
        
        if uuid:
            call_log[uuid] = {"to": data.get("to"), "status": status}
            
            # إرسال تقرير Gemini فقط في الحالات النهائية
            final_statuses = ["completed", "failed", "busy", "no-answer", "rejected"]
            if status in final_statuses:
                ai_report = generate_ai_report(data)
                background_tasks.add_task(send_whatsapp_fixed, ai_report)
                
        return Response(status_code=200)
    except Exception:
        return Response(status_code=200)

# ==================================================
# 6. تشغيل السيرفر
# ==================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 تشغيل النظام الذكي (Gemini 2.5 Flash) على المنفذ {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
