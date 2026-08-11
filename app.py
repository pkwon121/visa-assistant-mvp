import os
import re
import json
import hashlib

import streamlit as st
from dotenv import load_dotenv

# 🚀 구글 클라우드 Vertex AI 전용 라이브러리
import vertexai
from vertexai.generative_models import GenerativeModel, Part

from form_filler import fill_application
from arc_utils import normalize
import ui
import sms
import notify_store
import rag_search
import guardrails

load_dotenv()
st.set_page_config(page_title="유학생 체류기간 연장 신청서", page_icon="📄",
                   layout="centered")
ui.inject_theme()

# 실행 위치와 무관하게 항상 이 파일 기준으로 경로를 잡는다
APP_VERSION = "v9 · 2026-08-11 · Vertex AI Search RAG 연동"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "template.docx")

SERVICE_URL = os.getenv("SERVICE_URL", "https://우리팀웹주소.com")


# ----------------------------------------
# 서비스 카탈로그
# ----------------------------------------
# 항목을 늘릴 때 이 두 표에 한 줄을 더하면 화면·저장·발송 경로가 따라온다.
NOTIFY_TOPICS = [
    {
        "id": "visa_expiry",
        "ko": "체류기간 만료 알림",
        "en": "Period of stay expiry",
        "desc": "체류기간 만료 60일·30일·7일 전에 문자로 알려드립니다.",
    },
]

CONSULT_TOPICS = [
    {
        "id": "visa_extension",
        "ko": "체류기간 연장 신청서 자동 작성",
        "en": "Extension application assistant",
        "desc": "외국인등록증을 촬영하면 필요한 서류를 안내하고 "
                "법무부 통합신청서를 자동으로 채워 드립니다.",
    },
]

SERVICES = [("notify", "알림서비스"), ("consult", "상담서비스")]
SERVICE_LABELS = [label for _, label in SERVICES]
SERVICE_BY_LABEL = {label: key for key, label in SERVICES}


@st.cache_resource
def get_reminder_store():
    """Streamlit은 조작마다 스크립트를 처음부터 다시 실행한다.
    캐시하지 않으면 화면을 건드릴 때마다 Firestore 클라이언트가 새로 만들어진다.
    설정이 없으면 None을 돌려주고, 호출부는 알림 구역을 조용히 감춘다."""
    return notify_store.get_store()


# ----------------------------------------
# 🧠 1. Vision Agent 셋업 (Vertex AI)
# ----------------------------------------
# Cloud Shell은 프로젝트를 자동 상속하지만 Cloud Run은 상속하지 않으므로 명시한다.
vertexai.init(
    project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
    location=os.getenv("VERTEX_LOCATION", "asia-northeast3"),
)

VISION_PROMPT = """
너는 대한민국 외국인등록증(ARC) 정보 추출 전문가야.
이미지에서 아래 항목을 읽어 반드시 JSON으로만 대답해.
설명, 마크다운(```), 그 어떤 부가 텍스트도 절대 붙이지 마.

[추출 규칙]
- 읽을 수 없거나 카드에 없는 항목은 반드시 빈 문자열 ""로 둬. 절대 추측하거나 지어내지 마.
- name: 카드에 인쇄된 영문 이름을 그대로. 대문자 유지. 성이 먼저 오는 순서 그대로 적어.
- arc_no: 외국인등록번호. 하이픈 포함 13자리 숫자 (예: 901231-5123456).
  카드 앞면 상단에 가장 크게 인쇄된 번호야. 여권번호와 헷갈리지 마.
- visa_type: 체류자격. 'D-2'로 퉁치지 말고 괄호 안 세부코드(D-2-6, D-4-1, D-10-1 등)까지 끝까지 찾아.
  세부코드가 정말 없으면 대분류만.
- issue_date / expiry_date: YYYY-MM-DD 형식으로 변환해서.
  expiry_date는 '체류기간 만료일' 항목이야.

{
  "name": "",
  "nationality": "",
  "visa_type": "",
  "arc_no": "",
  "issue_date": "",
  "expiry_date": ""
}
"""


def extract_info_from_image(file_bytes, mime_type):
    """ARC 이미지에서 정보를 추출해 dict로 반환."""
    model = GenerativeModel("gemini-2.5-flash")
    image_part = Part.from_data(data=file_bytes, mime_type=mime_type)

    response = model.generate_content([image_part, VISION_PROMPT])

    raw = ""
    try:
        raw = response.text
        clean_text = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except json.JSONDecodeError:
        return {"error": "JSON 파싱 실패", "details": raw}
    except Exception as e:
        return {"error": "추출 실패", "details": f"{type(e).__name__}: {e}"}


# ----------------------------------------
# ⚖️ Policy Agent: 비자 코드 → 카테고리 매핑
# 매뉴얼 실체는 더 이상 로컬 txt가 아니라 Vertex AI Search 앱이다.
# 비자코드별로 데이터 스토어·앱을 완전히 분리해뒀기 때문에(rag_search.py 참고),
# 여기서는 비자코드만 결정하면 되고 다른 코드의 서류가 섞일 방법이 없다.
# ----------------------------------------
VISA_ROUTES = [
    ("D-10", "D-10 구직"),
    ("D-2", "D-2 유학"),
    ("D-4", "D-4 일반연수"),
]


# 상담 완료 신호. 프롬프트에서 AI에게 이 문장을 말하도록 지시해 둔다.
DONE_PHRASE = "서류가모두파악되었습니다"


def _squash(text):
    """공백·줄바꿈을 제거해 표기 흔들림에 강하게 만든다."""
    return re.sub(r"\s+", "", text or "")


def interview_complete():
    """AI가 완료 문장을 말했는지 대화 기록에서 확인.
    messages는 비자 변경·재스캔 시 초기화되므로 별도 플래그가 필요 없다."""
    for m in st.session_state.get("messages", []):
        if m.get("role") == "assistant" and DONE_PHRASE in _squash(m.get("content")):
            return True
    return False


def resolve_manual(visa_raw):
    """체류자격 문자열에서 비자코드와 카테고리를 결정.
    D-10을 먼저 검사해야 D-1 계열과 혼동되지 않는다."""
    v = (visa_raw or "").upper().replace(" ", "")
    for prefix, category in VISA_ROUTES:
        if prefix in v:
            return prefix, category
    return None, None


# ----------------------------------------
# 🛠️ 관리자 패널 — ?admin=1 로 접속했을 때만 노출
# 실제 운영에서는 만료 알림을 Cloud Scheduler + Cloud Run Job(notify.py)이 발송한다.
# 사람이 버튼을 눌러 보내는 건 시연용일 뿐이므로 학생 화면에서 감춘다.
# ----------------------------------------
if st.query_params.get("admin") == "1":
    st.sidebar.markdown("### 관리자 · Admin")
    st.sidebar.caption("운영 시에는 Cloud Scheduler 배치가 자동 발송합니다.")
    phone_number = st.sidebar.text_input("수신 번호", placeholder="01012345678")

    if st.sidebar.button("만료 알림 문자 보내기"):
        if phone_number:
            with st.spinner("문자 발송 중..."):
                is_success, error_msg = sms.send_sms(
                    phone_number, sms.build_message("D-30", SERVICE_URL)
                )
            if is_success:
                st.sidebar.success(f"{phone_number}로 발송했습니다.")
            else:
                st.sidebar.error("발송하지 못했습니다.")
                st.sidebar.code(error_msg)
        else:
            st.sidebar.error("번호를 입력하세요.")

    if st.sidebar.button("상담 잠금 해제"):
        st.session_state["force_unlock"] = True
        st.rerun()

    if st.sidebar.button("세션 비우기"):
        st.session_state.clear()
        st.rerun()


# ----------------------------------------
# 수신거부 — 알림 문자 하단 링크로 들어온다.
# 토큰을 심지 않고 번호만으로 처리한다. 문자에 든 토큰은 유출 위험만 키운다.
# ----------------------------------------
if st.query_params.get("unsub") == "1":
    ui.masthead()
    ui.band("수신거부", "Unsubscribe")
    st.markdown(
        "알림 수신을 중단합니다. 신청하신 휴대전화 번호를 입력해주세요.  \n"
        "<span style='color:#5F6B66;font-size:.85rem'>"
        "Enter the mobile number you signed up with.</span>",
        unsafe_allow_html=True,
    )
    with st.form("unsub_form"):
        unsub_phone = st.text_input("휴대전화 번호 Mobile", placeholder="010-1234-5678")
        unsub_go = st.form_submit_button("수신거부 Unsubscribe",
                                         use_container_width=True)
    if unsub_go:
        unsub_store = get_reminder_store()
        if unsub_store is None:
            st.error("지금은 처리할 수 없습니다. 잠시 후 다시 시도해주세요.")
        else:
            try:
                unsub_store.unsubscribe(unsub_phone)
            except ValueError:
                st.error("휴대전화 번호 형식이 아닙니다.")
            else:
                # 등록 여부를 알려주면 번호의 존재 여부가 새어 나가므로
                # 결과를 구분하지 않고 같은 메시지를 보여준다.
                st.success("처리했습니다. 더 이상 알림을 보내지 않습니다.")
                st.caption("Done. You will not receive further reminders.")
    st.stop()


# ----------------------------------------
# 화면 — 서비스 선택
# ----------------------------------------
ui.masthead()

# ?svc=notify 로 바로 들어올 수 있다 (문자 링크용)
if "service" not in st.session_state:
    requested = st.query_params.get("svc", "consult")
    st.session_state["service"] = requested if requested in dict(SERVICES) else "consult"

_picked = st.radio(
    "서비스", SERVICE_LABELS,
    index=[k for k, _ in SERVICES].index(st.session_state["service"]),
    horizontal=True, label_visibility="collapsed", key="service_nav",
)
st.session_state["service"] = SERVICE_BY_LABEL[_picked]


def render_reminder_form(default_expiry="", default_visa="", key_prefix="rm"):
    """알림 신청 폼. 알림서비스 화면과 상담 완료 화면에서 함께 쓴다.
    반환값: 신청 성공 여부(bool). 실패·미제출이면 False."""
    store = get_reminder_store()
    if store is None:
        st.info("지금은 알림 신청을 받을 수 없습니다. 잠시 후 다시 시도해주세요.")
        st.caption("Reminder sign-up is temporarily unavailable.")
        return False

    st.caption(
        "수집 항목: 휴대전화 번호, 체류기간 만료일, 체류자격 대분류 · "
        "이용 목적: 만료 사전 알림 문자 발송 · "
        "보유 기간: 만료일 이후 30일까지 보관 후 자동 파기 · "
        "동의하지 않아도 다른 기능 이용에는 제한이 없습니다."
    )

    with st.form(f"{key_prefix}_form"):
        phone = st.text_input("휴대전화 번호 Mobile", placeholder="010-1234-5678")
        expiry = st.text_input(
            "체류기간 만료일 Expiry date", value=default_expiry,
            placeholder="2027-03-15",
            help="외국인등록증에 적힌 체류기간 만료일을 입력하세요.",
        )
        visa = st.text_input("체류자격 Status", value=default_visa,
                             placeholder="D-2", help="선택 사항입니다.")
        agree = st.checkbox("위 내용에 동의합니다 · I agree")
        go = st.form_submit_button("알림 신청하기", use_container_width=True)

    if not go:
        return False
    if not agree:
        st.error("개인정보 수집·이용에 동의해야 신청할 수 있습니다.")
        return False

    try:
        store.subscribe(phone, expiry, visa_category=visa)
    except ValueError as exc:
        st.error(str(exc))
        return False
    except Exception:
        st.error("신청하지 못했습니다. 잠시 후 다시 시도해주세요.")
        return False

    # 확인 문자를 바로 보낸다. 번호를 잘못 적었으면
    # 60일 뒤가 아니라 지금 알 수 있어야 한다.
    sent_ok, _ = sms.send_sms(
        phone, sms.build_welcome_message(expiry, SERVICE_URL))
    st.session_state["reminder_done"] = True
    st.session_state["reminder_sms_ok"] = sent_ok
    st.rerun()


def render_reminder_result():
    """신청 완료 화면."""
    st.success("알림을 신청했습니다. 만료 60일·30일·7일 전에 문자로 알려드립니다.")
    st.caption("We'll text you 60, 30 and 7 days before your permit expires.")
    if st.session_state.get("reminder_sms_ok"):
        st.caption("확인 문자를 보냈습니다. 받지 못하셨다면 번호를 다시 확인해주세요. "
                   "· A confirmation text has been sent.")
    else:
        st.warning(
            "신청은 접수되었지만 확인 문자를 보내지 못했습니다. "
            "번호가 맞는지 확인해주세요.  \n"
            "Your reminder is saved, but we couldn't send the confirmation text."
        )


# ----------------------------------------
# 알림서비스
# ----------------------------------------
if st.session_state["service"] == "notify":
    ui.hero(
        "알림서비스 · Reminder service",
        "기한을 놓치지 마세요",
        "체류기간 만료일이 다가오면 문자로 알려드립니다. "
        "회원가입도, 앱 설치도, 로그인도 필요하지 않습니다.",
        "We'll text you before your period of stay expires. "
        "No sign-up, no app, no login.",
    )
    ui.howto([
        ("01", "번호와 만료일 입력", "Enter your details",
         "휴대전화 번호와 외국인등록증에 적힌 체류기간 만료일을 넣습니다."),
        ("02", "확인 문자 수신", "Get a confirmation",
         "바로 확인 문자가 갑니다. 번호가 맞는지 그 자리에서 알 수 있습니다."),
        ("03", "만료 전 자동 알림", "Automatic reminders",
         "만료 60일·30일·7일 전에 문자를 보내드립니다."),
    ])

    topic = NOTIFY_TOPICS[0]

    ui.band(topic["ko"], topic["en"])
    st.markdown(topic["desc"])

    if st.session_state.get("reminder_done"):
        render_reminder_result()
        if st.button("다른 번호로 신청하기", use_container_width=True):
            st.session_state.pop("reminder_done", None)
            st.session_state.pop("reminder_sms_ok", None)
            st.rerun()
    else:
        render_reminder_form(key_prefix="svc")

    with st.expander("알림 해지 · Unsubscribe"):
        with st.form("unsub_inline"):
            u_phone = st.text_input("휴대전화 번호 Mobile",
                                    placeholder="010-1234-5678")
            u_go = st.form_submit_button("수신거부 Unsubscribe",
                                         use_container_width=True)
        if u_go:
            u_store = get_reminder_store()
            if u_store is None:
                st.error("지금은 처리할 수 없습니다.")
            else:
                try:
                    u_store.unsubscribe(u_phone)
                except ValueError:
                    st.error("휴대전화 번호 형식이 아닙니다.")
                else:
                    # 등록 여부를 알려주면 번호 존재 여부가 새어 나간다
                    st.success("처리했습니다. 더 이상 알림을 보내지 않습니다.")
                    st.caption("Done. You will not receive further reminders.")

    st.markdown('<div class="doc-rule-thin" style="margin-top:2.4rem"></div>',
                unsafe_allow_html=True)
    st.caption(f"빌드 {APP_VERSION}")
    st.stop()


# ----------------------------------------
# 상담서비스 — 현재 단계만 보여준다
# ----------------------------------------
_consult = CONSULT_TOPICS[0]
ui.hero(
    "상담서비스 · Consultation service",
    "서류 상담부터 신청서 작성까지",
    "외국인등록증을 촬영하면 필요한 서류를 안내하고, "
    "법무부 통합신청서(별지 제34호 서식)를 자동으로 채워 드립니다.",
    "Scan your residence card. We'll tell you which documents you need "
    "and fill in the official application form for you.",
)
ui.howto([
    ("01", "신분증 확인", "Scan ID",
     "외국인등록증 앞면을 촬영하면 이름·국적·등록번호를 읽어옵니다."),
    ("02", "정보 입력", "Verify",
     "읽은 내용을 확인하고, 카드에 없는 항목만 채웁니다."),
    ("03", "서류 상담", "Consult",
     "상황을 묻고, 법령과 법무부 매뉴얼에 근거해 필요한 서류를 안내합니다."),
    ("04", "신청서 발급", "Generate",
     "통합신청서를 자동으로 채워 .docx 파일로 내려받습니다."),
])

has_scan = "extracted" in st.session_state
has_data = "user_data" in st.session_state
done_chat = has_data and interview_complete()
unlocked = done_chat or st.session_state.get("force_unlock", False)

step = 1
if has_scan:
    step = 2
if has_data:
    step = 3
if unlocked:
    step = 4
ui.rail(step)


# ── 01 신분증 ────────────────────────────────────────────
if not has_scan:
    ui.band("신분증 확인", "Scan your residence card")
    st.markdown(
        "외국인등록증(ARC) **앞면**을 찍어 올려주세요. "
        "이름·국적·등록번호를 읽어 신청서에 옮겨 적습니다.  \n"
        "<span style='color:#5F6B66;font-size:.85rem'>"
        "Upload the front of your Alien Registration Card.</span>",
        unsafe_allow_html=True,
    )

uploaded_file = st.file_uploader(
    "외국인등록증 앞면", type=["jpg", "png", "jpeg"],
    label_visibility="collapsed" if has_scan else "visible",
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()

    # 같은 사진이면 재호출하지 않는다. 이 가드가 없으면 채팅 한 줄마다
    # Vision API가 다시 불린다 (Streamlit은 조작마다 전체 재실행).
    if st.session_state.get("scanned_hash") != file_hash:
        with st.spinner("신분증을 읽는 중입니다..."):
            extracted_data = extract_info_from_image(file_bytes, uploaded_file.type)

        if "error" in extracted_data:
            st.error("신분증을 읽지 못했습니다. 빛 반사가 없는 밝은 곳에서 다시 찍어주세요.")
            st.caption(str(extracted_data.get("details"))[:300])
        else:
            for key in ("user_data", "docx_bytes", "chat_session",
                        "messages", "chat_visa", "force_unlock", "reminder_done"):
                st.session_state.pop(key, None)
            st.session_state["scanned_hash"] = file_hash
            st.session_state["extracted"] = normalize(extracted_data)
            st.rerun()


# ── 02 정보 확인 ─────────────────────────────────────────
if has_scan:
    e = st.session_state["extracted"]
    saved = st.session_state.get("user_data", {})

    if has_data:
        # 이미 확정했으면 요약만 보여주고 접어둔다
        ui.band("입력한 정보", "Your details")
        ui.recap([
            ("성명 Name", f"{saved.get('surname','')} {saved.get('given_names','')}".strip()),
            ("국적 Nationality", saved.get("nationality")),
            ("체류자격 Status", saved.get("visa_type")),
            ("등록번호 ARC No.", saved.get("arc_no")),
        ])
        edit = st.toggle("정보 고치기 · Edit details", value=False)
    else:
        ui.band("정보 확인", "Check what we read")
        st.markdown(
            "읽은 내용이 맞는지 확인하고, 신분증에 없는 항목을 채워주세요.  \n"
            "<span style='color:#5F6B66;font-size:.85rem'>"
            "Correct anything wrong, then fill in what the card doesn't show.</span>",
            unsafe_allow_html=True,
        )
        edit = True

    if edit:
        def prefill(key, default=""):
            return saved.get(key) or e.get(key) or default

        with st.form("confirm_form"):
            st.markdown("**신분증에서 읽은 정보** · From the card")
            c1, c2 = st.columns(2)
            surname = c1.text_input("성 Surname", prefill("surname"))
            given = c2.text_input("명 Given names", prefill("given_names"))

            c1, c2 = st.columns(2)
            nationality = c1.text_input("국적 Nationality", prefill("nationality"))
            arc_no = c2.text_input(
                "외국인등록번호 ARC No.", prefill("arc_no"),
                help="13자리를 넣으면 생년월일과 성별이 자동으로 계산됩니다.",
            )

            c1, c2 = st.columns(2)
            visa_type = c1.text_input("체류자격 Status", prefill("visa_type"))
            expiry_date = c2.text_input("체류기간 만료일 Expiry", prefill("expiry_date"),
                                        placeholder="2027-03-15")

            c1, c2, c3 = st.columns(3)
            by = c1.text_input("생년 YYYY", prefill("birth_yyyy"))
            bm = c2.text_input("월 MM", prefill("birth_mm"))
            bd = c3.text_input("일 DD", prefill("birth_dd"))

            sex = st.radio("성별 Sex", ["M", "F"],
                           index=1 if prefill("sex") == "F" else 0, horizontal=True)

            st.markdown("**여권** · Passport")
            c1, c2, c3 = st.columns(3)
            passport_no = c1.text_input("여권번호 No.", prefill("passport_no"))
            passport_issue = c2.text_input("발급일자 Issued", prefill("passport_issue"),
                                           placeholder="2022.04.14")
            passport_expiry = c3.text_input("유효기간 Expiry", prefill("passport_expiry"),
                                            placeholder="2033.04.30")

            st.markdown("**연락처와 주소** · Contact")
            address_kr = st.text_input("대한민국 내 주소 Address in Korea",
                                       prefill("address_kr"))
            c1, c2 = st.columns(2)
            cell_phone = c1.text_input("휴대 전화 Mobile", prefill("cell_phone"),
                                       placeholder="010-1234-5678")
            tel = c2.text_input("전화 번호 Telephone", prefill("tel"),
                                help="유선전화가 없으면 비워두세요.")
            email = st.text_input("전자우편 E-mail", prefill("email"))
            address_home = st.text_input("본국 주소 Address in home country",
                                         prefill("address_home"))
            home_phone = st.text_input("본국 전화 번호 Phone", prefill("home_phone"))

            st.markdown("**학교** · School")
            c1, c2 = st.columns(2)
            school_name = c1.text_input("학교 이름 Name", prefill("school_name"))
            school_phone = c2.text_input("학교 전화 번호 Phone", prefill("school_phone"))

            c1, c2 = st.columns(2)
            school_status = c1.selectbox(
                "재학 여부 School status",
                ["해당없음 (대학·대학원생)", "미취학", "초", "중", "고"],
                help="초·중·고 재학생만 선택하세요.",
            )
            school_type = c2.selectbox(
                "학교 종류 School type", ["해당없음", "교육청 인가", "대안학교"],
                help="초·중·고 재학생만 선택하세요.",
            )

            submitted = st.form_submit_button("이 내용으로 진행하기",
                                              use_container_width=True)

        if submitted:
            if not surname or not arc_no:
                st.error("성(Surname)과 외국인등록번호를 채워주세요.")
            else:
                st.session_state["user_data"] = normalize({
                    **e,
                    "surname": surname, "given_names": given,
                    "name": f"{surname} {given}".strip(),
                    "nationality": nationality, "arc_no": arc_no,
                    "visa_type": visa_type, "expiry_date": expiry_date,
                    "birth_yyyy": by, "birth_mm": bm, "birth_dd": bd, "sex": sex,
                    "passport_no": passport_no, "passport_issue": passport_issue,
                    "passport_expiry": passport_expiry,
                    "address_kr": address_kr, "cell_phone": cell_phone, "tel": tel,
                    "email": email, "address_home": address_home,
                    "home_phone": home_phone,
                    "school_name": school_name, "school_phone": school_phone,
                    "school_status": ("" if school_status.startswith("해당없음")
                                      else school_status),
                    "school_type": "" if school_type == "해당없음" else school_type,
                })
                st.session_state.pop("docx_bytes", None)
                st.rerun()


# ----------------------------------------
# 💬 4. Interview Agent (채팅 UI & AI 소통)
# ----------------------------------------
if "user_data" in st.session_state:
    ui.band("서류 상담", "Tell us your situation")

    visa_raw = st.session_state["user_data"].get("visa_type", "").upper()

    # 🔄 비자 종류가 바뀌었으면 기존 채팅을 버리고 새로 만든다
    if st.session_state.get("chat_visa") != visa_raw:
        st.session_state.pop("chat_session", None)
        st.session_state.pop("messages", None)
        st.session_state["chat_visa"] = visa_raw

    visa_code, visa_category = resolve_manual(visa_raw)

    if visa_code is None:
        st.warning(
            f"지금은 D-2·D-4·D-10 연장만 안내할 수 있습니다. "
            f"읽은 체류자격은 '{visa_raw}'입니다. "
            "잘못 읽혔다면 위에서 고쳐주세요."
        )
    else:
        if "chat_session" not in st.session_state:
            # 검색(top-k)이 놓칠 수 있는 짧고 중요한 항목
            # (공통사항·유의사항·'이 매뉴얼에 없는 내용')은 검색에 맡기지 않고
            # 여기서 항상 고정으로 넣는다. guardrails.py 참고.
            guardrail_text = guardrails.get(visa_code)

            interview_prompt = f"""
너는 유학생의 비자 연장을 돕는 친절한 한국어 상담사(Interview Agent)이자,
규정을 해석하는 마스터(Policy Agent)야.
현재 유저는 '{visa_category}' 비자 소지자야.
유저 정보: {st.session_state['user_data']}

[항상 지켜야 할 공통 규정 — {visa_category}]
{guardrail_text}

[대화 중 전달되는 참고자료]
유저가 답할 때마다 "[참고자료]"로 시작하는 블록이 함께 전달돼.
이건 법무부 {visa_category} 매뉴얼에서 지금 질문과 관련된 부분만 검색해서
붙인 것이야 (다른 비자코드 매뉴얼은 애초에 섞여 들어올 수 없어).
서류나 심사 기준을 안내할 때는 반드시 이 [참고자료]와 위
[항상 지켜야 할 공통 규정]에 있는 내용만 근거로 삼아.
🚨 수치(학점·출석률·금액 등)를 네가 기억으로 만들어내서 묻거나 안내하지 마.
🚨 기준을 옮길 때 그것이 '혜택'인지 '제한'인지 방향을 뒤집지 마.
   (예: 어떤 기준 '이상'이면 서류가 면제되는 우대 조항을,
    그 기준 '미만'이면 불이익을 받는 것처럼 말하면 안 된다.)
🚨 참고자료가 비어 있거나 질문과 무관하면, 지어내지 말고
   [항상 지켜야 할 공통 규정]의 안내 문구만으로 답해.

[진행 단계]
1. 질문 단계: '{visa_category}' 비자의 어떤 세부 자격인지, 연장에 영향을
   미치는 현재 상태를 차근차근 물어봐.
   🚨 "학업에 어려운 점이 있나요?"처럼 뭉뚱그려 묻지 마.
   🚨 심사 기준이 학교 유형·신청자 유형에 따라 나뉘면, 유저가 어느
      유형인지 먼저 물어봐. 모르면 학교 국제처나 1345 확인을 안내하고
      네가 임의로 가정해서 진행하지 마.
2. 서류 안내 단계: 상황이 모두 파악되면 더 이상 질문하지 말고,
   참고자료·공통 규정만 근거로 '최종 필수 서류 목록'을 마크다운으로 정리해.
   🚨 세부 체류자격(예: D-2-6, D-4-3, D-10-3)별로 서류가 나뉘면
      유저의 코드에 해당하는 항목만 안내해. 다른 코드의 서류를 섞지 마.
   🚨 안내를 마친 뒤에는 반드시 아래 문장을 글자 그대로,
   토씨 하나 바꾸지 말고 마지막 줄에 출력해:
   "✅ 서류가 모두 파악되었습니다. 아래 [신청서 만들기] 버튼을 눌러주세요!"
   이 문장을 출력해야만 유저가 서류 생성 버튼을 누를 수 있어.
   아직 질문할 것이 남았다면 절대 이 문장을 미리 말하지 마.

[대화 수칙]
- 친절하고 따뜻한 말투로 대화하되, 심사 기준은 명확하게 제시해.
- 한 번에 너무 여러 개를 묻지 말고 차근차근 대화해.
- 지침 변경 가능성을 유저가 물으면 솔직하게 알려줘.
"""
            try:
                model = GenerativeModel(
                    "gemini-2.5-flash", system_instruction=interview_prompt
                )
                st.session_state.chat_session = model.start_chat()
                initial_response = st.session_state.chat_session.send_message(
                    "유저에게 반갑게 첫 인사를 건네고, 신분증에서 추출된 정보를 "
                    "언급하며 부족한 정보 하나를 먼저 물어봐 줘."
                )
                st.session_state.messages = [
                    {"role": "assistant", "content": initial_response.text}
                ]
            except Exception as e:
                st.error(f"🚨 상담 시작에 실패했습니다: {type(e).__name__}: {e}")

        if "chat_session" in st.session_state:
            for msg in st.session_state.get("messages", []):
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt := st.chat_input("여기에 답변을 입력하세요 (예: 저 교환학생이에요)"):
                st.session_state.messages.append(
                    {"role": "user", "content": prompt}
                )
                with st.chat_message("user"):
                    st.markdown(prompt)

                # 🔍 유저 발화로 이 비자코드 전용 앱만 검색한다.
                # 다른 비자코드 앱은 애초에 조회 대상이 아니므로 섞일 수 없다.
                snippets = rag_search.search(visa_code, prompt, top_k=6)
                augmented_prompt = prompt
                if snippets:
                    augmented_prompt = (
                        prompt + "\n\n[참고자료]\n" + "\n---\n".join(snippets)
                    )

                with st.chat_message("assistant"):
                    with st.spinner("AI가 규정을 검토하여 답변을 작성 중입니다..."):
                        try:
                            answer = st.session_state.chat_session.send_message(
                                augmented_prompt
                            ).text
                        except Exception as e:
                            answer = f"⚠️ 응답 생성에 실패했습니다: {e}"
                    st.markdown(answer)

                # 🚨 messages에는 유저 원문(prompt)만 저장한다. augmented_prompt를
                # 저장하면 검색된 청크 안의 문자열이 우연히 DONE_PHRASE와 겹쳐
                # interview_complete()가 상담을 조기 종료시킬 위험이 있다.
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )
                # unlocked는 스크립트 상단에서 계산되므로, 방금 추가한
                # 응답을 반영하려면 전체를 다시 실행해야 한다.
                st.rerun()


# ----------------------------------------
# 04 신청서 발급
# ----------------------------------------
# 상담이 끝나기 전에는 이 구역을 아예 그리지 않는다.
# 서류 목록 안내를 건너뛴 신청서는 유학생에게 해로우므로 지름길을 두지 않는다.
if "user_data" in st.session_state and unlocked:
    ui.band("신청서 발급", "Get your form")

    if st.button("신청서 만들기", use_container_width=True):
        with st.spinner("신청서를 작성하는 중입니다..."):
            try:
                st.session_state["docx_bytes"] = fill_application(
                    st.session_state["user_data"], template_path=TEMPLATE_PATH
                )
                st.rerun()
            except Exception as exc:
                st.error(f"작성하지 못했습니다: {type(exc).__name__}: {exc}")

    if "docx_bytes" in st.session_state:
        ui.seal()
        st.download_button(
            label="신청서 내려받기 (.docx)",
            data=st.session_state["docx_bytes"],
            file_name=(
                f"통합신청서_{st.session_state['user_data'].get('name', '유학생')}.docx"
            ),
            mime=("application/vnd.openxmlformats-officedocument"
                  ".wordprocessingml.document"),
            use_container_width=True,
        )

        with st.expander("출력한 뒤 직접 하실 일 · Before you submit", expanded=True):
            st.markdown(
                """
자동으로 채울 수 없는 항목입니다.

**1. 자필 서명 두 곳** — 상단 `신청인 서명 또는 인`,
하단 행정정보 공동이용 동의서의 `신청인` 칸.
미성년자는 `신청인의 부 또는 모` 칸도 함께 서명합니다.

**2. 수수료** — 체류기간 연장허가 **6만 원**
(법무부 수수료표 기준, 2026.1. 확인).
전자민원(하이코리아) 신청 시 감면 여부는 하이코리아에서 확인하세요.

**3. 사진은 붙이지 않습니다** — 여권용 사진은 외국인 등록과
등록증 재발급 때만 필요합니다. 체류기간 연장은 해당하지 않습니다.

**4. 공용란은 비워둡니다** — 담당 공무원이 채우는 칸입니다.

**5. 상담에서 안내받은 첨부서류**를 함께 준비해 제출하세요.
"""
            )

        # ── 다음 만료일 알림 신청 (선택) ──────────────────
        # 알림서비스와 같은 폼을 재사용한다. 상담을 막 끝낸 시점이
        # 신청 의사가 가장 높으므로 여기에도 둔다.
        ui.band("만료 알림 신청", "Get reminded next time")
        if st.session_state.get("reminder_done"):
            render_reminder_result()
        else:
            st.markdown(
                "다음 만료일이 다가오면 문자로 알려드릴까요? 선택 사항입니다.  \n"
                "<span style='color:#5F6B66;font-size:.85rem'>"
                "Optional. We'll remind you before your next expiry date.</span>",
                unsafe_allow_html=True,
            )
            render_reminder_form(
                default_expiry=st.session_state["user_data"].get("expiry_date", ""),
                default_visa=st.session_state["user_data"].get("visa_type", ""),
                key_prefix="consult",
            )

st.markdown('<div class="doc-rule-thin" style="margin-top:2.4rem"></div>',
            unsafe_allow_html=True)
st.caption(f"빌드 {APP_VERSION}")
st.caption(
    "이 서비스는 서류 작성을 돕는 도구이며 법률·행정 자문이 아닙니다. "
    "안내한 서류 목록과 자동 작성된 신청서는 참고용입니다. "
    "제출 전 하이코리아(hikorea.go.kr)와 관할 출입국·외국인청의 안내를 확인하세요."
)