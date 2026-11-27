"""데이터 수집: S&P 500 구성종목, 일봉(수정주가), 실적 발표일.

결과는 data/ 폴더에 parquet/json으로 캐시한다.
실행: .venv/bin/python update_data.py
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

DATA_DIR = Path(__file__).parent / "data"
CONSTITUENTS_PATH = DATA_DIR / "constituents.parquet"
PRICES_PATH = DATA_DIR / "prices.parquet"
EARNINGS_PATH = DATA_DIR / "earnings.parquet"
META_PATH = DATA_DIR / "meta.json"

BENCHMARKS = ["SPY", "QQQ"]
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HISTORY_PERIOD = "2y"  # 120일선 워밍업 + 약 1년치 되짚어보기


def fetch_constituents() -> pd.DataFrame:
    """위키백과 S&P 500 목록 → ticker, name, sector, sub_industry."""
    resp = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (stock-screener)"}, timeout=30)
    resp.raise_for_status()
    table = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})[0]
    df = pd.DataFrame(
        {
            "ticker": table["Symbol"].str.replace(".", "-", regex=False),  # BRK.B → BRK-B (Yahoo 표기)
            "name": table["Security"],
            "sector": table["GICS Sector"],
            "sub_industry": table["GICS Sub-Industry"],
        }
    )
    return df.drop_duplicates("ticker").reset_index(drop=True)


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    """일봉(수정주가) long format: date, ticker, open, high, low, close, volume."""
    raw = yf.download(
        tickers,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    frames = []
    for t in tickers:
        if t not in raw.columns.get_level_values(0):
            continue
        sub = raw[t].dropna(how="all")
        if sub.empty:
            continue
        sub = sub.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        sub["ticker"] = t
        frames.append(sub.reset_index().rename(columns={"Date": "date"}))
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    # 미국장이 아직 안 끝났으면(뉴욕 16:30 전) 오늘 봉은 장중 미완성이라 버린다.
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if now_ny.hour * 60 + now_ny.minute < 16 * 60 + 30:
        df = df[df["date"] < now_ny.normalize().tz_localize(None)]
    return df


def fetch_earnings(tickers: list[str]) -> pd.DataFrame:
    """다음 실적 발표일. 실패한 종목은 비워 둔다."""
    rows = []
    today = pd.Timestamp.today().normalize()
    for t in tickers:
        next_date = None
        try:
            cal = yf.Ticker(t).calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if dates:
                future = [pd.Timestamp(d) for d in dates if pd.Timestamp(d) >= today]
                if future:
                    next_date = min(future)
        except Exception:
            pass
        rows.append({"ticker": t, "next_earnings": next_date})
    df = pd.DataFrame(rows)
    df["next_earnings"] = pd.to_datetime(df["next_earnings"])
    return df


def update_all(earnings_top_n: int = 100, log=print) -> dict:
    """전체 갱신. 실적일은 거래대금 상위 N개만 조회(속도)."""
    DATA_DIR.mkdir(exist_ok=True)

    log("S&P 500 구성종목 가져오는 중…")
    cons = fetch_constituents()
    cons.to_parquet(CONSTITUENTS_PATH, index=False)
    log(f"  {len(cons)}개 종목")

    log("일봉 가져오는 중… (1~3분)")
    tickers = cons["ticker"].tolist() + BENCHMARKS
    prices = fetch_prices(tickers)
    prices.to_parquet(PRICES_PATH, index=False)
    got = prices["ticker"].nunique()
    missing = sorted(set(tickers) - set(prices["ticker"].unique()))
    log(f"  {got}개 종목 수신, 누락 {len(missing)}개 {missing[:10]}")

    # 실적일: 최근 20일 평균 거래대금 상위 N
    recent = prices[prices["ticker"].isin(cons["ticker"])].copy()
    recent["dollar_vol"] = recent["close"] * recent["volume"]
    last_dates = sorted(recent["date"].unique())[-20:]
    top = (
        recent[recent["date"].isin(last_dates)]
        .groupby("ticker")["dollar_vol"].mean()
        .nlargest(earnings_top_n).index.tolist()
    )
    log(f"실적 발표일 가져오는 중… (상위 {len(top)}개, 1~2분)")
    earnings = fetch_earnings(top)
    earnings.to_parquet(EARNINGS_PATH, index=False)
    log(f"  {earnings['next_earnings'].notna().sum()}개 확인")

    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_bar_date": str(prices["date"].max().date()),
        "tickers": got,
        "missing": missing,
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    log(f"완료: 기준일 {meta['last_bar_date']}")
    return meta


def load_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict] | None:
    if not (CONSTITUENTS_PATH.exists() and PRICES_PATH.exists()):
        return None
    cons = pd.read_parquet(CONSTITUENTS_PATH)
    prices = pd.read_parquet(PRICES_PATH)
    earnings = pd.read_parquet(EARNINGS_PATH) if EARNINGS_PATH.exists() else pd.DataFrame(columns=["ticker", "next_earnings"])
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    return cons, prices, earnings, meta
