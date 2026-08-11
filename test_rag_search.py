# -*- coding: utf-8 -*-
"""rag_search.py 단독 테스트. Streamlit 없이 검색이 실제로 되는지만 확인.

실행:
    python3 test_rag_search.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

# 환경변수 로드 확인 (여기서 비어있으면 .env 자체를 못 읽은 것)
print("=== 환경변수 확인 ===")
for key in ("GOOGLE_CLOUD_PROJECT", "SEARCH_LOCATION",
            "SEARCH_APP_D2", "SEARCH_APP_D4", "SEARCH_APP_D10"):
    val = os.getenv(key)
    print(f"  {key} = {val!r}")
    if not val:
        print(f"  ⚠️ {key}가 비어있습니다. .env를 확인하세요.")
print()

import rag_search  # noqa: E402  (환경변수 로드 이후에 import)

TEST_QUERIES = {
    "D-2": "저 교환학생인데 필요한 서류가 뭐예요?",
    "D-4": "어학연수생인데 재정입증 어떻게 해요?",
    "D-10": "구직비자 점수제가 뭐예요?",
}

for visa_code, query in TEST_QUERIES.items():
    print(f"=== {visa_code} 검색: '{query}' ===")
    try:
        snippets = rag_search.search(visa_code, query, top_k=3)
    except Exception as e:
        print(f"  ❌ 예외 발생: {type(e).__name__}: {e}")
        continue

    if not snippets:
        print("  ⚠️ 결과 0건 — 검색 실패했거나(권한/설정 문제) "
              "정말 관련 청크가 없는 경우입니다. 아래 '흔한 원인' 참고.")
    else:
        print(f"  ✅ {len(snippets)}건 검색됨")
        for i, s in enumerate(snippets, 1):
            preview = s[:80].replace("\n", " ")
            print(f"    [{i}] {preview}...")
    print()