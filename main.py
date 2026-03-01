import os
from datetime import datetime, date
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
# التعديل الهام: استخدام Client بدلاً من Vonage
from vonage import Auth, Client, HttpClientOptions
from vonage_messages import WhatsappText
from vonage_voice import CreateCallRequest, Talk, Input, Dtmf

# تحميل متغيرات البيئة
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
TO_NUMBER = os.getenv("TO_NUMBER")
BASE_URL = os.getenv("BASE_URL")

app = FastAPI()

# إعداد المصادقة باستخدام العميل الجديد Client
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
options = HttpClientOptions(api_host="messages-sandbox.nexmo.com")

@app.get("/dial")
async def dial():
    talk = Talk(
        text='Hello! Please enter your birthday as two-digit month, two-digit day, and four-digit year, and then press pound.',
        loop=1,
        language='en-US'
    )
    
    dtmf_input = Input(
        type=['dtmf'],
        dtmf=Dtmf(timeOut=10, maxDigits=8, submitOnHash=True),
        eventUrl=[f"{BASE_URL}/birthday"],
        eventMethod='POST'
    )
    
    ncco = [talk.model_dump(), dtmf_input.model_dump()]

    call = CreateCallRequest(
        to=[{'type': 'phone', 'number': TO_NUMBER}],
        from_={'type': 'phone', 'number': VOICE_FROM_NUMBER},
        ncco=ncco,
        machine_detection='hangup'
    )

    # استخدام Client هنا بدلاً من Vonage
    vonage_client = Client(auth)
    response = vonage_client.voice.create_call(call)
    return response.model_dump()

@app.post("/events")
async def events(request: Request):
    data = await request.json()
    status = data.get("status")
    to = data.get("to")
    
    if status == "machine":
        message = WhatsappText(
            from_=WHATSAPP_SANDBOX_NUMBER,
            to=to,
            text='Want to know how many days left until your birthday? call us back!'
        )
        # تمرير خيارات الساند بوكس عند الإرسال
        vonage_client = Client(auth, http_client_options=options)
        vonage_client.messages.send(message)
    
    return Response(status_code=204)

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    
    days_until, next_age = get_birthday_data(dtmf_digits)

    if days_until is None:
        text = 'Invalid birthday format. Try again.'
    else:
        text = f"Your birthday is in {days_until} days and you will be {next_age} years old! Thank you!"

    talk = Talk(text=text, loop=1, language='en-US')
    return [talk.model_dump()]

def get_birthday_data(dtmf_digits: str):
    if len(dtmf_digits) != 8:
        return None, None
    try:
        bday = datetime.strptime(dtmf_digits, "%m%d%Y").date()
        today = date.today()
        
        next_bday = bday.replace(year=today.year)
        if next_bday < today:
            next_bday = next_bday.replace(year=today.year + 1)

        days_until = (next_bday - today).days
        next_age = next_bday.year - bday.year
        return days_until, next_age
    except ValueError:
        return None, None

if __name__ == "__main__":
    import uvicorn
    # تعديل المنفذ ليتوافق مع Render
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
