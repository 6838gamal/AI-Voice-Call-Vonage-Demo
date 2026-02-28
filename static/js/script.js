const sendBtn = document.getElementById('sendBtn');
const phoneInput = document.getElementById('phone');
const messageInput = document.getElementById('message');
const responseDiv = document.getElementById('response');

sendBtn.addEventListener('click', async () => {
  const phone = phoneInput.value.trim();
  const text = messageInput.value.trim();
  if (!phone || !text) {
    alert("يرجى إدخال رقم واتساب والنص!");
    return;
  }

  responseDiv.textContent = "جارٍ الإرسال...";

  try {
    const res = await fetch('/inbound', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: phone, text })
    });

    const data = await res.json();
    if (data.ok) {
      responseDiv.textContent = "تم الإرسال بنجاح!";
    } else {
      responseDiv.textContent = "حدث خطأ أثناء الإرسال.";
    }
  } catch (err) {
    responseDiv.textContent = "خطأ: " + err.message;
  }
});
