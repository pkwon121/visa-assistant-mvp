# 유학생 체류기간 연장 신청 도우미 (visa-assistant-mvp)

외국인등록증(ARC)을 촬영하면 체류자격을 인식하고, 법무부 매뉴얼 기반으로
필요 서류를 상담해준 뒤, 통합신청서(별지 제34호 서식)를 자동으로 채워주는
Streamlit 앱. 체류기간 만료 임박 시 문자 알림도 보낸다.

현재 D-2(유학) · D-4(일반연수) · D-10(구직) 세 가지 체류자격을 지원한다.

## 아키텍처

- **웹앱**: Streamlit → Cloud Run (Service)
- **신분증 인식**: Vertex AI (Gemini) Vision
- **서류 상담(RAG)**: Vertex AI Search — 비자코드별로 데이터 스토어·앱을
  완전히 분리해서, 검색 결과가 다른 비자코드 매뉴얼과 섞이지 않도록 구조적으로 보장
- **알림 저장소**: Firestore (전화번호는 KMS로 암호화)
- **알림 배치**: 같은 이미지, 다른 커맨드로 Cloud Run Job (Cloud Scheduler가 트리거)
- **문자 발송**: SOLAPI

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env를 열어 아래 "필요한 GCP 리소스" 값들을 채운다

streamlit run app.py
```

## 필요한 GCP 리소스 (사전 준비)

`.env.example`의 각 변수가 어떤 리소스를 가리키는지:

| 변수 | 리소스 |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP 프로젝트 ID |
| `SEARCH_APP_D2` / `D4` / `D10` | Vertex AI Search(AI Applications) 앱 ID. 매뉴얼당 데이터 스토어 1개 + 앱 1개로 완전히 분리해서 만든다 (콘솔 → AI Applications → 데이터 스토어 → 매뉴얼 txt 하나만 업로드 → 그 위에 검색 앱 생성) |
| `PHONE_ID_PEPPER` / `KMS_KEY_NAME` | Firestore에 전화번호를 HMAC 해싱 + KMS 암호화해서 저장하기 위한 값. 운영에서는 `ALLOW_PLAINTEXT_PHONE=0`이어야 하고 `KMS_KEY_NAME`이 반드시 채워져 있어야 한다 |
| `SOLAPI_*` | SOLAPI 콘솔에서 발급 |

Cloud Run 서비스 계정에는 `roles/discoveryengine.viewer`(Vertex AI Search 조회),
Firestore/KMS 관련 권한이 필요하다.

## 배포

```bash
gcloud run deploy visa-assistant \
  --source . \
  --region=asia-northeast3

# 환경변수는 .env가 아니라 별도로 주입
gcloud run services update visa-assistant \
  --region=asia-northeast3 \
  --update-env-vars="SEARCH_LOCATION=global,SEARCH_APP_D2=...,SEARCH_APP_D4=...,SEARCH_APP_D10=..."
```

## 주의

- 법률·행정 자문이 아니다. 안내된 서류 목록·자동 작성된 신청서는 참고용이며,
  제출 전 하이코리아(hikorea.go.kr)와 관할 출입국·외국인청 확인이 필요하다.
- `.env`는 절대 커밋하지 않는다 (`.gitignore` 참고).
