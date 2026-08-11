# -*- coding: utf-8 -*-
"""만료 알림 구독 저장소.

설계 원칙
- 발송에 꼭 필요한 것만 저장한다. 외국인등록번호·여권번호·이름·주소·상담 로그는
  이 모듈을 통과하지 않는다. 스캔/상담/서식 생성 파이프라인은 지금처럼 무상태로 둔다.
- 문서 ID = HMAC(전화번호). 같은 번호가 다시 등록하면 덮어써지므로 중복 발송이 없고,
  번호만 알면 삭제(수신거부)도 가능하다. 원본 번호는 ID에서 복원되지 않는다.
- 전화번호 본문은 KMS로 암호화해 저장하고, 발송 직전에만 복호화한다.
- ttl_at 필드에 Firestore TTL 정책을 걸어 보관기간을 코드가 아니라 인프라가 강제한다.

주의: HMAC의 pepper가 유출되면 전화번호 공간(약 10^8)은 전수 대입이 가능하다.
pepper는 반드시 Secret Manager에 두고 소스/이미지에 넣지 않는다.
"""
import base64
import datetime
import hashlib
import hmac
import os
import re

# ── 알림 단계. 급한 것부터 위에 둔다 ──────────────────────────
# (단계명, 남은 일수 임계값)
STAGES = [
    ("D-7", 7),
    ("D-30", 30),
    ("D-60", 60),
]
HORIZON_DAYS = max(threshold for _, threshold in STAGES)

# 알림 목적을 다한 뒤 남겨두는 기간. 만료일 + 이 일수에 자동 삭제된다.
RETAIN_DAYS_AFTER_EXPIRY = 30

COLLECTION = os.getenv("NOTIFY_COLLECTION", "visa_reminders")

# 알림 주제. 지금은 체류기간 만료 하나지만, 항목을 추가하면
# 저장·발송 경로를 그대로 재사용할 수 있다.
DEFAULT_TOPIC = "visa_expiry"


# ============================================================
# 순수 로직 — 외부 의존 없음. 테스트는 여기에 집중한다.
# ============================================================
def digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def parse_expiry(value):
    """'2027-03-15' / '2027.03.15' / '20270315' → datetime.date. 실패하면 None.

    Vision Agent가 YYYY-MM-DD로 주도록 프롬프트에 지시돼 있지만,
    확인 화면에서 사용자가 직접 고칠 수 있는 자유 입력 칸이므로
    '2027-3-15'처럼 0을 뺀 표기까지 받아준다.
    """
    text = str(value or "").strip()
    parts = [p for p in re.split(r"\D+", text) if p]

    if len(parts) == 3 and len(parts[0]) == 4:
        y, m, d = parts
    else:
        nums = "".join(parts)
        if len(nums) != 8:
            return None
        y, m, d = nums[0:4], nums[4:6], nums[6:8]

    try:
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        return None


def stage_for(days_left, sent_stages):
    """오늘 이 사람에게 보낼 단계 하나를 고른다. 없으면 None.

    한 번의 실행에서 한 사람에게 문자는 최대 한 통이다.
    가장 급한 단계를 고르므로, 배치가 며칠 밀려도 늦은 알림이 밀리지 않는다.
    """
    if days_left < 0:
        return None
    sent = set(sent_stages or [])
    for name, threshold in STAGES:
        if days_left <= threshold and name not in sent:
            return name
    return None


def stages_to_mark(stage):
    """D-30을 보냈으면 D-60도 소진된 것으로 본다.
    남은 일수는 줄어들기만 하므로 뒤늦게 D-60이 발송될 일은 없지만,
    기록을 남겨 두면 이력을 읽기 쉽고 재실행에도 안전하다."""
    thresholds = dict(STAGES)
    if stage not in thresholds:
        return []
    base = thresholds[stage]
    return [name for name, threshold in STAGES if threshold >= base]


def normalize_phone(value):
    """'010-1234-5678' → '01012345678'. 형식이 아니면 None."""
    d = digits(value)
    if re.fullmatch(r"01[016789]\d{7,8}", d):
        return d
    return None


# ============================================================
# 전화번호 암복호화
# ============================================================
class KmsCipher:
    """Cloud KMS 대칭키로 직접 암복호화한다.
    전화번호는 아주 짧아 봉투 암호화(DEK) 없이 KMS 한 번 호출로 충분하다.
    대신 발송 시점에 건당 KMS 호출이 발생한다 — 일 수백 건 규모에서는 무시할 만하다."""

    def __init__(self, key_name, client=None):
        self.key_name = key_name
        if client is None:
            from google.cloud import kms
            client = kms.KeyManagementServiceClient()
        self._client = client

    def encrypt(self, plaintext):
        res = self._client.encrypt(
            request={"name": self.key_name, "plaintext": plaintext.encode("utf-8")}
        )
        return base64.b64encode(res.ciphertext).decode("ascii")

    def decrypt(self, ciphertext_b64):
        res = self._client.decrypt(
            request={
                "name": self.key_name,
                "ciphertext": base64.b64decode(ciphertext_b64),
            }
        )
        return res.plaintext.decode("utf-8")


class PlainCipher:
    """로컬 개발 전용. 절대 운영에서 쓰지 않는다."""

    def encrypt(self, plaintext):
        return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext_b64):
        return base64.b64decode(ciphertext_b64).decode("utf-8")


def build_cipher():
    key_name = os.getenv("KMS_KEY_NAME")
    if key_name:
        return KmsCipher(key_name)
    if os.getenv("ALLOW_PLAINTEXT_PHONE") == "1":
        return PlainCipher()
    raise RuntimeError(
        "KMS_KEY_NAME이 없습니다. 로컬 테스트라면 ALLOW_PLAINTEXT_PHONE=1을 주세요."
    )


# ============================================================
# 저장소
# ============================================================
class SubscriptionStore:
    def __init__(self, db, cipher, pepper, collection=COLLECTION):
        if not pepper:
            raise RuntimeError("PHONE_ID_PEPPER가 필요합니다.")
        self._db = db
        self._cipher = cipher
        self._pepper = pepper.encode("utf-8")
        self._collection = collection

    # ── 식별자 ───────────────────────────────────────────
    def doc_id(self, phone, topic=DEFAULT_TOPIC):
        """주제를 함께 해싱한다. 한 사람이 여러 알림을 신청해도
        서로 덮어쓰지 않고, 주제별로 따로 해지할 수 있다."""
        p = normalize_phone(phone)
        if p is None:
            raise ValueError("휴대전화 번호 형식이 아닙니다.")
        key = f"{topic}:{p}".encode("utf-8")
        return hmac.new(self._pepper, key, hashlib.sha256).hexdigest()[:32]

    def _ref(self, phone, topic=DEFAULT_TOPIC):
        return self._db.collection(self._collection).document(
            self.doc_id(phone, topic))

    # ── 쓰기 ─────────────────────────────────────────────
    def subscribe(self, phone, expiry_date, visa_category="", locale="ko",
                  source="self", topic=DEFAULT_TOPIC, now=None):
        """구독 등록/갱신. 만료일이 그대로면 발송 이력을 유지해 재발송을 막고,
        만료일이 바뀌었으면(=연장 성공 후 재등록) 이력을 비운다."""
        expiry = parse_expiry(expiry_date)
        if expiry is None:
            raise ValueError("만료일을 읽을 수 없습니다.")
        now = now or datetime.datetime.now(datetime.timezone.utc)
        if expiry < now.date():
            raise ValueError("이미 지난 만료일입니다.")

        ref = self._ref(phone, topic)
        snap = ref.get()
        prev = snap.to_dict() if getattr(snap, "exists", False) else None

        expiry_str = expiry.isoformat()
        sent_stages = []
        if prev and prev.get("expiry_date") == expiry_str:
            sent_stages = list(prev.get("sent_stages") or [])

        record = {
            "phone_enc": self._cipher.encrypt(normalize_phone(phone)),
            "topic": topic,
            "expiry_date": expiry_str,
            # 대분류만 저장한다. 상담 중 추정한 세부코드는 정확도 보증이 안 되면서
            # 민감도만 올린다.
            "visa_category": (visa_category or "").split("-")[0:2],
            "locale": locale,
            "source": source,
            "consent_at": now,
            "sent_stages": sent_stages,
            "ttl_at": datetime.datetime.combine(
                expiry + datetime.timedelta(days=RETAIN_DAYS_AFTER_EXPIRY),
                datetime.time.min,
                tzinfo=datetime.timezone.utc,
            ),
        }
        record["visa_category"] = "-".join(record["visa_category"])
        ref.set(record)
        return ref.id

    def unsubscribe(self, phone, topic=DEFAULT_TOPIC):
        """수신거부. 번호만으로 지울 수 있다(토큰 불필요)."""
        ref = self._ref(phone, topic)
        snap = ref.get()
        if not getattr(snap, "exists", False):
            return False
        ref.delete()
        return True

    def mark_sent(self, doc_id, stages, now=None):
        now = now or datetime.datetime.now(datetime.timezone.utc)
        self._db.collection(self._collection).document(doc_id).update({
            "sent_stages": stages,
            "last_sent_at": now,
        })

    # ── 읽기 ─────────────────────────────────────────────
    def due(self, today, horizon_days=HORIZON_DAYS):
        """오늘부터 horizon일 이내에 만료되는 구독을 모두 읽어온다.

        단일 필드 범위 질의라 복합 색인이 필요 없다. 단계 판정은 파이썬에서 한다.
        배치가 하루 걸러 실행돼도 남은 일수로 다시 판정하므로 알림이 유실되지 않는다.
        (구독자가 수만 명 규모가 되면 만료일 구간을 쪼개 페이지네이션해야 한다.)
        """
        start = today.isoformat()
        end = (today + datetime.timedelta(days=horizon_days)).isoformat()
        query = (self._db.collection(self._collection)
                 .where("expiry_date", ">=", start)
                 .where("expiry_date", "<=", end))
        out = []
        for snap in query.stream():
            data = snap.to_dict()
            data["_id"] = snap.id
            out.append(data)
        return out

    def decrypt_phone(self, record):
        return self._cipher.decrypt(record["phone_enc"])


def get_store():
    """설정이 갖춰졌을 때만 저장소를 만든다. 없으면 None —
    호출부는 알림 기능을 조용히 숨기고 나머지 흐름은 그대로 돌게 한다."""
    pepper = os.getenv("PHONE_ID_PEPPER")
    if not pepper:
        return None
    try:
        from google.cloud import firestore
        db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None)
        return SubscriptionStore(db, build_cipher(), pepper)
    except Exception:
        return None