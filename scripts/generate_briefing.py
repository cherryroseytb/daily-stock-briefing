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
        market_data = json.load(f)
    
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    prompt = f"""
당신은 전문 투자 분석가입니다. 아래 제공된 시장 데이터를 분석하여 상세 주식 브리핑을 작성해주세요.

날짜: {market_data['date']}
시장 데이터:
{json.dumps(market_data['market_data'], ensure_ascii=False, indent=2)}

브리핑 구성:
1. 보유 종목 상세 분석
   - 지난 24시간: 최고/최저/최종 가격 기록
   - 최근 24시간 뉴스, 긍정 뉴스, 부정 뉴스, 전문가 코멘트 분리
2. 투자 인사이트: 보유 종목에 대한 객관적 진단
3. 고배당주 발굴 (Discovery): 배당 10% 이상, 재무 건전성 양호한 종목 5개 분석

톤앤매너: 전문적, 한국어. (이메일 발송용이므로 깔끔하게 작성해주세요)
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
