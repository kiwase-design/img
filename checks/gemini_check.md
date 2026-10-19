# Gemini API 점검 결과

- 실행 시각: 2026-10-19 23:32 KST
- 키 확인: ✅ 정상 (사용 가능 모델 63개)
- 이미지 모델: gemini-2.5-flash-image, gemini-3-pro-image-preview, gemini-3-pro-image, gemini-3.1-flash-image-preview, gemini-3.1-flash-image, gemini-3.1-flash-lite-image
- 텍스트 생성 (gemini-2.5-flash): ❌ HTTP 404 — This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash for the latest features and improvements. We recommend you to use the Interactions API (https://ai.google.dev/gemini-api/docs/get-started).
- 이미지 생성 (gemini-3-pro-image): ❌ HTTP 402 / status=RESOURCE_EXHAUSTED
  - 메시지: Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay. 
- 이미지 생성 (gemini-3.1-flash-image): ❌ HTTP 402 / status=RESOURCE_EXHAUSTED
  - 메시지: Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay. 
