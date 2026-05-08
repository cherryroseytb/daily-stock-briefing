import json
import os
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
from datetime import datetime

def strip_markdown(text):
    # Remove markdown headers, bold, italics, bullet points, etc.
    text = re.sub(r'#{1,6}\s?', '', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'^- ', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\* ', '', text, flags=re.MULTILINE)
    text = re.sub(r'^> ', '', text, flags=re.MULTILINE)
    return text

def send_email(subject, plain_text_body):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    receiver_env = os.getenv("EMAIL_RECEIVER")
    if not all([sender_email, sender_password, receiver_env]):
        return
    receivers = [r.strip() for r in receiver_env.split(",")]
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = ", ".join(receivers)
        msg['Subject'] = subject
        msg.attach(MIMEText(plain_text_body, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receivers, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")

def generate_briefing():
    with open("data/latest_market_data.json", "r", encoding="utf-8") as f:
        full_data = json.load(f)
        market_data = full_data['market_data']
    
    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)
    holdings_list = portfolio.get("holdings", [])
    
    # 데이터를 두 섹션으로 분리
    holdings_data = {k: v for k, v in market_data.items() if k in holdings_list}
    discovery_data = {k: v for k, v in market_data.items() if k not in holdings_list}
    
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    prompt = f"""
당신은 전문 투자 분석가입니다. 아래 데이터를 분석하여 브리핑을 작성하세요.

날짜: {full_data['date']}
보유 종목 데이터: {json.dumps(holdings_data, ensure_ascii=False)}
발굴 후보 데이터: {json.dumps(discovery_data, ensure_ascii=False)}

지침:
1. 섹션 1: 보유 종목 상세 분석
   - 보유 종목 데이터만 분석하세요.
   - 데이터의 'price', 'high_24h', 'low_24h', 'fiftyTwoWeekHigh', 'fiftyTwoWeekLow'를 사용하여 가격 분석을 명시하세요.
   - 차트 이미지 삽입: ![24시간](https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_24h.png)
     ![1개월](https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1m.png)

2. 섹션 2: 고배당주 발굴 (Discovery)
   - 발굴 후보 데이터만 분석하세요.
   - 제공된 'dividendYield', 'dividendRate', 'exDividendDate'를 사용하여 배당 분석표를 작성하세요.

3. 제약사항:
   - 각 섹션을 명확히 분리하세요.
   - '데이터가 없다'는 변명 금지. 0이면 전문 지식으로 추정치 분석.
"""




    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    briefing_md = response.text
    
    # Save Markdown briefing
    with open(f"briefings/{datetime.now().strftime('%Y-%m-%d')}.md", "w", encoding="utf-8") as f:
        f.write(briefing_md)
    
    # Send Cleaned Email
    email_body = strip_markdown(briefing_md)
    send_email(f"주식 리포트 {datetime.now().strftime('%Y-%m-%d')}", email_body)

if __name__ == "__main__":
    generate_briefing()
