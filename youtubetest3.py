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
import time  # time 모듈 추가

class YouTubeAnalytics:
    def __init__(self):
        # API 할당량 관리와 캐시 초기화 추가
        self.quota_limit = 10000  # 일일 할당량
        self.quota_used = 0  # 사용된 할당량 추적
        self.cache = {}  # 캐시 초기화
        
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

    def check_quota(self, cost):
        """API 호출 전 할당량 확인"""
        if self.quota_used + cost > self.quota_limit:
            raise Exception("일일 API 할당량 초과")
        self.quota_used += cost
        return True

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
        cache_key = f"{self.keyword}_{self.date_range}"
        
        # 캐시 확인
        if cache_key in self.cache:
            return self.cache[cache_key]
            
        try:
            date_limit = (datetime.now() - timedelta(days=30 * self.date_range)).isoformat() + "Z"
            
            # search().list 호출 전 할당량 확인 (100 units)
            self.check_quota(100)
            
            # 첫 번째 API 호출: 검색 및 snippet 정보 함께 가져오기
            search_response = youtube.search().list(
                q=self.keyword,
                type="video",
                part="id,snippet",  # snippet 포함하여 API 호출 최소화
                maxResults=min(50, self.max_results),
                publishedAfter=date_limit
            ).execute()
            
            videos = []
            video_ids = []
            
            for item in search_response.get('items', []):
                video_ids.append(item['id']['videoId'])
                videos.append({
                    'id': item['id']['videoId'],
                    'title': item['snippet']['title'],
                    'publishedAt': item['snippet']['publishedAt'],
                    'description': item['snippet']['description']
                })
            
            if video_ids:
                # videos().list 호출 전 할당량 확인 (1 unit per video)
                self.check_quota(len(video_ids))
                
                # API 호출 간격 조절
                time.sleep(0.5)
                
                # 두 번째 API 호출: 통계 정보
                videos_response = youtube.videos().list(
                    part='statistics,contentDetails',
                    id=','.join(video_ids)
                ).execute()
                
                # videos().list 호출 후에 댓글 수집 추가
                for video in videos:
                    try:
                        # 댓글 수집 전 할당량 확인
                        self.check_quota(1)
                        comments_response = youtube.commentThreads().list(
                            part="snippet",
                            videoId=video['id'],
                            maxResults=100
                        ).execute()
                        
                        video['comments_data'] = [
                            item['snippet']['topLevelComment']['snippet']['textDisplay']
                            for item in comments_response.get('items', [])
                        ]
                    except Exception as e:
                        video['comments_data'] = []
                
                for video_data in videos_response.get('items', []):
                    video_id = video_data['id']
                    for video in videos:
                        if video['id'] == video_id:
                            stats = video_data['statistics']
                            video.update({
                                'views': int(stats.get('viewCount', 0)),
                                'likes': int(stats.get('likeCount', 0)),
                                'comments': int(stats.get('commentCount', 0)),
                                'duration': video_data['contentDetails']['duration']
                            })
            
            # 1000회 이상 조회된 영상 필터링
            filtered_videos = [
                video for video in videos 
                if video.get('views', 0) >= 1000
            ]
            
            processed_videos = self.calculate_engagement_scores(filtered_videos)
            
            # 결과 캐싱
            self.cache[cache_key] = processed_videos
            
            return processed_videos
            
        except Exception as e:
            st.error(f"데이터 수집 중 오류: {str(e)}")
            return []

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
            current_dir = os.path.dirname(os.path.abspath(__file__))
            font_path = os.path.join(current_dir, 'Pretendard-Bold.ttf')

            wordcloud = WordCloud(
                width=800, 
                height=400,
                background_color='white',
                font_path=font_path,
                prefer_horizontal=0.7
            ).generate(' '.join(df['title']))

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis('off')
            st.pyplot(fig)

        except Exception as e:
            st.error(f"워드클라우드 생성 중 오류가 발생했습니다: {str(e)}")
            st.info("워드클라우드를 생성할 수 없습니다. 한글 폰트 설정을 확인해주세요.")

    def run_analysis(self):
        try:
            if not self.youtube_api_key:
                st.error("YouTube API 키가 필요합니다.")
                return
                
            st.info("YouTube 데이터를 수집 중입니다...")
            youtube = build("youtube", "v3", developerKey=self.youtube_api_key)
            
            # API 할당량 초과 확인
            try:
                videos_data = self.collect_videos_data(youtube)
            except Exception as e:
                if "일일 API 할당량 초과" in str(e):
                    st.error("YouTube API 일일 할당량이 초과되었습니다. 내일 다시 시도해주세요.")
                    return
                raise e
            
            if not videos_data:
                st.error("수집된 데이터가 없습니다.")
                return
                
            df = pd.DataFrame(videos_data)
            self.create_dashboard(df)
            
            # Claude AI 분석 실행
            if self.claude_api_key:
                self.run_ai_analysis(df)
            
        except Exception as e:
            st.error(f"분석 중 오류가 발생했습니다: {str(e)}")


    def format_analysis_response(self, text):
        """Claude API 응답을 가독성 있게 포맷팅하는 함수"""
        formatted_text = ""
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:  # 빈 줄 처리
                formatted_text += "\n"
            elif any(emoji in line for emoji in ['1️⃣', '2️⃣', '3️⃣', '4️⃣']):
                formatted_text += f"\n\n### {line}\n"
            elif line.startswith('▶️'):
                formatted_text += f"\n#### {line}\n"
            elif line.startswith('####'):
                formatted_text += f"\n{line}\n"
            elif line.startswith('•'):
                formatted_text += f"\n    * {line[1:].strip()}\n"
            elif line.strip().startswith('-'):
                formatted_text += f"\n        - {line[1:].strip()}\n"
            else:
                formatted_text += f"{line}\n"
        
        return formatted_text

    def run_ai_analysis(self, df):
        st.subheader("🤖 AI 분석 인사이트")
        
        if not self.claude_api_key:
            st.warning("Claude API 키가 설정되지 않았습니다.")
            return
            
        with st.spinner("AI 분석을 수행중입니다..."):
            try:
                client = Anthropic(api_key=self.claude_api_key)
                
                # DataFrame을 JSON으로 변환하기 전에 전처리
                df_for_analysis = df.copy()
                df_for_analysis['date'] = df_for_analysis['date'].astype(str)
                
                # 필요한 컬럼만 선택
                analysis_data = df_for_analysis[[
                    'title', 'views', 'likes', 'comments', 
                    'engagement_score', 'date'
                ]].to_dict('records')
                
                # 기존의 두 부분으로 나눈 프롬프트 방식 유지
                first_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.first_prompt(analysis_data)
                    }]
                )

                time.sleep(4)  # API 호출 간격 조절

                second_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.second_prompt(analysis_data)
                    }]
                )

                # 결과 표시
                if hasattr(first_response.content[0], 'text'):
                    # 새로운 API 응답 형식
                    first_analysis = first_response.content[0].text
                    second_analysis = second_response.content[0].text
                else:
                    # 기존 API 응답 형식
                    first_analysis = first_response.content
                    second_analysis = second_response.content

                st.markdown(self.format_analysis_response(first_analysis))
                st.markdown("---")  # 구분선 추가
                st.markdown(self.format_analysis_response(second_analysis))
                
            except Exception as e:
                st.error(f"AI 분석 중 오류가 발생했습니다: {str(e)}")
                st.write("상세 오류:", e)

    # 프롬프트 생성 함수들 추가
    def first_prompt(self, analysis_data):
        return f"""당신은 YouTube 데이터 분석 전문가입니다. 
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


분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 데이터 기반의 구체적인 수치는 다음과 같이 표현해주세요:
   - 정확한 수치: '47%', '2.3배' 등
   - 시간 범위: '오전 9시~오후 3시', '15시~19시' 등
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.
4. '주요 키워드 분석', '시청자 관심을 끄는 키워드'에서는 분석할 키워드는 제외하고 그외 키워드를 위주로 분석해주세요.
5. 각 항목별 분석 데이터를 토대로 왜 이런 값이 나왔을지 요인에 대한 가설을 내세워보세요.

각 항목은 20개의 영상들의 예시와 데이터에 기반한 구체적인 수치를 포함해서 내용을 쉽게 풀어서 설명해주세요."""

    def second_prompt(self, analysis_data):
        return f"""이어서 다음 데이터를 분석하여 두 번째 파트의 인사이트를 도출해주세요:

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

▶️ 댓글 분석을 통한 기획
#### 댓글 내용 분석:
    • 주요 키워드 및 토픽
        - 자주 언급되는 키워드
        - 주요 관심사 및 주제
    • 시청자 감정/태도
        - 긍정적 반응 패턴
        - 부정적 피드백 분석
    • 시청자 니즈 파악
        - 자주 나오는 질문
        - 요청사항 및 제안


분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 데이터 기반의 구체적인 수치는 다음과 같이 표현해주세요:
   - 정확한 수치: '47%', '2.3배' 등
   - 시간 범위: '오전 9시~오후 3시', '15시~19시' 등
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.
4. '핵심 키워드'에 대해 분석할 때는 분석할 키워드는 제외하고 그외 키워드를 위주로 분석해주세요.
5. 각 항목별 분석 데이터를 토대로 왜 이런 값이 나왔을지 요인에 대한 가설을 내세워보세요.

각 항목은 20개의 영상들의 예시와 데이터에 기반한 구체적인 수치를 포함해서 내용을 쉽게 풀어서 설명해주세요."""

    def run(self):
        """앱 실행"""
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
