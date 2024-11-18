```markdown
# YouTube Content Analysis Dashboard

## 개요
YouTube 콘텐츠 분석 대시보드는 YouTube 데이터 API와 Claude AI를 활용하여 채널 및 콘텐츠 성과를 분석하는 도구입니다.

## 설치 방법
1. 저장소 클론
```bash
git clone https://github.com/[YOUR_USERNAME]/[REPOSITORY_NAME].git
```

2. 필요한 패키지 설치
```bash
pip install -r requirements.txt
```

3. 환경 변수 설정
- `.env` 파일을 생성하고 다음 내용을 추가:
```env
YOUTUBE_API_KEY=your_youtube_api_key_here
CLAUDE_API_KEY=your_claude_api_key_here
```

## 실행 방법
```bash
streamlit run youtubetest3.py
```

## 주요 기능
- YouTube 영상 데이터 분석
- 시간대별 성과 분석
- 키워드 분석
- AI 기반 인사이트 제공
```