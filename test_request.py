import asyncio
import httpx

BASE_URL = "http://localhost:8000"


async def test_send_api():
    user_id = "child_A"
    guardian_email = "krsoup09@gmail.com"  # ◀ 실제 수신할 보호자 메일 주소 입력

    async with httpx.AsyncClient() as client:
        # 테스트 전제조건: 서버에 해당 유저의 위치 데이터가 한 번은 업로드되어 있어야 합니다.
        print("1️⃣ 테스트용 자녀 위치 데이터를 먼저 업로드합니다...")
        upload_payload = {
            "user_id": user_id,
            "lat": 37.249283,
            "lon": 127.073483
        }
        await client.post(f"{BASE_URL}/user/location", json=upload_payload)

        # 이메일 발송 API 호출 (이메일 주소만 파라미터로 전송)
        print("\n2️⃣ 서버에 이메일 발송 엔드포인트를 요청합니다...")
        params = {
            "user_id": user_id,
            "email": guardian_email
        }

        response = await client.post(f"{BASE_URL}/user/send-alert-email", params=params)

        if response.status_code == 200:
            print("\n==================================================")
            print("🎉 서버 응답 성공!")
            print(response.json()["message"])
            print("==================================================")
            print("💡 잠시 후 입력하신 수신 메일함을 확인해 보세요.")
        else:
            print(f"❌ 요청 실패: {response.status_code}, {response.text}")


if __name__ == "__main__":
    asyncio.run(test_send_api())