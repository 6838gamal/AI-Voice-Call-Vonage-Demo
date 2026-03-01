import os
import re
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from vonage import Auth, Vonage

load_dotenv()

app = FastAPI()

# إعداد المجلدات
# تأكد من وجود مجلد templates ومجلد static في الـ GitHub الخاص بك
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# إعداد المصادقة
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
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    form_data = await request.form()
    to_number_raw = form_data.get("phone")
    
    if not to_number_raw:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Please enter a phone number."})

    # تنظيف رقم المستلم
    clean_to = re.sub(r'\D', '', to_number_raw)

    # --- الإصلاح الجذري للخطأ ---
    from_env = os.getenv("VONAGE_FROM_NUMBER")
    # إذا كان المتغير فارغاً في Render، سيستخدم هذا الرقم تلقائياً
    if not from_env or len(from_env.strip()) < 5:
        from_env = "967774440982"
    
    clean_from = re.sub(r'\D', '', from_env)
    # ---------------------------

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

    # ملاحظة: نستخدم "from" كمفتاح في القاموس
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
            "message": f"Success! Calling {clean_to} from {clean_from}..."
        })
    except Exception as e:
        # طباعة الخطأ في السجلات للتصحيح
        print(f"Detailed Error: {str(e)}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Error: {str(e)}"
        })

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    days_until, next_age = get_birthday_data(dtmf_digits)
    
    if days_until is not None:
        text = f"Your birthday is in {days_until} days, and you will be {next_age} years old! Goodbye."
    else:
        text = "Sorry, the date format was not recognized. Goodbye."
        
    return [{"action": "talk", "text": text}]

@app.post("/events")
async def events(request: Request):
    return Response(status_code=204)

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
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
