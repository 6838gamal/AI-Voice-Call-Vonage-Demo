import os
from datetime import datetime, date
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from vonage import Auth, Vonage
from vonage_voice import CreateCallRequest, Talk, Input, Dtmf

load_dotenv()

app = FastAPI()

# إعداد الملفات الثابتة والقوالب
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

auth = Auth(application_id=os.getenv("VONAGE_APPLICATION_ID"), private_key=os.getenv("VONAGE_PRIVATE_KEY_PATH"))
vonage_client = Vonage(auth)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # عرض صفحة البداية
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/dial")
async def dial(request: Request):
    # استقبال الرقم من الفورم في الـ HTML
    form_data = await request.form()
    to_number = form_data.get("phone") or os.getenv("TO_NUMBER")
    
    talk_action = Talk(
        text='Hello! Please enter your birthday as two-digit month, two-digit day, and four-digit year, then press pound.',
        loop=1,
        language='en-US'
    )
    
    dtmf_input = Input(
        type=['dtmf'],
        dtmf=Dtmf(timeOut=10, maxDigits=8, submitOnHash=True),
        eventUrl=[f"{os.getenv('BASE_URL')}/birthday"],
        eventMethod='POST'
    )
    
    ncco = [talk_action.model_dump(), dtmf_input.model_dump()]

    call = CreateCallRequest(
        to=[{'type': 'phone', 'number': to_number}],
        from_={'type': 'phone', 'number': os.getenv("VONAGE_FROM_NUMBER")},
        ncco=ncco
    )

    response = vonage_client.voice.create_call(call)
    return {"status": "Call initiated", "detail": response.model_dump()}

# باقي المسارات (birthday, events) تبقى كما هي في الكود السابق...
@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    days_until, next_age = get_birthday_data(dtmf_digits)
    text = f"Your birthday is in {days_until} days and you will be {next_age}!" if days_until else "Invalid format."
    return [Talk(text=text).model_dump()]

def get_birthday_data(dtmf_digits: str):
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
