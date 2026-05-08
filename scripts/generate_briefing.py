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

    === 공통 형식 규칙 ===
    - 들여쓰기는 스페이스 4칸 단위로 계층을 엄격히 구분하세요. 섹션명(주가분석/뉴스/공시/배당정보/투자 등급)은 4칸, 그 하위 항목은 8칸, 내용은 12칸.
    - 섹션명(주가분석, 배당정보, 뉴스/공시, 투자 등급)에는 [] 기호를 절대 사용하지 마세요.
    - 별점은 채워진 별(★)과 빈 별(☆)을 합쳐 항상 5칸: 예) 3점=★★★☆☆, 5점=★★★★★, 1점=★☆☆☆☆
    - 뉴스: `title`과 `summary` 필드를 모두 참고하여 해당 종목과 직접 관련된 핵심 내용을 한 줄로 요약하세요. (소스, 날짜, 긍정/중립/부정)
    - 공시: `sec_filings_6m`의 `description` 필드를 기반으로 핵심 내용을 한 줄로 요약하세요. `title`은 사용하지 마세요. `error` 필드가 있으면 해당 값을 그대로 표시하세요. (SEC/FMP, 날짜, 긍정/중립/부정)
    - 뉴스/공시 우선순위: 최근 24시간 우선, 실적·M&A·배당정책 변경 등 주가 영향 큰 항목은 기간 외라도 상위 배치.
    - `주요뉴스(최근3일)` 데이터가 없으면 정확히 `최근 3일간 주요한 뉴스 없음`으로 작성하세요.
    - `주요공시(최근6달)` 데이터가 없으면 정확히 `최근 6개월간 주요한 공시 없음`으로 작성하세요.
    - 배당락일의 주당 금액은 해당 지급 주기 기준으로 계산: `dividendRate`(연간)÷12(월배당), ÷4(분기배당), 그대로(연배당).
    - 최근1달(1M) 값은 반드시 `low_1m`, `high_1m` 사용. N/A 금지.
    - 최근1년(1Y) 값은 `fiftyTwoWeekLow` ~ `fiftyTwoWeekHigh` 사용.

    지침:
    1. 섹션 1: 보유 종목 상세 분석 (Holdings)
    - 아래 형식을 그대로 따르세요 (들여쓰기 포함):

SYMBOL (회사명)

    주가분석
        현재가: $... (24H : $저가 - $고가)
            [24H] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_24h.png
        최근1달(1M): $저가 - $고가
            [1M] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1m.png
        최근1년(1Y): $저가 ~ $고가
            [1Y] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1y.png

    뉴스/공시
        주요뉴스(최근3일):
            뉴스 핵심 한 줄. (소스, 날짜, 긍정/중립/부정)
        주요공시(최근6달):
            공시 핵심 한 줄. (SEC/FMP, 날짜, 긍정/중립/부정)

    투자 등급
        종합매력도: ★★★☆☆ (근거)
        배당성향도: ★★★★☆ (근거)
        가격적정성: ★★★☆☆ (근거)
        자본성장력: ★★☆☆☆ (근거)
        산업모멘텀: ★★★☆☆ (근거)

    2. 섹션 2: 고배당주 발굴 (Discovery)
    - 후보군 전체를 평가한 뒤, 종합매력도(★) 기준 상위 5개 종목만 내림차순으로 작성하세요.
    - 종합매력도 계산: 배당성향도(30%) + 자본성장력(25%) + 산업모멘텀(25%) + 가격적정성(20%). 동점 시 배당 수익률이 높은 종목 우선.
    - 아래 형식을 그대로 따르세요 (들여쓰기 포함):

SYMBOL (회사명)

    주가분석
        현재가: $... (24H : $저가 - $고가)
            [24H] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_24h.png
        최근1달(1M): $저가 - $고가
            [1M] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1m.png
        최근1년(1Y): $저가 ~ $고가
            [1Y] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1y.png

    배당정보
        배당 수익률(연간 추정치): ...% (월/분기/연)
        다음 배당락일: YYYY-MM-DD (주당 $... - 월배당이면 연간÷12, 분기배당이면 연간÷4, 연배당이면 연간 그대로)

    뉴스/공시
        주요뉴스(최근3일):
            뉴스 핵심 한 줄. (소스, 날짜, 긍정/중립/부정)
        주요공시(최근6달):
            공시 핵심 한 줄. (SEC/FMP, 날짜, 긍정/중립/부정)

    투자 등급
        종합매력도: ★★★☆☆ (근거)
        배당성향도: ★★★★☆ (근거)
        가격적정성: ★★★☆☆ (근거)
        자본성장력: ★★☆☆☆ (근거)
        산업모멘텀: ★★★☆☆ (근거)

    분석: ...

    3. 제약사항:
    - 마크다운 테이블, 굵게(#, **) 등 이메일에서 깨지는 기호는 절대 사용 금지.
    - 데이터가 0이면 전문 지식으로 추정치 분석.
    - 섹션을 명확히 분리하세요.
    - 불필요한 수식어 없이 간결한 문장으로 작성하세요.
    - 분석 마지막에 'API 사용량 리포트' 섹션을 포함하세요.

    톤앤매너: 전문적, 한국어. (깔끔한 텍스트 구조로 작성)
    """

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    briefing_md = response.text
    usage = response.usage_metadata

    # 3. Calculate Token Usage (for report)
    LIMIT_TPM = 250000
    total_tokens = (usage.total_token_count or 0)
    usage_percent = (total_tokens / LIMIT_TPM) * 100
    usage_report = f"\n\n--- [API 사용량 리포트] ---\n- 모델: Gemini 2.5 Flash\n- 세션 토큰: {total_tokens:,}\n- 분당 한도 대비: {usage_percent:.2f}%\n"

    final_text = briefing_md + usage_report

    # Save Markdown briefing
    with open(f"briefings/{datetime.now().strftime('%Y-%m-%d')}.md", "w", encoding="utf-8") as f:
        f.write(final_text)

    # Send Cleaned Email
    email_body = strip_markdown(final_text)
    send_email(f"주식 리포트 {datetime.now().strftime('%Y-%m-%d')}", email_body)


if __name__ == "__main__":
    generate_briefing()
