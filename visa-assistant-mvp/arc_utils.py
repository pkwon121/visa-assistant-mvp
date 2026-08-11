# -*- coding: utf-8 -*-
"""외국인등록번호(ARC) 파생 정보 추출 + 데이터 정규화"""
import datetime

def _digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def derive_from_arc(arc_no):
    """
    외국인등록번호 13자리에서 생년월일/성별 역산.
    형식: YYMMDD-SXXXXXX
      S=5 → 19xx 남 / S=6 → 19xx 여
      S=7 → 20xx 남 / S=8 → 20xx 여
      S=1,3 → 남 / S=2,4 → 여 (귀화/특수 케이스 방어)
    """
    d = _digits(arc_no)
    if len(d) != 13:
        return {}

    yy, mm, dd, s = d[0:2], d[2:4], d[4:6], d[6]

    century = {"1": 19, "2": 19, "3": 20, "4": 20,
               "5": 19, "6": 19, "7": 20, "8": 20}.get(s)
    sex = {"1": "M", "3": "M", "5": "M", "7": "M",
           "2": "F", "4": "F", "6": "F", "8": "F"}.get(s)
    if century is None:
        return {}

    # 월/일 유효성 검사 (OCR 오독 방어)
    if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31):
        return {}

    return {
        "birth_yyyy": f"{century}{yy}",
        "birth_mm": mm,
        "birth_dd": dd,
        "sex": sex,
    }

def normalize(raw):
    """Vision Agent 원본 JSON → form_filler가 먹는 형태로 정리."""
    data = dict(raw or {})

    # 1) ARC 번호 정리 (하이픈/공백 제거)
    if data.get("arc_no"):
        data["arc_no"] = _digits(data["arc_no"])

    # 2) 생년월일/성별이 비어있으면 ARC에서 역산
    derived = derive_from_arc(data.get("arc_no"))
    for k, v in derived.items():
        if not data.get(k):
            data[k] = v

    # 3) 성별 표기 통일 (남/여/MALE/Male → M/F)
    sex = str(data.get("sex", "")).strip().upper()
    if sex.startswith("M") or sex == "남":
        data["sex"] = "M"
    elif sex.startswith("F") or sex == "여":
        data["sex"] = "F"

    # 4) 이름 대문자 + 성/명 분리
    if data.get("name") and not data.get("surname"):
        parts = str(data["name"]).strip().upper().split()
        if parts:
            data["surname"] = parts[0]
            data["given_names"] = " ".join(parts[1:])

    # 5) 날짜 표기 통일 (2033-04-30 / 20330430 → 2033.04.30)
    for k in ("passport_issue", "passport_expiry", "visa_expiry"):
        v = str(data.get(k) or "").strip()
        nums = _digits(v)
        if len(nums) == 8:
            data[k] = f"{nums[0:4]}.{nums[4:6]}.{nums[6:8]}"

    # 6) 신청일은 OCR 필요 없음 — 오늘 날짜 자동
    if not data.get("apply_date"):
        today = datetime.date.today()
        data["apply_date"] = f"{today.year}. {today.month:02d}. {today.day:02d}."

    return data


if __name__ == "__main__":
    tests = ["901231-5123456", "010203-7123456", "990101-6987654", "12345", "010203-9999999"]
    for t in tests:
        print(f"{t:>16} → {derive_from_arc(t)}")
    print()
    print(normalize({"name": "hong sample", "arc_no": "010203-7123456",
                     "passport_expiry": "2033-04-30"}))