# -*- coding: utf-8 -*-
"""문자 발송 — app.py(관리자 버튼)와 notify.py(배치)가 함께 쓴다.

app.py에 있던 send_solapi_sms를 여기로 옮기고, 본문을 인자로 받도록 바꿨다.
배치가 단계별로 다른 문구를 보내야 하므로 본문이 함수 안에 박혀 있으면 안 된다.
"""
import datetime
import hashlib
import hmac
import os
import uuid

import requests

SOLAPI_URL = "https://api.solapi.com/messages/v4/send"


def _auth_headers(api_key, api_secret):
    date = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    salt = uuid.uuid1().hex
    signature = hmac.new(
        api_secret.encode("utf-8"),
        (date + salt).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": (
            f"HMAC-SHA256 apiKey={api_key}, date={date}, "
            f"salt={salt}, signature={signature}"
        ),
        "Content-Type": "application/json",
    }


def send_sms(to_number, text):
    """(성공여부, 메시지) 반환. 예외를 밖으로 던지지 않는다 —
    배치가 한 건 실패로 전체를 멈추면 안 되기 때문."""
    api_key = os.getenv("SOLAPI_API_KEY")
    api_secret = os.getenv("SOLAPI_API_SECRET")
    from_number = os.getenv("SOLAPI_FROM_NUMBER")

    if not all([api_key, api_secret, from_number]):
        return False, "SOLAPI 환경변수가 설정되지 않았습니다."

    try:
        response = requests.post(
            SOLAPI_URL,
            headers=_auth_headers(api_key, api_secret),
            json={"message": {"to": to_number, "from": from_number, "text": text}},
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"네트워크 오류: {e}"

    if response.status_code == 200:
        return True, "성공"
    return False, response.text


# ── 문구 ────────────────────────────────────────────────────
# 한글이 섞이면 SMS(45자)를 넘겨 LMS로 발송된다. 건당 단가가 오르는 대신
# 한국어를 못 읽는 이용자를 놓치지 않는다. 이 트레이드오프는 의도한 것이다.
LEAD = {
    "D-60": (
        "체류기간 만료 60일 전입니다. 지금부터 연장을 신청할 수 있습니다.\n"
        "Your period of stay expires in 60 days. You can apply for an extension now."
    ),
    "D-30": (
        "체류기간 만료 30일 전입니다. 서류 준비를 시작하세요.\n"
        "30 days left. Start preparing your documents."
    ),
    "D-7": (
        "체류기간 만료 7일 전입니다. 만료일 전에 반드시 신청하세요.\n"
        "7 days left. You must apply before your expiry date."
    ),
}


def build_message(stage, service_url=None):
    url = service_url or os.getenv("SERVICE_URL", "https://example.com")
    lead = LEAD.get(stage, LEAD["D-30"])
    return (
        f"[체류기간 알림]\n{lead}\n\n"
        f"필요 서류 확인 · 신청서 작성\n{url}\n\n"
        "※ 본인이 신청한 알림입니다. 개인정보나 결제를 요구하지 않습니다.\n"
        f"※ 수신거부 Unsubscribe: {url}?unsub=1"
    )


def build_welcome_message(expiry_date, service_url=None):
    """신청 직후 보내는 확인 문자.
    번호를 잘못 적었는지 그 자리에서 알 수 있게 하는 것이 목적이다.
    이게 없으면 학생은 60일 뒤에야 등록 실패를 알게 된다."""
    url = service_url or os.getenv("SERVICE_URL", "https://example.com")
    return (
        "[체류기간 알림] 신청이 완료되었습니다.\n"
        f"체류기간 만료일: {expiry_date}\n"
        "만료 60일 · 30일 · 7일 전에 문자로 알려드립니다.\n\n"
        "Reminder set. We'll text you 60, 30 and 7 days before your permit expires.\n\n"
        f"서류 확인 · 신청서 작성\n{url}\n\n"
        f"※ 수신거부 Unsubscribe: {url}?unsub=1"
    )