# 결제 없는 PC 실행 + 임시 공개 주소

앱은 사용자 PC의 Docker에서 실행하고 Cloudflare Quick Tunnel로 임시 HTTPS 주소를 받습니다. 호스팅 계정·도메인 구매·Cloudflare 가입은 필요하지 않습니다. PC와 Docker가 켜져 있고 인터넷이 연결된 동안 사용할 수 있습니다. PC의 전기·인터넷 비용은 별도이며, 영구 호스팅이 아닙니다.

## 준비

- RAM 16GB 이상인 PC를 권장합니다. Docker에 8GB 이상 메모리를 배정해 주세요.
- Docker가 사용하는 디스크에 100GB 이상 여유 공간을 권장합니다. 영상·모델·중간 파일·출력을 모두 저장합니다.
- 첫 실행은 앱 이미지와 약 1.5GB 한국어 모델을 인터넷에서 설치합니다. 이미 설치한 모델과 프로젝트는 Docker 볼륨에 남습니다.

## Windows: 처음 실행

1. [Docker Desktop 공식 설치 안내](https://docs.docker.com/desktop/setup/install/windows-install/)에서 설치합니다. WSL 2 설치·재부팅 안내가 나오면 완료합니다.
2. Docker Desktop을 실행합니다. 설정의 메모리·디스크 용량을 확인하세요. WSL 2의 메모리 설정은 Docker 공식 안내를 따릅니다.
3. 받은 ZIP을 **모두 압축 해제**합니다. ZIP 안에서 바로 실행하지 마세요.
4. `shot_project → deploy → free-local` 폴더의 **start.cmd**를 더블클릭합니다.
5. 로그인에 사용할 **영문/숫자 12자 이상 비밀번호**를 입력하고 Enter를 누릅니다. 입력은 화면에 보이지 않습니다. 첫 설치가 끝나면 실제 접속을 확인한 `https://…trycloudflare.com` 주소를 표시하고 브라우저를 엽니다. 비밀번호로 로그인하세요.

비밀번호는 이 PC의 `.env` 파일에 저장됩니다. ZIP·공개 저장소에 추가하거나 다른 사람에게 보내지 마세요. 이 배포 패키지에는 비밀번호·사용자 영상·기존 프로젝트가 들어 있지 않습니다.

## Mac / Linux

Mac은 [Docker Desktop 공식 설치 안내](https://docs.docker.com/desktop/setup/install/mac-install/)에 따라 Intel/Apple Silicon에 맞는 버전을 설치합니다. Linux는 Docker Engine + Compose 플러그인이 필요합니다. Docker 실행 후 압축 해제한 `deploy/free-local` 폴더에서:

```bash
bash start.sh
```

비밀번호 입력 후 표시된 공개 주소로 접속합니다. Apple Silicon/ARM에서의 이미지 빌드·음성 인식은 현재 작업 공간에서 실제 실행 검증하지 않았습니다.

## 테스트·종료·다시 실행

- 처음에는 짧은 영상으로 업로드 → 기획 → 컷 편집 → 자막 검수 → MP4/SRT 출력을 확인하세요. 고밀도 10GB·2시간 실제 원본의 전체 부하 검증은 아직 수행하지 않았습니다.
- Windows는 **stop.cmd**, Mac/Linux는 `bash stop.sh`로 종료합니다. 종료하면 공개 주소 접속이 끊기며 실행 중인 작업이 중단될 수 있습니다. 출력이 끝난 후 종료하세요.
- 다시 실행할 때 같은 폴더의 시작 파일을 사용합니다. 임시 주소는 바뀔 수 있으며, PC와 Docker를 종료하면 접속할 수 없습니다. `public-url.txt`는 마지막으로 확인한 주소일 뿐 현재 접속을 보장하지 않습니다.
- 프로젝트·원본·출력은 `iyoring-free-local_studio-data` Docker 볼륨에 남습니다. **Docker의 볼륨 삭제·초기화·`down -v`는 사용하지 마세요.** 별도 백업은 필요합니다.
- 피드백 수정본은 같은 폴더의 소스에 반영하고 시작 파일을 다시 실행하면 이미지를 새로 빌드합니다. 모델과 데이터 볼륨은 유지합니다. `.env`를 보존하고 이전 소스도 따로 보관하세요.
- 인터넷이 Cloudflare 터널을 차단하면 공개 주소가 생성되지 않습니다. 이 개발 환경에서는 실제 연결이 실패했으며, 사용자 PC의 네트워크에서의 성공도 미리 보장하지 않습니다.

## 확인된 무료 호스팅 조건 (2026-10-12)

| 서비스 | 확인한 조건 | 현재 앱에 대한 판단 |
|---|---|---|
| [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) | 가입 없이 임시 공개 주소; 최대 200개 동시 요청·SSE 미지원 | 이 패키지에 사용. 앱은 청크 업로드와 상태 폴링을 사용합니다. 별도 처리 서버로 PC가 필요합니다. |
| [Replit Starter](https://docs.replit.com/billing/plans/starter-plan) | 무료 공개 앱 1개, 공개 링크 30일 후 종료, Autoscale/Static 사용량 크레딧 | 백그라운드 작업에 적합한 상시 서버 자원·대용량 영속 저장을 무료로 확보했는지 확인하지 못해 전체 앱 배포안으로 제시하지 않습니다. |
| [Hugging Face ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) | 이메일 인증·30일 이상 된 개인 무료 계정은 최대 2개, Gradio SDK 전용, 무료 GPU 하루 5분 | 현재 FastAPI/네이티브 CTranslate2 앱을 그대로 올리는 Docker 배포와 다릅니다. 긴 영상 처리 요구를 충족하는 배포로 검증하지 않았습니다. Docker Space는 유료 플랜이 필요합니다. |
| [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) | A1 ARM 합계 2 OCPU·12GB RAM, 부트/블록 합계 200GB, 홈 리전 한정 | 자원상 서버 후보지만 계정·대개 카드 확인이 필요하며 빈 서버가 없을 수 있습니다. 유휴 서버 회수·ARM 실행 미검증. 무결제·무카드 즉시 배포 방식으로 안내하지 않습니다. |

무료 웹페이지 공개와 이 앱의 영상 처리 서버 실행은 다릅니다. 앱의 10GB 업로드·2시간 입력·medium 인식·검수 기능을 없애는 정적 데모로 대체하지 않았습니다. 가입·결제·외부 서비스 생성은 진행하지 않았습니다.
