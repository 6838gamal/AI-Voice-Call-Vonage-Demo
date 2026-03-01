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

# محاولة تحميل المجلدات
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass
templates = Jinja2Templates(directory="templates")

# إعداد المصادقة
auth = Auth(
    application_id=os.getenv("VONAGE_APPLICATION_ID"), 
    private_key=os.getenv("VONAGE_PRIVATE_KEY")
)
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    form_data = await request.form()
    to_number = re.sub(r'\D', '', form_data.get("phone", ""))
    
    if not to_number:
        return templates.TemplateResponse("index.html", {"request": request, "message": "Error: Phone number is required!"})

    # تحديد الرقم (استخدام الرقم الذي طلبته مباشرة في حال فشل متغير البيئة)
    from_number = os.getenv("VONAGE_FROM_NUMBER")
    if not from_number:
        from_number = "967774440982"
    from_number = re.sub(r'\D', '', from_number)

    # بناء التعليمات الصوتية
    ncco = [
        {"action": "talk", "text": "Hello, please enter your birth date as 8 digits."},
        {
            "action": "input",
            "type": ["dtmf"],
            "dtmf": {"maxDigits": 8, "submitOnHash": True},
            "eventUrl": [f"{os.getenv('BASE_URL')}/birthday"]
        }
    ]

    # القاموس النهائي (لاحظ المفتاح "from" بدون شرطة سفلية)
    payload = {
        "to": [{"type": "phone", "number": to_number}],
        "from": {"type": "phone", "number": from_number},
        "ncco": ncco
    }

    try:
        response = vonage_client.voice.create_call(payload)
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Success! Call UUID: {response.get('uuid')}"
        })
    except Exception as e:
        print(f"Vonage API Error: {str(e)}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "message": f"Failed: {str(e)}"
        })

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    digits = data.get("dtmf", {}).get("digits", "")
    # (هنا نضع منطق حساب العمر كما في النسخ السابقة)
    return [{"action": "talk", "text": "Thank you, goodbye."}]

@app.post("/events")
async def events(request: Request):
    return Response(status_code=204)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
