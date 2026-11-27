# 추세추종 스크리너 (S&P 500 · 1·2단계)

## 실행
```bash
cd /Users/martinshim/Desktop/AGENT/07_stock/screener
.venv/bin/python update_data.py      # 데이터 갱신 (약 1분, 미국장 마감 후)
.venv/bin/streamlit run app.py       # http://localhost:8501
```
처음 설치: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

## 배포 · 자동 갱신
- 코드는 `main`, 배포는 `deploy` 브랜치 (= main 코드 + 최신 `data/`).
- GitHub Actions `update-data`가 **매일 한국시간 17:07**(UTC 08:07)에 데이터를 받아 `deploy`를 커밋 1개로 덮어씀. main에 푸시해도 다시 만듦. Actions 탭에서 수동 실행도 가능.
- Streamlit Community Cloud가 `deploy` 브랜치의 `app.py`를 띄우고, 푸시될 때마다 자동으로 다시 시작함.
- GitHub 예약 실행은 늦게 돌 수 있음 (실제로 몇 시간 밀린 적 있음). 미국장 중에 돌면 미완성 당일 봉은 버림.
- 앱: https://trend-screener.streamlit.app

## 파일
- `data.py` — S&P 500 목록(위키백과), 일봉(yfinance, 수정주가), 실적일 → `data/`
- `screener.py` — 계절·1단계·2단계 판정 (`Params`에 기본값)
- `app.py` — Streamlit 화면

## 기본 규칙
| 항목 | 값 | 출처 |
|---|---|---|
| 시장 상태 | SPY·QQQ 60·120일선 상태를 **참고로만** 표시 (매수 필터 아님) | 영상은 필터로 사용 → 사용자 선택으로 제외 |
| 1단계 | 20일 평균 거래대금 상위 10 → 60>120, 종가>20선, 20일 수익률 > 비교지수 | 영상 (기간은 제안) |
| 선정 범위 | 거래대금 상위 30 (TOP 10 강조) → 위 조건 → 초과수익 상위 15 → 섹터당 2 → 최대 10 | 제안 |
| 비교지수 | IT·커뮤니케이션 = QQQ, 그 외 = SPY | 제안 |
| 전황 존 | -2.5% / -6% (또는 ATR 0.5 / 1.2) | 영상 (ATR은 제안) |

yfinance는 비공식 무료 소스라 지연·누락이 있을 수 있습니다. 투자 자문이 아닙니다.
