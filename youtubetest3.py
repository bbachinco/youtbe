import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import numpy as np
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from anthropic import Anthropic
import json
import os
from dotenv import load_dotenv

class YouTubeAnalytics:
    def __init__(self):
            self.load_api_keys()
            st.set_page_config(page_title="YouTube 콘텐츠 분석 대시보드", layout="wide")
            
            # Custom CSS 추가
            st.markdown("""
                <style>
                    h3 {
                        margin-top: 40px;
                        margin-bottom: 20px;
                        color: #1e88e5;
                        font-size: 1.5em;
                    }
                    h4 {
                        margin-top: 25px;
                        margin-bottom: 15px;
                        color: #2196f3;
                        font-size: 1.2em;
                    }
                    ul {
                        margin-left: 20px;
                        margin-bottom: 15px;
                    }
                    li {
                        margin-bottom: 8px;
                    }
                </style>
            """, unsafe_allow_html=True)
            
            self.setup_sidebar()

    def load_api_keys(self):
        # .env 파일에서 API 키 로드
        load_dotenv()
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY')
        self.claude_api_key = os.getenv('CLAUDE_API_KEY')
        
        # API 키가 환경변수에 없는 경우 Streamlit secrets에서 시도
        if not self.youtube_api_key:
            try:
                self.youtube_api_key = st.secrets["YOUTUBE_API_KEY"]
            except:
                self.youtube_api_key = None
                
        if not self.claude_api_key:
            try:
                self.claude_api_key = st.secrets["CLAUDE_API_KEY"]
            except:
                self.claude_api_key = None

    def setup_sidebar(self):
        with st.sidebar:
            st.title("⚙️ 설정")
            
            # API 키 입력 필드 (이미 로드된 키가 없는 경우에만 표시)
            if not self.youtube_api_key:
                self.youtube_api_key = st.text_input("YouTube API Key", type="password")
            if not self.claude_api_key:
                self.claude_api_key = st.text_input("Claude API Key", type="password")
            
            self.keyword = st.text_input("분석할 키워드")
            self.max_results = st.slider("검색할 최대 영상 수", 10, 100, 50)
            self.date_range = st.slider("분석 기간 (개월)", 1, 24, 12)

    def collect_videos_data(self, youtube):
        date_limit = (datetime.now() - timedelta(days=30 * self.date_range)).isoformat() + "Z"
        videos = []
        next_page_token = None
        
        while len(videos) < self.max_results:
            try:
                # 1. 검색 요청
                search_response = youtube.search().list(
                    q=self.keyword,
                    type="video",
                    part="id",
                    maxResults=min(50, self.max_results - len(videos)),
                    pageToken=next_page_token,
                    publishedAfter=date_limit
                ).execute()
                
                video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]
                
                # 2. 비디오 상세 정보 수집
                videos_response = youtube.videos().list(
                    part='snippet,statistics,contentDetails',
                    id=','.join(video_ids)
                ).execute()
                
                # 3. 데이터 처리 및 필터링
                for video in videos_response.get('items', []):
                    try:
                        stats = video['statistics']
                        views = int(stats.get('viewCount', 0))
                        
                        # 1000회 이상 조회된 영상만 포함
                        if views >= 1000:
                            videos.append({
                                'id': video['id'],
                                'title': video['snippet']['title'],
                                'publishedAt': video['snippet']['publishedAt'],
                                'description': video['snippet']['description'],
                                'views': views,
                                'likes': int(stats.get('likeCount', 0)),
                                'comments': int(stats.get('commentCount', 0)),
                                'tags': video['snippet'].get('tags', []),
                                'duration': video['contentDetails']['duration']
                            })
                    except Exception as e:
                        st.warning(f"영상 처리 중 오류: {str(e)}")
                        continue
                
                next_page_token = search_response.get('nextPageToken')
                if not next_page_token:
                    break
                    
            except Exception as e:
                st.error(f"데이터 수집 중 오류: {str(e)}")
                break
        
        return self.calculate_engagement_scores(videos)

    def calculate_engagement_scores(self, videos):
        if not videos:
            return []
            
        # 댓글 비율 분석을 통한 이상치 제거
        comment_ratios = [
            (video['comments'] / video['views'] * 100) 
            for video in videos if video['views'] > 0
        ]
        avg_ratio = np.mean(comment_ratios)
        std_ratio = np.std(comment_ratios)
        threshold = avg_ratio + (2 * std_ratio)
        
        one_week_ago = datetime.now() - timedelta(days=7)
        
        processed_videos = []
        for video in videos:
            try:
                views = video['views']
                likes = video['likes']
                comments = video['comments']
                publish_date = datetime.strptime(
                    video['publishedAt'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                )
                
                comment_ratio = (comments / views * 100) if views > 0 else 0
                
                # 비정상적인 댓글 비율 제외
                if comment_ratio > threshold:
                    continue
                    
                like_ratio = (likes / views * 100) if views > 0 else 0
                recency_score = 1.2 if publish_date > one_week_ago else 1.0
                
                engagement_score = (
                    like_ratio + 
                    (comment_ratio * 3)  # 댓글 가중치 3배
                ) * recency_score
                
                video['engagement_score'] = engagement_score
                video['like_ratio'] = like_ratio
                video['comment_ratio'] = comment_ratio
                video['is_recent'] = publish_date > one_week_ago
                
                processed_videos.append(video)
                
            except Exception as e:
                st.warning(f"점수 계산 중 오류: {str(e)}")
                continue
        
        # 인게이지먼트 점수 기준 정렬
        return sorted(
            processed_videos, 
            key=lambda x: x['engagement_score'], 
            reverse=True
        )[:20]  # 상위 20개만 반환

    def create_dashboard(self, df):
        st.title(f"📊 YouTube 키워드 분석: {self.keyword}")
        
        # 1. 주요 지표 카드
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("총 분석 영상", f"{len(df):,}개")
        with col2:
            st.metric("총 조회수", f"{df['views'].sum():,}회")
        with col3:
            st.metric("평균 좋아요", f"{int(df['likes'].mean()):,}개")
        with col4:
            st.metric("평균 댓글", f"{int(df['comments'].mean()):,}개")
        
# 2. 시계열 분석
        st.subheader("📈 시간대별 성과 분석")
        df['date'] = pd.to_datetime(df['publishedAt'])
        
        # 2-1. 일자별 추이
        st.markdown("#### 📅 일자별 추이")
        daily_stats = df.groupby(df['date'].dt.date).agg({
            'views': 'sum',
            'comments': 'sum'
        }).reset_index()
        
        # 일자별 조회수 추이
        fig_daily_views = go.Figure()
        fig_daily_views.add_trace(go.Scatter(
            x=daily_stats['date'],
            y=daily_stats['views'],
            name='조회수',
            mode='lines+markers',
            line=dict(color='#1976D2')
        ))
        fig_daily_views.update_layout(
            title='일자별 조회수 추이',
            xaxis_title='날짜',
            yaxis_title='조회수',
            height=400
        )
        st.plotly_chart(fig_daily_views, use_container_width=True)
        
        # 2-2. 요일별 분석
        st.markdown("#### 📅 요일별 분석")
        df['weekday'] = df['date'].dt.day_name()
        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_korean = {
            'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일',
            'Thursday': '목요일', 'Friday': '금요일', 'Saturday': '토요일',
            'Sunday': '일요일'
        }
        
        weekday_stats = df.groupby('weekday').agg({
            'views': 'mean',
            'comments': 'mean'
        }).reindex(weekday_order).reset_index()
        weekday_stats['weekday'] = weekday_stats['weekday'].map(weekday_korean)
        
        col1, col2 = st.columns(2)
        
        # 요일별 평균 조회수
        with col1:
            fig_weekday_views = go.Figure()
            fig_weekday_views.add_trace(go.Bar(
                x=weekday_stats['weekday'],
                y=weekday_stats['views'],
                marker_color='#1976D2'
            ))
            fig_weekday_views.update_layout(
                title='요일별 평균 조회수',
                xaxis_title='요일',
                yaxis_title='평균 조회수',
                height=400
            )
            st.plotly_chart(fig_weekday_views, use_container_width=True)
            
        # 요일별 평균 댓글수
        with col2:
            fig_weekday_comments = go.Figure()
            fig_weekday_comments.add_trace(go.Bar(
                x=weekday_stats['weekday'],
                y=weekday_stats['comments'],
                marker_color='#FFA726'
            ))
            fig_weekday_comments.update_layout(
                title='요일별 평균 댓글수',
                xaxis_title='요일',
                yaxis_title='평균 댓글수',
                height=400
            )
            st.plotly_chart(fig_weekday_comments, use_container_width=True)
        
# 2-3. 시간대별 분석
        st.markdown("#### 🕒 시간대별 분석")
        df['hour'] = df['date'].dt.hour
        hourly_stats = df.groupby('hour').agg({
            'views': 'mean',
            'comments': 'mean'
        }).reset_index()
        
        # 모든 시간대(0-23)가 포함되도록 보장
        all_hours = pd.DataFrame({'hour': range(24)})
        hourly_stats = pd.merge(all_hours, hourly_stats, on='hour', how='left').fillna(0)
        
        col3, col4 = st.columns(2)
        
        # 시간대별 평균 조회수
        with col3:
            fig_hourly_views = go.Figure()
            fig_hourly_views.add_trace(go.Bar(
                x=hourly_stats['hour'],
                y=hourly_stats['views'],
                marker_color='#1976D2'
            ))
            fig_hourly_views.update_layout(
                title='시간대별 평균 조회수',
                xaxis_title='시간',
                yaxis_title='평균 조회수',
                height=400,
                xaxis=dict(
                    tickmode='array',
                    ticktext=[f'{i:02d}시' for i in range(24)],
                    tickvals=list(range(24)),
                    range=[-0.5, 23.5]  # X축 범위 설정
                )
            )
            st.plotly_chart(fig_hourly_views, use_container_width=True)
            
        # 시간대별 평균 댓글수
        with col4:
            fig_hourly_comments = go.Figure()
            fig_hourly_comments.add_trace(go.Bar(
                x=hourly_stats['hour'],
                y=hourly_stats['comments'],
                marker_color='#FFA726'
            ))
            fig_hourly_comments.update_layout(
                title='시간대별 평균 댓글수',
                xaxis_title='시간',
                yaxis_title='평균 댓글수',
                height=400,
                xaxis=dict(
                    tickmode='array',
                    ticktext=[f'{i:02d}시' for i in range(24)],
                    tickvals=list(range(24)),
                    range=[-0.5, 23.5]  # X축 범위 설정
                )
            )
            st.plotly_chart(fig_hourly_comments, use_container_width=True)
        
# 4. 상위 영상 테이블
        st.subheader("🏆 상위 20개 영상")
        df_display = df.nlargest(20, 'engagement_score')[
            ['title', 'views', 'likes', 'comments', 'engagement_score']
        ].reset_index(drop=True)
        df_display.index += 1
        st.table(df_display)
        
# 5. 워드클라우드 분석
        st.subheader("🔍 제목 키워드 분석")
        try:
            # 폰트 경로 설정: 프로젝트 폴더에 포함된 폰트 사용
            current_dir = os.path.dirname(os.path.abspath(__file__))
            font_path = os.path.join(current_dir, 'NanumGothic.ttf')

            # 워드클라우드 생성
            wordcloud = WordCloud(
                width=800, 
                height=400,
                background_color='white',
                font_path=font_path,  # 폰트 경로 설정
                prefer_horizontal=0.7
            ).generate(' '.join(df['title']))

            # 워드클라우드 표시
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis('off')
            st.pyplot(fig)

        except Exception as e:
            st.error(f"워드클라우드 생성 중 오류가 발생했습니다: {str(e)}")
            st.info("워드클라우드를 생성할 수 없습니다. 한글 폰트 설정을 확인해주세요.")

# 6. Claude AI 분석
        st.subheader("🤖 AI 분석 인사이트")

        def format_analysis_response(text):
            """Claude API 응답을 가독성 있게 포맷팅하는 함수"""
            formatted_text = ""
            lines = text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:  # 빈 줄 처리
                    formatted_text += "\n"
                # 주요 섹션 헤더 (1️⃣, 2️⃣, 3️⃣, 4️⃣)
                elif any(emoji in line for emoji in ['1️⃣', '2️⃣', '3️⃣', '4️⃣']):
                    formatted_text += f"\n\n### {line}\n"
                # 하위 섹션 헤더 (▶️)
                elif line.startswith('▶️'):
                    formatted_text += f"\n#### {line}\n"
                # 섹션 제목 (####으로 시작하는 라인)
                elif line.startswith('####'):
                    formatted_text += f"\n{line}\n"
                # 주요 항목 (•로 시작하는 라인)
                elif line.startswith('•'):
                    formatted_text += f"\n    * {line[1:].strip()}\n"
                # 하위 상세 설명 (-로 시작하는 라인)
                elif line.strip().startswith('-'):
                    formatted_text += f"\n        - {line[1:].strip()}\n"
                # 기타 텍스트
                else:
                    formatted_text += f"{line}\n"
            
            return formatted_text

        if self.claude_api_key:
            with st.spinner("AI 분석을 수행중입니다..."):
                try:
                    client = Anthropic(api_key=self.claude_api_key)
                    
                    # DataFrame을 JSON으로 변환하기 전에 전처리
                    df_for_analysis = df.copy()
                    # Timestamp를 문자열로 변환
                    df_for_analysis['date'] = df_for_analysis['date'].astype(str)
                    # 필요한 컬럼만 선택
                    analysis_data = df_for_analysis[[
                        'title', 'views', 'likes', 'comments', 
                        'engagement_score', 'date'
                    ]].to_dict('records')
                    
                    # 첫 번째 분석: 성과 패턴 및 최적화
                    first_prompt = f"""당신은 YouTube 데이터 분석 전문가입니다. 
다음 데이터를 분석하여 첫 번째 파트의 인사이트를 도출해주세요:

{json.dumps(analysis_data, ensure_ascii=False, indent=2)}

1️⃣ 데이터 기반 성과 패턴
▶️ 조회수 상위 25% 영상 특징
 #### 제목 패턴 분석:
    • 주요 키워드 분석
        - 사용 빈도가 높은 핵심 키워드
        - 키워드 조합 패턴
        - 성과별 키워드 분포
    • 제목 구조의 특징
        - 효과적인 제목 길이
        - 주요 문장 구성 패턴
        - 시청자 호응이 높은 구조
    • 효과적인 제목 사례
        - 대표적 성공 사례 분석
        - 공통된 성공 요인
        - 실제 적용 방안

 #### 조회수와 참여도 상관관계:
    • 주목할 만한 패턴
        - 특이점 분석
        - 성공 요인 도출
        - 적용 가능한 인사이트

 #### 성공적인 영상의 공통점:
    • 콘텐츠 구성 특징
        - 효과적인 구성 요소
        - 시청자 반응이 좋은 포맷
        - 핵심 성공 요인
    • 시청자 반응 패턴
        - 긍정적 반응 요인
        - 참여도 증가 요소
        - 시청자 행동 분석
    • 차별화 요소
        - 독특한 강점 분석
        - 경쟁력 있는 특징
        - 벤치마킹 포인트

2️⃣ 최적화 인사이트
▶️ 제목 최적화 전략
 #### 효과적인 제목 구성 요소:
    • 핵심 키워드
        - 필수 포함 키워드
        - 효과적인 키워드 순서
        - 키워드 조합 전략
    • 구조적 특징
        - 최적의 제목 구조
        - 효과적인 문장 패턴
        - 시청자 주목도 높은 형식
    • 길이 및 형식
        - 최적의 제목 길이
        - 추천 포맷 가이드
        - 실용적 적용 방안

 #### 시청자 관심을 끄는 키워드:
    • 상위 성과 키워드
        - 조회수 연관 키워드
        - 참여도 연관 키워드
        - 성과별 키워드 분석
    • 시청자 반응이 좋은 표현
        - 효과적인 문구 패턴
        - 감정 반응 유도 요소
        - 참여 유도 표현
    • 트렌드 키워드
        - 최신 트렌드 분석
        - 시기별 유효 키워드
        - 활용 전략 제안

 #### 개선 제안:
    • 구체적 최적화 방안
        - 즉시 적용 가능한 개선점
        - 단계별 최적화 전략
        - 실행 우선순위
    • 테스트 추천 사항
        - A/B 테스트 항목
        - 성과 측정 방법
        - 개선 프로세스
    • 주의해야 할 점
        - 위험 요소 분석
        - 회피해야 할 패턴
        - 품질 관리 포인트

분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 데이터 기반의 구체적인 수치는 다음과 같이 표현해주세요:
   - 정확한 수치: '47%', '2.3배' 등
   - 시간 범위: '오전 9시~오후 3시', '15시~19시' 등
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.

각 항목은 데이터에 기반한 구체적인 수치와 예시를 포함해서 설명해주세요."""

                    first_response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=3000,
                        temperature=0.3,
                        messages=[{"role": "user", "content": first_prompt}]
                    )

                    # 두 번째 분석: 시간 기반 분석 및 제작 가이드
                    second_prompt = f"""이어서 다음 데이터를 분석하여 두 번째 파트의 인사이트를 도출해주세요:

{json.dumps(analysis_data, ensure_ascii=False, indent=2)}

3️⃣ 시간 기반 인사이트
▶️ 업로드 전략
 #### 최적의 업로드 시간대:
    • 조회수가 가장 높은 시간대
        - 시간대별 조회수 분석
        - 최적 시간대 도출
        - 시간대별 성과 차이
    • 참여도가 가장 높은 시간대
        - 댓글/좋아요 참여율 분석
        - 시청자 활동 시간대
        - 효과적인 업로드 타이밍
    • 시간대별 성과 차이
        - 주요 성과 지표 비교
        - 시간대별 특성 분석
        - 전략적 시사점

 #### 시청자 참여가 높은 기간:
    • 요일별 성과 분석
        - 요일별 조회수 패턴
        - 참여도 변화 추이
        - 최적 업로드 요일
    • 월별/계절별 트렌드
        - 월별 성과 비교
        - 계절적 특성 분석
        - 장기 트렌드 패턴
    • 특정 기간 성과 패턴
        - 주요 성과 구간 분석
        - 성공 요인 도출
        - 전략적 활용 방안

 #### 시즌별 트렌드:
    • 계절별 성과 비교
        - 계절별 성과 차이
        - 시즌별 특성 분석
        - 시즌 맞춤 전략
    • 특별한 시기/이벤트 영향
        - 주요 이벤트 영향도
        - 특별 시기 전략
        - 이벤트 활용 방안
    • 장기적 트렌드 패턴
        - 연간 트렌드 분석
        - 성장 패턴 도출
        - 장기 전략 수립

4️⃣ 콘텐츠 제작 가이드
▶️ 포맷 최적화
 #### 성과가 좋은 콘텐츠 유형:
    • 상위 성과 콘텐츠 분석
        - 핵심 성공 요인
        - 포맷별 성과 비교
        - 최적화 포인트
    • 공통된 구성 요소
        - 효과적인 구성 방식
        - 핵심 구성 요소
        - 시청자 선호 패턴
    • 차별화 포인트
        - 독특한 강점 분석
        - 경쟁력 요소
        - 차별화 전략

 #### 시청자 참여도를 높이는 요소:
    • 효과적인 참여 유도 방법
        - 댓글 유도 전략
        - 시청자 호응 요소
        - 상호작용 최적화
    • 댓글 활성화 전략
        - 효과적인 호응 유도
        - 댓글 관리 방안
        - 커뮤니티 활성화
    • 시청자 상호작용 패턴
        - 참여 패턴 분석
        - 효과적인 소통 방식
        - 관계 구축 전략

▶️ 실전 제작 전략
 #### 구체적인 실행 방안:
    • 콘텐츠 기획 가이드
        - 기획 프로세스
        - 핵심 고려사항
        - 품질 관리 방안
    • 제작 프로세스 최적화
        - 효율적 제작 과정
        - 리소스 최적화
        - 품질 향상 방안
    • 품질 향상 전략
        - 핵심 품질 요소
        - 개선 포인트
        - 실행 가이드라인

 #### 개선점 제안:
    • 단기 개선 사항
        - 즉시 적용 가능한 개선점
        - 우선순위 설정
        - 실행 계획
    • 장기 발전 방향
        - 장기 목표 설정
        - 단계별 발전 계획
        - 성장 전략
    • 경쟁력 강화 포인트
        - 핵심 경쟁력 요소
        - 차별화 전략
        - 지속가능한 성장 방안

분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 데이터 기반의 구체적인 수치는 다음과 같이 표현해주세요:
   - 정확한 수치: '47%', '2.3배' 등
   - 시간 범위: '오전 9시~오후 3시', '15시~19시' 등
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.

각 항목은 데이터에 기반한 구체적인 수치와 예시를 포함해서 설명해주세요."""

                    second_response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=3000,
                        temperature=0.3,
                        messages=[{"role": "user", "content": second_prompt}]
                    )

# 분석 결과 표시
                    if hasattr(first_response.content[0], 'text'):
                        # 새로운 API 응답 형식
                        first_analysis = first_response.content[0].text
                        second_analysis = second_response.content[0].text
                    else:
                        # 기존 API 응답 형식
                        first_analysis = first_response.content
                        second_analysis = second_response.content

                    st.markdown(format_analysis_response(first_analysis))
                    st.markdown("---")  # 구분선 추가
                    st.markdown(format_analysis_response(second_analysis))

                except Exception as e:
                    st.error(f"AI 분석 중 오류가 발생했습니다: {str(e)}")
                    st.write("상세 오류:", e)  # 디버깅을 위한 상세 오류 표시
        else:
            st.warning("Claude API 키가 설정되지 않았습니다.")
            
    def run_analysis(self):
        try:
            if not self.youtube_api_key:
                st.error("YouTube API 키가 필요합니다.")
                return
                
            st.info("YouTube 데이터를 수집 중입니다...")
            youtube = build("youtube", "v3", developerKey=self.youtube_api_key)
            videos_data = self.collect_videos_data(youtube)
            
            if not videos_data:
                st.error("수집된 데이터가 없습니다.")
                return
                
            df = pd.DataFrame(videos_data)
            self.create_dashboard(df)
            
        except Exception as e:
            st.error(f"분석 중 오류가 발생했습니다: {str(e)}")

    def run(self):
        if not self.youtube_api_key:
            st.error("YouTube API 키를 입력해주세요.")
            return
            
        if st.sidebar.button("분석 시작", use_container_width=True):
            if self.keyword:
                self.run_analysis()
            else:
                st.error("키워드를 입력해주세요.")

if __name__ == "__main__":
    app = YouTubeAnalytics()
    app.run()
