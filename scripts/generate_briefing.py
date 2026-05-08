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
당신은 전문 투자 분석가입니다. 아래 데이터를 사용하여 이메일 발송용 브리핑을 작성하세요.

날짜: {full_data['date']}
보유 종목 데이터: {json.dumps(holdings_data, ensure_ascii=False)}
발굴 후보 데이터: {json.dumps(discovery_data, ensure_ascii=False)}

지침:
1. 섹션 1: 보유 종목 상세 분석 (Holdings)
   - 보유 종목 리스트만 분석하세요.
   - 각 종목별로 종목명, 현재가, 24시간 변동률, 24시간 최고/최저가, 52주 고/저가를 하이라키 구조로 나열하세요.
   - 차트 이미지 링크: https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_24h.png 와 .../SYMBOL_1m.png 를 텍스트 링크로 표시하세요.
   - 뉴스는 [주요 뉴스], [긍정/공시], [부정/공시]로 분류하세요.

2. 섹션 2: 고배당주 발굴 (Discovery)
   - 발굴 후보 리스트만 분석하세요.
   - 표 대신 하이라키(계층형) 구조로 작성하세요:
     종목명
       현재가: $...
       52주 신고/신저가: $... / $...
       주당 배당금: $...
       배당 수익률: ...%
       다음 배당락일: ...
       분석: ...

3. 제약사항:
   - 마크다운 테이블, 굵게(#, **) 등 이메일에서 깨지는 기호는 절대 사용 금지.
   - 데이터가 0이면 전문 지식으로 분석치를 추정하여 작성(변명 금지).
   - 섹션을 명확히 분리하세요.

톤앤매너: 전문적, 한국어. (깔끔한 텍스트 구조로 작성)
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
