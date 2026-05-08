import html as html_lib
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from google import genai


def text_to_html(text):
    lines = text.split('\n')
    parts = [
        '<html><body style="font-family:Arial,sans-serif;font-size:14px;'
        'line-height:1.8;color:#222;max-width:820px;margin:0 auto;padding:16px;">'
    ]

    for line in lines:
        if not line.strip():
            parts.append('<div style="height:6px;"></div>')
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        margin = indent * 7
        s = f'margin-left:{margin}px;padding:1px 0;'
        esc = html_lib.escape(stripped)

        # --- 구분선
        if re.match(r'^-{3,}', stripped):
            parts.append('<hr style="border:none;border-top:1px solid #ddd;margin:10px 0;">')
            continue

        # 차트 링크: [TAG] URL
        m = re.match(r'^(\[(?:24H|1M|1Y)\])\s+(https?://\S+)$', stripped)
        if m:
            tag, url = m.group(1), m.group(2)
            parts.append(
                f'<div style="{s}font-size:11px;color:#999;">'
                f'<a href="{url}" style="color:#999;text-decoration:none;">{tag}</a>'
                f'</div>'
            )
            continue

        # 섹션 제목 (섹션 1:, 섹션 2:)
        if re.match(r'^섹션 \d+:', stripped):
            parts.append(f'<div style="{s}font-size:16px;font-weight:bold;margin-top:20px;">{esc}</div>')
            continue

        # API 사용량 리포트 헤더
        if stripped == 'API 사용량 리포트':
            parts.append(f'<div style="{s}font-weight:bold;margin-top:20px;">{esc}</div>')
            continue

        # 종목명 (SYMBOL (회사명), 최상위 레벨)
        if re.match(r'^[A-Z]{1,6}\s+\(.+\)\s*$', stripped) and indent == 0:
            parts.append(f'<div style="{s}font-size:15px;font-weight:bold;margin-top:14px;">{esc}</div>')
            continue

        # 서브섹션 헤더 (주가분석, 뉴스/공시, 배당정보, 투자 등급)
        if re.match(r'^(주가분석|뉴스/공시|배당정보|투자 등급)$', stripped):
            parts.append(f'<div style="{s}font-weight:bold;margin-top:10px;">{esc}</div>')
            continue

        # 뉴스/공시 서브헤더
        if re.match(r'^주요(뉴스|공시)\(.+\):$', stripped):
            parts.append(f'<div style="{s}font-weight:bold;">{esc}</div>')
            continue

        # 분석: ("분석:" 부분만 bold)
        if stripped.startswith('분석:'):
            rest = html_lib.escape(stripped[3:])
            parts.append(f'<div style="{s}"><b>분석:</b>{rest}</div>')
            continue

        # 일반 텍스트
        parts.append(f'<div style="{s}">{esc}</div>')

    parts.append('</body></html>')
    return '\n'.join(parts)


def strip_markdown(text):
    text = re.sub(r'#{1,6}\s?', '', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'^[-*] ', '', text, flags=re.MULTILINE)
    text = re.sub(r'^> ', '', text, flags=re.MULTILINE)
    return text


def send_email(subject, plain_body, html_body):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    receiver_env = os.getenv("EMAIL_RECEIVER")
    if not all([sender_email, sender_password, receiver_env]):
        return
    receivers = [r.strip() for r in receiver_env.split(",")]
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = ", ".join(receivers)
        msg['Subject'] = subject
        msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
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

    분석: 해당 종목의 핵심 투자 포인트와 주의 사항을 2~3문장으로 요약.

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

    톤앤매너: 전문적, 한국어. (깔끔한 텍스트 구조로 작성)
    """

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    briefing_md = response.text
    usage = response.usage_metadata

    # API 사용량 리포트 (프로그래밍 방식으로 생성)
    LIMIT_TPM = 250000
    total_tokens = usage.total_token_count or 0
    usage_percent = (total_tokens / LIMIT_TPM) * 100

    stats = full_data.get("api_stats", {})
    n = stats.get("yfinance", 0)
    usage_report = (
        f"\n\n---\n\nAPI 사용량 리포트\n\n"
        f"    주식 가격 데이터: {stats.get('yfinance', n)}회 (yfinance)\n"
        f"    뉴스 데이터: {stats.get('news', n)}회 (Finnhub / Yahoo Finance)\n"
        f"    SEC 공시 데이터: {stats.get('fmp', n)}회 (FMP)\n"
        f"    차트 생성: {stats.get('charts', n * 3)}회 (로컬)\n\n"
        f"    Gemini AI 분석\n"
        f"        모델: Gemini 2.5 Flash\n"
        f"        세션 토큰: {total_tokens:,}\n"
        f"        분당 한도 대비: {usage_percent:.2f}%\n"
    )

    final_text = briefing_md + usage_report

    # .md 파일 저장
    with open(f"briefings/{datetime.now().strftime('%Y-%m-%d')}.md", "w", encoding="utf-8") as f:
        f.write(final_text)

    # 이메일 발송 (HTML + plain text 동시 첨부)
    plain_body = strip_markdown(final_text)
    html_body = text_to_html(final_text)
    send_email(f"주식 리포트 {datetime.now().strftime('%Y-%m-%d')}", plain_body, html_body)


if __name__ == "__main__":
    generate_briefing()
