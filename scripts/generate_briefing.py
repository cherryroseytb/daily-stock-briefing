import html as html_lib
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return datetime.now(KST)


def _merge_chart_links(text):
    """[TAG] URL 줄을 앞 줄 끝에 인라인 마커로 병합"""
    tag_labels = {
        '[24H]': '[24H 주가 흐름]',
        '[1M]': '[1M 주가 흐름]',
        '[1Y]': '[1Y 주가 흐름]',
    }
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            m = re.match(r'^\s*(\[(?:24H|1M|1Y)\])\s+(https?://\S+)\s*$', lines[i + 1])
            if m:
                label = tag_labels.get(m.group(1), m.group(1))
                url = m.group(2)
                result.append(lines[i].rstrip() + f'\x00{url}\x01{label}\x02')
                i += 2
                continue
        result.append(lines[i])
        i += 1
    return '\n'.join(result)


def text_to_html(text):
    # ** 마크다운 제거 후 차트 링크 병합
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = _merge_chart_links(text)

    lines = text.split('\n')
    parts = [
        '<html><body style="font-family:Arial,sans-serif;font-size:14px;'
        'line-height:1.8;color:#222;max-width:1200px;margin:0;padding:16px;">'
    ]

    for line in lines:
        if not line.strip():
            parts.append('<div style="height:6px;"></div>')
            continue

        # 인라인 차트 링크 마커 처리
        inline_link = ''
        if '\x00' in line:
            before, rest = line.split('\x00', 1)
            url, label_end = rest.split('\x01', 1)
            label = label_end.rstrip('\x02')
            line = before
            inline_link = f' <a href="{url}" style="color:#1a73e8;font-size:12px;text-decoration:none;">{label}</a>'

        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        margin = indent * 7
        s = f'margin-left:{margin}px;padding:1px 0;'
        esc = html_lib.escape(stripped)

        # --- 구분선
        if re.match(r'^-{3,}', stripped):
            parts.append('<hr style="border:none;border-top:1px solid #ddd;margin:10px 0;">')
            continue

        # 섹션 제목 (섹션 1:, 섹션 2: 또는 1. 형식 모두 처리)
        if re.match(r'^섹션 \d+:', stripped) or re.match(r'^\d+\.\s*(보유|고배당)', stripped):
            parts.append(f'<div style="{s}font-size:16px;font-weight:bold;color:#c0392b;margin-top:20px;">{esc}{inline_link}</div>')
            continue

        # API 사용량 리포트 헤더
        if stripped == 'API 사용량 리포트':
            parts.append(f'<div style="{s}font-weight:bold;margin-top:20px;">{esc}</div>')
            continue

        # 종목명 (SYMBOL (회사명), 최상위 레벨)
        if re.match(r'^[A-Z]{1,6}\s+\(.+\)\s*$', stripped) and indent == 0:
            parts.append(f'<div style="{s}font-size:15px;font-weight:bold;margin-top:14px;">{esc}{inline_link}</div>')
            continue

        # 서브섹션 헤더
        if re.match(r'^(주가분석|뉴스/공시|배당정보|투자 등급)$', stripped):
            parts.append(f'<div style="{s}font-weight:bold;margin-top:10px;">{esc}{inline_link}</div>')
            continue

        # 뉴스/공시 서브헤더
        if re.match(r'^주요(뉴스|공시)\(.+\):$', stripped):
            parts.append(f'<div style="{s}font-weight:bold;">{esc}{inline_link}</div>')
            continue

        # 분석:
        if stripped.startswith('분석:'):
            rest = html_lib.escape(stripped[3:])
            parts.append(f'<div style="{s}"><b>분석:</b>{rest}{inline_link}</div>')
            continue

        # 일반 텍스트
        parts.append(f'<div style="{s}">{esc}{inline_link}</div>')

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
    # 수신자 목록은 portfolio.json에서 관리한다 (GitHub Secrets 의존성 제거)
    try:
        with open("portfolio.json", "r", encoding="utf-8") as f:
            receivers = [r.strip() for r in json.load(f).get("email_receivers", []) if r.strip()]
    except Exception:
        receivers = []
    if not all([sender_email, sender_password, receivers]):
        return
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


def build_weekly_prompt(full_data):
    weekly_sources = full_data.get("weekly_sources", [])
    return f"""
    당신은 전문 투자 분석가입니다. 아래 이번 주 브리핑 자료를 사용하여 주간 요약을 작성하세요.

    날짜: {full_data['date']}
    주간 브리핑 원문: {json.dumps(weekly_sources, ensure_ascii=False)}

    === 출력 규칙 ===
    - 인사말, 수신/발신/날짜 헤더, 맺음말 금지.
    - **, *, #, __ 등 마크다운 기호 일체 사용 금지. 순수 텍스트만 사용.
    - 섹션 제목은 반드시 `섹션 1:`, `섹션 2:`, `섹션 3:` 형식으로 작성하세요.
    - 들여쓰기는 스페이스 4칸 단위로 계층을 구분하세요.
    - 같은 종목이 여러 번 등장하면 반복 신호로 묶어서 설명하세요.
    - 외부 데이터가 아니라 제공된 이번 주 브리핑만 근거로 요약하세요.

    지침:
    1. 섹션 1: 보유 종목 주간 변화
    - 이번 주 보유 종목에서 반복된 긍정/부정 이슈를 정리하세요.
    - 가격, 뉴스, 공시, 투자등급 변화 관점으로 5~8줄로 요약하세요.

    2. 섹션 2: 이번 주 발굴 후보 요약
    - 이번 주 섹션2에 등장한 후보 중 반복 등장하거나 중요도가 높았던 종목을 정리하세요.
    - 고배당, 테마, 장기 퀄리티 후보가 섞여 있으면 유형별로 나눠 설명하세요.

    3. 섹션 3: 다음 주 체크포인트
    - 다음 주에 확인할 가격 구간, 뉴스 이벤트, 공시 리스크, 배당 이슈를 구체적으로 정리하세요.
    - 신규 매수 권고처럼 단정하지 말고 관찰 포인트 중심으로 작성하세요.

    톤앤매너: 전문적, 한국어, 간결한 문장.
    """


def section2_guidance(screening_meta, report_profile):
    title = report_profile.get("title", "발굴 후보")
    report_type = report_profile.get("type", "dividend")

    if report_type == "theme":
        criteria = (
            "모멘텀강도(30%) + 산업모멘텀(25%) + 재무안정성(20%) + "
            "가격적정성(15%) + 자본성장력(10%)"
        )
        extra = (
            "- 배당정보는 있으면 짧게 언급하되, 배당이 핵심 평가 기준이 아닙니다.\n"
            "- 최근 뉴스/공시와 사업 촉매를 중심으로 테마 적합성을 설명하세요."
        )
        subsection = "테마/모멘텀"
    elif report_type == "quality":
        criteria = (
            "사업품질(30%) + 자본성장력(25%) + 재무안정성(20%) + "
            "가격적정성(15%) + 산업모멘텀(10%)"
        )
        extra = (
            "- 3년 이상 장기 보유 관점에서 경쟁력, 수익성, 현금흐름, 밸류에이션 리스크를 설명하세요.\n"
            "- 배당정보는 보조 정보로만 사용하세요."
        )
        subsection = "장기투자 적합성"
    else:
        criteria = (
            "배당성향도(30%) + 자본성장력(25%) + 산업모멘텀(25%) + 가격적정성(20%)"
        )
        extra = (
            "- 배당수익률, 배당 지속성, 부채 부담, 배당 삭감 리스크를 중심으로 설명하세요.\n"
            "- 배당정보 섹션을 반드시 포함하세요."
        )
        subsection = "배당정보"

    return f"""
    2. 섹션 2: {title} (Discovery)
    - 이 후보들은 글로벌 {screening_meta.get('seed_pool_size', '?')}개 후보 풀 → AI 1차 선정 → 100점 스코어링을 통해 추려진 Top 5입니다.
    - 오늘의 발굴 주제: {report_profile.get('description', '')}
    - 스크리닝 사전 순위(screening_score 기준)를 참고하되, 최종 순서는 종합매력도 기준으로 작성하세요.
    - 종합매력도 계산: {criteria}.
    - 5개 전부 작성하세요 (상위 5개만 이미 전달된 상태입니다).
    {extra}
    - 아래 형식을 정확히 따르세요:

SYMBOL (회사명)

    주가분석
        현재가: $... (24H : $저가 - $고가)
            [24H] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_24h.png
        최근1달(1M): $저가 - $고가
            [1M] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1m.png
        최근1년(1Y): $저가 ~ $고가
            [1Y] https://raw.githubusercontent.com/cherryroseytb/daily-stock-briefing/main/charts/SYMBOL_1y.png

    {subsection}
        오늘 주제와 연결되는 핵심 평가 요소를 1~2줄로 설명.

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
    """


def generate_briefing():
    with open("data/latest_market_data.json", "r", encoding="utf-8") as f:
        full_data = json.load(f)
        market_data = full_data['market_data']

    report_profile = full_data.get("report_profile", {})

    with open("portfolio.json", "r") as f:
        portfolio = json.load(f)
    holdings_list = portfolio.get("holdings", [])

    holdings_data = {k: v for k, v in market_data.items() if k in holdings_list}
    discovery_data = {k: v for k, v in market_data.items() if k not in holdings_list}
    candidate_rankings = full_data.get("candidate_rankings", [])
    screening_meta = full_data.get("screening_meta", {})

    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    if report_profile.get("type") == "weekly_summary":
        prompt = build_weekly_prompt(full_data)
    else:
        section2_text = section2_guidance(screening_meta, report_profile)

        prompt = f"""
    당신은 전문 투자 분석가입니다. 아래 데이터를 사용하여 브리핑을 작성하세요.

    날짜: {full_data['date']}
    보유 종목 데이터: {json.dumps(holdings_data, ensure_ascii=False)}
    발굴 후보 데이터: {json.dumps(discovery_data, ensure_ascii=False)}
    스크리닝 사전 순위 (참고용): {json.dumps(candidate_rankings, ensure_ascii=False)}
    스크리닝 메타: 글로벌 {screening_meta.get('seed_pool_size', '?')}개 풀 → AI {screening_meta.get('ai_selected_count', '?')}개 선정 → 점수 상위 5개

    === 출력 규칙 ===
    - 인사말(안녕하세요 등), 수신/발신/날짜 헤더, 서론 문단, 맺음말(궁금한 점... 감사합니다... 드림 등) 일체 금지.
    - **, *, #, __ 등 마크다운 기호 일체 사용 금지. 순수 텍스트만 사용.
    - 섹션 제목은 반드시 `섹션 1:`, `섹션 2:` 형식으로 작성하세요.
    - 들여쓰기는 스페이스 4칸 단위로 계층을 엄격히 구분. 섹션명은 4칸, 하위 항목은 8칸, 내용은 12칸.
    - 섹션명(주가분석, 배당정보, 뉴스/공시, 투자 등급)에는 [] 기호 사용 금지.
    - 별점은 ★/☆ 합쳐 항상 5칸: 예) 3점=★★★☆☆
    - 뉴스: title+summary 참고해 종목 관련 핵심 한 줄 요약. (소스, 날짜, 긍정/중립/부정)
    - 공시: `sec_filings_6m`의 `form_label`(한글 공시 유형), `form_type`, `importance`, `description`을 함께 활용해 한 줄 요약. 형식: "한글유형(form_type, 중요도): 핵심내용. (SEC/FMP, 날짜, 긍정/중립/부정)". error 필드 있으면 그대로 표시.
    - 공시 필터: `sec_filings_filter.raw_count`가 1 이상인데 `sec_filings_6m`에 fallback_reason이 있으면 "중요 공시는 아니지만 최근 기타 SEC 공시 N건 확인"처럼 표현하고, 절대 "공시 없음"이라고 쓰지 마세요.
    - 공시 필터: `sec_filings_filter.excluded_count`가 크면 Form 4/S-8 등 저중요도 공시가 제외되었음을 한 줄로만 간단히 언급하세요. 단, 핵심 공시보다 위에 배치하지 마세요.
    - 뉴스/공시 우선순위: 최근 24시간 우선, 실적·M&A·배당정책 등 주가 영향 큰 항목 상위 배치.
    - 뉴스 없으면: `최근 3일간 주요한 뉴스 없음`
    - 공시 없으면: `sec_filings_filter.raw_count`가 0일 때만 `최근 6개월간 주요한 공시 없음`이라고 쓰세요.
    - 비미국 종목: `sec_filings_filter.status`가 `non_us`이면 공시 항목을 `미국 종목만 검색 가능합니다`라고만 쓰세요.
    - 배당락일 주당 금액: dividendRate(연간)÷12(월배당), ÷4(분기배당), 그대로(연배당).
    - 최근1달(1M): low_1m, high_1m 사용. N/A 금지.
    - 최근1년(1Y): fiftyTwoWeekLow ~ fiftyTwoWeekHigh 사용.

    지침:
    1. 섹션 1: 보유 종목 상세 분석 (Holdings)
    - 아래 형식을 정확히 따르세요:

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

    분석: 핵심 투자 포인트와 주의 사항을 2~3문장으로 요약.

    {section2_text}

    3. 제약사항:
    - 마크다운 기호(**, *, #) 절대 사용 금지.
    - 데이터가 0이면 전문 지식으로 추정치 분석.
    - 섹션을 명확히 분리하세요.
    - 간결한 문장으로 작성하세요.

    톤앤매너: 전문적, 한국어.
    """

    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    briefing_md = response.text
    usage = response.usage_metadata

    LIMIT_TPM = 250000
    total_tokens = usage.total_token_count or 0
    usage_percent = (total_tokens / LIMIT_TPM) * 100

    stats = full_data.get("api_stats", {})
    limits = stats.get("limits", {})
    n = stats.get("yfinance", 0)
    usage_report = (
        f"\n\n---\n\nAPI 사용량 리포트\n\n"
        f"    주식 가격 데이터: {stats.get('yfinance', n)}회 (yfinance)\n"
        f"    뉴스 데이터: {stats.get('news', n)}회 (Finnhub / Yahoo Finance)\n"
        f"    SEC 공시 데이터: {stats.get('fmp', n)}회 (FMP)\n\n"
        f"    요청 제한/캐시\n"
        f"        스크리닝 후보 상한: {limits.get('max_screening_candidates', 'N/A')}개\n"
        f"        뉴스 캐시: {limits.get('news_cache_hours', 'N/A')}시간\n"
        f"        SEC 공시 캐시: {limits.get('sec_cache_hours', 'N/A')}시간\n\n"
        f"    Gemini AI 분석\n"
        f"        모델: Gemini 2.5 Flash\n"
        f"        세션 토큰: {total_tokens:,}\n"
        f"        분당 한도 대비: {usage_percent:.2f}%\n"
    )

    final_text = briefing_md + usage_report

    today = now_kst().strftime('%Y-%m-%d')
    with open(f"briefings/{today}.md", "w", encoding="utf-8") as f:
        f.write(final_text)

    plain_body = strip_markdown(final_text)
    html_body = text_to_html(final_text)
    send_email(f"주식 리포트 {today}", plain_body, html_body)


if __name__ == "__main__":
    generate_briefing()
