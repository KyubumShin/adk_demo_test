"""
소설 등장인물 추출 및 저장 에이전트

Sequential Pipeline: 등장인물 추출 → 검증 → DB 저장 (순차 실행)
Character Query Agent: 저장된 캐릭터 조회 (별도 유지)
Root Agent: 요청에 따라 적절한 sub_agent 호출
"""
import json
import re
from typing import AsyncGenerator

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types

from .tools import save_character, get_character, list_all_characters


# ============================================================
# Step 1: 등장인물 데이터 추출 에이전트
# ============================================================
character_extractor_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='character_extractor',
    description='소설 텍스트에서 등장인물 정보를 추출하는 에이전트',
    instruction="""당신은 소설 텍스트 분석 전문가입니다. 주어진 소설 텍스트에서 등장인물들의 정보를 추출합니다.

각 등장인물에 대해 다음 정보를 추출하세요:
- full_name: 등장인물의 전체 이름 (소설에 나온 그대로)
- events: 해당 인물이 관련된 사건들 (소설에서 직접 언급된 것만), 연속된 사건일 경우 요약해서 하나의 사건으로 처리
- characteristics: 인물의 특징들 (성격, 외모, 습관 등 - 명시적으로 언급된 것만)
- occupation: 인물의 직업 또는 역할
- relationships: 다른 인물과의 관계
- evidence: 각 정보의 근거가 되는 원문 인용구

중요 규칙:
- 소설 텍스트에 명시적으로 언급된 정보만 추출하세요
- 추론이나 가정은 하지 마세요
- 각 정보의 근거가 될 수 있는 원문 인용구를 반드시 함께 제시하세요

반드시 아래 JSON 형식으로만 응답하세요:
```json
{
    "novel_text": "원본 소설 텍스트 (다음 단계로 전달용)",
    "characters": [
        {
            "full_name": "인물 이름",
            "events": ["사건1", "사건2"],
            "characteristics": ["특징1", "특징2"],
            "occupation": "직업",
            "relationships": ["관계1", "관계2"],
            "evidence": {
                "name_evidence": "이름이 언급된 원문",
                "events_evidence": ["사건 관련 원문1"],
                "characteristics_evidence": ["특징 관련 원문1"],
                "occupation_evidence": "직업 관련 원문"
            }
        }
    ]
}
```""",
)


# ============================================================
# Step 2: 데이터 검증 에이전트 (Judge)
# ============================================================
data_validator_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='data_validator',
    description='추출된 등장인물 데이터가 실제 소설 내용과 일치하는지 검증하는 Judge 에이전트',
    instruction="""당신은 데이터 검증 전문가(Judge)입니다. 이전 단계에서 추출된 등장인물 정보가 실제 소설 텍스트에 존재하는지 엄격하게 검증합니다.

이전 에이전트의 출력에서 novel_text와 characters 정보를 받아 검증을 수행합니다.

검증 기준:
- 이름 검증: 추출된 이름이 소설에 정확히 존재하는가?
- 사건 검증: 해당 인물이 언급된 사건들이 실제로 소설에 있는가?
- 특징 검증: 인물의 특징이 소설에서 명시적으로 언급되었는가?
- 직업 검증: 직업/역할이 소설에서 확인되는가?
- 관계 검증: 다른 인물과의 관계가 소설에서 확인되는가?

검증 규칙:
- 소설 원문에 명확한 근거가 있어야만 "PASS"
- 추론이나 해석에 의존한 정보는 "FAIL"
- 부분적으로 맞는 경우에도 엄격하게 판단

PASS 기준 (overall_verdict):
- 이름이 정확히 일치해야 함
- 사건 중 50% 이상이 검증되어야 함
- 특징 중 50% 이상이 검증되어야 함
- 직업이 확인되거나 "불명"으로 표시되어야 함

반드시 아래 JSON 형식으로만 응답하세요:
```json
{
    "validation_results": [
        {
            "full_name": "인물 이름",
            "overall_verdict": "PASS",
            "validation_details": {
                "name": {"verdict": "PASS", "reason": "검증 이유"},
                "events": {"verdict": "PASS", "reason": "검증 이유", "valid_events": ["검증된 사건"], "invalid_events": []},
                "characteristics": {"verdict": "PASS", "reason": "검증 이유", "valid_chars": ["검증된 특징"], "invalid_chars": []},
                "occupation": {"verdict": "PASS", "reason": "검증 이유"},
                "relationships": {"verdict": "PASS", "reason": "검증 이유"}
            },
            "verified_data": {
                "full_name": "검증된 이름",
                "events": ["검증된 사건만"],
                "characteristics": ["검증된 특징만"],
                "occupation": "검증된 직업",
                "relationships": ["검증된 관계만"]
            }
        }
    ]
}
```""",
)


# ============================================================
# Step 3: DB 저장 에이전트 (LLM 없이 Event 객체 반환)
# ============================================================
class CharacterSaverAgent(BaseAgent):
    """검증 결과에서 PASS인 캐릭터만 저장하는 에이전트 (LLM 미사용)"""
    
    def __init__(self):
        super().__init__(
            name='character_saver',
            description='검증된 등장인물 정보를 데이터베이스에 저장하는 에이전트'
        )
    
    def _extract_json_from_text(self, text: str) -> dict | None:
        """텍스트에서 JSON 블록 추출"""
        # text: 접두사 제거
        if text.startswith('text:'):
            text = text[5:]
        
        # 앞뒤 따옴표 제거
        text = text.strip().strip('"').strip("'")
        
        # ```json ... ``` 블록 찾기
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # { 로 시작하는 JSON 객체 찾기
        json_obj_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_obj_match:
            try:
                return json.loads(json_obj_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 그냥 JSON 파싱 시도
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _create_event(self, text: str) -> Event:
        """텍스트로 Event 객체 생성"""
        return Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[genai_types.Part(text=text)]
            ),
            turnComplete=True
        )
    
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """검증 결과에서 PASS인 캐릭터만 저장"""
        
        # 세션 이벤트에서 validation_results가 포함된 텍스트 찾기
        validation_text = ""
        for event in reversed(list(ctx.session.events)):
            try:
                # event.content.parts[].text 구조
                if hasattr(event, 'content') and event.content:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                if 'validation_results' in part.text:
                                    validation_text = part.text
                                    break
                if validation_text:
                    break
            except Exception:
                continue
        
        if not validation_text:
            yield self._create_event("이전 단계의 검증 결과를 찾을 수 없습니다.")
            return
        
        # JSON 파싱
        data = self._extract_json_from_text(validation_text)
        if not data or 'validation_results' not in data:
            yield self._create_event(f"검증 결과 JSON을 파싱할 수 없습니다.")
            return
        
        # PASS인 캐릭터만 저장
        saved = []
        failed = []
        
        for result in data['validation_results']:
            if result.get('overall_verdict') == 'PASS':
                verified = result.get('verified_data', {})
                # occupation이 null인 경우 '불명'으로 처리
                occupation = verified.get('occupation')
                if occupation is None:
                    occupation = '불명'
                
                save_result = save_character(
                    full_name=verified.get('full_name', ''),
                    events=verified.get('events', []),
                    characteristics=verified.get('characteristics', []),
                    occupation=occupation,
                    relationships=verified.get('relationships', [])
                )
                if save_result.get('status') == 'success':
                    saved.append(verified.get('full_name'))
                else:
                    failed.append({
                        'name': verified.get('full_name'),
                        'reason': save_result.get('message')
                    })
            else:
                failed.append({
                    'name': result.get('full_name'),
                    'reason': '검증 실패 (FAIL)'
                })
        
        # 결과 보고
        report_lines = ["## 저장 결과\n"]
        report_lines.append(f"✅ **저장 성공**: {len(saved)}명")
        if saved:
            report_lines.append(f"   - {', '.join(saved)}")
        
        report_lines.append(f"\n❌ **저장 실패**: {len(failed)}명")
        for f in failed:
            report_lines.append(f"   - {f['name']}: {f['reason']}")
        
        yield self._create_event('\n'.join(report_lines))


character_saver_agent = CharacterSaverAgent()


# ============================================================
# Sequential Pipeline: 소설 분석 파이프라인
# ============================================================
novel_analysis_pipeline = SequentialAgent(
    name='novel_analysis_pipeline',
    description='소설 텍스트를 분석하여 등장인물을 추출, 검증, 저장하는 순차 파이프라인. 소설 내용이 입력되면 이 파이프라인을 사용합니다.',
    sub_agents=[character_extractor_agent, data_validator_agent, character_saver_agent],
)


# ============================================================
# Character Query Agent: 저장된 캐릭터 조회
# ============================================================
character_query_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='character_query',
    description='저장된 등장인물 정보를 조회하는 에이전트. 캐릭터 목록 조회, 특정 캐릭터 정보 조회 시 사용합니다.',
    instruction="""당신은 등장인물 데이터베이스 조회 전문가입니다.

사용 가능한 도구:
- get_character: 특정 등장인물의 상세 정보 조회 (full_name 필요)
- list_all_characters: 저장된 모든 등장인물 목록 조회

사용자의 요청에 따라 적절한 도구를 사용하여 정보를 제공하세요.
결과를 사용자가 이해하기 쉽게 정리하여 보여주세요.""",
    tools=[get_character, list_all_characters],
)


# ============================================================
# Root Agent: 전체 시스템 조정
# ============================================================
root_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='novel_character_manager',
    description='소설 등장인물 관리 시스템의 최상위 에이전트',
    instruction="""당신은 소설 등장인물 관리 시스템의 총괄 에이전트입니다.

## 사용 가능한 Sub Agents

1. **novel_analysis_pipeline**: 소설 분석 순차 파이프라인
   - 소설 텍스트가 입력되면 이 파이프라인을 사용합니다
   - 자동으로 추출 → 검증 → 저장이 순차적으로 실행됩니다

2. **character_query**: 캐릭터 조회 에이전트
   - 저장된 캐릭터 목록 보기
   - 특정 캐릭터 상세 정보 조회

## 요청 분류 및 처리

- 소설 텍스트 제공 / "소설 분석해줘" → novel_analysis_pipeline 호출
- "저장된 인물 보여줘" / "캐릭터 목록" → character_query 호출
- 특정 인물 정보 요청 → character_query 호출

사용자의 요청을 정확히 파악하여 적절한 sub_agent에게 위임하세요.""",
    sub_agents=[novel_analysis_pipeline, character_query_agent],
)
