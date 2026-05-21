# Daily Stock Briefing — 계획서 및 제안사항 (Gemini 2.5 Flash 구현 완료)

> 마지막 업데이트: 2026-05-09  
> 목표: 매일 오전 8:30 KST, 해외 주식 시장 브리핑을 자동으로 생성해 이 레포에 저장 (Gemini 2.5 Flash 활용)

---

## 구현 완료된 구조 ✅

**구조:**
```
GitHub Actions (매일 08:30 KST) → fetch_data.py (yfinance) → generate_briefing.py (Gemini 2.5 Flash) → Commit & Push
```

**상세 흐름:**
1. **GitHub Actions**: 스케줄러에 의해 매일 한국시간 오전 8:30 실행.
2. **fetch_data.py**: `portfolio.json`을 읽어 `yfinance`를 통해 주가 및 최근 뉴스 수집 후 `data/latest_market_data.json` 저장.
3. **generate_briefing.py**: Gemini 2.5 Flash (Free Tier)가 수집된 데이터를 읽고 투자자용 마크다운 브리핑 생성.
4. **사용량 리포트**: 브리핑 하단에 해당 세션의 토큰 사용량 및 한도 대비 비율(%)을 자동으로 포함.
5. **결과 저장**: `briefings/YYYY-MM-DD.md` 파일로 커밋 및 푸시.

---

## 필수 설정 (사용자 작업 필요) 🚀

자동 실행을 위해 다음 설정을 반드시 완료해주세요:

1. **API 키 발급**:
   - [Google AI Studio](https://aistudio.google.com/app/apikey)에서 **무료 티어(Free Tier)** Gemini API 키 발급
   - Alpha Vantage 및 Finnhub 무료 API 키 발급

2. **이메일 발송용 앱 비밀번호 설정 (Gmail 기준)**:
   - 보내는 메일(Gmail) 계정의 보안 설정에서 '2단계 인증'을 켭니다.
   - '앱 비밀번호(App Passwords)'를 생성합니다. (이름은 'GitHub Actions' 등 임의로 지정)

3. **GitHub Secrets 등록**:
   - GitHub 레포지토리의 `Settings` > `Secrets and variables` > `Actions` 메뉴로 이동.
   - `New repository secret` 버튼 클릭하여 다음 키들을 각각 등록하세요:
     - `GEMINI_API_KEY`: Gemini API 키 (2.5 Flash 모델 지원)
     - `ALPHA_VANTAGE_API_KEY`: Alpha Vantage API 키
     - `FINNHUB_API_KEY`: Finnhub API 키
     - `EMAIL_SENDER`: 브리핑을 보낼 이메일 주소
     - `EMAIL_PASSWORD`: 생성한 메일 '앱 비밀번호'
   - 수신자 이메일은 `portfolio.json`의 `email_receivers` 배열에서 관리합니다 (GitHub Secrets 사용 안 함).

---

## 파일 구조

```
daily-stock-briefing/
├── .github/workflows/
│   └── daily_briefing.yml   # 자동화 워크플로우 (KST 08:30)
├── scripts/
│   ├── fetch_data.py        # yfinance 데이터 수집 스크립트
│   └── generate_briefing.py # Gemini 브리핑 생성 스크립트
├── portfolio.json           # 보유 종목 설정
├── requirements.txt         # 파이썬 의존성
└── briefings/               # 날짜별 브리핑 저장소
```

---

## 보유 종목 수정 방법

`portfolio.json` 파일을 수정하면 다음 날 자동 반영됩니다.

```json
{
  "holdings": ["QCOM", "IONQ", "MSFT", "OXLC"],
  "watchlist_criteria": "연배당 10%+ 고배당주, 1-2년 내 부도 위험 없는 종목"
}
```
