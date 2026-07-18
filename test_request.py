import io
import matplotlib.pyplot as plt
import requests
from PIL import Image

# 1. 실행 중인 FastAPI 서버의 WMS 엔드포인트 주소
TEST_URL = "http://127.0.0.1:8000/map/wms/sexual_crime"

# 2. 테스트용 파라미터 설정 (서울 시청 중심 부근 영역)
# srs가 EPSG:4326이므로 경도,위도 순서로 범위를 지정합니다.
params = {
    "bbox": "126.970,37.560,126.985,37.570",
    "srs": "EPSG:4326",
    "width": "512",
    "height": "512",
}

print("FastAPI 서버에 WMS 이미지 요청을 보냅니다...")

try:
    # FastAPI 서버로 요청 송신
    response = requests.get(TEST_URL, params=params)

    print(f"응답 상태 코드: {response.status_code}")
    print(f"응답 Content-Type: {response.headers.get('Content-Type')}")

    if response.status_code == 200:
        content_type = response.headers.get("Content-Type", "")

        if "image" in content_type:
            # 바이너리 데이터를 이미지로 변환하여 화면에 표시
            image = Image.open(io.BytesIO(response.content))

            plt.figure(figsize=(6, 6))
            plt.imshow(image)
            plt.title("FastAPI WMS Test Result")
            plt.axis("off")
            plt.show()

            # 필요한 경우 파일로 저장
            # image.save("fastapi_wms_result.png")
            print("테스트 성공: 이미지를 정상적으로 띄웠습니다.")
        else:
            print("성공 코드는 받았으나 이미지가 아닙니다. 응답 본문:")
            print(response.text)

    elif response.status_code == 400:
        print("서버가 400 에러를 반환했습니다. 행안부 API가 보낸 메시지:")
        print(response.text)
    else:
        print(f"서버 에러 발생 (코드: {response.status_code}):")
        print(response.text)

except Exception as e:
    print(f"테스트 중 오류가 발생했습니다: {e}")