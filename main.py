import io
import math
from contextlib import asynccontextmanager
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import BaseModel, EmailStr
import httpx
import pandas as pd
from PIL import Image
import os
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------------
# [데이터 구조] 실시간 다중 사용자 위치 데이터 저장소
# -------------------------------------------------------------------------
user_locations: Dict[str, Dict] = {}

# 1. 이메일 서버 및 API 설정
GOOGLE_MAPS_API_KEY = os.getenv("api_key")

conf = ConnectionConfig(
    MAIL_USERNAME="krsoup09@gmail.com",
    MAIL_PASSWORD=os.getenv("app_pw"),
    MAIL_FROM="krsoup09@gmail.com",
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)


# 2. 클라이언트 입력 데이터 스키마 정의
class NotificationRequest(BaseModel):
    user_id: str  # 자녀를 식별하기 위한 고유 ID 필수 추가
    to_email: EmailStr
    risk_type: str
    detected_at: str
    latitude: float
    longitude: float


class LocationUpdate(BaseModel):
    user_id: str
    lat: float
    lon: float


# -------------------------------------------------------------------------
# [설정] CSV 파일 경로 및 전역 변수 설정
# -------------------------------------------------------------------------
CSV_FILE_PATH = "cctv_data.csv"
async_client = None
cctv_df = None


# 하버사인(Haversine) 거리 계산 함수
def calculate_distance(lat1, lon1, lat2, lon2):
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return float('inf')
    R = 6371000
    rad_lat1 = math.radians(lat1)
    rad_lat2 = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client, cctv_df
    async_client = httpx.AsyncClient(timeout=10.0)
    print("HTTP 비동기 클라이언트가 준비되었습니다.")

    try:
        cctv_df = pd.read_csv(CSV_FILE_PATH, encoding="cp949")
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

    yield
    await async_client.close()
    print("HTTP 비동기 클라이언트가 안전하게 종료되었습니다.")


app = FastAPI(title="공공데이터 기반 위험도 분석 API", lifespan=lifespan)

SERVICE_KEY = "BXXSTZPH-BXXS-BXXS-BXXS-BXXSTZPHMK"
TYPE_LIST = {
    "gambling": 72, "sexual_crime": 85, "theft": 84, "fire": 66,
    "attraction": 48, "drug": 74, "murder": 73, "robbery": 86, "violence": 83
}


# -------------------------------------------------------------------------
# [추가] 실시간 위치 관리 및 관제 대시보드 엔드포인트
# -------------------------------------------------------------------------
@app.post("/user/location")
async def update_user_location(data: LocationUpdate):
    user_locations[data.user_id] = {
        "lat": data.lat,
        "lon": data.lon,
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return {"status": "success", "message": f"User {data.user_id} location updated."}


@app.get("/user/location/{user_id}")
async def get_user_location_raw(user_id: str):
    if user_id not in user_locations:
        raise HTTPException(status_code=404, detail="위치 데이터가 없습니다.")
    return user_locations[user_id]


@app.get("/tracking/{user_id}", response_class=HTMLResponse)
async def tracking_view(user_id: str):
    gmaps_base_url = "https://maps.google.com/?q="

    template_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>실시간 위치 추적 - __USER_ID__</title>
        <style>
            body { font-family: sans-serif; background: #edf2f7; padding: 40px; text-align: center; }
            .container { max-width: 500px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
            .status { font-size: 24px; color: #2d3748; font-weight: bold; margin-bottom: 20px; }
            .info-box { background: #f7fafc; padding: 15px; border-radius: 6px; margin-bottom: 20px; text-align: left; font-size: 15px; }
            .btn { display: inline-block; padding: 12px 24px; background: #4299e1; color: white; text-decoration: none; border-radius: 4px; font-weight: bold; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="status">📋 실시간 위치 모니터링 [__USER_ID__]</div>
            <div class="info-box">
                <div><strong>위도 (Lat):</strong> <span id="lat-val">로딩 중...</span></div>
                <div style="margin-top: 8px;"><strong>경도 (Lon):</strong> <span id="lon-val">로딩 중...</span></div>
                <div style="margin-top: 8px;"><strong>최종 수신 시각:</strong> <span id="time-val">-</span></div>
            </div>
            <a id="gmaps-btn" href="#" target="_blank" class="btn">구글 지도에서 보기</a>
        </div>
        <script>
            const userId = "__USER_ID__";
            const gmapsBase = "__GMAPS_BASE__";
            async function fetchLocation() {
                try {
                    const response = await fetch(`/user/location/${userId}`);
                    if (response.ok) {
                        const data = await response.json();
                        document.getElementById("lat-val").innerText = data.lat;
                        document.getElementById("lon-val").innerText = data.lon;
                        document.getElementById("time-val").innerText = data.updated_at;
                        document.getElementById("gmaps-btn").href = gmapsBase + data.lat + "," + data.lon;
                    }
                } catch (error) { console.error(error); }
            }
            fetchLocation();
            setInterval(fetchLocation, 5000);
        </script>
    </body>
    </html>
    """
    rendered_html = template_html.replace("__USER_ID__", user_id).replace("__GMAPS_BASE__", gmaps_base_url)
    return HTMLResponse(content=rendered_html, status_code=200)


# -------------------------------------------------------------------------
# [엔드포인트 4] 알림 발송 및 이메일 템플릿 처리
# -------------------------------------------------------------------------
@app.post("/send-notification")
async def send_notification(payload: NotificationRequest):
    # 동적 추적 주소 생성
    tracking_url = f"http://localhost:8000/tracking/{payload.user_id}"

    # 🔥 [중요] HTML 내부 CSS의 중괄호가 훼손되지 않도록 .replace() 치환 기법 도입으로 완벽 방어
    HTML_TEMPLATE = """
    <!doctype html>
    <html lang="ko">
      <head><meta charset="utf-8" /></head>
      <body style="margin:0; padding:0; background:#f5f6f8; font-family:Arial, sans-serif; color:#222222;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f6f8;">
          <tr>
            <td align="center" style="padding:32px 16px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px; background:#ffffff; border:1px solid #e5e7eb;">
                <tr>
                  <td style="padding:24px 32px; border-bottom:1px solid #e5e7eb;">
                    <p style="margin:0; color:#3567b7; font-size:15px; font-weight:700;">Safe Walk 알림</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:34px 32px 28px;">
                    <h1 style="margin:0 0 16px; color:#1f2937; font-size:25px; font-weight:700;">⚠️ 자녀가 위험 지역에 진입했습니다</h1>
                    <p style="margin:0 0 24px; color:#4b5563; font-size:15px;">안전 여부를 확인해 주세요.</p>
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px; border-collapse:collapse; font-size:14px;">
                      <tr>
                        <td style="width:112px; padding:11px 12px; background:#fafafa; border-top:1px solid #e5e7eb;">감지된 위험</td>
                        <td style="padding:11px 12px; font-weight:700; border-top:1px solid #e5e7eb;">__RISK_TYPE__</td>
                      </tr>
                      <tr>
                        <td style="padding:11px 12px; background:#fafafa; border-top:1px solid #e5e7eb;">감지 시각</td>
                        <td style="padding:11px 12px; border-top:1px solid #e5e7eb;">__DETECTED_AT__</td>
                      </tr>
                    </table>
                    <a href="__TRACKING_URL__" target="_blank" style="display:block; text-decoration:none;">
                      <img src="https://maps.googleapis.com/maps/api/staticmap?center=__LAT__,__LON__&zoom=16&size=600x320&scale=2&maptype=roadmap&markers=color:red%7Clabel:C%7C__LAT__,__LON__&key=__GMAPS_KEY__" alt="자녀 위치 지도" width="554" style="display:block; width:100%; border:0;" />
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    formatted_html = HTML_TEMPLATE.replace("__RISK_TYPE__", payload.risk_type) \
        .replace("__DETECTED_AT__", payload.detected_at) \
        .replace("__TRACKING_URL__", tracking_url) \
        .replace("__LAT__", str(payload.latitude)) \
        .replace("__LON__", str(payload.longitude)) \
        .replace("__GMAPS_KEY__", GOOGLE_MAPS_API_KEY or "")

    message = MessageSchema(
        subject="[Safe Walk] 자녀 위험 지역 진입 알림",
        recipients=[payload.to_email],
        body=formatted_html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        return {"status": "success", "message": "Notification email sent successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------------
# [엔드포인트 1 & 2 & 3] 기존 조회 및 다중 분석 로직 (CCTV 컬럼 안정성 보강)
# -------------------------------------------------------------------------
@app.get("/map/wms/{type}")
async def get_wms_image(type: str, bbox: str = Query(...), srs: str = Query("EPSG:4326"), width: str = Query("512"),
                        height: str = Query("512")):
    if type not in TYPE_LIST: raise HTTPException(status_code=400, detail="올바르지 않은 위험 종류입니다.")
    params = {"serviceKey": SERVICE_KEY, "srs": srs, "bbox": bbox, "format": "image/png", "width": width,
              "height": height, "transparent": "TRUE"}
    try:
        response = await async_client.get(f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[type]}_WMS",
                                          params=params)
        return Response(content=response.content, media_type=response.headers.get("Content-Type", ""))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/map/risk-analysis/{type}")
async def analyze_safety_risk(type: str, lon: float = Query(...), lat: float = Query(...),
                              radius: float = Query(100.0)):
    if type not in TYPE_LIST: raise HTTPException(status_code=400, detail="올바르지 않은 위험 종류입니다.")

    delta = 0.0001
    bbox_str = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
    wms_params = {"serviceKey": SERVICE_KEY, "srs": "EPSG:4326", "bbox": bbox_str, "format": "image/png", "width": "3",
                  "height": "3", "transparent": "TRUE"}

    wms_risk_score = 0
    try:
        res = await async_client.get(f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[type]}_WMS",
                                     params=wms_params)
        if res.status_code == 200 and "image" in res.headers.get("Content-Type", ""):
            img = Image.open(io.BytesIO(res.content)).convert("RGBA")
            _, g, _, a = img.getpixel((1, 1))
            if a > 0: wms_risk_score = round(30 + ((255 - g) / 255) * 70)
    except Exception as e:
        print(e)

    nearby_cctv_count = 0
    total_camera_units = 0
    cctv_mitigation_score = 0

    if cctv_df is not None:
        # 데이터프레임 컬럼 공백 유연성 가드 코드 추가
        lat_col = "WGS84위도" if "WGS84위도" in cctv_df.columns else ("WGS84 위도" if "WGS84 위도" in cctv_df.columns else None)
        lon_col = "WGS84경도" if "WGS84경도" in cctv_df.columns else ("WGS84 경도" if "WGS84 경도" in cctv_df.columns else None)

        if lat_col and lon_col:
            df_filtered = cctv_df[(cctv_df[lat_col].between(lat - 0.01, lat + 0.01)) & (
                cctv_df[lon_col].between(lon - 0.01, lon + 0.01))].copy()
            if not df_filtered.empty:
                df_filtered["distance"] = df_filtered.apply(
                    lambda r: calculate_distance(lat, lon, r[lat_col], r[lon_col]), axis=1)
                df_result = df_filtered[df_filtered["distance"] <= radius]
                nearby_cctv_count = len(df_result)
                if nearby_cctv_count > 0:
                    total_camera_units = int(df_result["카메라대수"].fillna(1).sum())
                    cctv_mitigation_score = min(total_camera_units * 3, 15)

    final_risk_score = max(wms_risk_score - cctv_mitigation_score, 0)
    status = "안전" if final_risk_score == 0 else (
        "보통" if final_risk_score < 40 else ("주의" if final_risk_score < 75 else "위험"))

    return {"final_composite_risk": {"score": final_risk_score, "level": status}}


@app.get("/map/multi-risk-analysis")
async def analyze_multiple_safety_risks(types: List[str] = Query(...), lon: float = Query(...), lat: float = Query(...),
                                        radius: float = Query(100.0)):
    invalid_types = [t for t in types if t not in TYPE_LIST]
    if invalid_types: raise HTTPException(status_code=400, detail=f"Invalid types: {invalid_types}")

    delta = 0.0001
    bbox_str = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
    detected_warnings = []

    for r_type in types:
        wms_params = {"serviceKey": SERVICE_KEY, "srs": "EPSG:4326", "bbox": bbox_str, "format": "image/png",
                      "width": "3", "height": "3", "transparent": "TRUE"}
        try:
            response = await async_client.get(f"https://www.safemap.go.kr/openapi2/IF_00{TYPE_LIST[r_type]}_WMS",
                                              params=wms_params)
            if response.status_code == 200 and "image" in response.headers.get("Content-Type", ""):
                image = Image.open(io.BytesIO(response.content)).convert("RGBA")
                _, g, _, a = image.getpixel((1, 1))
                if a > 0:
                    score = round(30 + ((255 - g) / 255) * 70)
                    status = "주의" if score < 60 else "위험"
                    detected_warnings.append({"risk_type": r_type, "level": status, "score": score})
        except Exception as exc:
            print(exc)

    return {"detected_risk_elements": detected_warnings, "has_risk_element": len(detected_warnings) > 0}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)