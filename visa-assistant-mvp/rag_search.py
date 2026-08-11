# -*- coding: utf-8 -*-
"""Vertex AI Search(구 Discovery Engine) 검색 래퍼.

비자코드별로 데이터 스토어·앱을 완전히 분리해뒀기 때문에,
여기서는 필터 로직 없이 '어느 앱을 조회하느냐'만으로 분리가 보장된다.
D-2 유저 질문이 D-4/D-10 청크를 끌고 올 방법이 구조적으로 없다.
"""
import os

from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine

LOCATION = os.getenv("SEARCH_LOCATION", "global")

APP_IDS = {
    "D-2": os.getenv("SEARCH_APP_D2"),
    "D-4": os.getenv("SEARCH_APP_D4"),
    "D-10": os.getenv("SEARCH_APP_D10"),
}


def _client():
    client_options = (
        ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
        if LOCATION != "global" else None
    )
    return discoveryengine.SearchServiceClient(client_options=client_options)


def search(visa_code, query, top_k=6):
    """비자코드에 해당하는 앱에서만 검색. 반환: 텍스트 구간(segment) 리스트.

    스토어마다 문서가 1개(매뉴얼 전문)뿐이라 snippet_spec은 문서당 스니펫을
    1개만 주는 바람에 사실상 검색이 아니라 '아무 조각 하나 찍기'가 됐었다.
    extractive_content_spec의 max_extractive_segment_count는 같은 문서
    안에서도 쿼리와 관련된 구간을 여러 개 뽑아주므로 이걸로 교체.

    앱 ID가 설정 안 돼 있거나 호출이 실패하면 빈 리스트를 돌려준다.
    get_store()와 같은 철학: 검색이 죽어도 상담 자체는 계속 진행되게 한다.
    (이 경우 상담은 guardrails.py의 고정 컨텍스트만으로 진행된다.)
    """
    app_id = APP_IDS.get(visa_code)
    if not app_id or not query:
        return []

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        return []

    try:
        client = _client()
        serving_config = (
            f"projects/{project_id}/locations/{LOCATION}"
            f"/collections/default_collection/engines/{app_id}"
            f"/servingConfigs/default_search"
        )
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=top_k,
            content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                extractive_content_spec=(
                    discoveryengine.SearchRequest.ContentSearchSpec
                    .ExtractiveContentSpec(
                        max_extractive_segment_count=top_k,
                    )
                ),
            ),
        )
        response = client.search(request)
    except Exception:
        return []

    segments = []
    for result in response.results:
        data = result.document.derived_struct_data
        for seg in (data.get("extractive_segments") or []):
            text = seg.get("content")
            if text:
                segments.append(text.strip())
    return segments