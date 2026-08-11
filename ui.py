# -*- coding: utf-8 -*-
"""
UI 레이어 — 한국 관공서 서식의 시각 언어를 웹으로 옮긴 테마.

디자인 근거
- 소재: 별지 제34호 서식. 격자 셀, 얇은 괘선, 회색 구분 밴드,
  '한글 위 / English 아래' 이중 라벨.
- 이중 라벨은 장식이 아니라 기능이다. 이용자 상당수가 한국어를 못 읽는다.
- 시그니처: 완료 시 찍히는 인주색 도장. 단, '승인/허가'가 아니라
  '작성완료'로 표기한다. 이 서류는 심사를 통과한 것이 아니기 때문.
- 상단 구조는 국민비서를 참조했다. 서비스 탭 두 개와 큰 안내 패널.
"""
import streamlit as st

# ── 색 토큰 ──────────────────────────────────────────────
DESK = "#E8EAE9"      # 책상 (배경)
PAPER = "#FFFFFF"     # 종이 (카드)
INK = "#16181A"       # 본문
MUTED = "#5F6B66"     # 영문 라벨·보조
RULE = "#C9CFCB"      # 괘선
BAND = "#DCE0DE"      # 서식의 회색 구분 밴드
OFFICIAL = "#14508C"  # 관공서 청색 (강조)
SEAL = "#B32020"      # 인주색 (완료 도장 전용)
HERO_BG = "#EDF2F8"   # 안내 패널 배경 (청색 계열 옅은 톤)

FONT_CSS = """
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css');
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
"""


def inject_theme():
    st.markdown(
        f"""<style>
{FONT_CSS}

:root {{
  --desk:{DESK}; --paper:{PAPER}; --ink:{INK}; --muted:{MUTED};
  --rule:{RULE}; --band:{BAND}; --official:{OFFICIAL}; --seal:{SEAL};
  --hero:{HERO_BG};
}}

html, body, [class*="css"], .stApp {{
  font-family:'Pretendard Variable', Pretendard, -apple-system, sans-serif;
  color:var(--ink);
}}
.stApp {{ background:var(--desk); }}

/* 본문을 '종이' 위에 올린다 */
.stMainBlockContainer {{
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:2px;
  padding:2.6rem 2.4rem 3.2rem;
  max-width:820px;
  box-shadow:0 1px 0 rgba(0,0,0,.04), 0 12px 28px -22px rgba(0,0,0,.5);
}}
@media (max-width:640px){{
  .stMainBlockContainer{{ padding:1.5rem 1.1rem 2.2rem; border-left:0; border-right:0; }}
}}

/* 서식 상단 머리글 */
.doc-eyebrow {{
  font-family:'IBM Plex Mono',monospace; font-size:.68rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted); margin-bottom:.55rem;
}}
.doc-title {{
  font-family:'IBM Plex Sans KR',sans-serif; font-weight:600;
  font-size:1.55rem; line-height:1.24; letter-spacing:-.02em; margin:0;
}}
.doc-title-en {{
  font-size:.84rem; color:var(--muted); margin-top:.3rem; letter-spacing:.01em;
}}
.doc-rule {{ height:2px; background:var(--ink); margin:1.0rem 0 0; }}
.doc-rule-thin {{ height:1px; background:var(--rule); margin:.25rem 0 1.2rem; }}

/* ── 상단 서비스 탭 (국민비서식 가로 메뉴) ───────────────
   .st-key-service_nav 로 범위를 좁힌다. 이렇게 하지 않으면
   상담 화면의 '성별' 라디오까지 탭처럼 보인다. */
.st-key-service_nav div[role="radiogroup"] {{
  display:flex; gap:0; border-bottom:2px solid var(--rule); margin:0 0 1.8rem;
}}
.st-key-service_nav div[role="radiogroup"] > label {{
  flex:1; justify-content:center; margin:0; padding:.8rem .4rem;
  border-bottom:3px solid transparent;
}}
.st-key-service_nav div[role="radiogroup"] > label > div:first-child {{
  display:none;   /* 라디오 동그라미 숨김 */
}}
.st-key-service_nav div[role="radiogroup"] > label p {{
  font-size:1.02rem !important; font-weight:600; color:var(--muted);
}}
.st-key-service_nav div[role="radiogroup"] > label:has(input:checked) {{
  border-bottom-color:var(--official);
}}
.st-key-service_nav div[role="radiogroup"] > label:has(input:checked) p {{
  color:var(--official);
}}

/* ── 큰 안내 패널 ────────────────────────────────────── */
.hero {{
  background:var(--hero); border:1px solid #D6E0EC; border-radius:3px;
  padding:1.9rem 1.8rem; margin:0 0 1.1rem;
}}
.hero .eyebrow {{
  font-size:.8rem; color:var(--official); font-weight:600;
  letter-spacing:.01em; margin-bottom:.5rem;
}}
.hero .title {{
  font-family:'IBM Plex Sans KR',sans-serif; font-weight:600;
  font-size:1.62rem; line-height:1.3; letter-spacing:-.02em; margin:0;
}}
.hero .sub {{
  font-size:.95rem; color:#3C4A55; margin-top:.7rem; line-height:1.65;
}}
.hero .sub-en {{
  font-size:.82rem; color:var(--muted); margin-top:.35rem; line-height:1.55;
}}
@media (max-width:640px){{
  .hero {{ padding:1.4rem 1.1rem; }}
  .hero .title {{ font-size:1.32rem; }}
}}

/* 이용방법 단계 */
.howto {{ display:flex; gap:.7rem; flex-wrap:wrap; margin:.2rem 0 .3rem; }}
.howto-step {{
  flex:1 1 150px; background:var(--paper); border:1px solid var(--rule);
  border-radius:2px; padding:.85rem .9rem;
}}
.howto-step .n {{
  font-family:'IBM Plex Mono',monospace; font-size:.72rem; font-weight:500;
  color:var(--official); display:block; margin-bottom:.3rem;
}}
.howto-step .k {{ font-size:.9rem; font-weight:600; display:block; line-height:1.35; }}
.howto-step .e {{ font-size:.72rem; color:var(--muted); display:block; margin-top:.2rem; }}
.howto-step .d {{ font-size:.8rem; color:#3C4A55; display:block; margin-top:.4rem; line-height:1.5; }}

/* 진행 레일 — 실제 순서가 있는 절차라 번호를 쓴다 */
.rail {{ display:flex; gap:0; margin:0 0 2rem; border:1px solid var(--rule); }}
.rail-step {{
  flex:1; padding:.6rem .5rem .55rem; text-align:center;
  border-right:1px solid var(--rule); background:var(--paper);
}}
.rail-step:last-child {{ border-right:0; }}
.rail-step .n {{
  font-family:'IBM Plex Mono',monospace; font-size:.7rem; font-weight:500;
  display:block; margin-bottom:.12rem;
}}
.rail-step .k {{ font-size:.76rem; font-weight:600; display:block; line-height:1.3; }}
.rail-step .e {{ font-size:.6rem; color:var(--muted); display:block; letter-spacing:.02em; }}
.rail-step.todo {{ background:#F3F5F4; }}
.rail-step.todo .n, .rail-step.todo .k {{ color:#A6AEAA; }}
.rail-step.todo .e {{ color:#BCC3BF; }}
.rail-step.now {{ background:var(--official); }}
.rail-step.now .n, .rail-step.now .k, .rail-step.now .e {{ color:#fff; }}
.rail-step.done .n, .rail-step.done .k {{ color:var(--official); }}

/* 구역 제목 — 서식의 회색 밴드 */
.band {{
  background:var(--band); border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);
  padding:.42rem .8rem; margin:1.9rem 0 1.1rem;
  display:flex; align-items:baseline; gap:.6rem;
}}
.band .k {{ font-weight:600; font-size:.95rem; }}
.band .e {{ font-size:.72rem; color:var(--muted); }}

/* 완료된 단계 요약 줄 */
.recap {{
  display:flex; justify-content:space-between; gap:1rem;
  border-bottom:1px dotted var(--rule); padding:.42rem 0; font-size:.85rem;
}}
.recap .l {{ color:var(--muted); }}
.recap .v {{ font-family:'IBM Plex Mono',monospace; font-weight:500; text-align:right; }}

/* 도장 — 시그니처 요소 */
@keyframes press {{
  0%   {{ transform:scale(1.5) rotate(-14deg); opacity:0; }}
  55%  {{ transform:scale(.94) rotate(-7deg); opacity:1; }}
  100% {{ transform:scale(1) rotate(-7deg); opacity:1; }}
}}
.seal-wrap {{ display:flex; justify-content:center; margin:1.4rem 0 .4rem; }}
.seal {{
  width:96px; height:96px; border-radius:50%;
  border:3px solid var(--seal); box-shadow:inset 0 0 0 2.5px var(--seal);
  color:var(--seal); display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:.1rem;
  animation:press .5s cubic-bezier(.2,1.5,.4,1) both;
  opacity:.88;
}}
.seal .big {{ font-family:'IBM Plex Sans KR',sans-serif; font-weight:600; font-size:1.15rem; letter-spacing:.04em; }}
.seal .small {{ font-family:'IBM Plex Mono',monospace; font-size:.52rem; letter-spacing:.1em; }}
@media (prefers-reduced-motion:reduce) {{ .seal {{ animation:none; }} }}

/* 버튼 */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {{
  border-radius:2px; border:1px solid var(--ink); background:var(--ink);
  color:var(--paper); font-weight:600; letter-spacing:-.01em;
  transition:background .12s ease;
}}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
  background:var(--official); border-color:var(--official); color:#fff;
}}
.stButton button:disabled {{
  background:#EDEFEE; border-color:var(--rule); color:#A6AEAA;
}}
.stDownloadButton button {{ background:var(--official); border-color:var(--official); }}

/* 입력 */
.stTextInput input, .stSelectbox div[data-baseweb="select"] > div {{
  border-radius:2px; border-color:var(--rule); background:#FCFDFC;
}}
.stTextInput input:focus {{ border-color:var(--official); box-shadow:none; }}
.stTextInput label, .stSelectbox label, .stRadio label {{
  font-size:.8rem !important; font-weight:600;
}}

/* 파일 업로더 */
[data-testid="stFileUploaderDropzone"] {{
  border:1.5px dashed var(--rule); border-radius:2px; background:#FBFCFB;
}}

/* 채팅 */
[data-testid="stChatMessage"] {{
  background:#FBFCFB; border:1px solid var(--rule); border-radius:2px;
}}

/* 사이드바 */
[data-testid="stSidebar"] {{ background:#DFE3E1; border-right:1px solid var(--rule); }}

/* Streamlit 기본 장식 제거 */
[data-testid="stHeader"] {{ background:transparent; }}
[data-testid="stDecoration"] {{ display:none; }}
footer {{ visibility:hidden; }}
</style>""",
        unsafe_allow_html=True,
    )


def masthead():
    st.markdown(
        """<div class="doc-eyebrow">출입국관리법 시행규칙 별지 제34호서식</div>
<h1 class="doc-title">국민비서 유학생편</h1>
<div class="doc-title-en">Public Service Assistant for International Students</div>
<div class="doc-rule"></div><div class="doc-rule-thin"></div>""",
        unsafe_allow_html=True,
    )


def hero(eyebrow, title, sub, sub_en=""):
    """서비스 상단의 큰 안내 패널."""
    en = f'<div class="sub-en">{sub_en}</div>' if sub_en else ""
    st.markdown(
        f"""<div class="hero">
<div class="eyebrow">{eyebrow}</div>
<div class="title">{title}</div>
<div class="sub">{sub}</div>{en}
</div>""",
        unsafe_allow_html=True,
    )


def howto(steps):
    """이용방법. steps: [(번호, 한글, English, 설명), ...]"""
    with st.expander("이용방법 알아보기 · How it works", expanded=False):
        html = ['<div class="howto">']
        for n, ko, en, desc in steps:
            html.append(
                f'<div class="howto-step"><span class="n">{n}</span>'
                f'<span class="k">{ko}</span><span class="e">{en}</span>'
                f'<span class="d">{desc}</span></div>'
            )
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)


STEPS = [
    ("신분증 확인", "Scan ID"),
    ("정보 입력", "Verify"),
    ("서류 상담", "Consult"),
    ("신청서 발급", "Generate"),
]


def rail(current):
    """current: 1~4. 현재 단계를 강조하고 완료 단계는 청색 처리."""
    html = ['<div class="rail">']
    for i, (ko, en) in enumerate(STEPS, start=1):
        cls = "done" if i < current else ("now" if i == current else "todo")
        html.append(
            f'<div class="rail-step {cls}"><span class="n">{i:02d}</span>'
            f'<span class="k">{ko}</span><span class="e">{en}</span></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def band(ko, en):
    st.markdown(
        f'<div class="band"><span class="k">{ko}</span><span class="e">{en}</span></div>',
        unsafe_allow_html=True,
    )


def recap(rows):
    """완료된 단계를 접힌 요약으로 보여준다. rows: [(라벨, 값), ...]"""
    out = []
    for label, value in rows:
        if value:
            out.append(
                f'<div class="recap"><span class="l">{label}</span>'
                f'<span class="v">{value}</span></div>'
            )
    if out:
        st.markdown("".join(out), unsafe_allow_html=True)


def seal():
    """작성 완료 도장. '승인'이 아니라 '작성완료'인 점이 중요하다."""
    st.markdown(
        '<div class="seal-wrap"><div class="seal">'
        '<span class="big">작성완료</span>'
        '<span class="small">DRAFTED</span></div></div>',
        unsafe_allow_html=True,
    )