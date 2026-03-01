import os
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# سنكتفي باستيراد الأساسيات لتجنب تضارب الكلاسات
from vonage import Auth, Vonage
from vonage_voice import CreateCallRequest, Talk, Input, Dtmf

load_dotenv()

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

auth = Auth(application_id=os.getenv("VONAGE_APPLICATION_ID"), private_key=os.getenv("VONAGE_PRIVATE_KEY_PATH"))
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    form_data = await request.form()
    raw_number = form_data.get("phone") or os.getenv("TO_NUMBER")
    
    # تنظيف الرقم (أرقام فقط)
    clean_number = "".join(filter(str.isdigit, raw_number))
    from_number = "".join(filter(str.isdigit, os.getenv("VONAGE_FROM_NUMBER", "")))

    # إعداد الـ NCCO كـ قواميس مباشرة
    ncco = [
        {
            "action": "talk",
            "text": "Hello! Please enter your birthday as two-digit month, two-digit day, and four-digit year, then press pound.",
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

    # بناء الطلب باستخدام القواميس لتجنب أخطاء Validation الخاصة بالكلاسات
    call_payload = {
        "to": [{"type": "phone", "number": clean_number}],
        "from": {"type": "phone", "number": from_number},
        "ncco": ncco,
        "machine_detection": "hangup"
    }

    try:
        # استخدام العميل لإرسال البيانات الخام
        response = vonage_client.voice.create_call(call_payload)
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Success! Calling {clean_number}..."
        })
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Error: {str(e)}"
        })

# باقي الدوال (birthday, get_birthday_data) تبقى كما هي دون تغيير
@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    days_until, next_age = get_birthday_data(dtmf_digits)
    text = f"Your birthday is in {days_until} days and you will be {next_age}!" if days_until else "Invalid format."
    return [{"action": "talk", "text": text}]

def get_birthday_data(dtmf_digits: str):
    if len(dtmf_digits) != 8: return None, None
    try:
        bday = datetime.strptime(dtmf_digits, "%m%d%Y").date()
        today = date.today()
        next_bday = bday.replace(year=today.year)
        if next_bday < today: next_bday = next_bday.replace(year=today.year + 1)
        return (next_bday - today).days, next_bday.year - bday.year
    except: return None, None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
