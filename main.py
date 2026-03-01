import os
import re
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد المكتبة الأساسية فقط لضمان أقصى درجات التوافق
from vonage import Auth, Vonage

load_dotenv()

app = FastAPI()

# إعداد المجلدات - تأكد من وجود مجلد 'templates' ومجلد 'static' في مشروعك على GitHub
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# إعداد المصادقة (دعم القراءة من متغير بيئة نصي أو ملف)
application_id = os.getenv("VONAGE_APPLICATION_ID")
private_key = os.getenv("VONAGE_PRIVATE_KEY")

if not private_key:
    key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            private_key = f.read()

auth = Auth(application_id=application_id, private_key=private_key)
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """عرض صفحة طلب المكالمة"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    """بدء المكالمة الصادرة"""
    form_data = await request.form()
    to_number_raw = form_data.get("phone")
    
    if not to_number_raw:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Please enter a destination number."})

    # 1. تنظيف رقم المستلم (To)
    clean_to = re.sub(r'\D', '', to_number_raw)

    # 2. تحديد رقم المرسل (From) 
    # الأولوية لمتغير البيئة، وإذا لم يوجد نستخدم الرقم الافتراضي الذي طلبته
    from_env = os.getenv("VONAGE_FROM_NUMBER")
    if not from_env or from_env.strip() == "":
        from_env = "967774440982"
    
    clean_from = re.sub(r'\D', '', from_env)

    # 3. بناء الـ NCCO كـ List of Dictionaries (أكثر استقراراً)
    ncco = [
        {
            "action": "talk",
            "text": "Hello! Please enter your birth date as 8 digits. For example, zero one, zero one, nineteen ninety.",
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

    # 4. تجهيز حمولة الطلب (Payload)
    call_payload = {
        "to": [{"type": "phone", "number": clean_to}],
        "from": {"type": "phone", "number": clean_from},
        "ncco": ncco,
        "machine_detection": "hangup"
    }

    try:
        # إرسال طلب المكالمة
        response = vonage_client.voice.create_call(call_payload)
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Success! Call initiated from {clean_from} to {clean_to}."
        })
    except Exception as e:
        print(f"Deployment Error: {e}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Error: {str(e)}"
        })

@app.post("/birthday")
async def birthday(request: Request):
    """معالجة رقم الـ DTMF الذي أدخله المستخدم"""
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    
    days_until, next_age = get_birthday_data(dtmf_digits)

    if days_until is None:
        text = "Sorry, the date format is incorrect. Goodbye."
    else:
        text = f"Your birthday is in {days_until} days, and you will be {next_age} years old! Goodbye."

    return [{"action": "talk", "text": text}]

@app.post("/events")
async def events(request: Request):
    """مسار لمراقبة أحداث المكالمة (ضروري لـ Vonage)"""
    return Response(status_code=204)

def get_birthday_data(dtmf_digits: str):
    """حساب فرق الأيام والعمر القادم"""
    if len(dtmf_digits) != 8:
        return None, None
    try:
        # التنسيق المتوقع MMDDYYYY
        bday = datetime.strptime(dtmf_digits, "%m%d%Y").date()
        today = date.today()
        next_bday = bday.replace(year=today.year)
        if next_bday < today:
            next_bday = next_bday.replace(year=today.year + 1)
        return (next_bday - today).days, next_bday.year - bday.year
    except:
        return None, None

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
