# Point3 CRM - 영업지도

## 프로젝트 개요
영업팀용 CRM 웹앱. 가맹점 위치를 지도에 표시하고 방문기록/일정을 관리한다.

## 기술 스택
- **백엔드**: Flask (Python 3) — `main.py` 단일 파일
- **프론트엔드**: HTML/CSS/JS (templates/ 폴더), Leaflet.js 지도, Chart.js 대시보드
- **DB**: Firebase Firestore (REST API, API 키 인증)
- **배포**: Render.com (Free 플랜, GitHub push → 자동 배포)
- **지오코딩**: 카카오 API

## 파일 구조
```
main.py              # Flask 백엔드 전체 (인증, API, Firestore 헬퍼)
requirements.txt     # Python 의존성
render.yaml          # Render 배포 설정
Dockerfile           # 컨테이너 빌드
templates/
  map.html           # 메인 지도 (마커, 클러스터, 다크모드, 상세패널)
  admin.html         # 가맹점 등록/엑셀 업로드
  stores.html        # 가맹점 목록 테이블
  dashboard.html     # 통계 대시보드
  calendar.html      # 방문 캘린더
  login.html         # 로그인/회원가입 + Google OAuth
  team-setup.html    # 팀 이름 설정
  pending.html       # 승인 대기
  approve.html       # 관리자 팀원 관리
static/
  manifest.json      # PWA 매니페스트
  sw.js              # 서비스워커
  icon.svg           # 앱 아이콘
```

## 개발 규칙

### 코드 스타일
- main.py는 모놀리식 구조. 새 기능도 main.py에 추가.
- 프론트엔드는 각 HTML 파일에 인라인 `<style>`, `<script>` 포함 (별도 JS/CSS 파일 없음).
- 한국어 주석 사용.

### 배포
- `git push origin master` → Render 자동 배포 (2~3분).
- 배포 전 반드시 로컬에서 `python main.py`로 테스트.
- push/배포는 사용자가 명시적으로 요청할 때만 실행.

### DB (Firestore)
- REST API 방식 (`requests` 모듈). 서비스 계정 키 없이 API 키로 접근.
- 주요 컬렉션: `stores`, `users`
- 팀 기반 데이터 격리: 같은 `teamName`만 데이터 공유.
- Firestore 응답은 `_fs_to_dict()` / `_dict_to_fs()`로 변환.

### 인증
- 자체 회원가입 + Google OAuth.
- 가입 → 팀 이름 설정 → 관리자 승인 → 사용 가능.
- superadmin: `leesk0130`

### UI/디자인
- 프리미엄 디자인 스타일 유지 (깔끔하고 세련되게).
- Pretendard Variable 폰트 사용.
- 모바일 반응형 필수.

### 주의사항
- API 키, 비밀번호 등 민감 정보를 커밋 메시지나 로그에 노출하지 않기.
- HTML 파일 수정 시 기존 인라인 스타일/스크립트 구조 유지.
- 수정 후 반드시 결과 검증 (코드 읽기, 로컬 테스트).
