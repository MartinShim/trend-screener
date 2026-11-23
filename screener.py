"""판정 로직. [영상] = 영상 원칙, [제안] = 추가한 규칙."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

QQQ_SECTORS = {"Information Technology", "Communication Services"}  # [제안] 그 외는 SPY


@dataclass
class Params:
    rs_days: int = 20             # [제안] 지수 대비 수익률 비교 기간
    dv_days: int = 20             # [제안] 거래대금 평균 기간
    core_top: int = 10            # [영상] 거래대금 상위 10
    ext_top: int = 100            # [제안] 2단계 거래대금 상위 100
    ext_rs_top: int = 15          # [제안] 초과수익 상위 N
    sector_cap: int = 2           # [제안] 섹터당 최대
    final_max: int = 10           # [제안] 최종 후보 최대
    zone1_pct: float = 2.5        # [영상]
    zone2_pct: float = 6.0        # [영상]
    atr_mult1: float = 0.5        # [제안]
    atr_mult2: float = 1.2        # [제안]
    earnings_warn_days: int = 2   # [제안]
    exclude_earnings: bool = False  # [제안] 실적 임박 종목 제외


def add_indicators(prices: pd.DataFrame, p: Params) -> pd.DataFrame:
    df = prices.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker", group_keys=False)
    for n in (20, 60, 120):
        df[f"sma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n).mean())
    df["dollar_vol"] = df["close"] * df["volume"]
    df["dv_avg"] = g["dollar_vol"].transform(lambda s: s.rolling(p.dv_days).mean())
    df["ret_rs"] = g["close"].transform(lambda s: s.pct_change(p.rs_days))
    prev_close = g["close"].shift(1)
    tr = np.maximum(df["high"] - df["low"],
                    np.maximum((df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()))
    df["atr14"] = tr.groupby(df["ticker"]).transform(lambda s: s.rolling(14).mean())
    return df


def season_of(row: pd.Series) -> bool:
    """가격이 60·120일선 위 + 60 > 120 (정배열)."""
    return bool(row["close"] > row["sma60"] and row["close"] > row["sma120"] and row["sma60"] > row["sma120"])


def market_season(latest: pd.DataFrame) -> dict:
    spy, qqq = latest.loc["SPY"], latest.loc["QQQ"]
    s_ok, q_ok = season_of(spy), season_of(qqq)
    if s_ok and q_ok:
        state = "spring"       # [영상]
    elif s_ok or q_ok:
        state = "transition"   # [제안]
    else:
        state = "winter"       # [영상]
    return {"state": state, "SPY": s_ok, "QQQ": q_ok, "spy": spy, "qqq": qqq}


def build_table(cons: pd.DataFrame, ind: pd.DataFrame, earnings: pd.DataFrame, p: Params) -> tuple[pd.DataFrame, pd.Timestamp]:
    """기준일(최신) 스냅샷 + 각 조건 통과 여부."""
    asof = ind["date"].max()
    latest = ind[ind["date"] == asof].set_index("ticker")
    bench_ret = {b: latest.loc[b, "ret_rs"] for b in ("SPY", "QQQ")}

    t = cons.set_index("ticker").join(latest, how="inner")
    t["bench"] = np.where(t["sector"].isin(QQQ_SECTORS), "QQQ", "SPY")
    t["excess"] = t["ret_rs"] - t["bench"].map(bench_ret)
    t["dv_rank"] = t["dv_avg"].rank(ascending=False, method="first").astype(int)

    t["ok_trend"] = t["sma60"] > t["sma120"]         # [영상]
    t["ok_above20"] = t["close"] > t["sma20"]        # [영상]
    t["ok_strong"] = t["excess"] > 0                 # [영상] 개념 / [제안] 기간

    t["zone1"] = t["close"] * (1 - p.zone1_pct / 100)
    t["zone2"] = t["close"] * (1 - p.zone2_pct / 100)
    t["zone1_atr"] = t["close"] - p.atr_mult1 * t["atr14"]
    t["zone2_atr"] = t["close"] - p.atr_mult2 * t["atr14"]
    t["risk_pct"] = (t["zone1"] - t["sma20"]) / t["zone1"]  # 1차 매수가 → 20일선 거리

    e = earnings.set_index("ticker")["next_earnings"] if len(earnings) else pd.Series(dtype="datetime64[ns]")
    t["next_earnings"] = t.index.map(e)
    t["earn_bdays"] = [
        np.busday_count(asof.date(), d.date()) if pd.notna(d) else np.nan
        for d in t["next_earnings"]
    ]
    t["earn_warn"] = t["earn_bdays"].le(p.earnings_warn_days)
    t["pass_all"] = t["ok_trend"] & t["ok_above20"] & t["ok_strong"]
    return t.sort_values("dv_rank"), asof


def fail_reasons(row: pd.Series) -> str:
    r = []
    if not row["ok_trend"]:
        r.append("역배열(60<120)")
    if not row["ok_above20"]:
        r.append("20선 아래")
    if not row["ok_strong"]:
        r.append("지수보다 약함")
    return ", ".join(r)


def core_tier(t: pd.DataFrame, p: Params) -> pd.DataFrame:
    """1단계: 거래대금 상위 10 → 조건 판정."""
    return t[t["dv_rank"] <= p.core_top].copy()


def extended_tier(t: pd.DataFrame, p: Params) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[str, int]]]:
    """2단계: 상위 100 → 추세 → 20선 → 지수보다 강함 → 초과수익 상위 N → 섹터 한도 → 최대 M."""
    funnel = [("S&P 500", len(t))]
    u = t[t["dv_rank"] <= p.ext_top].copy()
    funnel.append((f"거래대금 상위 {p.ext_top}", len(u)))
    u["drop_reason"] = ""

    def step(mask, label, reason):
        nonlocal u
        u.loc[(u["drop_reason"] == "") & ~mask, "drop_reason"] = reason
        funnel.append((label, int((u["drop_reason"] == "").sum())))

    step(u["ok_trend"], "60일선 > 120일선", "역배열(60<120)")
    step(u["ok_above20"], "종가 > 20일선", "20선 아래")
    step(u["ok_strong"], f"지수보다 강함({p.rs_days}일)", "지수보다 약함")
    if p.exclude_earnings:
        step(~u["earn_warn"], f"실적 D-{p.earnings_warn_days} 제외", "실적 임박")

    alive = u["drop_reason"] == ""
    rs_rank = u.loc[alive, "excess"].rank(ascending=False, method="first")
    u.loc[rs_rank[rs_rank > p.ext_rs_top].index, "drop_reason"] = f"초과수익 상위 {p.ext_rs_top} 밖"
    funnel.append((f"초과수익 상위 {p.ext_rs_top}", int((u["drop_reason"] == "").sum())))

    alive_idx = u[u["drop_reason"] == ""].sort_values("excess", ascending=False).index
    counts: dict[str, int] = {}
    kept = []
    for tk in alive_idx:
        sec = u.at[tk, "sector"]
        if counts.get(sec, 0) >= p.sector_cap:
            u.at[tk, "drop_reason"] = "섹터 한도 초과"
            continue
        if len(kept) >= p.final_max:
            u.at[tk, "drop_reason"] = f"최대 {p.final_max}개 초과"
            continue
        counts[sec] = counts.get(sec, 0) + 1
        kept.append(tk)
    funnel.append((f"섹터당 최대 {p.sector_cap}", len(kept)))

    final = u.loc[kept]
    dropped = u[u["drop_reason"] != ""].sort_values("excess", ascending=False)
    return final, dropped, funnel


# ════════════════════════════════════════════════════════════
# 일자별 되짚어보기: 모든 거래일에 대해 같은 규칙을 그 날까지의 데이터로 적용
# ════════════════════════════════════════════════════════════
def screen_panel(cons: pd.DataFrame, ind: pd.DataFrame, p: Params) -> pd.DataFrame:
    """(date, ticker)별 판정. 거래대금 상위 ext_top 안의 종목만 반환, selected=최종 선정."""
    bench = ind[ind["ticker"].isin(["SPY", "QQQ"])].pivot(index="date", columns="ticker", values="ret_rs")
    bench = bench.rename(columns={"SPY": "spy_ret", "QQQ": "qqq_ret"})
    df = ind[ind["ticker"].isin(cons["ticker"])].merge(cons[["ticker", "name", "sector"]], on="ticker")
    df = df.dropna(subset=["sma20", "sma60", "sma120", "dv_avg", "ret_rs"])
    df = df.merge(bench, left_on="date", right_index=True, how="left")
    df["bench"] = np.where(df["sector"].isin(QQQ_SECTORS), "QQQ", "SPY")
    df["bench_ret"] = np.where(df["bench"] == "QQQ", df["qqq_ret"], df["spy_ret"])
    df["excess"] = df["ret_rs"] - df["bench_ret"]
    df["dv_rank"] = df.groupby("date")["dv_avg"].rank(ascending=False, method="first").astype(int)
    df = df[df["dv_rank"] <= p.ext_top].copy()

    df["ok_trend"] = df["sma60"] > df["sma120"]
    df["ok_above20"] = df["close"] > df["sma20"]
    df["ok_strong"] = df["excess"] > 0
    df["pass_all"] = df["ok_trend"] & df["ok_above20"] & df["ok_strong"]
    df["top10"] = df["dv_rank"] <= p.core_top
    df["zone1"] = df["close"] * (1 - p.zone1_pct / 100)
    df["zone2"] = df["close"] * (1 - p.zone2_pct / 100)
    df["good_entry"] = df["zone1"] > df["sma20"]
    df["drop_reason"] = np.select(
        [~df["ok_trend"], ~df["ok_above20"], ~df["ok_strong"]],
        ["역배열(60<120)", "20선 아래", "지수보다 약함"], default="",
    )

    alive = df[df["drop_reason"] == ""].sort_values(["date", "excess"], ascending=[True, False])
    alive["rs_pos"] = alive.groupby("date").cumcount() + 1
    over = alive["rs_pos"] > p.ext_rs_top
    df.loc[alive.index[over], "drop_reason"] = f"초과수익 상위 {p.ext_rs_top} 밖"
    alive = alive[~over]
    sec_pos = alive.groupby(["date", "sector"]).cumcount()
    over = sec_pos >= p.sector_cap
    df.loc[alive.index[over], "drop_reason"] = "섹터 한도 초과"
    alive = alive[~over]
    over = alive.groupby("date").cumcount() >= p.final_max
    df.loc[alive.index[over], "drop_reason"] = f"최대 {p.final_max}개 초과"

    df["selected"] = df["drop_reason"] == ""
    df["rs_rank"] = df[df["pass_all"]].groupby("date")["excess"].rank(ascending=False, method="first")
    return df


def index_eval(ind: pd.DataFrame, ticker: str, date: pd.Timestamp) -> dict:
    """지수 상태 평가 (그 날까지의 데이터)."""
    d = ind[(ind["ticker"] == ticker) & (ind["date"] <= date)]
    r, prev = d.iloc[-1], d.iloc[-2]
    above60, above120 = r["close"] > r["sma60"], r["close"] > r["sma120"]
    aligned = r["sma60"] > r["sma120"]
    if above60 and above120 and aligned:
        trend, tone = "상승 추세", "green"
    elif not above60 and not above120:
        trend, tone = "하락 추세", "red"
    else:
        trend, tone = "혼조", "amber"
    high = d["close"].tail(252).max()
    return dict(
        ticker=ticker, close=r["close"], day=r["close"] / prev["close"] - 1,
        ret20=r["close"] / d["close"].iloc[-21] - 1 if len(d) > 21 else np.nan,
        dd=r["close"] / high - 1, above20=r["close"] > r["sma20"], above60=above60, above120=above120,
        aligned=aligned, trend=trend, tone=tone,
        gap20=r["close"] / r["sma20"] - 1, gap60=r["close"] / r["sma60"] - 1, gap120=r["close"] / r["sma120"] - 1,
    )


def simulate(tk_df: pd.DataFrame, date: pd.Timestamp, zone1: float, zone2: float) -> dict:
    """선정일 종가 기준 지정가(다음 거래일 하루 유효) → 종가가 20일선 아래로 마감하면 전량 매도."""
    after = tk_df[tk_df["date"] > date]
    if after.empty:
        return {"status": "대기", "detail": "다음 거래일 결과 대기"}
    d1 = after.iloc[0]
    fills = []
    if d1["low"] <= zone1:
        fills.append(min(d1["open"], zone1))   # 갭하락이면 시가 체결
    if d1["low"] <= zone2:
        fills.append(min(d1["open"], zone2))
    if not fills:
        return {"status": "미체결", "detail": f"{d1['date']:%m/%d} 저가 ${d1['low']:,.2f} > 매수가"}
    entry = float(np.mean(fills))
    exits = after[after["close"] < after["sma20"]]
    if len(exits):
        x = exits.iloc[0]
        days = int((after["date"] <= x["date"]).sum())
        return {"status": "청산", "entry": entry, "fills": len(fills), "fill_date": d1["date"],
                "exit_date": x["date"], "exit": x["close"], "ret": x["close"] / entry - 1, "days": days}
    last = after.iloc[-1]
    return {"status": "보유 중", "entry": entry, "fills": len(fills), "fill_date": d1["date"],
            "exit_date": None, "exit": last["close"], "ret": last["close"] / entry - 1, "days": len(after)}
