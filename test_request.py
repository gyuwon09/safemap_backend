import httpx

# FastAPI 서버가 실행 중인 주소
BASE_URL = "http://127.0.0.1:8000"


def get_single_risk():
    """[엔드포인트 2] 단일 구역 안전도 분석 요청"""
    print("\n--- [엔드포인트 2] 단일 위험도 분석 결과 호출 ---")

    url = f"{BASE_URL}/map/risk-analysis/theft"
    params = {
        "lon": 127.10545342254238,  # 서울시청 중심 경도
        "lat": 37.256197702645444,  # 서울시청 중심 위도
        "radius": 100.0  # 검색 반경 (미터)
    }

    # 동기 방식으로 요청 후 JSON 파싱
    with httpx.Client() as client:
        response = client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            # 보기 편하게 정렬하여 출력
            import json
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"에러 발생 ({response.status_code}): {response.text}")


def get_multi_risk():
    """[엔드포인트 3] 다중 위험 요소 분석 요청"""
    print("\n--- [엔드포인트 3] 다중 위험도 분석 결과 호출 ---")

    url = f"{BASE_URL}/map/multi-risk-analysis"
    # 동일한 key(types)로 여러 값을 넘길 때는 튜플 리스트 형태를 사용합니다.
    params = [
        ("types", "theft"),
        ("types", "violence"),
        ("lon", 126.9779),
        ("lat", 37.5665),
        ("radius", 150.0)
    ]

    with httpx.Client() as client:
        response = client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            import json
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"에러 발생 ({response.status_code}): {response.text}")


if __name__ == "__main__":
    # 필요한 함수만 주석을 해제하며 테스트해 보세요.
    get_single_risk()
    get_multi_risk()