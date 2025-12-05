"""DuckDB를 이용한 등장인물 저장 및 조회 tools"""
import duckdb
import json
from pathlib import Path

# DuckDB 파일 경로
DB_PATH = Path(__file__).parent / "characters.db"

def _get_connection():
    """DuckDB 연결 생성 및 테이블 초기화"""
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            full_name VARCHAR PRIMARY KEY,
            events TEXT,
            characteristics TEXT,
            occupation VARCHAR,
            relationships TEXT,
            novel_title VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn

def save_character(
    full_name: str,
    events: list[str],
    characteristics: list[str],
    occupation: str,
    relationships: list[str] = None,
    novel_title: str = None
) -> dict:
    """
    검증된 등장인물 정보를 DuckDB에 저장합니다.
    
    Args:
        full_name: 등장인물의 전체 이름 (Primary Key)
        events: 해당 인물이 관련된 사건들의 리스트
        characteristics: 인물의 특징들 (성격, 외모 등)
        occupation: 인물의 직업
        relationships: 다른 인물과의 관계 (선택)
        novel_title: 소설 제목 (선택)
    
    Returns:
        저장 결과를 담은 딕셔너리
    """
    try:
        conn = _get_connection()
        
        # 리스트를 JSON 문자열로 변환
        events_json = json.dumps(events, ensure_ascii=False)
        characteristics_json = json.dumps(characteristics, ensure_ascii=False)
        relationships_json = json.dumps(relationships or [], ensure_ascii=False)
        
        # UPSERT 수행 (이미 존재하면 업데이트)
        conn.execute("""
            INSERT INTO characters (full_name, events, characteristics, occupation, relationships, novel_title)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (full_name) DO UPDATE SET
                events = EXCLUDED.events,
                characteristics = EXCLUDED.characteristics,
                occupation = EXCLUDED.occupation,
                relationships = EXCLUDED.relationships,
                novel_title = EXCLUDED.novel_title,
                created_at = NOW()
        """, [full_name, events_json, characteristics_json, occupation, relationships_json, novel_title])
        
        conn.close()
        
        return {
            "status": "success",
            "message": f"등장인물 '{full_name}'이(가) 성공적으로 저장되었습니다.",
            "saved_data": {
                "full_name": full_name,
                "events": events,
                "characteristics": characteristics,
                "occupation": occupation,
                "relationships": relationships,
                "novel_title": novel_title
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"저장 중 오류 발생: {str(e)}"
        }

def get_character(full_name: str) -> dict:
    """
    저장된 등장인물 정보를 조회합니다.
    
    Args:
        full_name: 조회할 등장인물의 전체 이름
    
    Returns:
        등장인물 정보 또는 오류 메시지
    """
    try:
        conn = _get_connection()
        result = conn.execute(
            "SELECT * FROM characters WHERE full_name = ?", 
            [full_name]
        ).fetchone()
        conn.close()
        
        if result:
            return {
                "status": "found",
                "character": {
                    "full_name": result[0],
                    "events": json.loads(result[1]),
                    "characteristics": json.loads(result[2]),
                    "occupation": result[3],
                    "relationships": json.loads(result[4]) if result[4] else [],
                    "novel_title": result[5],
                    "created_at": str(result[6])
                }
            }
        else:
            return {
                "status": "not_found",
                "message": f"등장인물 '{full_name}'을(를) 찾을 수 없습니다."
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"조회 중 오류 발생: {str(e)}"
        }

def list_all_characters() -> dict:
    """
    저장된 모든 등장인물 목록을 조회합니다.
    
    Returns:
        등장인물 목록
    """
    try:
        conn = _get_connection()
        results = conn.execute(
            "SELECT full_name, occupation, novel_title FROM characters ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        
        characters = [
            {"full_name": r[0], "occupation": r[1], "novel_title": r[2]}
            for r in results
        ]
        
        return {
            "status": "success",
            "count": len(characters),
            "characters": characters
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"조회 중 오류 발생: {str(e)}"
        }


def save_validated_characters(validation_results: list[dict]) -> dict:
    """
    검증 결과에서 PASS인 캐릭터만 데이터베이스에 저장합니다.
    검증이 완료된 후 이 함수를 호출하세요.
    
    Args:
        validation_results: 검증 결과 리스트. 각 항목은 다음 구조를 가짐:
            - full_name: 인물 이름
            - overall_verdict: "PASS" 또는 "FAIL"
            - verified_data: 검증된 데이터 (full_name, events, characteristics, occupation, relationships)
    
    Returns:
        저장 결과 요약
    """
    saved = []
    failed = []
    
    for result in validation_results:
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
    
    return {
        "status": "success",
        "saved_count": len(saved),
        "failed_count": len(failed),
        "saved_characters": saved,
        "failed_characters": failed
    }

