import asyncio
import httpx

# FastAPI 서버 주소
BASE_URL = "http://127.0.0.1:8000"


async def main():
    # 1. 서버로 전송할 테스트 데이터 객체
    payload = {
        "to_email": "krsoup09@gmail.com",  # 👈 수신할 메일 주소를 적어주세요.
        "risk_type": "theft (절도 발생 구역)",
        "detected_at": "2026-07-19 11:55:00",
        "latitude": 37.5665,
        "longitude": 126.9779,
        "tracking_url": "https://maps.google.com"
    }

    print("[테스트] 이메일 알림 발송 요청을 시작합니다...")

    # 2. 비동기 HTTP 클라이언트로 POST 요청 전송
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(f"{BASE_URL}/send-notification", json=payload)

            # 3. 결과 출력
            print(f"▶ 서버 응답 상태 코드: {response.status_code}")
            print(f"▶ 서버 응답 데이터: {response.json()}")

            if response.status_code == 200:
                print("🎉 이메일 발송 요청 성공!")
            else:
                print("❌ 발송 실패 (서버 에러)")

        except httpx.ConnectError:
            print("❌ 서버 연결 실패! FastAPI 서버가 켜져 있는지 확인하세요 (port: 8000)")
        except Exception as e:
            print(f"❌ 오류 발생: {e}")


# 스크립트 실행 진입점
if __name__ == "__main__":
    asyncio.run(main())