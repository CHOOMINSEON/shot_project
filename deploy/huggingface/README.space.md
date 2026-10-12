---
title: 이요링 컷 스튜디오
emoji: 🎬
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 8000
fullWidth: true
startup_duration_timeout: 30m
---

# 이요링 컷 스튜디오 · 테스트 배포

회색 디자인, 파일당 10GB 청크 업로드, 최대 2시간 원본 처리, 숏폼 기획, 자막 검수 및 MP4/SRT 출력 앱입니다. 큰 파일 전체의 부하 검증은 수행하지 않았으므로 짧은 샘플부터 확인하세요.

Space **Settings → Variables and secrets**에서 **Secret**으로 `STUDIO_PASSWORD`를 추가하세요. 직접 정한 12자 이상 비밀번호를 사용하며, 소스 파일·README·공개 Variable에 넣지 않습니다. 필요하면 일반 Variable `STUDIO_WHISPER_MODEL`을 `small`로 설정해 CPU 처리량을 줄일 수 있습니다. 기본은 검수 정확도를 우선한 `medium`입니다.

처음 시작할 때 로컬 음성 모델을 다운로드합니다. 영상·오디오는 이 Space 서버에서 처리하며 외부 음성 인식 API로 보내지 않습니다. 앱의 프레임 삽입 제한과 브라우저 쿠키 정책 때문에, Space 안의 내장 화면 대신 앱의 직접 주소인 `https://…hf.space`를 새 탭으로 여세요.

CPU Basic의 시간당 사용료는 없지만, 2026-10-12에 확인한 공식 안내에서는 Docker Space 생성에 유료 플랜이 필요합니다. 플랜·하드웨어·스토리지 비용은 계정에서 직접 확인하세요. 이 파일은 가입이나 결제를 수행하지 않습니다.

기본 디스크는 영속 저장소가 아니며 재시작·재배포 시 영상과 프로젝트가 사라질 수 있습니다. 이 구성은 테스트용입니다. 출력 파일은 내려받아 보관하고, 장기 사용에는 영속 저장소가 있는 운영 서버를 사용하세요.

사용 방법은 `APP_GUIDE.md`, 검증 기록은 `VALIDATION.md`를 참고하세요. 이 저장소에는 원본 영상·로그인 비밀번호·사용자 데이터를 넣지 않습니다.
