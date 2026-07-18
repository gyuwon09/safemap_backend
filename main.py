from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
import httpx

# 1. 전역 클라이언트를 미리 선언만 해둡니다.
async_client = None

# 2. 서버의 시작과 종료를 관리하는 lifespan 함수 정의
@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client
    # [Startup] 서버가 시작될 때 클라이언트 생성
    async_client = httpx.AsyncClient(timeout=10.0)
    print("HTTP 비동기 클라이언트가 준비되었습니다.")

    yield  # ◀ 이 시점에 FastAPI 앱이 열심히 돌아갑니다.

    # [Shutdown] 서버가 종료될 때 클라이언트 안전하게 닫기
    await async_client.close()
    print("HTTP 비동기 클라이언트가 안전하게 종료되었습니다.")


# 3. FastAPI 인스턴스 생성 시 lifespan 등록
app = FastAPI(title="행정안전부 WMS 프록시 API", lifespan=lifespan)

# 행안부 WMS 서비스 URL 및 인증키 설정

SERVICE_KEY = "BXXSTZPH-BXXS-BXXS-BXXS-BXXSTZPHMK"

@app.get("/map/wms/{type}")
async def get_wms_image(
        type:str,
        bbox: str = Query(..., description="경계 영역 좌표 (예: 127.0,37.5,127.1,37.6)"),
        srs: str = Query("EPSG:4326", description="좌표계 (기본값: EPSG:4326)"),
        width: str = Query("512", description="이미지 가로 크기"),
        height: str = Query("512", description="이미지 세로 크기"),
):
    """
    여러 사용자가 동시에 요청해도 비동기(async)로 행안부 서버에 요청을 보내고,
    받은 이미지를 클라이언트에게 그대로 반환하는 API입니다.
    """


    # 명세서에 맞춘 파라미터 구성
    params = {
        "serviceKey": SERVICE_KEY,
        "srs": srs,
        "bbox": bbox,
        "format": "image/png",
        "width": width,
        "height": height,
        "transparent": "TRUE",
    }

    type_list = {
        "gambling":72, #도박
        "sexual_crime":85, #성범죄
        "theft":84, #절도
        "fire":66, #방화
        "attraction":48, #약취/유인
        "drug":74, #마약
        "murder":73, #살인
        "robbery":86, #강도
        "violence":83 #폭력
    }

    WMS_URL = f"https://www.safemap.go.kr/openapi2/IF_00{type_list[type]}_WMS"

    try:
        # httpx를 사용한 비동기 비블로킹(Non-blocking) 호출
        # 이 구간에서 다른 사용자의 요청을 멈추지 않고 대기 없이 처리합니다.
        response = await async_client.get(WMS_URL, params=params)

        # 행안부 서버의 응답 코드가 200이 아닌 경우
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="원격 GIS 서버가 응답하지 않거나 오류가 발생했습니다.")

        content_type = response.headers.get("Content-Type", "")

        # 반환된 데이터가 올바른 이미지 포맷인지 확인
        if "image" in content_type:
            # 획득한 바이너리 이미지 데이터를 그대로 클라이언트에게 반환 (FastAPI Response 이용)
            return Response(content=response.content, media_type=content_type)
        else:
            # 에러 메시지가 텍스트나 XML로 온 경우
            return Response(content=response.text, media_type=content_type, status_code=400)

    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"원격 서버 연결 실패: {exc}")


if __name__ == "__main__":
    import uvicorn

    # 동시성 처리를 극대화하기 위해 다중 워커(workers)를 지정하여 실행할 수 있습니다.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)