"""추세추종 리포트 — 일자별 되짚어보기.

구성: 날짜 선택 → ① 시장 흐름(S&P 500·나스닥) → ② 선별 종목과 선정 이유(차트) → ③ 지난 기록
실행: .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import load_all, update_all
from screener import Params, add_indicators, index_eval, screen_panel, simulate

st.set_page_config(page_title="추세추종 리포트", page_icon="📈", layout="centered",
                   initial_sidebar_state="collapsed")
FONT_CSS = ("https://cdn.jsdelivr.net/gh/wanteddev/wanted-sans@v1.0.3/packages/wanted-sans/fonts/"
            "webfonts/variable/split/WantedSansVariable.min.css")
# 숫자·기호만 Inter(광학 크기 축 포함)로 — 한글·영문은 Wanted Sans 유지
NUM_FONT = "https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.1.0/files/inter-latin-opsz-normal.woff2"
NUM_RANGE = "U+0030-0039, U+0024-0025, U+002B-002F, U+003A, U+2212, U+2013, U+00B7"
FONT_STACK = '"Num", "Wanted Sans Variable"'
st.markdown(
    f'<style>@import url("{FONT_CSS}");'
    f'@font-face{{font-family:"Num";src:url("{NUM_FONT}") format("woff2-variations");'
    f'font-weight:100 900;font-display:swap;unicode-range:{NUM_RANGE};}}'
    f':root{{--font:{FONT_STACK};--tracking:-0.015em;}}'
    + (Path(__file__).parent / "style.css").read_text() + "</style>",
    unsafe_allow_html=True,
)

def show_chart(fig: go.Figure, **kw):
    """차트 글꼴도 사이트와 같게 (숫자 = Inter, 글자 = Wanted Sans)."""
    fig.update_layout(font=dict(family=FONT_STACK + ", sans-serif"),
                      hoverlabel=dict(font=dict(family=FONT_STACK + ", sans-serif")))
    return st.plotly_chart(fig, **kw)


p = Params(ext_top=30)  # 거래대금 상위 30개에서 고르고, 상위 10개는 강조
INDEX_NAME = {"SPY": "S&P 500", "QQQ": "나스닥 100"}
WEEK = "월화수목금토일"


def h(markup: str) -> None:
    st.markdown(" ".join(line.strip() for line in markup.splitlines() if line.strip()), unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s))


def money(x: float) -> str:
    return f"${x:,.2f}"


def pct(x: float, sign: bool = True) -> str:
    return f"{x * 100:+.1f}%" if sign else f"{x * 100:.1f}%"


def chg_cls(x: float) -> str:
    return "up" if x >= 0 else "down"


# ── 데이터 ─────────────────────────────────────────────
loaded = load_all()
if loaded is None:
    h('<div class="page-title">추세추종 리포트</div>')
    if st.button("데이터 받기 (약 1분)", type="primary"):
        with st.spinner("받는 중…"):
            update_all(log=lambda *_: None)
        st.rerun()
    st.stop()


@st.cache_data(show_spinner="계산 중…")
def compute(_mtime: str):
    cons, prices, earnings, meta = load_all()
    ind = add_indicators(prices, p)
    panel = screen_panel(cons, ind, p)
    return ind, panel, earnings, meta


@st.cache_data(show_spinner="지난 기록 계산 중…")
def history(_mtime: str) -> pd.DataFrame:
    ind, panel, _, _ = compute(_mtime)
    sel = panel[panel["selected"]]
    by_tk = {tk: g for tk, g in ind.groupby("ticker")}
    rows = []
    for _, r in sel.iterrows():
        o = simulate(by_tk[r["ticker"]], r["date"], r["zone1"], r["zone2"])
        rows.append({"date": r["date"], "ticker": r["ticker"], "name": r["name"], "top10": r["top10"],
                     "good_entry": r["good_entry"], **o})
    return pd.DataFrame(rows)


mtime = loaded[3].get("updated_at", "")
ind, panel, earnings, meta = compute(mtime)
dates = sorted(panel["date"].unique())
latest = dates[-1]

# ── 날짜 선택 ───────────────────────────────────────────
if "asof_input" not in st.session_state:
    st.session_state.asof_input = pd.Timestamp(latest).date()


def snap(d) -> pd.Timestamp:
    d = pd.Timestamp(d)
    valid = [x for x in dates if x <= d]
    return valid[-1] if valid else dates[0]


def go_latest() -> None:
    st.session_state.asof_input = pd.Timestamp(latest).date()


h('<div class="page-head"><div class="page-title">추세추종 리포트</div>'
  f'<div class="page-date">S&amp;P 500 · 거래대금 상위 {p.ext_top}</div></div>')

c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
c1.date_input("날짜", key="asof_input", min_value=pd.Timestamp(dates[0]).date(),
              max_value=pd.Timestamp(latest).date(), label_visibility="collapsed", format="YYYY-MM-DD")
c2.button("최신", on_click=go_latest, use_container_width=True)

asof = snap(st.session_state.asof_input)
is_latest = asof == latest
day_label = f"{asof:%Y.%m.%d}({WEEK[asof.weekday()]})"
if pd.Timestamp(st.session_state.asof_input) != asof:
    st.caption(f"휴장일이라 직전 거래일 {day_label} 기준으로 보여 줘요.")

# 일자별 선정 개수 타임라인
counts = panel[panel["selected"]].groupby("date").size().reindex(dates, fill_value=0)
win = counts[counts.index <= asof].tail(90)
tfig = go.Figure(go.Bar(
    x=win.index, y=win.values,
    marker_color=["#FACC15" if d == asof else "#2B3A55" for d in win.index],
    hovertemplate="%{x|%m/%d} · %{y}개<extra></extra>",
))
tfig.update_layout(height=90, margin=dict(l=0, r=0, t=0, b=0), bargap=0.25,
                   xaxis=dict(showgrid=False, tickformat="%m/%d", tickfont=dict(size=10)),
                   yaxis=dict(visible=False), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
show_chart(tfig, use_container_width=True, config={"displayModeBar": False}, key="timeline")
h(f'<div class="legend-note">최근 90거래일 동안 날마다 선정된 종목 수 · 노란 막대 = {day_label}</div>')

# ══ ① 시장 흐름 ═══════════════════════════════════════
spy, qqq = index_eval(ind, "SPY", asof), index_eval(ind, "QQQ", asof)
tones = {spy["tone"], qqq["tone"]}
if tones == {"green"}:
    m_tone, m_pill, m_title = "green", "강세", "시장 전체가 상승 흐름이에요"
elif tones == {"red"}:
    m_tone, m_pill, m_title = "red", "약세", "시장 전체가 하락 흐름이에요"
else:
    m_tone, m_pill, m_title = "amber", "혼조", "시장 흐름이 엇갈려요"


def describe(e: dict) -> str:
    name = INDEX_NAME[e["ticker"]]
    pos = ("60·120일선 위, 정배열" if e["tone"] == "green"
           else "60·120일선 아래" if e["tone"] == "red"
           else f"60일선 {'위' if e['above60'] else '아래'}·120일선 {'위' if e['above120'] else '아래'}")
    short = "단기적으로도 20일선 위에서 버티고" if e["above20"] else "단기적으로 20일선 아래로 밀려"
    return (f"<b>{name}</b>은 {pos}로 <b>{e['trend']}</b>예요. {short} 있고, "
            f"최근 20일 {pct(e['ret20'])}, 1년 고점 대비 {pct(e['dd'])} 수준이에요.")


h('<div class="section-title" style="margin-top:22px">① 시장 흐름</div>')
h(f"""
<div class="hero {m_tone}">
  <span class="pill"><span class="dot"></span>{m_pill}</span>
  <div class="hero-title">{m_title}</div>
  <div class="hero-sub">{describe(spy)}<br>{describe(qqq)}</div>
</div>
""")


MA_STYLE = ((20, "20일선", "orange"), (60, "60일선", "#1f77b4"), (120, "120일선", "#9467bd"))


def candle_chart(d: pd.DataFrame, after: pd.DataFrame | None = None, height: int = 360) -> go.Figure:
    """일봉 캔들 + 20/60/120일선 + 오른쪽 끝 이평선 값 + 종가선. after = 기준일 이후(흐리게)."""
    last = d.iloc[-1]
    fig = go.Figure()
    fig.add_candlestick(x=d["date"], open=d["open"], high=d["high"], low=d["low"], close=d["close"],
                        name="일봉", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
                        increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350", whiskerwidth=0.3)
    both = d
    if after is not None and len(after):
        fig.add_candlestick(x=after["date"], open=after["open"], high=after["high"], low=after["low"],
                            close=after["close"], name="이후 흐름", opacity=0.35,
                            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
                            increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350", whiskerwidth=0.3)
        both = pd.concat([d, after])
    for n, label, color in MA_STYLE:
        fig.add_scatter(x=both["date"], y=both[f"sma{n}"], name=label, line=dict(color=color, width=2),
                        hovertemplate=f"{label} %{{y:,.2f}}<extra></extra>")
    # 오른쪽 끝 이평선 값 라벨 (기준일 값, 겹치지 않게 간격 조정)
    ys = sorted(((last[f"sma{n}"], label, color) for n, label, color in MA_STYLE), reverse=True)
    span = both["high"].max() - both["low"].min()
    placed: list[float] = []
    for y, label, color in ys:
        y_lab = min([y] + [py - span * 0.06 for py in placed])
        placed.append(y_lab)
        fig.add_annotation(x=1.0, xref="paper", y=y_lab, text=f"{label.replace('선', '')} {y:,.1f}",
                           showarrow=False, xanchor="left", xshift=4, font=dict(size=10.5, color=color))
    fig.add_hline(y=last["close"], line=dict(color="#e0e0e0", width=1, dash="dash"),
                  annotation_text=f"종가 {last['close']:,.2f}", annotation_position="top left",
                  annotation_font=dict(size=11, color="#e0e0e0"))
    fig.update_layout(
        height=height, margin=dict(l=0, r=64, t=10, b=0), xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=-0.1, font=dict(size=11)), hovermode="x unified",
        xaxis=dict(rangebreaks=[dict(bounds=["sat", "mon"])], tickformat="%m/%d"),
    )
    return fig


def index_chart(tk: str) -> go.Figure:
    return candle_chart(ind[(ind["ticker"] == tk) & (ind["date"] <= asof)].tail(120))


cols = st.columns(2)
for col, e in zip(cols, (spy, qqq)):
    with col:
        h(f"""
<div class="idx">
  <div class="idx-head">
    <div><div class="idx-name">{INDEX_NAME[e['ticker']]}</div><div class="idx-sub">{e['ticker']} · {day_label}</div></div>
    <span class="tag {e['tone']}">{e['trend']}</span>
  </div>
  <div class="idx-price">{money(e['close'])} <span class="chg {chg_cls(e['day'])}">{pct(e['day'])}</span></div>
  <div class="idx-stats">
    <span>20일 <b class="{chg_cls(e['ret20'])}">{pct(e['ret20'])}</b></span>
    <span>고점 대비 <b>{pct(e['dd'])}</b></span>
    <span>20일선 <b>{pct(e['gap20'])}</b></span>
  </div>
</div>
""")

ctab = st.tabs([f"{INDEX_NAME['SPY']} 차트", f"{INDEX_NAME['QQQ']} 차트"])
for tab, e in zip(ctab, (spy, qqq)):
    with tab:
        show_chart(index_chart(e["ticker"]), use_container_width=True,
                        config={"displayModeBar": False}, key=f"idx_{e['ticker']}")
h('<div class="legend-note">최근 6개월 일봉 · 주황 20일선(단기) · 파랑 60일선(중기) · 보라 120일선(장기) · '
  '파랑이 보라 위 = 정배열(상승 추세) · 시장 흐름은 참고용이며 종목 선정에는 쓰지 않아요</div>')

# ══ ② 선별 종목 ═══════════════════════════════════════
day = panel[panel["date"] == asof].sort_values("dv_rank").set_index("ticker")
n_sel = int(day["selected"].sum())
blk_top = list(day.index[day["top10"]])
blk_rest = list(day.index[~day["top10"]])

h('<div class="section-title" style="margin-top:34px">② 선별 종목</div>')
h(f'<div class="section-sub">{day_label} 거래대금 상위 {p.ext_top}개 중 규칙을 통과한 종목 <b>{n_sel}개</b>. '
  f'<span class="up">초록</span> = 선정, 회색 = 탈락. 종목을 누르면 선정·탈락 이유를 차트와 함께 보여 줘요.</div>')

# 선택 상태: 두 블록이 하나의 선택을 공유
pick_key = f"pick_{asof:%Y%m%d}"
if pick_key not in st.session_state:
    first_sel = day.index[day["selected"]]
    st.session_state[pick_key] = first_sel[0] if len(first_sel) else day.index[0]


BLOCK_KEYS = [f"top_{asof:%Y%m%d}", f"rest_{asof:%Y%m%d}"]


def on_pick(src: str) -> None:
    v = st.session_state.get(src)
    if v:  # 한 블록에서 고르면 다른 블록 선택은 해제
        st.session_state[pick_key] = v
        for k in BLOCK_KEYS:
            if k != src:
                st.session_state[k] = None
    else:  # 같은 종목을 다시 눌러 해제하면 원래 선택 유지
        st.session_state[src] = st.session_state[pick_key]


def tile_label(tk: str) -> str:
    r = day.loc[tk]
    return f"{int(r['dv_rank'])}  {tk}{'  ✓' if r['selected'] else ''}"


def block(title: str, badge_cls: str, tickers: list[str], key: str) -> None:
    sel = int(day.loc[tickers, "selected"].sum())
    with st.container(key=f"blk_{key}"):
        h(f'<div class="blk-head"><span class="badge {badge_cls}">{title}</span>'
          f'<span class="top10-sum">선정 <b>{sel}</b> / {len(tickers)}</span></div>')
        wkey = f"{key}_{asof:%Y%m%d}"
        if wkey not in st.session_state:
            cur = st.session_state[pick_key]
            st.session_state[wkey] = cur if cur in tickers else None
        st.pills(title, tickers, format_func=tile_label, key=wkey, on_change=on_pick, args=(wkey,),
                 label_visibility="collapsed")
    # 선정 종목은 초록으로 (pills 버튼 순서 = tickers 순서)
    on = [i + 1 for i, tk in enumerate(tickers) if day.loc[tk, "selected"]]
    if on:
        sels = ",".join(f".st-key-blk_{key} [data-testid='stButtonGroup'] button:nth-of-type({i})" for i in on)
        st.markdown(f"<style>{sels}{{color:var(--green)!important;border-color:rgba(34,197,94,.45)!important;"
                    f"background:var(--green-bg)!important;}}</style>", unsafe_allow_html=True)


block("거래대금 TOP 10", "top", blk_top, "top")
block(f"거래대금 11~{p.ext_top}위", "rest", blk_rest, "rest")

pick = st.session_state[pick_key]
if pick not in day.index:
    pick = day.index[0]
r = day.loc[pick]
tk_df = ind[ind["ticker"] == pick]
b_df = ind[ind["ticker"] == r["bench"]]
upto = tk_df[tk_df["date"] <= asof]
ret_b = r["bench_ret"]
chosen = bool(r["selected"])


def reason(ok: bool, title: str, body: str) -> str:
    mark = '<span class="ok">✓</span>' if ok else '<span class="ng">✕</span>'
    return f'<div class="reason{"" if ok else " fail"}">{mark}<div><b>{title}</b><div class="rs-sub">{body}</div></div></div>'


trend_gap = r["sma60"] / r["sma120"] - 1
gap20 = r["close"] / r["sma20"] - 1
rows = [
    reason(True, "돈이 몰리는 종목",
           f"최근 20일 평균 거래대금 ${r['dv_avg'] / 1e9:,.1f}B · S&amp;P 500 중 <b>{int(r['dv_rank'])}위</b> (기준: 상위 {p.ext_top})"),
    reason(r["ok_trend"], "중기 상승 추세" if r["ok_trend"] else "중기 상승 추세 아님",
           f"60일선 {money(r['sma60'])} {'&gt;' if r['ok_trend'] else '&lt;'} 120일선 {money(r['sma120'])} ({pct(trend_gap)})"),
    reason(r["ok_above20"], "단기 흐름 유지" if r["ok_above20"] else "단기 흐름 이탈",
           f"종가 {money(r['close'])} {'&gt;' if r['ok_above20'] else '&lt;'} 20일선 {money(r['sma20'])} "
           f"({pct(abs(gap20), False)} {'위' if gap20 >= 0 else '아래'})"),
    reason(r["ok_strong"], "지수보다 강함" if r["ok_strong"] else "지수보다 약함",
           f"최근 20일 수익률 <b class=\"{chg_cls(r['ret_rs'])}\">{pct(r['ret_rs'])}</b> vs {INDEX_NAME[r['bench']]} {pct(ret_b)}"
           f" → <b class=\"{chg_cls(r['excess'])}\">{r['excess'] * 100:+.1f}%p</b>"
           + (f" · 통과 종목 중 {int(r['rs_rank'])}위" if pd.notna(r["rs_rank"]) else "")),
]
if r["pass_all"] and not chosen:
    rows.append(reason(False, "순위·업종 한도에서 제외", esc(r["drop_reason"])))

status = ('<span class="tag green">선정</span>' if chosen
          else f'<span class="tag red">탈락</span><span class="drop">{esc(r["drop_reason"])}</span>')
badge = '<span class="badge top">TOP 10</span>' if r["top10"] else ""
h(f"""
<div class="card{' core' if r['top10'] else ''}">
  <div class="card-head">
    <div>
      <div class="ticker">{esc(pick)} {badge} <span class="rank">거래대금 {int(r['dv_rank'])}위</span></div>
      <div class="name">{esc(r['name'])} · {esc(r['sector'])} · 비교 지수 {INDEX_NAME[r['bench']]}</div>
      <div style="margin-top:10px">{status}</div>
    </div>
    <div class="price">
      <div class="label">{asof:%m/%d} 종가</div>
      <div class="value">{money(r['close'])}</div>
    </div>
  </div>
  <div class="reasons">
    <div class="reasons-title">{'왜 선정했나요?' if chosen else '왜 탈락했나요?'}</div>
    {''.join(rows)}
  </div>
</div>
""")

# 차트 1: 가격 + 이동평균 (+ 선정 종목이면 매수 구간) (+ 기준일 이후 흐름)
before = upto.tail(120)
after = tk_df[tk_df["date"] > asof].head(60)
fig = candle_chart(before, after, height=420)
if chosen:
    x0 = asof + pd.Timedelta(hours=12)
    x1 = asof + pd.offsets.BDay(3)
    fig.add_shape(type="rect", x0=x0, x1=x1, y0=r["zone2"], y1=r["zone1"],
                  fillcolor="rgba(34,197,94,0.22)", line=dict(color="#22C55E", width=1))
    fig.add_annotation(x=x0, y=r["zone1"], text=f"살 가격 {r['zone1']:,.2f} / {r['zone2']:,.2f}",
                       showarrow=False, yshift=12, xanchor="left", font=dict(size=11, color="#22C55E"))
fig.add_vline(x=asof, line=dict(color="#FACC15", width=1, dash="dot"))
fig.add_annotation(x=asof, y=1, yref="paper", text="기준일", showarrow=False, yshift=8,
                   font=dict(color="#FACC15", size=11))
fig.update_layout(margin=dict(l=0, r=64, t=24, b=0))
show_chart(fig, use_container_width=True, config={"displayModeBar": False},
                key=f"price_{pick}_{asof:%Y%m%d}")
h('<div class="legend-note">최근 6개월 일봉 · 주황 20일선(팔 기준) · 파랑 60일선 · 보라 120일선 · '
  '노란 점선 = 기준일 · 초록 상자 = 살 가격 구간(선정 종목만) · 흐린 캔들 = 기준일 이후 실제 흐름</div>')

# 차트 2: 최근 20일 지수 대비 상대 성과
w = upto.tail(p.rs_days + 1)
wb = b_df[b_df["date"].isin(w["date"])]
rfig = go.Figure()
rfig.add_scatter(x=w["date"], y=(w["close"] / w["close"].iloc[0] - 1) * 100, name=pick,
                 line=dict(color="#22C55E" if r["ok_strong"] else "#F05252", width=2.5))
rfig.add_scatter(x=wb["date"], y=(wb["close"] / wb["close"].iloc[0] - 1) * 100,
                 name=INDEX_NAME[r["bench"]], line=dict(color="#8A93A6", width=2, dash="dot"))
rfig.add_hline(y=0, line=dict(color="#3A4459", width=1))
rfig.update_layout(height=230, margin=dict(l=0, r=0, t=26, b=0), yaxis=dict(ticksuffix="%"),
                   title=dict(text=f"최근 {p.rs_days}일 수익률: {pick} vs {INDEX_NAME[r['bench']]}",
                              font=dict(size=13)),
                   legend=dict(orientation="h", y=-0.2))
show_chart(rfig, use_container_width=True, config={"displayModeBar": False},
                key=f"rs_{pick}_{asof:%Y%m%d}")

# 매매 계획 + (과거 날짜면) 실제 결과 — 선정 종목만
if chosen:
    loss = (r["zone1"] - r["sma20"]) / r["zone1"]
    plan_note = (f"① 가격에 사면 예상 손실 약 <b>{pct(loss, False)}</b>"
                 if r["good_entry"] else "⚠ 살 가격이 이미 손절선보다 낮아요. 사자마자 팔아야 할 수 있어 규칙상 애매해요.")
    o = simulate(tk_df, asof, r["zone1"], r["zone2"])
    if o["status"] in ("청산", "보유 중"):
        ret_cls = chg_cls(o["ret"])
        tail = (f"{o['exit_date']:%m/%d} 종가 {money(o['exit'])}에 매도 ({o['days']}거래일 보유)"
                if o["status"] == "청산" else f"최신 종가 {money(o['exit'])} 기준 ({o['days']}거래일째)")
        outcome = (f'<div class="outcome"><span class="tag {"green" if o["ret"] >= 0 else "red"}">{o["status"]}</span>'
                   f'<b class="{ret_cls}">{pct(o["ret"])}</b> · {o["fill_date"]:%m/%d} {o["fills"]}회 체결 '
                   f'(평균 {money(o["entry"])}) → {tail}</div>')
    else:
        outcome = f'<div class="outcome"><span class="tag amber">{o["status"]}</span>{esc(o["detail"])}</div>'
    earn_note = ""
    if is_latest:
        e = earnings.set_index("ticker")["next_earnings"].get(pick) if len(earnings) else None
        if e is not None and pd.notna(e) and np.busday_count(asof.date(), pd.Timestamp(e).date()) <= p.earnings_warn_days:
            earn_note = '<div class="note warn">⚠ 2거래일 안에 실적 발표가 있어요. 가격이 크게 튈 수 있어요.</div>'
    h(f"""
<div class="card">
  <div class="reasons-title">매매 계획</div>
  <div class="levels">
    <div class="level buy"><div class="k">① 살 가격 · 절반</div><div class="v">{money(r['zone1'])}</div><div class="s">-{p.zone1_pct}%</div></div>
    <div class="level buy"><div class="k">② 살 가격 · 절반</div><div class="v">{money(r['zone2'])}</div><div class="s">-{p.zone2_pct}%</div></div>
    <div class="level stop"><div class="k">손절선 · 20일선</div><div class="v">{money(r['sma20'])}</div><div class="s">종가 기준 이탈 시 매도</div></div>
  </div>
  <div class="note">{plan_note}</div>{earn_note}
  <div class="reasons-title" style="margin-top:18px">규칙대로 했다면</div>
  {outcome}
</div>
""")
else:
    h('<div class="empty" style="padding:18px">탈락 종목이라 매매 계획은 없어요.</div>')

# ══ ③ 지난 기록 ═══════════════════════════════════════
hist = history(mtime)
h('<div class="section-title" style="margin-top:34px">③ 지난 기록</div>')
h('<div class="section-sub">날마다 선정된 종목을 규칙대로 매매했다면 어땠는지 되짚어 봐요. '
  '다음 거래일 하루만 지정가가 유효하고, 종가가 20일선 아래로 마감하면 전량 매도한다고 가정했어요.</div>')
period = st.segmented_control("기간", ["1개월", "3개월", "6개월", "전체"], default="3개월",
                              label_visibility="collapsed")
days_back = {"1개월": 21, "3개월": 63, "6개월": 126, "전체": len(dates)}[period or "3개월"]
start = dates[max(0, dates.index(asof) - days_back + 1)]
hv = hist[(hist["date"] >= start) & (hist["date"] <= asof)]
filled = hv[hv["status"].isin(["청산", "보유 중"])]
closed = hv[hv["status"] == "청산"]
win_rate = (closed["ret"] > 0).mean() if len(closed) else np.nan
h(f"""
<div class="stats four">
  <div class="stat"><div class="k">선정</div><div class="v">{len(hv)}건</div></div>
  <div class="stat"><div class="k">체결률</div><div class="v">{(len(filled) / len(hv) * 100 if len(hv) else 0):.0f}%</div></div>
  <div class="stat"><div class="k">승률 (청산 기준)</div><div class="v">{'-' if np.isnan(win_rate) else f'{win_rate * 100:.0f}%'}</div></div>
  <div class="stat"><div class="k">평균 수익 (체결 기준)</div><div class="v {chg_cls(filled['ret'].mean() if len(filled) else 0)}">{pct(filled['ret'].mean()) if len(filled) else '-'}</div></div>
</div>
""")
if len(hv):
    tv = hv.sort_values(["date", "ticker"], ascending=[False, True])
    st.dataframe(
        pd.DataFrame({
            "선정일": tv["date"].dt.strftime("%Y-%m-%d"),
            "종목": [("★ " if t else "") + k for k, t in zip(tv["ticker"], tv["top10"])],
            "이름": tv["name"],
            "결과": tv["status"],
            "수익률": [f"{x * 100:+.1f}%" if pd.notna(x) else "–" for x in pd.to_numeric(tv["ret"], errors="coerce")],
            "보유일": [f"{int(x)}일" if pd.notna(x) else "–" for x in pd.to_numeric(tv["days"], errors="coerce")],
        }),
        hide_index=True, use_container_width=True, height=320,
    )
    st.caption("★ = 거래대금 TOP 10 · 표의 날짜를 위 날짜 선택에 넣으면 그날의 선정 이유를 볼 수 있어요.")

# ── 하단 ───────────────────────────────────────────────
h('<div style="height:24px"></div>')
with st.expander("규칙과 한계"):
    st.markdown(
        """
**선정 규칙** — 거래대금(최근 20일 평균) 상위 30개 S&P 500 종목 중
60일선 > 120일선, 종가 > 20일선, 최근 20일 수익률이 지수보다 높은 종목 → 초과수익 상위 15 → 업종당 2개 → 최대 10개.
**매매** — 종가 -2.5%·-6%에 절반씩 지정가, 종가가 20일선 아래로 마감하면 매도.

**영상과 다른 점** — 영상은 지수 하락 추세면 쉬고 거래대금 상위 10개만 보지만, 여기서는 지수 필터 없이 상위 30개를 본다.

**되짚어보기의 한계**
- S&P 500 구성종목은 **현재 기준**이라, 과거에 편입·퇴출된 종목은 반영되지 않아요(생존편향).
- 실적 발표 경고는 최신 날짜에만 있어요.
- 체결은 일봉 저가로만 판단해서 실제 체결 순서와 다를 수 있고, 수수료·세금은 빠져 있어요.
"""
    )

updated = meta.get("updated_at")
upd = pd.Timestamp(updated).tz_convert("Asia/Seoul").strftime("%m월 %d일 %H:%M") if updated else "-"
f1, f2 = st.columns([3, 1], vertical_alignment="center")
with f1:
    h(f'<div class="footer">데이터 갱신 {upd} · Yahoo Finance<br>투자 자문이 아니며, 규칙이 고른 결과일 뿐이에요.</div>')
if f2.button("새로 받기", use_container_width=True):
    with st.spinner("받는 중… (약 1분)"):
        update_all(log=lambda *_: None)
    st.cache_data.clear()
    st.rerun()
