import os
import re
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد مكتبة Vonage الأساسية
from vonage import Auth, Vonage

load_dotenv()

app = FastAPI()

# إعداد المجلدات - تأكد من وجود مجلد 'templates' و 'static' في مشروعك
# إذا لم يكن لديك ملف CSS، سيتجاهل التطبيق الخطأ ويستمر
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    print("Warning: 'static' directory not found. CSS might not load.")

templates = Jinja2Templates(directory="templates")

# إعداد المصادقة
application_id = os.getenv("VONAGE_APPLICATION_ID")
private_key = os.getenv("VONAGE_PRIVATE_KEY")

# محاولة قراءة المفتاح من الملف إذا لم يكن في متغيرات البيئة
if not private_key:
    key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            private_key = f.read()

auth = Auth(application_id=application_id, private_key=private_key)
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    form_data = await request.form()
    to_number_raw = form_data.get("phone")
    
    if not to_number_raw:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Error: Phone number is required!"})

    # 1. تنظيف رقم المستلم (To)
    clean_to = re.sub(r'\D', '', to_number_raw)

    # 2. تحديد رقم المرسل (From) - الحل الجذري للخطأ السابق
    from_env = os.getenv("VONAGE_FROM_NUMBER")
    if not from_env or from_env.strip() == "":
        from_env = "967774440982" # الرقم الافتراضي الخاص بك
    
    clean_from = re.sub(r'\D', '', from_env)

    # 3. بناء الـ NCCO (التعليمات الصوتية)
    ncco = [
        {
            "action": "talk",
            "text": "Hello! Welcome to your AI birthday assistant. Please enter your birth date as eight digits. For example, zero one, zero five, nineteen ninety five, then press hash.",
            "language": "en-US"
        },
        {
            "action": "input",
            "type": ["dtmf"],
            "dtmf": {"timeOut": 10, "maxDigits": 8, "submitOnHash": True},
            "eventUrl": [f"{os.getenv('BASE_URL')}/birthday"],
            "eventMethod": "POST"
        }
    ]

    # 4. تجهيز الطلب
    call_payload = {
        "to": [{"type": "phone", "number": clean_to}],
        "from": {"type": "phone", "number": clean_from},
        "ncco": ncco,
        "machine_detection": "hangup"
    }

    try:
        # إرسال طلب المكالمة
        response = vonage_client.voice.create_call(call_payload)
        
        # استخراج المعرف الفريد للمكالمة
        call_uuid = response.get('uuid', 'Unknown')
        
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Success! Call ID: {call_uuid}. If phone doesn't ring, check 'Verified Numbers' in Vonage Dashboard."
        })
    except Exception as e:
        # التقاط الخطأ الحقيقي من Vonage (مثل Invalid Number أو Destination Not Permitted)
        error_detail = str(e)
        print(f"Vonage API Error: {error_detail}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Vonage Error: {error_detail}. Make sure your number is VERIFIED in Vonage settings."
        })

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    
    days_until, next_age = get_birthday_data(dtmf_digits)

    if days_until is None:
        text = "I'm sorry, I couldn't process that date. Have a great day, goodbye!"
    else:
        text = f"Your birthday is in {days_until} days! You will be {next_age} years old. Happy birthday in advance! Goodbye."

    return [{"action": "talk", "text": text}]

@app.post("/events")
async def events(request: Request):
    """استقبال تحديثات الحالة من فوناج"""
    return Response(status_code=204)

def get_birthday_data(dtmf_digits: str):
    """منطق حساب الأيام المتبقية للعيد ميلاد"""
    if len(dtmf_digits) != 8:
        return None, None
    try:
        # التنسيق: MMDDYYYY
        bday = datetime.strptime(dtmf_digits, "%m%d%Y").date()
        today = date.today()
        next_bday = bday.replace(year=today.year)
        if next_bday < today:
            next_bday = next_bday.replace(year=today.year + 1)
        
        days_until = (next_bday - today).days
        next_age = next_bday.year - bday.year
        return days_until, next_age
    except:
        return None, None

if __name__ == "__main__":
    import uvicorn
    # Render يستخدم المتغير PORT
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
