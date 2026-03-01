import os
import re
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد المكتبات الأساسية
from vonage import Auth, Vonage

load_dotenv()

app = FastAPI()

# إعداد المجلدات (تأكد من وجود مجلدي static و templates في مشروعك)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# إعداد المصادقة - قراءة المفتاح من متغير بيئة نصي (أضمن لـ Render)
private_key = os.getenv("VONAGE_PRIVATE_KEY")
application_id = os.getenv("VONAGE_APPLICATION_ID")

# إذا لم يجد نص المفتاح، يحاول القراءة من الملف (للتجربة المحلية)
if not private_key:
    key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            private_key = f.read()

auth = Auth(application_id=application_id, private_key=private_key)
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """عرض الصفحة الرئيسية"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    """بدء عملية الاتصال"""
    form_data = await request.form()
    raw_number = form_data.get("phone")
    
    if not raw_number:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Please enter a phone number."})

    # تنظيف الرقم: إبقاء الأرقام فقط (يزيل +، المسافات، الأقواس)
    clean_to = re.sub(r'\D', '', raw_number)
    clean_from = re.sub(r'\D', '', os.getenv("VONAGE_FROM_NUMBER", "1234567890"))

    # بناء الـ NCCO كقواميس (أكثر استقراراً مع تحديثات المكتبة)
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

    # طلب المكالمة الصادرة
    call_payload = {
        "to": [{"type": "phone", "number": clean_to}],
        "from": {"type": "phone", "number": clean_from},
        "ncco": ncco,
        "machine_detection": "hangup"
    }

    try:
        response = vonage_client.voice.create_call(call_payload)
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Success! Call initiated to {clean_to}. Check your phone!"
        })
    except Exception as e:
        print(f"Error calling: {e}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Connection Error: {str(e)}"
        })

@app.post("/birthday")
async def birthday(request: Request):
    """معالجة مدخلات المستخدم أثناء المكالمة"""
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    
    days_until, next_age = get_birthday_data(dtmf_digits)

    if days_until is None:
        text = "Sorry, I couldn't understand that date. Goodbye."
    else:
        text = f"Your birthday is in {days_until} days, and you will be {next_age} years old! Thank you for using our AI service. Goodbye."

    return [{"action": "talk", "text": text}]

@app.post("/events")
async def events(request: Request):
    """استقبال تحديثات حالة المكالمة"""
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
    except Exception:
        return None, None

if __name__ == "__main__":
    import uvicorn
    # Render يمرر المنفذ عبر متغير PORT
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
