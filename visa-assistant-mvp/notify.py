# -*- coding: utf-8 -*-
"""만료 알림 배치 — Cloud Scheduler → Cloud Run Job 엔트리포인트.

    python3 notify.py

환경변수
    NOTIFY_ENABLED=1        없으면 아무것도 하지 않는다 (킬 스위치)
    NOTIFY_DRY_RUN=1        발송하지 않고 로그만 남긴다
    NOTIFY_MAX_PER_RUN=500  후보가 이보다 많으면 한 통도 보내지 않고 중단한다
    PHONE_ID_PEPPER, KMS_KEY_NAME, SOLAPI_*, SERVICE_URL

Streamlit 앱(Cloud Run Service)이 아니라 별도 Job으로 돌린다.
Streamlit에는 /cron 같은 임의 라우트를 깔끔히 붙일 수 없고, 붙이더라도
앱 재배포가 발송을 흔들기 때문이다. 같은 이미지에 커맨드만 바꿔 쓰면 된다.
"""
import datetime
import logging
import os
import sys

import notify_store
import sms

# 로컬 실행용. Cloud Run Job은 배포 시 환경변수를 주입하므로 없어도 된다.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

KST = datetime.timezone(datetime.timedelta(hours=9))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("notify")


def today_kst():
    """만료일 계산의 기준은 한국 날짜다. UTC로 계산하면 자정 근처에서 하루가 어긋난다."""
    return datetime.datetime.now(KST).date()


def run(store, send, today, dry_run=False, cap=500):
    """하루치 발송. 결과 요약 dict를 돌려준다.

    - 한 사람에게 한 실행당 최대 한 통
    - 이미 보낸 단계는 건너뛴다 (재실행·재시도에 안전)
    - 후보가 cap을 넘으면 한 통도 보내지 않고 멈춘다
    """
    records = store.due(today)
    plan = []
    for rec in records:
        expiry = notify_store.parse_expiry(rec.get("expiry_date"))
        if expiry is None:
            log.warning("만료일을 읽을 수 없는 문서를 건너뜁니다: %s", rec.get("_id"))
            continue
        days_left = (expiry - today).days
        stage = notify_store.stage_for(days_left, rec.get("sent_stages"))
        if stage:
            plan.append((rec, stage, days_left))

    summary = {
        "scanned": len(records),
        "planned": len(plan),
        "sent": 0,
        "failed": 0,
        "dry_run": bool(dry_run),
        "aborted": False,
    }

    if len(plan) > cap:
        # 질의나 데이터가 잘못됐을 때 전량 발송으로 번지는 것을 막는 안전장치.
        # 부분 발송보다 완전 중단이 낫다 — 사람이 보고 판단해야 한다.
        log.error("발송 후보 %d건이 상한 %d건을 넘었습니다. 중단합니다.", len(plan), cap)
        summary["aborted"] = True
        return summary

    for rec, stage, days_left in plan:
        doc_id = rec["_id"]
        if dry_run:
            log.info("[DRY-RUN] %s 단계=%s 남은일수=%d", doc_id, stage, days_left)
            summary["sent"] += 1
            continue
        try:
            phone = store.decrypt_phone(rec)
            ok, detail = send(phone, sms.build_message(stage))
        except Exception as e:                      # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"

        if ok:
            # 발송 성공 뒤에만 기록한다. 실패는 다음 실행에서 다시 시도된다.
            store.mark_sent(doc_id, notify_store.stages_to_mark(stage))
            summary["sent"] += 1
            log.info("발송 %s 단계=%s", doc_id, stage)
        else:
            summary["failed"] += 1
            # 전화번호는 로그에 남기지 않는다.
            log.error("발송 실패 %s 단계=%s 사유=%s", doc_id, stage, detail)

    return summary


def main():
    if os.getenv("NOTIFY_ENABLED") != "1":
        log.warning("NOTIFY_ENABLED=1이 아니므로 아무것도 하지 않습니다.")
        return 0

    store = notify_store.get_store()
    if store is None:
        log.error("저장소를 만들지 못했습니다. PHONE_ID_PEPPER/KMS_KEY_NAME을 확인하세요.")
        return 1

    dry_run = os.getenv("NOTIFY_DRY_RUN") == "1"
    cap = int(os.getenv("NOTIFY_MAX_PER_RUN", "500"))

    summary = run(store, sms.send_sms, today_kst(), dry_run=dry_run, cap=cap)
    log.info("요약 %s", summary)
    return 1 if (summary["aborted"] or summary["failed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
