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
import requests
from datetime import datetime, timedelta, timezone
import pytz
from supabase import create_client

class AuthManager:
    def __init__(self):
        load_dotenv()
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_ANON_KEY')  # 여기를 수정
        
        # Supabase 클라이언트 초기화
        if not self.supabase_url or not self.supabase_key:
            try:
                self.supabase_url = st.secrets["SUPABASE_URL"]
                self.supabase_key = st.secrets["SUPABASE_ANON_KEY"]  # 여기도 수정
            except:
                st.error("Supabase 설정이 필요합니다.")
                return
                
        self.supabase = create_client(self.supabase_url, self.supabase_key)
        
    def signup(self, email, password):
        try:
            response = self.supabase.auth.sign_up({
                "email": email,
                "password": password
            })
            return True, "회원가입이 완료되었습니다."
        except Exception as e:
            return False, f"회원가입 실패: {str(e)}"
            
    def login(self, email, password):
        try:
            response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            return True, response.user
        except Exception as e:
            return False, f"로그인 실패: {str(e)}"
            
    def logout(self):
        try:
            self.supabase.auth.sign_out()
            return True
        except Exception as e:
            return False

class YouTubeAnalytics:
    def __init__(self):
        self.auth = AuthManager()
        
        # 세션 상태 초기화
        if 'logged_in' not in st.session_state:
            st.session_state.logged_in = False
            
        st.set_page_config(page_title="YouTube 콘텐츠 분석 대시보드", layout="wide")
        
        # 로그인 상태가 아닐 때는 로그인/회원가입 UI 표시
        if not st.session_state.logged_in:
            self.show_auth_ui()
        else:
            # 기존 초기화 코드
            self.quota_limit = 10000
            self.quota_used = 0
            self.cache = {}
            self.load_api_keys()
            self.setup_sidebar()
            
    def show_auth_ui(self):
        st.title("🔐 로그인")
        
        tab1, tab2 = st.tabs(["로그인", "회원가입"])
        
        with tab1:
            email = st.text_input("이메일", key="login_email")
            password = st.text_input("비밀번호", type="password", key="login_password")
            
            if st.button("로그인", use_container_width=True):
                if email and password:
                    success, result = self.auth.login(email, password)
                    if success:
                        st.session_state.logged_in = True
                        st.success("로그인 성공!")
                        st.rerun()
                    else:
                        st.error(result)
                else:
                    st.warning("이메일과 비밀번호를 입력해주세요.")
                    
        with tab2:
            email = st.text_input("이메일", key="signup_email")
            password = st.text_input("비밀번호", type="password", key="signup_password")
            password_confirm = st.text_input("비밀번호 확인", type="password")
            
            if st.button("회원가입", use_container_width=True):
                if email and password and password_confirm:
                    if password != password_confirm:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        success, message = self.auth.signup(email, password)
                        if success:
                            st.success(message)
                        else:
                            st.error(message)
                else:
                    st.warning("모든 필드를 입력해주세요.")

    def setup_sidebar(self):
        with st.sidebar:
            st.title("⚙️ 검색 설정")
            
            # 로그아웃 버튼 추가
            if st.button("로그아웃", key="logout"):
                if self.auth.logout():
                    st.session_state.logged_in = False
                    st.rerun()
            
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
                # publishedAt을 datetime 객체로 파싱하고 명시적으로 UTC로 처리
                published_at = datetime.strptime(
                    item['snippet']['publishedAt'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                ).replace(tzinfo=timezone.utc)
                
                videos.append({
                    'id': item['id']['videoId'],
                    'title': item['snippet']['title'],
                    'publishedAt': published_at.isoformat(),  # ISO 형식으로 저장
                    'description': item['snippet']['description']
                })
                video_ids.append(item['id']['videoId'])
            
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
                
                # ISO 형식 날짜 파싱 수정
                publish_date = pd.to_datetime(video['publishedAt']).replace(tzinfo=None)
                
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
        
    def calculate_weekday_stats(self, df):
        # date 컬럼이 datetime 타입인지 확인하고 변환
        df['date'] = pd.to_datetime(df['date'])
        try:
            df['date'] = df['date'].dt.tz_localize(None).tz_localize('UTC').tz_convert('Asia/Seoul')
        except AttributeError:
            pass  # 이미 timezone이 설정된 경우
        except TypeError:
            df['date'] = df['date'].dt.tz_convert('Asia/Seoul')  # 이미 tz-aware인 경우
        
        df['weekday'] = df['date'].dt.day_name()
        
        # 월요일부터 시작하는 순서로 변경
        weekday_order = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
        weekday_korean = {
            'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일',
            'Thursday': '목요일', 'Friday': '금요일', 'Saturday': '토요일',
            'Sunday': '일요일'
        }
        
        weekday_stats = df.groupby('weekday').agg({
            'views': ['mean', 'sum', 'count'],
            'comments': ['mean', 'sum'],
            'likes': ['mean', 'sum'],
            'engagement_score': 'mean'
        }).round(2)
        
        weekday_stats.columns = ['평균_조회수', '총_조회수', '영상수', '평균_댓글수', '총_댓글수', 
                                '평균_좋아요수', '총_좋아요수', '평균_참여도']
                                
        # 요일 이름을 한글로 변환
        weekday_stats.index = weekday_stats.index.map(weekday_korean)
        # 월요일부터 일요일 순서로 정렬
        weekday_stats = weekday_stats.reindex(weekday_order)
        
        return weekday_stats
    
    def calculate_hourly_stats(self, df):
        # date 컬럼이 datetime 타입인지 확인하고 변환
        df['date'] = pd.to_datetime(df['date'])
        try:
            df['date'] = df['date'].dt.tz_localize(None).tz_localize('UTC').tz_convert('Asia/Seoul')
        except AttributeError:
            pass  # 이미 timezone이 설정된 경우
        except TypeError:
            df['date'] = df['date'].dt.tz_convert('Asia/Seoul')  # 이미 tz-aware인 경우
        
        df['hour'] = df['date'].dt.hour
        
        hourly_stats = df.groupby('hour').agg({
            'views': ['mean', 'sum', 'count'],
            'comments': ['mean', 'sum'],
            'likes': ['mean', 'sum'],
            'engagement_score': 'mean'
        }).round(2)
        
        hourly_stats.columns = ['평균_조회수', '총_조회수', '영상수', '평균_댓글수', '총_댓글수',
                               '평균_좋아요수', '총_좋아요수', '평균_참여도']
        
        # 모든 시간대 포함
        all_hours = pd.DataFrame(index=range(24))
        hourly_stats = hourly_stats.reindex(all_hours.index).fillna(0)
        
        return hourly_stats
        

    def create_dashboard(self, df):
        st.title(f"📊 YouTube 키워드 분석: {self.keyword}")
        
        # date 컬럼 생성을 가장 먼저 수행하고 timezone 처리
        df = df.copy()  # 원본 데이터 보호
        df['date'] = pd.to_datetime(df['publishedAt'])
        
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
        
    # 2. 통계 계산
        weekday_stats = self.calculate_weekday_stats(df.copy())
        hourly_stats = self.calculate_hourly_stats(df.copy())
        
        # AI 분석용 데이터에 시간 통계 추가할 때 데이터 검증 추가
        weekday_data = weekday_stats.to_dict('index')
        hourly_data = hourly_stats.to_dict('index')
        
        self.temporal_stats = {
            'weekday_stats': {
                'data': weekday_stats.to_dict('index'),
                'max_views_day': weekday_stats['평균_조회수'].idxmax(),
                'max_views_value': weekday_stats['평균_조회수'].max(),
                'max_engagement_day': weekday_stats['평균_참여도'].idxmax(),
                'weekday_engagement': weekday_stats['평균_참여도'].to_dict(),  # 전체 요일별 참여도 추가
                'weekday_views': weekday_stats['평균_조회수'].to_dict()  # 전체 요일별 조회수 추가
            },
            'hourly_stats': {
                'data': hourly_stats.to_dict('index'),
                'max_views_hour': int(hourly_stats['평균_조회수'].idxmax()),
                'max_views_value': hourly_stats['평균_조회수'].max(),
                'max_engagement_hour': int(hourly_stats['평균_참여도'].idxmax()),
                'hourly_engagement': hourly_stats['평균_참여도'].to_dict(),  # 전체 시간대별 참여도 추가
                'hourly_views': hourly_stats['평균_조회수'].to_dict()  # 전체 시간대별 조회수 추가
            }
        }
        
        # 3. 시계열 분석 시각화
        st.subheader("📈 시간대별 성과 분석")
        
        # 3-1. 요일별 분석
        st.markdown("#### 📅 요일별 분석")
        self.visualize_weekday_stats(weekday_stats)
        
        # 3-2. 시간대별 분석
        st.markdown("#### 🕒 시간대별 분석")
        self.visualize_hourly_stats(hourly_stats)
        
        # 4. 상위 영상 테이블
        st.subheader("🏆 상위 20개 영상")
        cols = st.columns(4)  # 한 행에 4개의 영상 표시
        
        videos_data = df.nlargest(20, 'engagement_score').to_dict('records')
        
        for idx, video in enumerate(videos_data):
           with cols[idx % 4]:
               try:
                   # 썸네일 URL 예외 처리
                   thumbnail_url = f"https://img.youtube.com/vi/{video['id']}/maxresdefault.jpg"
                   # 이미지 존재 여부 확인
                   response = requests.head(thumbnail_url)
                   if response.status_code != 200:
                       thumbnail_url = f"https://img.youtube.com/vi/{video['id']}/hqdefault.jpg"
               except:
                   thumbnail_url = f"https://img.youtube.com/vi/{video['id']}/hqdefault.jpg"
                   
               video_url = f"https://www.youtube.com/watch?v={video['id']}"
               
               # 카드 스타일의 레이아웃
               st.markdown(f"""
                   <div style="border: 1px solid #ddd; padding: 10px; border-radius: 5px; margin-bottom: 20px;">
                       <a href="{video_url}" target="_blank">
                           <img src="{thumbnail_url}" style="width: 100%; border-radius: 5px;">
                       </a>
                       <a href="{video_url}" target="_blank" style="text-decoration: none; color: #1e88e5;">
                           <p style="margin: 10px 0; font-size: 0.9em; font-weight: bold;">{video['title']}</p>
                       </a>
                       <p style="margin: 5px 0; font-size: 0.8em;">👀 조회수: {video['views']:,}</p>
                       <p style="margin: 5px 0; font-size: 0.8em;">👍 좋아요: {video['likes']:,}</p>
                       <p style="margin: 5px 0; font-size: 0.8em;">💬 댓글: {video['comments']:,}</p>
                       <p style="margin: 5px 0; font-size: 0.8em;">📊 참여도: {video['engagement_score']:.2f}</p>
                   </div>
               """, unsafe_allow_html=True)

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

    def visualize_weekday_stats(self, weekday_stats):
        col1, col2 = st.columns(2)
        
        with col1:
            fig_weekday_views = go.Figure()
            fig_weekday_views.add_trace(go.Bar(
                x=weekday_stats.index,
                y=weekday_stats['평균_조회수'],
                marker_color='#1976D2'
            ))
            fig_weekday_views.update_layout(
                title='요일별 평균 조회수',
                xaxis_title='요일',
                yaxis_title='평균 조회수',
                height=400
            )
            st.plotly_chart(fig_weekday_views, use_container_width=True)
        
        with col2:
            fig_weekday_comments = go.Figure()
            fig_weekday_comments.add_trace(go.Bar(
                x=weekday_stats.index,
                y=weekday_stats['평균_댓글수'],
                marker_color='#FFA726'
            ))
            fig_weekday_comments.update_layout(
                title='요일별 평균 댓글수',
                xaxis_title='요일',
                yaxis_title='평균 댓글수',
                height=400
            )
            st.plotly_chart(fig_weekday_comments, use_container_width=True)
    
    def visualize_hourly_stats(self, hourly_stats):
        col3, col4 = st.columns(2)
        
        with col3:
            fig_hourly_views = go.Figure()
            fig_hourly_views.add_trace(go.Bar(
                x=hourly_stats.index,
                y=hourly_stats['평균_조회수'],
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
                    range=[-0.5, 23.5]
                )
            )
            st.plotly_chart(fig_hourly_views, use_container_width=True)
        
        with col4:
            fig_hourly_comments = go.Figure()
            fig_hourly_comments.add_trace(go.Bar(
                x=hourly_stats.index,
                y=hourly_stats['평균_댓글수'],
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
                    range=[-0.5, 23.5]
                )
            )
            st.plotly_chart(fig_hourly_comments, use_container_width=True)        
            
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
                df_for_analysis['date'] = pd.to_datetime(df_for_analysis['publishedAt']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                # 필요한 컬럼만 선택
                analysis_data = df_for_analysis[[
                    'title', 'views', 'likes', 'comments', 
                    'engagement_score', 'date'
                ]].to_dict('records')
                
                # 4개의 프롬프트로 나누어 실행
                first_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.first_part_prompt(analysis_data)
                    }]
                )
                
                time.sleep(3)  # API 호출 간격 조절
    
                second_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.second_part_prompt(analysis_data)
                    }]
                )
                
                time.sleep(3)  # API 호출 간격 조절
    
                third_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.third_part_prompt(analysis_data)
                    }]
                )
                
                time.sleep(3)  # API 호출 간격 조절
    
                fourth_response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2000,
                    temperature=0.3,
                    messages=[{
                        "role": "user", 
                        "content": self.fourth_part_prompt(analysis_data)
                    }]
                )
    
                # 결과 표시
                if hasattr(first_response.content[0], 'text'):
                    # 새로운 API 응답 형식
                    analysis_parts = [
                        first_response.content[0].text,
                        second_response.content[0].text,
                        third_response.content[0].text,
                        fourth_response.content[0].text
                    ]
                else:
                    # 기존 API 응답 형식
                    analysis_parts = [
                        first_response.content,
                        second_response.content,
                        third_response.content,
                        fourth_response.content
                    ]
    
                # 각 부분을 순차적으로 표시
                for i, part in enumerate(analysis_parts):
                    st.markdown(self.format_analysis_response(part))
                    if i < len(analysis_parts) - 1:  # 마지막 부분이 아닐 경우에만 구분선 추가
                        st.markdown("---")
                
            except Exception as e:
                st.error(f"AI 분석 중 오류가 발생했습니다: {str(e)}")
                st.write("상세 오류:", e)

    def first_part_prompt(self, analysis_data):
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

분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 데이터 기반의 구체적인 수치는 다음과 같이 표현해주세요:
   - 정확한 수치: '47%', '2.3배' 등
   - 시간 범위: '오전 9시~오후 3시', '15시~19시' 등
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.
4. '주요 키워드 분석', '시청자 관심을 끄는 키워드'에서는 분석할 키워드는 제외하고 그외 키워드를 위주로 분석해주세요.
5. 마지막 부분에 분석 결과 데이터에 영향을 미친 요인에 대한 가설을 제시해주세요.

각 항목은 20개의 영상들의 예시와 데이터에 기반한 구체적인 수치를 포함해서 내용을 쉽게 풀어서 설명해주세요."""

    def second_part_prompt(self, analysis_data):
        return f"""이어서 다음 데이터를 분석하여 두 번째 파트의 인사이트를 도출해주세요:
    
    {json.dumps(analysis_data, ensure_ascii=False, indent=2)}
    
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
5. 각 항목마다 분석 데이터를 토대로 결과 데이터에 영향을 미친 요인에 대한가설을 제시해주세요.

각 항목은 20개의 영상들의 예시와 데이터에 기반한 구체적인 수치를 포함해서 내용을 쉽게 풀어서 설명해주세요."""

    def third_part_prompt(self, analysis_data):
        # temporal_stats의 상세 데이터 활용
        weekday_stats = self.temporal_stats['weekday_stats']
        hourly_stats = self.temporal_stats['hourly_stats']
        
        # 요일별, 시간별 전체 데이터를 문자열로 포맷팅 (댓글 수 중심으로 변경)
        weekday_performance = "\n".join([
            f"    - {day}: 평균 조회수 {views:,.0f}, 평균 댓글수 {weekday_stats['data'][day]['평균_댓글수']:.1f}"
            for day, views in weekday_stats['weekday_views'].items()
        ])
        
        hourly_performance = "\n".join([
            f"    - {hour}시: 평균 조회수 {views:,.0f}, 평균 댓글수 {hourly_stats['data'][hour]['평균_댓글수']:.1f}"
            for hour, views in hourly_stats['hourly_views'].items()
        ])

        # 최대값 계산 로직 수정 (댓글 수 기준)
        max_comments_day = max(weekday_stats['data'].items(), key=lambda x: x[1]['평균_댓글수'])[0]
        max_comments_hour = int(max(hourly_stats['data'].items(), key=lambda x: x[1]['평균_댓글수'])[0])
        max_comments_day_value = weekday_stats['data'][max_comments_day]['평균_댓글수']
        max_comments_hour_value = hourly_stats['data'][max_comments_hour]['평균_댓글수']

        content = f"""다음 데이터를 분석하여 세 번째 파트의 인사이트를 도출해주세요.
        실제 데이터 분석 결과:
        
        요일별 성과:
    {weekday_performance}

        시간대별 성과:
    {hourly_performance}

        주요 성과 지표:
        - 최고 조회수 요일: {weekday_stats['max_views_day']} ({weekday_stats['max_views_value']:,.0f}회)
        - 최다 댓글 요일: {max_comments_day} ({max_comments_day_value:.1f}개)
        - 최고 조회수 시간: {hourly_stats['max_views_hour']}시 ({hourly_stats['max_views_value']:,.0f}회)
        - 최다 댓글 시간: {max_comments_hour}시 ({max_comments_hour_value:.1f}개)
        
        분석할 데이터:
        {json.dumps(analysis_data, ensure_ascii=False, indent=2)}

3️⃣ 시간 기반 인사이트
▶️ 업로드 전략
 #### 최적의 업로드 시간대:
    • 실제 데이터 기반 분석
        - 시간대별 평균 조회수 분석
        - 시간대별 평균 댓글수 분석
        - 최고 성과를 보인 구체적인 시간대 명시
    • 시청자 참여가 가장 활발한 시간대
        - 댓글 작성이 가장 활발한 시간대 분석
        - 구체적인 최적 시간대 도출
        - 시간대별 댓글수 차이의 정량적 분석

 #### 요일별 성과 분석:
    • 구체적인 요일별 성과
        - 각 요일별 평균 조회수 분석
        - 각 요일별 평균 댓글수 분석
        - 최적의 업로드 요일 도출
    • 요일별 시청자 참여 패턴
        - 댓글 작성이 가장 활발한 요일 분석
        - 최고/최저 댓글수를 기록한 요일
        - 요일별 시청자 참여도 차이의 정량적 분석

 #### 시즌별 트렌드:
    • 계절별 성과 비교
        - 계절별 조회수와 댓글수 차이
        - 시즌별 시청자 참여 특성
        - 시즌 맞춤 전략
    • 특정 기간 성과 패턴
        - 주요 성과 구간 분석
        - 성공 요인 도출
        - 전략적 활용 방안
    • 장기적 트렌드 패턴
        - 연간 트렌드 분석
        - 성장 패턴 도출
        - 장기 전략 수립

분석 시 다음 가이드라인을 준수해주세요:
1. 시간 범위를 표현할 때는 '~' 를 사용해주세요 (예: 오전 9시~오후 3시)
2. 모든 수치는 구체적인 값으로 제시 (예: '평균 47.2개의 댓글', '2.3배 높은 조회수')
3. 모든 분석 내용은 들여쓰기와 함께 계층 구조로 표현해주세요.
4. 시간은 24시간 형식으로 표시해주세요. (예: '15시~19시')
5. 최적 시간대와 요일은 데이터상 가장 높은 수치를 보인 것을 기준으로 제시해주세요
6. 인게이지먼트 스코어 대신 순수 댓글 수를 기준으로 시청자 참여도를 분석해주세요.
7. 시간 기반 인사이트를 토대로 전략적인 제언을 제시해주세요.

실제 데이터에 기반한 구체적인 수치와 함께 인사이트를 제공하고 내용을 쉽게 풀어서 설명해주세요."""

        return content

    def fourth_part_prompt(self, analysis_data):
        return f"""이어서 다음 데이터를 분석하여 네 번째 파트의 인사이트를 도출해주세요:
        
    {json.dumps(analysis_data, ensure_ascii=False, indent=2)}

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
5. 시청자들의 댓글 분석 섹션의 내용이 좀더 디테일하게 구성하고 실제 댓글 예시를 들어서 설명해주세요.
6. 댓글 분석 시 부정 댓글과 긍정적 댓글은 각각 어떤 내용이 많았는지도 보여주세요.
7. 댓글 기반 인사이트를 토대로 시청자들이 가장 중요하게 생각하는 포인트들을 분석해주세요.

각 항목은 20개의 영상들의 예시와 데이터에 기반한 구체적인 수치를 포함해서 내용을 쉽게 풀어서 설명해주세요."""

    def run(self):
        """앱 실행"""
        if not st.session_state.logged_in:
            return
            
        if not self.youtube_api_key:
            st.error("YouTube API 키를 입력해주세요.")
            return
            
        if not self.keyword:  # 키워드가 입력되지 않았을 때 소개 페이지 표시
            st.header("⛏️유튜브 인사이트 마이닝💎")
            
            # 섹션 1: 소개
            st.subheader("🤓피부과 인하우스 마케터 태팀장입니다!")
            st.markdown("""
            여러분은 콘텐츠 기획을 어떻게 하시나요?  
            저는 유튜브API를 통해 얻은 데이터를 활용하는데요.  
            추출한 데이터를 이용해 인기 영상의 제목 패턴과 댓글 키워드를  
            Claude ai로 분석하고 인사이트를 도출합니다.  
            유튜브 인싸이트 마이닝은 이러한 분석 과정을 자동화한 도구입니다.  
            실무에 활용할 수 있는 실용적인 콘텐츠 인사이트를 가져가세요!
            
            * 📊 상세한 데이터 분석과 시각화
            * 🤖 Claude AI를 활용한 인사이트 도출
            * ⏰ 최적의 업로드 시간 분석
            * 📈 시청자 댓글 분석
            """)
            
            # 섹션 2: 사용 방법
            st.subheader("📝 사용법")
            st.markdown("""
            1️⃣ **분석 설정**
            * 분석하고 싶은 키워드를 입력해주세요
            * 검색할 영상 수를 선택해주세요 (10~100개)
            * 분석 기간을 선택해주세요 (1~24개월)
            
            2️⃣ **분석 시작**
            * 모든 설정을 완료한 후 '분석 시작' 버튼을 클릭하세요
            * 분석에는 약 1~2분이 소요됩니다
            
            3️⃣ **결과 확인**
            * 데이터 기반 성과 패턴
            * 최적화 인사이트
            * 시간 기반 인사이트
            * 콘텐츠 제작 가이드
            """)
            
            # 제안
            st.warning("""
            📢 **알림**
            * 성형어플 경쟁사 가격 조사 앱이 곧 완성됩니다. 필요하신 분들께 무료로 공유하겠습니다.  
            * 병원 마케팅 질문 많이 주시는데.. 아는 선에서 최대한 답변 드리도록 하겠습니다.    
            * 이 앱은 개인적으로 업무에 활용하기 위해 만들어졌습니다.  
             콘텐츠 기획에 어려움을 겪고 있는 분들을 위해 무료로 공유합니다.  
             부족한 점이 있더라도 이해해주시고, 업무에 조금이나마 도움이 되셨으면 좋겠습니다.  
            * 마케팅 자동화 관련 아이디어 환영합니다. bbachinco@gmail.com
            """)
            
            # 주의사항
            st.warning("""
            ⚠️ **주의사항**
            * 더 정확한 분석을 위해 충분한 수의 영상을 선택해주세요.  
            * YouTube API는 일일 할당량이 제한되어 있습니다.  
            * Claude API 잔액이 부족할 경우 AI 분석이 지원되지 않을 수 있습니다.
            """)
            
        elif st.sidebar.button("분석 시작", use_container_width=True):
            self.run_analysis()

if __name__ == "__main__":
    app = YouTubeAnalytics()
    app.run()
