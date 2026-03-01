import os
import re
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# استيراد المكتبة الأساسية
from vonage import Auth, Vonage

load_dotenv()

app = FastAPI()

# إعداد المجلدات مع فحص وجودها لتجنب المشاكل
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_vonage_client():
    """وظيفة للتحقق من المفاتيح وتهيئة العميل"""
    app_id = os.getenv("VONAGE_APPLICATION_ID")
    priv_key = os.getenv("VONAGE_PRIVATE_KEY")
    
    # محاولة قراءة المفتاح من ملف إذا لم يوجد في المتغيرات
    if not priv_key:
        key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH", "private.key")
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                priv_key = f.read()
    
    if not app_id or not priv_key:
        return None
    
    try:
        auth = Auth(application_id=app_id, private_key=priv_key)
        return Vonage(auth)
    except Exception as e:
        print(f"Auth Initialization Error: {e}")
        return None

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    client = get_vonage_client()
    if not client:
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": "❌ Configuration Error: Missing Application ID or Private Key in Render settings!"
        })

    form_data = await request.form()
    to_number_raw = form_data.get("phone")
    if not to_number_raw:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Please enter a phone number."})

    # تنظيف الأرقام
    clean_to = re.sub(r'\D', '', to_number_raw)
    from_number = re.sub(r'\D', '', os.getenv("VONAGE_FROM_NUMBER", "967774440982"))

    ncco = [
        {
            "action": "talk",
            "text": "Hello! This is your AI birthday assistant. Please enter your birth date as 8 digits, then press hash.",
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

    # القاموس النهائي (from بدون شرطة سفلية)
    payload = {
        "to": [{"type": "phone", "number": clean_to}],
        "from": {"type": "phone", "number": from_number},
        "ncco": ncco
    }

    try:
        response = client.voice.create_call(payload)
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"✅ Success! Call initiated. UUID: {response.get('uuid')}"
        })
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"❌ Vonage API Error: {str(e)}"
        })

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    days_until, next_age = get_birthday_data(dtmf_digits)
    
    if days_until is not None:
        text = f"Your birthday is in {days_until} days and you will be {next_age}! Goodbye."
    else:
        text = "Sorry, I couldn't understand the date. Goodbye."
    
    return [{"action": "talk", "text": text}]

@app.post("/events")
async def events():
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
