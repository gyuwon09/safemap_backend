import io
import math
from contextlib import asynccontextmanager
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel
import httpx
import pandas as pd
from PIL import Image

# -------------------------------------------------------------------------
# [데이터 구조] 실시간 다중 사용자 위치 데이터 저장소
# -------------------------------------------------------------------------
# 실무 환경에서는 Redis나 DB를 쓰지만, 다중 접속 처리가 가능하도록
# 스레드 세이프하게 접근 가능한 인메모리 딕셔너리를 구성합니다.
user_locations: Dict[str, Dict] = {}



class LocationUpdate(BaseModel):
    user_id: str
    lat: float
    lon: float

# (기존 lifespan 및 이전 턴 변수들은 유지된다고 가정합니다)

# -------------------------------------------------------------------------
# [설정] CSV 파일 경로 및 전역 변수 설정
# -------------------------------------------------------------------------
CSV_FILE_PATH = "cctv_data.csv"  # 보유하신 csv 파일명을 입력하세요
async_client = None
cctv_df = None  # CSV 데이터를 담을 전역 변수


# 하버사인(Haversine) 공식을 이용한 두 위경도 간의 거리 계산 함수 (단위: 미터)
def calculate_distance(lat1, lon1, lat2, lon2):
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return float('inf')
    R = 6371000  # 지구 반지름 (미터)
    rad_lat1 = math.radians(lat1)
    rad_lat2 = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# -------------------------------------------------------------------------
# Lifespan: 서버 시작 시 HTTP 클라이언트 생성 및 CSV 데이터 미리 로드
# -------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client, cctv_df

    # 1. HTTP 비동기 클라이언트 준비
    async_client = httpx.AsyncClient(timeout=10.0)
    print("HTTP 비동기 클라이언트가 준비되었습니다.")

    # 2. CCTV CSV 데이터셋 로드 (인코딩 수정)
    try:
        # 한국 공공데이터 필수 인코딩인 cp949로 변경 시도
        cctv_df = pd.read_csv(CSV_FILE_PATH, encoding="cp949")
        # 컬럼명 공백 제거
        cctv_df.columns = cctv_df.columns.str.strip()
        print(f"🎉 CCTV 데이터 로드 성공 (총 {len(cctv_df)}건)")
    except Exception as e:
        print(f"❌ cp949 로드 실패, utf-8-sig로 재시도합니다. 사유: {e}")
        try:
            cctv_df = pd.read_csv(CSV_FILE_PATH, encoding="utf-8-sig")
            cctv_df.columns = cctv_df.columns.str.strip()
            print(f"🎉 CCTV 데이터 로드 성공 (총 {len(cctv_df)}건)")
        except Exception as e2:
            print(f"❌ 모든 인코딩 로드 실패: {e2}")
            cctv_df = None

    yield  # ◀ 앱 구동 구간

    # 3. 종료 시 자원 해제
    await async_client.close()
    print("HTTP 비동기 클라이언트가 안전하게 종료되었습니다.")


app = FastAPI(title="공공데이터 기반 위험도 분석 API", lifespan=lifespan)

SERVICE_KEY = "BXXSTZPH-BXXS-BXXS-BXXS-BXXSTZPHMK"
TYPE_LIST = {
    "gambling": 72, "sexual_crime": 85, "theft": 84, "fire": 66,
    "attraction": 48, "drug": 74, "murder": 73, "robbery": 86, "violence": 83
}


# -------------------------------------------------------------------------
# [엔드포인트 1] 기본 WMS 이미지 프록시 반환
# -------------------------------------------------------------------------
@app.get("/map/wms/{type}")
async def get_wms_image(
        type: str,
        bbox: str = Query(..., description="경계 영역 좌표 (예: 127.0,37.5,127.1,37.6)"),
        srs: str = Query("EPSG:4326", description="좌표계"),
        width: str = Query("512"),
        height: str = Query("512"),
):
    if type not in TYPE_LIST:
        raise HTTPException(status_code=400, detail="올바르지 않은 위험 종류입니다.")

    params = {
        "serviceKey": SERVICE_KEY, "srs": srs, "bbox": bbox,
        "format": "image/png", "width": width, "height": height, "transparent": "TRUE",
    }
    WMS_URL = f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[type]}_WMS"

    try:
        response = await async_client.get(WMS_URL, params=params)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="원격 GIS 서버 오류")

        content_type = response.headers.get("Content-Type", "")
        if "image" in content_type:
            return Response(content=response.content, media_type=content_type)
        return Response(content=response.text, media_type=content_type, status_code=400)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"서버 연결 실패: {exc}")


# -------------------------------------------------------------------------
# [엔드포인트 2] 위경도 + CSV 데이터 연동 종합 위험도 분석
# -------------------------------------------------------------------------
@app.get("/map/risk-analysis/{type}")
async def analyze_safety_risk(
        type: str,
        lon: float = Query(..., description="경도 (WGS84 경도, 예: 126.9779)"),
        lat: float = Query(..., description="위도 (WGS84 위도, 예: 37.5665)"),
        radius: float = Query(100.0, description="CCTV 검색 반경 (미터 단위, 기본값 100m)")
):
    if type not in TYPE_LIST:
        raise HTTPException(status_code=400, detail="올바르지 않은 위험 종류입니다.")

    # 1. WMS 타일 색상 분석 (기본 위험도 산출)
    delta = 0.0001
    bbox_str = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"

    wms_params = {
        "serviceKey": SERVICE_KEY, "srs": "EPSG:4326", "bbox": bbox_str,
        "format": "image/png", "width": "3", "height": "3", "transparent": "TRUE",
    }
    WMS_URL = f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[type]}_WMS"

    wms_risk_score = 0
    pixel_rgba = {"r": 0, "g": 0, "b": 0, "a": 0}

    try:
        response = await async_client.get(WMS_URL, params=wms_params)
        if response.status_code == 200 and "image" in response.headers.get("Content-Type", ""):
            image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            r, g, b, a = image.getpixel((1, 1))
            pixel_rgba = {"r": r, "g": g, "b": b, "a": a}

            if a > 0:  # 투명이 아니면 점수 부여 (노랑~빨강 분석)
                base_score = 30
                additional_score = ((255 - g) / 255) * 70
                wms_risk_score = round(base_score + additional_score)
    except Exception as exc:
        # WMS 통신 실패 시 로그를 남기고 WMS 점수는 0점으로 처리 (CCTV 단독 계산 방어코드)
        print(f"WMS 통신 또는 분석 실패: {exc}")

    # 2. CSV 기반 주변 CCTV 분석 (방범 환경 분석)
    nearby_cctv_count = 0
    total_camera_units = 0
    avg_pixels = 0
    cctv_mitigation_score = 0  # CCTV로 인해 경감되는 위험도 점수
    cctv_details = []

    if cctv_df is not None:
        # 거리 계산 및 필터링
        # 데이터가 클 경우 사전에 경위도 오차범위 컷을 하면 더 빨라집니다.
        df_filtered = cctv_df[
            (cctv_df["WGS84위도"].between(lat - 0.01, lat + 0.01)) &
            (cctv_df["WGS84경도"].between(lon - 0.01, lon + 0.01))
            ].copy()

        if not df_filtered.empty:
            df_filtered["distance"] = df_filtered.apply(
                lambda row: calculate_distance(lat, lon, row["WGS84위도"], row["WGS84경도"]), axis=1
            )
            # 반경 이내 CCTV만 추출
            df_result = df_filtered[df_filtered["distance"] <= radius]

            nearby_cctv_count = len(df_result)

            if nearby_cctv_count > 0:
                # '카메라대수' 수치 합산 (결측치는 1대로 가정)
                total_camera_units = int(df_result["카메라대수"].fillna(1).sum())
                # '카메라화소수' 평균 계산 (결측치는 200만 화소 표준 가정)
                avg_pixels = float(df_result["카메라화소수"].fillna(2000000).mean())

                # 방범 지수(경감 점수) 알고리즘 설계
                # 예시: 카메라 1대당 3점 경감 (최대 15점), 평균 화소수가 200만 이상이면 추가 5점 경감
                unit_mitigation = min(total_camera_units * 3, 15)
                pixel_mitigation = 5 if avg_pixels >= 2000000 else 0
                cctv_mitigation_score = unit_mitigation + pixel_mitigation

                # 상위 3개 장소 샘플 데이터 반환용 저장
                for _, row in df_result.head(3).iterrows():
                    cctv_details.append({
                        "address": row.get("소재지도로명주소") or row.get("소재지지번주소") or "주소 불명",
                        "purpose": str(row.get("설치목적구분")),
                        "cameras": int(row.get("카메라대수") or 1),
                        "distance_m": round(row["distance"], 1)
                    })

    # 3. 최종 종합 위험도 결합 계산
    # WMS 위험도 점수에서 CCTV 방범 요소를 차감하되 최소 0점 보장
    final_risk_score = max(wms_risk_score - cctv_mitigation_score, 0)

    # 종합 등급 분류
    if final_risk_score == 0:
        status = "안전"
    elif final_risk_score < 40:
        status = "보통"
    elif final_risk_score < 75:
        status = "주의"
    else:
        status = "위험"

    return {
        "analysis_info": {
            "requested_type": type,
            "target_coordinates": {"lon": lon, "lat": lat},
            "search_radius_m": radius
        },
        "wms_environmental_risk": {
            "wms_score": wms_risk_score,
            "pixel_rgba": pixel_rgba
        },
        "cctv_security_factor": {
            "nearby_cctv_places": nearby_cctv_count,
            "total_camera_units": total_camera_units,
            "average_camera_pixels": round(avg_pixels, 0),
            "mitigation_score": cctv_mitigation_score,
            "sample_details": cctv_details
        },
        "final_composite_risk": {
            "score": final_risk_score,
            "level": status
        }
    }


# -------------------------------------------------------------------------
# [엔드포인트 3] 여러 위험 요소 중 위험/주의 항목만 추출하여 반환
# -------------------------------------------------------------------------
@app.get("/map/multi-risk-analysis")
async def analyze_multiple_safety_risks(
        types: List[str] = Query(..., description="분석할 위험 종류 목록 (예: types=theft&types=violence)"),
        lon: float = Query(..., description="경도 (WGS84 경도)"),
        lat: float = Query(..., description="위도 (WGS84 위도)"),
        radius: float = Query(100.0, description="CCTV 검색 반경 (미터 단위)")
):
    # 입력된 위험 타입 검증
    invalid_types = [t for t in types if t not in TYPE_LIST]
    if invalid_types:
        raise HTTPException(
            status_code=400,
            detail=f"올바르지 않은 위험 종류가 포함되어 있습니다: {invalid_types}"
        )

    delta = 0.0001
    bbox_str = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"

    detected_warnings = []  # 위험 및 주의 요소가 발견된 항목들을 담을 리스트
    all_results = {}  # 전체 검사 결과 기록용

    # 1. 입력받은 모든 타입에 대해 개별 분석 진행
    for r_type in types:
        wms_params = {
            "serviceKey": SERVICE_KEY, "srs": "EPSG:4326", "bbox": bbox_str,
            "format": "image/png", "width": "3", "height": "3", "transparent": "TRUE",
        }
        WMS_URL = f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[r_type]}_WMS"

        score = 0
        status = "안전"

        try:
            response = await async_client.get(WMS_URL, params=wms_params)
            if response.status_code == 200 and "image" in response.headers.get("Content-Type", ""):
                image = Image.open(io.BytesIO(response.content)).convert("RGBA")
                _, g, _, a = image.getpixel((1, 1))

                if a > 0:  # 색상이 투명이 아닌 경우 (위험 요소 존재)
                    score = round(30 + ((255 - g) / 255) * 70)

                    # 등급 분류
                    if score < 60:
                        status = "주의"
                    else:
                        status = "위험"
        except Exception as exc:
            print(f"[{r_type}] WMS 분석 실패: {exc}")
            status = "분석 실패"

        all_results[r_type] = {"score": score, "level": status}

        # 🔥 위험 또는 주의 요소가 있는 입력값만 필터링하여 수집
        if status in ["주의", "위험"]:
            detected_warnings.append({
                "risk_type": r_type,
                "level": status,
                "score": score
            })

    # 2. CSV 기반 주변 CCTV 분석 (인프라 현황 파악용)
    nearby_cctv_count = 0
    total_camera_units = 0
    cctv_details = []

    if cctv_df is not None:
        try:
            lat_col = "WGS84 위도" if "WGS84 위도" in cctv_df.columns else ("위도" if "위도" in cctv_df.columns else None)
            lon_col = "WGS84 경도" if "WGS84 경도" in cctv_df.columns else ("경도" if "경도" in cctv_df.columns else None)

            if lat_col and lon_col:
                df_filtered = cctv_df[
                    (cctv_df[lat_col].between(lat - 0.01, lat + 0.01)) &
                    (cctv_df[lon_col].between(lon - 0.01, lon + 0.01))
                    ].copy()

                if not df_filtered.empty:
                    df_filtered["distance"] = df_filtered.apply(
                        lambda row: calculate_distance(lat, lon, row[lat_col], row[lon_col]), axis=1
                    )
                    df_result = df_filtered[df_filtered["distance"] <= radius]
                    nearby_cctv_count = len(df_result)

                    if nearby_cctv_count > 0:
                        cam_count_col = "카메라대수" if "카메라대수" in df_result.columns else \
                        [c for c in df_result.columns if "대수" in c or "카메라" in c][0]
                        total_camera_units = int(df_result[cam_count_col].fillna(1).sum())

                        for _, row in df_result.head(3).iterrows():
                            addr = row.get("소재지도로명주소") or row.get("소재지지번주소") or "주소 불명"
                            cctv_details.append({
                                "address": str(addr),
                                "cameras": int(row.get(cam_count_col, 1)),
                                "distance_m": round(row["distance"], 1)
                            })
        except Exception as e:
            print(f"❌ CCTV 분석 중 오류 발생: {e}")

    # 3. 최종 결과 반환 구조
    return {
        "analysis_info": {
            "target_coordinates": {"lon": lon, "lat": lat},
            "search_radius_m": radius
        },
        # 핵심 피드백: 위험 및 주의가 감지된 항목 리스트
        "detected_risk_elements": detected_warnings,
        "has_risk_element": len(detected_warnings) > 0,

        # 참고용 주변 방범 인프라 상태
        "security_infrastructure": {
            "nearby_cctv_places": nearby_cctv_count,
            "total_camera_units": total_camera_units,
            "sample_details": cctv_details
        },
        # 검사한 모든 요소의 상세 데이터
        "full_inspection_details": all_results
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)