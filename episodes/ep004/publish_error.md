# 게시 실패

- 시각: 2026-10-24 02:17 KST
- 오류: me: HTTP 400 — API access blocked. (code 200, type OAuthException)

**원인: 인스타그램(Meta)이 이 토큰의 API 접근을 막았어요.** 코드 문제가 아니라 토큰을 새로 발급해야 해요.
1. 인스타그램 앱에서 보안 알림('본인이 맞나요?' 등)이 있으면 확인
2. developers.facebook.com → 내 앱 → Instagram → 'Instagram 로그인으로 API 설정' → 계정 옆 **토큰 생성**
3. GitHub 레포 Settings → Secrets → `INSTAGRAM_ACCESS_TOKEN` 값을 새 토큰으로 교체
4. 이 이슈에 `지금 게시` 댓글
