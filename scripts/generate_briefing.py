import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
from datetime import datetime

def send_email(subject, plain_text_body):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    receiver_email = os.getenv("EMAIL_RECEIVER")

    if not all([sender_email, sender_password, receiver_email]):
        print("Email credentials (EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER) not fully configured. Skipping email.")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject

        msg.attach(MIMEText(plain_text_body, 'plain'))

        # Using Gmail's SMTP server as default
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, receiver_email, text)
        server.quit()
        print(f"Email sent successfully to {receiver_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def generate_briefing():
    # Load the latest market data
    with open("data/latest_market_data.json", "r", encoding="utf-8") as f:
        market_data = json.load(f)
    
    # Configure Gemini API
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in environment variables.")
        return

    client = genai.Client(api_key=api_key)

    # 1. Generate Markdown version for GitHub
    prompt_md = f"""
당신은 전문 주식 분석가입니다. 아래 제공된 시장 데이터를 바탕으로 매일 아침 투자자를 위한 '주식 시장 브리핑'을 작성해주세요.

날짜: {market_data['date']}
포트폴리오 기준: {market_data['watchlist_criteria']}
시장 데이터:
{json.dumps(market_data['market_data'], ensure_ascii=False, indent=2)}

브리핑은 다음 형식을 따라야 합니다:
1. **오늘의 시장 요약**: 전체적인 시장 분위기와 주요 지표 요약
2. **보유 종목 집중 분석**: 각 종목별 주가 변동, 최근 뉴스 요약 및 간단한 코멘트
3. **투자 인사이트**: 포트폴리오 기준에 맞춘 오늘의 관전 포인트 또는 제안
4. **참고 링크**: 관련 주요 뉴스 링크들

톤앤매너: 전문적이면서도 가독성 좋게 마크다운 형식으로 작성해주세요. 언어는 한국어로 작성하세요.
"""
    response_md = client.models.generate_content(model="gemini-2.0-flash", contents=prompt_md)
    briefing_md = response_md.text

    # 2. Generate Plain Text version for Email
    prompt_text = f"""
당신은 전문 주식 분석가입니다. 방금 작성한 마크다운 형식의 브리핑 내용을 이메일 본문용 '일반 텍스트(Plain Text)'로 변환해주세요.
마크다운 특수기호(#, *, -, > 등)를 모두 제거하고, 텍스트 자체의 들여쓰기와 줄바꿈만으로 깔끔하게 읽히도록 정리해주세요.

원본 마크다운 내용:
{briefing_md}
"""
    response_text = client.models.generate_content(model="gemini-2.0-flash", contents=prompt_text)
    briefing_plain_text = response_text.text

    # Save the Markdown briefing
    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("briefings", exist_ok=True)
    file_path = f"briefings/{date_str}.md"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(briefing_md)
    
    print(f"Briefing generated and saved to {file_path}")

    # Send Email
    email_subject = f"[일일 주식 브리핑] {date_str} 시장 요약"
    send_email(email_subject, briefing_plain_text)

if __name__ == "__main__":
    generate_briefing()
