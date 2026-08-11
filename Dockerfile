# Python 3.11
# google-cloud-firestore / google-cloud-kms 최신 릴리스가 3.10 이상을 요구한다.
# 3.9로 두면 pip가 구버전으로 내려가거나 설치가 실패한다.
FROM python:3.11-slim

WORKDIR /app

# 라이브러리 먼저 설치해 레이어 캐시를 살린다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Cloud Run Service(웹앱)의 기본 커맨드.
# 알림 배치는 같은 이미지로 Job을 만들고 이 CMD를 덮어쓴다.
CMD ["streamlit", "run", "app.py", \
     "--server.port=8080", "--server.address=0.0.0.0"]