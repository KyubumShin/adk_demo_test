# 소설 등장인물 추출 에이전트 (ADK Demo 3)

소설 텍스트에서 등장인물을 자동으로 추출하고, 검증한 후 데이터베이스에 저장하는 Google ADK 기반 멀티 에이전트 시스템입니다.

## 아키텍처

```
root_agent (novel_character_manager)
├── novel_analysis_pipeline (SequentialAgent)
│   ├── Step 1: character_extractor (LlmAgent) - 등장인물 추출
│   ├── Step 2: data_validator (LlmAgent) - 데이터 검증
│   └── Step 3: character_saver (BaseAgent) - DB 저장 (LLM 미사용)
│
└── character_query_agent (LlmAgent) - 저장된 캐릭터 조회
```

## 주요 기능

- **등장인물 추출**: 소설 텍스트에서 인물 정보 (이름, 사건, 특징, 직업, 관계) 자동 추출
- **데이터 검증**: 추출된 정보가 실제 소설에 존재하는지 Judge 에이전트가 검증
- **DB 저장**: 검증 통과(PASS)한 인물만 DuckDB에 저장 (LLM 호출 없이 직접 저장)
- **캐릭터 조회**: 저장된 인물 목록 및 상세 정보 조회

## 설치

### 1. 가상환경 생성 및 활성화

```bash
# conda 사용 시
conda create -n adk_demo python=3.10
conda activate adk_demo

# 또는 venv 사용 시
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate  # Windows
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 3. Google API 키 설정

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

또는 `.env` 파일 생성:
```
GOOGLE_API_KEY=your-api-key-here
```

## 실행

### ADK Web UI로 실행

```bash
# 프로젝트 상위 디렉토리에서 실행
cd /path/to/project
adk web adk_demo3
```

브라우저에서 `http://localhost:8000` 접속

### 프로그래밍 방식으로 실행

```python
from adk_demo3 import root_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

async def main():
    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="novel_character_manager",
        session_service=session_service
    )
    
    session = await session_service.create_session(
        app_name="novel_character_manager",
        user_id="user1"
    )
    
    # 소설 분석 요청
    novel_text = """
    지후는 오래된 사진 한 장을 들고 낡은 카페 바람결 앞에 멈춰 섰다.
    사진 속에는 환하게 웃던 지후, 말없이 둘을 바라보던 윤아, 
    그리고 장난스러운 표정의 수안이 있었다...
    """
    
    async for event in runner.run_async(
        user_id="user1",
        session_id=session.id,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=novel_text)]
        )
    ):
        if event.content and event.content.parts:
            print(event.content.parts[0].text)

import asyncio
asyncio.run(main())
```

## 사용 예시

### 소설 분석

채팅창에 소설 텍스트를 입력하면 자동으로:
1. 등장인물 정보 추출
2. 추출된 정보 검증
3. 검증 통과한 인물 DB 저장

### 저장된 캐릭터 조회

```
저장된 인물 보여줘
```

```
지후에 대해 알려줘
```

## 파일 구조

```
adk_demo3/
├── __init__.py          # 패키지 초기화, root_agent 노출
├── agent.py             # 에이전트 정의
├── tools.py             # DuckDB 저장/조회 함수
├── requirements.txt     # 의존성 목록
├── characters.db        # DuckDB 데이터베이스 (자동 생성)
└── README.md            # 이 파일
```

## 데이터베이스 스키마

```sql
CREATE TABLE characters (
    full_name VARCHAR PRIMARY KEY,    -- 인물 이름
    events TEXT,                      -- 관련 사건 (JSON)
    characteristics TEXT,             -- 특징 (JSON)
    occupation VARCHAR,               -- 직업
    relationships TEXT,               -- 관계 (JSON)
    novel_title VARCHAR,              -- 소설 제목
    created_at TIMESTAMP              -- 생성 시간
)
```

## 기술 스택

- **Google ADK**: 멀티 에이전트 프레임워크
- **Gemini 2.5 Flash**: LLM 모델
- **DuckDB**: 임베디드 데이터베이스
- **Python 3.10+**

## 트러블슈팅

### `GOOGLE_API_KEY` 오류
```bash
export GOOGLE_API_KEY="your-key"
```

### DuckDB 권한 오류
`characters.db` 파일이 있는 디렉토리에 쓰기 권한이 있는지 확인

### 모듈 import 오류
프로젝트 상위 디렉토리에서 `adk web` 명령 실행 (패키지로 인식되어야 함)

