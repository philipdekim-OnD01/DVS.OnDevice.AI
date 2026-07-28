# SSH 설치 및 사용법(Ubuntu)

작성일: 2026-07-16

## 대상 장비

- 호스트: `192.168.0.100`
- 사용자: `philip`
- 접속 방식: SSH
- 확인된 장비명: `PhilipRP5`
- OS: Debian GNU/Linux 13 `trixie`, Raspberry Pi OS 계열
- 아키텍처: `arm64`
- 데스크톱 세션: Wayland `labwc`

## SSH 접속 메모

Windows PowerShell에서 기본 SSH 접속:

```powershell
ssh philip@192.168.0.100
```

비밀번호 인증이 필요하다. 자동화 작업에서는 로컬 Python의 `paramiko`를 사용해 접속했다.

주의:

- 원격 명령 안에 `|`, `$(...)`, 큰따옴표가 많으면 로컬 PowerShell이 먼저 해석해서 명령이 깨질 수 있다.
- 복잡한 원격 작업은 짧은 명령으로 나누거나, SFTP로 스크립트를 올린 뒤 실행하는 방식이 안전하다.

## 오늘 수행한 작업

### 1. SSH 연결 확인

- `192.168.0.100`은 SSH로 접속 가능함을 확인했다.
- `philip` 계정은 `sudo` 권한이 있다.

### 2. 한글 표시 및 입력 환경 설치

설치한 패키지:

```text
locales
fonts-noto-cjk
fonts-nanum
ibus
ibus-hangul
im-config
```

적용한 설정:

```text
LANG=ko_KR.UTF-8
~/.xinputrc: run_im ibus
```

확인 결과:

- `fc-match :lang=ko`가 `NanumGothic.ttf`를 반환했다.
- Chromium 프로세스에 `--lang=ko`가 보였다.
- `ibus-engine-hangul` 프로세스가 실행 중이었다.

메모:

- 한글 폰트는 설치되어 있으므로 새로 실행한 앱에서는 한글 표시가 가능해야 한다.
- 기존에 떠 있던 Chromium은 폰트 캐시를 못 볼 수 있으므로 브라우저 재시작이 필요할 수 있다.
- 한글 입력은 로그아웃 후 재로그인하면 가장 확실하게 반영된다.

### 3. Chrome Remote Desktop 검토

- 대상 장비는 `arm64`.
- Google 공식 Chrome Remote Desktop Linux 호스트 패키지는 `chrome-remote-desktop_current_amd64.deb`로 확인되어 Raspberry Pi ARM64에는 맞지 않는다.
- apt 저장소에서도 `chrome-remote-desktop` 패키지는 발견되지 않았다.

대안:

- Raspberry Pi Connect가 이미 설치되어 있고 로그인되어 있었다.
- 확인 상태:

```text
Signed in: yes
Screen sharing: allowed
Remote shell: allowed
```

접속 URL:

```text
https://connect.raspberrypi.com
```

주의:

- Raspberry Pi Connect 웹 로그인에서 2FA가 요구된다.
- 2FA 코드는 계정 소유자의 인증 앱 또는 복구 코드가 필요하며 SSH로 우회할 수 없다.

### 4. 카메라 상태 확인

확인된 카메라:

```text
HD camera : HD camera (usb-xhci-hcd.1-1)
  /dev/video0
  /dev/video1
```

설치된 도구:

```text
/usr/bin/rpicam-still
/usr/bin/ffmpeg
/usr/bin/v4l2-ctl
```

CSI 카메라 상태:

```text
rpicam-hello --list-cameras
No cameras available!
```

USB 카메라 테스트:

```bash
mkdir -p /home/philip/camera_snapshots
ffmpeg -y -hide_banner -loglevel error -f video4linux2 -i /dev/video0 -frames:v 1 /home/philip/camera_snapshots/test.jpg
```

결과:

- 첫 시도는 `/dev/video0`이 busy라 실패했다.
- 이후 다시 실행했을 때 `/home/philip/camera_snapshots/test.jpg`가 생성되었다.
- 생성 파일은 `640x480` JPEG, 약 34KB였다.

### 5. 갑작스러운 다운 관련 확인

장비가 재부팅된 흔적:

```text
Boot time: 2026-07-16 09:52:58
```

현재 부팅 로그에서 확인된 중요한 메시지:

```text
hwmon hwmon2: Undervoltage detected!
hwmon hwmon2: Voltage normalised
```

판단:

- 정확한 종료 원인은 이전 부팅 로그가 남아 있지 않아 단정할 수 없다.
- 현재 확인 가능한 가장 강한 단서는 저전압이다.
- Raspberry Pi 5에 USB 카메라, 디스플레이, 브라우저, 원격접속이 동시에 걸리면 전원 어댑터나 케이블 품질 문제가 재부팅 원인이 될 수 있다.

권장:

- Raspberry Pi 5 공식 전원 또는 충분한 출력의 USB-C PD 전원 사용.
- 카메라가 USB 전원을 많이 쓰면 powered USB hub 사용 검토.
- 저전압 반복 여부는 `dmesg` 또는 `journalctl -k`에서 `Undervoltage`를 확인한다.

## 앞으로 할 작업

### A. 카메라 자동 스냅샷 저장

목표:

- `/home/philip/camera_snapshots`에 타임스탬프 파일명으로 이미지 저장.
- 예: `20260716_095500.jpg`
- 1시간이 지난 `.jpg` 파일은 자동 삭제.
- 촬영 주기는 3초마다 저장으로 변경.

구현 상태:

- `/home/philip/bin/camera_snapshot.sh`
- `systemd --user` service/timer:
  - `camera-snapshot.service`
  - `camera-snapshot.timer`
- `camera-snapshot.timer`는 enabled/active 상태.
- Timer 설정:

```text
OnUnitActiveSec=3s
AccuracySec=1s
```

- 실제 생성 확인:

```text
/home/philip/camera_snapshots/20260716_100214.jpg
/home/philip/camera_snapshots/20260716_100318.jpg
/home/philip/camera_snapshots/20260716_101858.jpg
/home/philip/camera_snapshots/20260716_101909.jpg
/home/philip/camera_snapshots/20260716_102956.jpg
/home/philip/camera_snapshots/20260716_103000.jpg
/home/philip/camera_snapshots/20260716_103004.jpg
```

재부팅 후 자동 실행을 위해 적용:

```bash
sudo loginctl enable-linger philip
```

주의:

- 이전 자동화 스크립트 생성 시도는 로컬 PowerShell 인용 문제로 실패했고 원격에는 적용되지 않았다.
- 다음에는 SFTP로 파일을 올리거나, 로컬 인용이 깨지지 않는 방식으로 진행해야 한다.
- 카메라가 다른 프로세스에서 사용 중이면 캡처가 실패할 수 있다.

### B. 카메라 스냅샷 웹서버

목표:

- 원격 브라우저에서 저장된 카메라 이미지를 썸네일 갤러리 형태로 볼 수 있도록 HTTP 서버 실행.
- 최신 이미지를 크게 표시.
- CPU, 메모리, 온도, throttled 플래그, 캡처 timer 상태, 웹서비스 상태, 디스크 여유 공간을 표시.
- Core 전압, ARM clock, ARM/GPU memory split, USB 장치, video device, GPIO/I2C 장치 목록 표시.
- 온도는 최근 최대 24시간 히스토리를 서버 메모리와 파일에 저장하고 canvas 라인 그래프로 표시.
- 온도 기록 파일: `/home/philip/.local/state/camera-snapshots/temperature-history.json`

구현 상태:

- 서비스 파일:

```text
/home/philip/.config/systemd/user/camera-snapshots-web.service
```

- 실행 명령:

```bash
/usr/bin/python3 /home/philip/bin/camera_gallery_server.py
```

- 서비스 상태:

```text
camera-snapshots-web.service: enabled, active
LISTEN 0.0.0.0:8080
```

접속 URL:

```text
http://192.168.0.100:8080/
```

Windows에서 HTTP 200 응답을 확인했다.

상태 API:

```text
http://192.168.0.100:8080/status.json
```

`status.json`에는 CPU/메모리/센서 상태뿐 아니라 최근 이미지 목록도 포함되어, 브라우저가 3초마다 새 스냅샷만 반영할 수 있다.

대시보드 기능:

- 전체 페이지 자동 새로고침은 제거.
- `/status.json`을 3초마다 polling해서 상태값과 썸네일 목록만 갱신.
- `/status.json`에는 `temp_history`와 `temp_history_hours: 24`가 포함된다.
- 확대 모달이 열린 상태에서도 페이지가 새로고침되어 닫히지 않도록 구성.
- 메인 이미지 영역은 제거하고 최근 이미지 썸네일 그리드를 중심으로 구성.
- 썸네일도 `object-fit: contain`으로 변경해 프레임에서 잘린 듯한 표시를 줄임.
- 썸네일 그리드는 메인 이미지 바로 아래 왼쪽 콘텐츠 컬럼에 배치.
- 썸네일 클릭 시 페이지 안 확대 모달로 원본 이미지를 표시.
- 클릭 확대 이벤트는 썸네일 개별 바인딩이 아니라 `snapshot-grid` 이벤트 위임 방식으로 처리.
- 3초 polling 중 썸네일 DOM이 갱신되어도 클릭 이벤트가 사라지지 않도록 수정.
- 확대 모달이 열려 있을 때는 썸네일 재렌더링을 건너뛰어 확대 보기가 끊기지 않도록 구성.
- JavaScript 문자열 줄바꿈 이스케이프 오류를 수정했다.
- 썸네일은 `<a href="/image/...">` 링크 fallback을 갖도록 변경했다. JS가 정상 동작하면 모달 확대가 열리고, JS가 실패해도 원본 이미지 링크로 이동 가능하다.
- 상태 패널은 데스크톱에서 오른쪽 sticky sidebar로 고정.
- CPU 사용률은 짧은 즉시 샘플 대신 이전 `/proc/stat` 샘플과 현재 샘플의 delta로 계산하도록 수정.
- 최근 캡처 로그 표시.

용량 메모:

- 현재 640x480 JPEG 한 장은 약 34KB 수준.
- 3초 주기, 1시간 보관이면 최대 약 1200장.
- 현재 캡처 처리 시간 때문에 실제 생성 간격은 약 3-4초로 관측됨.
- 현재 640x480 JPEG 한 장이 약 34KB 수준이므로 예상 사용량은 약 40-60MB 수준이다.
- 온도 기록은 3초 간격 24시간 기준 약 28,800포인트이며 JSON 파일 크기는 대략 1-2MB 수준으로 예상된다.

### C. 사람 감지 별도 저장

목표:

- 사람이 지나가는 장면을 일반 스냅샷과 별도로 저장.

구현 상태:

- 설치한 패키지:

```text
python3-opencv
```

- 감지 스크립트:

```text
/home/philip/bin/person_detect.py
```

- 별도 저장 폴더:

```text
/home/philip/person_snapshots
```

- 이벤트 로그:

```text
/home/philip/.local/state/camera-snapshots/person-events.log
```

- 캡처 스크립트 `/home/philip/bin/camera_snapshot.sh`에서 일반 스냅샷 저장 직후 `person_detect.py`를 실행.
- 일반 스냅샷에서 사람이 감지되면 `/dev/video0`에서 0.5초 간격으로 burst 3장을 추가 촬영한다.
- 초기 감지 프레임과 burst 프레임 중 감지 점수(score)가 가장 높은 1장만 선택한다.
- 선택된 1장에 bounding box를 그려 `/home/philip/person_snapshots`에 같은 타임스탬프 파일명으로 저장한다.
- 사람 감지 이미지는 24시간 보관.
- 대시보드에 `Person events` 섹션 추가.
- 메인 대시보드 상단에 사람 감지 전용 썸네일 페이지 링크 추가.
- 사람 감지 전용 페이지:

```text
http://192.168.0.100:8080/person
```

- 별도 이미지 endpoint:

```text
http://192.168.0.100:8080/person-image/<파일명>
```

확인 결과:

```text
/home/philip/person_snapshots/20260722_103612.jpg
/home/philip/person_snapshots/20260722_103626.jpg
/home/philip/person_snapshots/20260722_104016.jpg
```

새 로그 형식 예:

```text
person detected burst_saved /home/philip/person_snapshots/20260722_104016.jpg count=2 score=1.02 source=20260722_104016.jpg burst_frames=3
person detected burst_saved /home/philip/person_snapshots/20260722_104031.jpg ...
```

주의:

- 현재 감지는 OpenCV DNN + YOLOv5n ONNX로 변경했다.
- 모델 파일:

```text
/home/philip/models/yolov5n.onnx
```

- 다운로드 출처:

```text
https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx
```

- YOLOv5n 모델 로드 시간은 약 0.08초로 확인.
- 최신 스냅샷 기준 직접 감지 실행 시간은 약 1.6초로 확인.
- 사람 클래스만 사용하며 confidence threshold는 `0.35`.
- HOG보다 오탐을 줄이는 방향이지만 조명/각도/배경에 따라 여전히 미탐이 있을 수 있다.
- 사람이 화면에 계속 있으면 일반 캡처 주기마다 burst가 실행되고, 각 burst당 1장만 별도 저장된다.
- 이벤트 수가 너무 많으면 cooldown 저장 방식으로 바꿀 수 있다.
- ResNet 계열 detector도 검토했다.
- 설치한 패키지:

```text
python3-torch
python3-torchvision
```

- 테스트한 모델:

```text
torchvision.models.detection.fasterrcnn_resnet50_fpn
```

- 확인 결과:

```text
model load: 약 35초
single image inference: 약 54-58초
```

- 현재 3초 캡처 주기에는 ResNet/Faster R-CNN을 실시간 자동 감지기로 연결하기 어렵다.
- 실시간성까지 원하면 ResNet보다 MobileNet-SSD, YOLO-nano, EfficientDet-Lite 같은 경량 object detector가 더 적합하다.

장애/재부팅 확인 메모:

- 2026-07-22 오후에 Pi가 한동안 ping만 되고 SSH/웹 포트가 닫혀 있었다.
- 사용자가 직접 리부팅한 뒤 SSH와 웹서비스가 다시 정상 동작했다.
- 재부팅 후 확인된 상태:

```text
boot time: 2026-07-22 14:15:34 KST
camera-snapshot.timer: active
camera-snapshots-web.service: active
vcgencmd get_throttled: 0x0
```

- 현재 부팅 로그에서는 저전압, OOM kill, kernel panic 증거가 확인되지 않았다.
- `journalctl --list-boots`에는 현재 boot만 남아 있어 이전 boot의 정확한 종료 원인은 확인할 수 없었다.
- 장애 직전 로그에는 YOLO 감지 이벤트가 14:09-14:12 사이 기록되어 있었고, 이후 사용자가 리부팅했다.
- 가능성은 YOLO 감지, 3초 캡처, burst 촬영, 유사 이미지 pruning이 겹친 사용자 공간 부하 또는 전원/부팅 서비스 문제다.

### D. HDMI 화면을 메인으로 설정

현재 상태:

- Wayland `labwc` 사용 중.
- `kanshi`가 실행 중.
- `~/.config/kanshi/config`는 존재하지만 비어 있었다.
- `wlr-randr`, `kanshi`, `xrandr`가 설치되어 있다.

다음 단계:

1. Wayland socket 확인:

```bash
ls -la /run/user/1000
```

2. 출력 이름 확인:

```bash
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 wlr-randr
```

또는:

```bash
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 wlr-randr
```

3. HDMI 출력 이름이 확인되면 `~/.config/kanshi/config`에 HDMI를 `(0,0)` 위치로 두는 profile을 작성한다.

예시 형태:

```text
profile {
    output HDMI-A-1 enable position 0,0
    output <OTHER_OUTPUT> enable position 1920,0
}
```

정확한 출력 이름과 해상도는 `wlr-randr` 결과를 보고 결정해야 한다.

## 다음 작업 시 주의할 점

- 라즈베리파이가 저전압으로 재부팅될 수 있으므로 무거운 작업을 연속 실행하기 전에 전원 상태를 먼저 확인한다.
- 복잡한 원격 명령은 PowerShell 인용 문제를 피하기 위해 원격 파일로 만들어 실행한다.
- 사용자가 중간에 중단한 작업은 재개 전에 현재 상태를 다시 확인한다.
- Chrome Remote Desktop 설치는 ARM64 공식 패키지가 없으므로 Raspberry Pi Connect 또는 VNC 계열 대안을 우선 사용한다.


## 2026-07-22 DVS 제안서 메일 발송

- 수신자: philip.de.kim@gmail.com
- 제목: DVS 기반 고속 이동 정보 융합 영상 생성 시스템 제안서
- 발송 방식: 로컬 Outlook COM 자동화
- 포함 내용:
  - 현재 Raspberry Pi 카메라/YOLO 대시보드 구조
  - DVS 센서 추가 목적
  - DVS 이벤트 좌표 기반 영상 합성 아키텍처
  - 저장 구조, 웹 대시보드 확장안, 구현 단계
  - 리스크와 다음 작업
- 결과: Outlook에서 발송 명령 완료


## 2026-07-22 TimeLens-XL 참고 DVS 합성 제안서 메일 발송

- 수신자: philip.de.kim@gmail.com
- 제목: TimeLens-XL 참고 DVS/RGB 합성 구체 방안 및 경량화 제안
- 참고:
  - Notion: https://www.notion.so/neurorealityvision/Making-Fire-TimeLens-XL-38abbe782398800f9be3ea63552a7320?source=copy_link
  - TimeLens-XL 공개 프로젝트: https://openimaginglab.github.io/TimeLens-XL/
  - TimeLens-XL 공개 코드: https://github.com/OpenImagingLab/TimeLens-XL
- 주요 내용:
  - TimeLens-XL의 RGB 2프레임 + 이벤트 스트림 기반 frame interpolation 개념 정리
  - Raspberry Pi 현재 카메라/YOLO 대시보드에 DVS를 붙이는 구조 제안
  - 경량 overlay, motion-field/warping, TLXNet 오프로드 3단계 합성 전략
  - ROI crop, time-bin 축소, event clipping, polarity 단순화, ONNX/INT8, 비동기 slow path 등 경량화 방안
- 결과: 로컬 Outlook COM으로 발송 완료


## 2026-07-22 가상 DVS 경량 합성 그리드 구현

- 요청 내용:
  - 동영상 파일 생성 대신, 빠진 중간 화면을 JPG 그리드로 표시
  - 현재 고속 DVS 센서가 없으므로 RGB 두 장의 차이를 이용해 가상 이벤트 데이터를 생성
  - 경량화 최적화 우선

- 구현 위치:
  - 합성 스크립트: /home/philip/bin/synthesize_virtual_dvs_grid.py
  - 별도 웹서버: /home/philip/bin/synthetic_grid_server.py
  - 합성 결과: /home/philip/synthetic_frames
  - systemd user service: synthetic-grid-web.service
  - systemd user timer: synthetic-grid-maker.timer

- 웹 접속:
  - http://192.168.0.100:8081/

- 동작 방식:
  - 최신 person snapshot 2장을 우선 사용하고, 없으면 일반 camera snapshot 2장을 사용
  - 두 이미지의 grayscale 차분으로 가상 DVS event mask 생성
  - threshold, morphology open/dilate로 노이즈 제거
  - 변화영역 중심으로 가벼운 shift vector 추정
  - before/after 이미지를 작은 affine translation과 alpha blend로 9장 중간 프레임 생성
  - event mask를 녹색/적색 heat overlay로 합성
  - 영상 인코딩 없이 JPG만 저장

- 경량화 포인트:
  - 최대 폭 640px로 축소 후 처리
  - optical flow 전체 계산 생략
  - 딥러닝 추론 없음
  - mp4/webp 인코딩 없음
  - JPG quality 82
  - 이벤트당 9장만 생성
  - 최대 200개 synthetic event 디렉터리 유지
  - 30초마다 자동 생성

- 확인 결과:
  - synthetic-grid-web.service active
  - synthetic-grid-maker.timer active
  - Windows에서 http://192.168.0.100:8081/ GET 200 확인
  - /home/philip/synthetic_frames 아래 JPG 생성 확인


## 2026-07-22 Synthetic Grid 프레임 수 조정

- 변경 내용:
  - /home/philip/bin/synthesize_virtual_dvs_grid.py 의 GRID_STEPS 값을 8에서 20으로 변경
  - 합성 결과는 t=0.00부터 t=1.00까지 포함해 이벤트당 21장 JPG 생성
  - 20개 구간으로 더 촘촘하게 보간되어 그리드 연속성이 개선됨

- 영향:
  - 영상 인코딩과 딥러닝 추론은 계속 사용하지 않음
  - 처리 방식은 기존 lightweight affine shift + alpha blend + virtual event heat overlay 유지
  - 저장량은 이벤트당 약 9장 기준에서 21장으로 증가
  - synthetic-grid-maker.timer 는 계속 30초 주기 유지


## 2026-07-22 Synthetic Grid 20fps 플레이어 추가

- 요청 내용:
  - 20프레임 합성 결과를 동영상처럼 볼 수 있는 별도 창 추가

- 구현 방식:
  - MP4 인코딩 없이 기존 JPG 프레임을 브라우저 JavaScript로 20fps 재생
  - 각 synthetic event 카드에 `Open Player` 링크 추가
  - 새 창/탭에서 `/play/<event_id>` 접속
  - Play/Pause, Prev, Next, seek slider 제공

- 경량화 이유:
  - ffmpeg 인코딩 부하 없음
  - 추가 저장 파일 없음
  - 이미 생성된 21장 JPG를 재사용
  - Pi CPU/MEM 사용량 증가 최소화

- 확인:
  - synthetic-grid-web.service 재시작 완료
  - http://192.168.0.100:8081/ 에 Open Player 링크 확인
  - /play/<event_id> 응답 200 확인


## 2026-07-22 사람 감지 시에만 Synthetic Grid 생성 및 메일 발송

- 변경 요청:
  - Synthetic grid를 주기적으로 만들지 않음
  - 사람 인식이 되었을 때만 1회 생성
  - 생성될 때마다 philip.de.kim@gmail.com 으로 메일 발송

- Raspberry Pi 변경:
  - synthetic-grid-maker.timer 중지 및 disable
  - /home/philip/bin/person_detect.py 에서 사람 이미지 저장 직후 trigger_person_synthesis_once() 호출
  - /home/philip/bin/trigger_person_synthesis.py 추가

- 합성 트리거 동작:
  - 최신 person snapshot을 after 이미지로 사용
  - 그 직전 일반 camera snapshot을 before 이미지로 우선 사용
  - 두 이미지를 기반으로 가상 DVS lightweight grid를 1회 생성
  - 결과는 /home/philip/synthetic_frames/<event_id> 에 21장 JPG로 저장
  - /home/philip/.local/state/camera-snapshots/mail-queue/<event_id>.json 메일 큐 생성

- 메일 발송 구조:
  - Raspberry Pi는 SMTP 설정 없이 메일 큐 JSON만 생성
  - Windows의 raspi_person_mail_watcher.py 가 5초마다 Pi mail-queue를 확인
  - 새 큐가 있으면 로컬 Outlook COM으로 philip.de.kim@gmail.com 에 발송
  - 메일에는 Grid/Player 링크와 대표 JPG 최대 3장을 첨부

- 현재 상태:
  - synthetic-grid-maker.timer: inactive
  - synthetic-grid-web.service: active
  - Windows Outlook 프로세스 실행 중
  - Windows 메일 워처 프로세스 실행 중


## 2026-07-22 Watchdog, MP4 Player, Navigation 마무리

- 자동 복구/재부팅:
  - ssh 서비스 enable 및 active 확인
  - philip 사용자 linger 활성화
  - systemd watchdog 설정 추가: /etc/systemd/system.conf.d/10-watchdog.conf
  - /boot/firmware/config.txt 에 dtparam=watchdog=on 추가
  - /dev/watchdog 및 /dev/watchdog0 확인
  - camera-stack-healthcheck.timer 추가: 1분마다 SSH/웹서비스 상태 확인
  - 반복 복구 실패 시 제한 sudoers 규칙으로 reboot 실행

- Synthetic 20fps 영상:
  - /home/philip/bin/synthesize_virtual_dvs_grid.py 에 MP4 생성 추가
  - 21장 JPG를 ffmpeg로 20fps MP4 생성
  - codec: libx264, preset ultrafast, crf 28, yuv420p
  - /play/<event_id> 화면에서 MP4 video 태그 우선 표시
  - MP4가 없을 경우 기존 JPG JavaScript player fallback 유지

- Navigation:
  - 8080 첫 화면에 Home / Person / Synthetic Grid 링크 추가
  - 8080 Person 페이지에도 Home / Person / Synthetic Grid 링크 추가
  - 8081 Synthetic Grid 페이지에 Home / Person 링크 추가
  - 8081 Player 페이지에 Home / Grid 링크 추가

- 확인:
  - http://192.168.0.100:8080/ navigation 확인
  - http://192.168.0.100:8080/person navigation 확인
  - http://192.168.0.100:8081/ navigation 확인
  - /play/<event_id> video 태그 확인
  - /video/<event_id>/<event_id>.mp4 Content-Type video/mp4 확인


## 2026-07-22 사람 감지 Burst 0.1초 변경 및 Navigation 중앙 정렬

- 사람 감지 burst 변경:
  - /home/philip/bin/person_detect.py
  - BURST_FPS = 10
  - BURST_FRAMES = 5
  - 사람 인식 시 0.1초 단위로 약 0.5초 구간을 촬영

- Navigation 정리:
  - 8080 Home, 8080 Person, 8081 Synthetic Grid, 8081 Player의 상단 링크를 중앙 정렬 스타일로 통일
  - f-string HTML 템플릿 내부 CSS 중괄호 escape 문제를 수정

- 확인:
  - camera-snapshots-web.service active
  - synthetic-grid-web.service active
  - 8080 Home 중앙 nav 확인
  - 8080 Person 중앙 nav 확인
  - 8081 Synthetic Grid 중앙 nav 확인


## 2026-07-22 사진-그리드 교차 방식 20프레임 합성 및 홈 자동 영상 표시

- 합성 방식 변경:
  - /home/philip/bin/synthesize_virtual_dvs_grid.py 재작성
  - 기존 before/after 2장 기반 보간에서 여러 실제 사진 시퀀스 기반으로 변경
  - 사람 감지 burst 사진이 있으면 실제 사진들을 모두 사용
  - 실제 사진 사이에 가상 DVS grid 프레임을 균등 배치
  - 결과 구성: 사진-그리드-그리드-...-사진-그리드-...-사진
  - 최종 출력은 총 20프레임, 20fps MP4

- 트리거 변경:
  - /home/philip/bin/trigger_person_synthesis.py
  - 최신 person burst 디렉터리를 우선 사용
  - burst가 없으면 기존 person/snapshot fallback 사용

- 웹 표시 변경:
  - /home/philip/bin/synthetic_grid_server.py
  - /play/<event_id>를 누르지 않아도 8081 홈 이벤트 카드에 MP4 자동 표시
  - video 태그: autoplay, muted, loop, playsinline, controls
  - 기존 thumbnail grid와 Open Player 링크는 유지

- 확인:
  - 최신 합성 이벤트: 20프레임 MP4 생성 확인
  - http://192.168.0.100:8081/ 에 inline video 태그 확인
  - /video/<event_id>/<event_id>.mp4 Content-Type video/mp4 확인


## 2026-07-22 사진-그리드-그리드-그리드-사진 패턴 개선

- 요청 내용:
  - 사람 인식에 따른 20프레임 영상 합성을 더 자연스럽게 개선
  - 실제 사진 사이에 여러 grid 프레임을 넣는 `사진-그리드-그리드-그리드-사진...` 흐름 적용

- 변경 내용:
  - /home/philip/bin/person_detect.py
    - 사람 감지 시 0.1초 burst 원본들을 별도 보존
    - 보존 위치: /home/philip/.local/state/camera-snapshots/person-bursts
    - 초기 감지 사진 + burst 5장을 시퀀스로 저장
  - /home/philip/bin/synthesize_virtual_dvs_grid.py
    - 실제 burst 사진 시퀀스를 우선 사용
    - 총 20프레임을 유지
    - 실제 사진 사이에 grid 프레임을 우선 3장 정도 배치
    - 일반적인 6장 실제 burst 기준 분포는 [3, 3, 3, 3, 2]
  - /home/philip/bin/trigger_person_synthesis.py
    - 최신 burst 디렉터리를 우선 입력으로 사용

- 확인:
  - synthetic-grid-web.service active
  - camera-snapshot.timer active
  - camera-snapshots-web.service active
  - 최신 fallback 합성 MP4 생성 및 8081 홈 inline video 표시 확인
  - 실제 사람 감지 이벤트부터는 burst 원본 기반으로 사진-그리드 반복 패턴 적용


## 2026-07-22 Grid 증가 및 사람 실루엣형 Mask 개선

- 요청 내용:
  - grid 프레임을 더 넣어 자연스럽게 보이도록 개선
  - grid가 가능한 한 사람 shape 형태를 따르도록 개선

- 변경 내용:
  - /home/philip/bin/synthesize_virtual_dvs_grid.py
  - OUTPUT_FRAMES = 32
  - VIDEO_FPS = 20 유지
  - 실제 사람 감지 burst가 6장일 경우 사진 사이에 보통 5~6개 grid 프레임 삽입
  - 20프레임보다 더 촘촘한 움직임 표현 가능

- 사람 shape grid 개선:
  - 기존 단순 frame difference mask에서 개선
  - grayscale 차분 후 threshold
  - morphology open/close/dilate로 노이즈 제거
  - contour 분석으로 가장 큰 움직임 blob 1~2개 선택
  - convex hull로 사람 실루엣에 가까운 mask 생성
  - 배경의 작은 움직임은 최대한 제거

- 확인:
  - 샘플 32프레임 MP4 생성 확인
  - meta shape_mask = largest_motion_silhouette
  - 8081 홈 inline video 표시 확인
  - MP4 Content-Type video/mp4 확인


## 2026-07-22 사람 인식 자동 합성 및 8081 자동 표시 검증

- 요구 내용:
  - 사람이 인식되면 합성을 자동으로 수행
  - 생성된 합성 영상을 홈페이지에서 자동으로 보여줌

- 확인한 자동 흐름:
  - /home/philip/bin/person_detect.py
    - 사람 저장 직후 trigger_person_synthesis_once() 호출
    - 0.1초 burst 원본은 person-bursts 디렉터리에 보존
  - /home/philip/bin/trigger_person_synthesis.py
    - 최신 burst 디렉터리를 우선 입력으로 사용
    - 합성 스크립트를 호출하고 mail queue 생성
  - /home/philip/bin/synthesize_virtual_dvs_grid.py
    - 32프레임, 20fps MP4 생성
    - 사람 shape 기반 grid mask 사용
  - /home/philip/bin/synthetic_grid_server.py
    - 8081 홈 이벤트 카드에서 MP4를 자동 표시

- 검증:
  - 수동 트리거 테스트 이벤트: 20260722_170411
  - 8081 홈에서 20260722_170411.mp4 inline video 표시 확인
  - /video/20260722_170411/20260722_170411.mp4 Content-Type video/mp4 확인
  - mail queue는 20260722_170411.json.sent 로 처리 완료 확인
  - 관련 서비스 active


## 2026-07-22 여러 Person 사진 활용 합성 개선

- 문제:
  - 최신 합성 이벤트가 같은 person 사진 2장을 before/after로 사용한 사례가 있었음
  - 이 경우 실제 사람 사진이 많아도 활용되지 않아 영상이 부자연스러움

- 원인:
  - person-bursts 디렉터리가 비어 있는 상황에서 fallback 입력 선택이 너무 좁았음
  - 중복 파일이 before/after로 들어갈 수 있었음

- 변경:
  - /home/philip/bin/trigger_person_synthesis.py 재작성
  - 최신 burst 디렉터리가 있으면 burst 사진 전체를 시간순으로 사용
  - burst가 없으면 최근 person_snapshots 6~8장을 시간순으로 사용
  - 최근 90초 cluster를 우선 사용해 다른 이벤트 사진이 섞이는 것을 줄임
  - 같은 파일 중복 사용 금지

- 검증:
  - 테스트 이벤트: 20260722_170858
  - source_images 5장 사용 확인
  - grid_distribution: [7, 7, 7, 6]
  - output_frames: 32
  - shape_mask: largest_motion_silhouette
  - 8081 홈 inline video 표시 확인

- 기대 효과:
  - 실제 사람 인식 사진이 많을수록 더 자연스러운 연속 영상 생성
  - 같은 사진 2장을 반복해 합성하는 부자연스러운 결과 방지


## 2026-07-22 8081 중복 Navigation 제거

- 문제:
  - 8081 Synthetic Grid 페이지 상단 중앙 메뉴가 중복 표시됨

- 변경:
  - /home/philip/bin/synthetic_grid_server.py
  - 중복 global-nav HTML 블록 제거
  - 플레이어 페이지의 중복 nav도 정리

- 확인:
  - 8081 홈에서 class="global-nav" 1개 확인
  - 8081 플레이어에서 class="global-nav" 1개 확인
  - synthetic-grid-web.service active


## 2026-07-22 디스크 사용률 70% 자동 정리 설정

- 요청 내용:
  - 저장용량이 70% 정도 차면 먼저 저장된 사진들을 삭제
  - 사용률이 70%를 넘지 않도록 관리

- 구현:
  - /home/philip/bin/disk_usage_guard.py
  - systemd user service: disk-usage-guard.service
  - systemd user timer: disk-usage-guard.timer
  - 1분마다 실행

- 삭제 대상:
  - /home/philip/camera_snapshots
  - /home/philip/.local/state/camera-snapshots/person-bursts
  - /home/philip/synthetic_frames
  - /home/philip/person_snapshots

- 정책:
  - /home/philip 기준 디스크 사용률 확인
  - 70% 이하이면 삭제하지 않음
  - 70% 초과 시 오래된 파일부터 삭제
  - 대상 확장자: jpg, jpeg, png, mp4, json, txt
  - 빈 synthetic/person-burst 디렉터리 정리
  - 로그: /home/philip/.local/state/camera-snapshots/disk-guard.log

- 현재 확인:
  - disk-usage-guard.timer active
  - 현재 디스크 사용률 약 9%
  - camera_snapshots 약 8.7M
  - person_snapshots 약 11M
  - synthetic_frames 약 36M
  - 현재는 70% 이하라 삭제 없음


## 2026-07-23 Synthetic DVS Grid 자동 업데이트 복구

- 증상:
  - 사람 인식 사진은 /home/philip/person_snapshots 에 정상 저장됨
  - Synthetic DVS Grid는 최신 person 이벤트 이후 업데이트되지 않음
  - 8081 홈은 오래된 synthetic 이벤트를 표시하고 있었음

- 확인:
  - 최근 person snapshot: 20260723_090911 등 오늘 파일 다수 존재
  - 최신 synthetic은 20260722_170858로 멈춰 있었음
  - trigger_person_synthesis.py 수동 실행은 정상 동작

- 원인:
  - person_detect.py에서 합성 트리거를 완전 백그라운드(Popen + stdout/stderr DEVNULL)로 실행해 실패가 숨겨짐
  - burst 원본 보존 호출이 실제 main flow에 빠져 있었음
  - save_detection 내부에서 너무 이른 시점에 trigger가 호출됨

- 수정:
  - person_detect.py에서 save_detection 내부 trigger 제거
  - person 이벤트 로그 기록 후 trigger_person_synthesis_once() 호출
  - trigger를 subprocess.run으로 실행하고 timeout=45 적용
  - stdout/stderr를 /home/philip/.local/state/camera-snapshots/trigger-synthesis.log 에 기록
  - capture_burst 결과를 keep_burst_sequence()로 보존하도록 복구

- 검증:
  - person_detect.py end-to-end 직접 실행
  - 입력: 최신 person snapshot
  - 새 synthetic 이벤트 생성: 20260723_091146
  - trigger log: exit=0
  - 8081 홈에서 20260723_091146.mp4 자동 표시 확인
  - MP4 Content-Type video/mp4 확인


## 2026-07-23 사람 인식 저장 기준 60%로 변경

- 요청 내용:
  - 사람 인식 confidence가 60% 이상일 때만 저장

- 변경:
  - /home/philip/bin/person_detect.py
  - CONF_THRESHOLD = 0.60

- 영향:
  - YOLO person confidence 60% 미만은 저장하지 않음
  - person snapshot 저장, burst 보존, Synthetic DVS Grid 합성, 메일 큐 생성도 60% 이상 감지에서만 이어짐

- 확인:
  - person_detect.py 문법 검사 통과
  - camera-snapshot.timer 재시작
  - camera-snapshot.timer active


## 2026-07-23 촬영 주기 재확인

- 일반 카메라 스냅샷:
  - /home/philip/.config/systemd/user/camera-snapshot.timer
  - OnUnitActiveSec=3s
  - AccuracySec=1s

- 사람 인식 시 burst:
  - /home/philip/bin/person_detect.py
  - BURST_FPS = 10
  - BURST_FRAMES = 5
  - 0.1초 간격으로 약 0.5초 구간 촬영

- 확인:
  - person_detect.py 문법 검사 통과
  - camera-snapshot.timer active


## 2026-07-24 Raspberry Pi HALT/전원/카메라 장애 진단

- 현재 상태:
  - Raspberry Pi 접속 가능
  - ping, SSH, 8080 정상
  - 부팅 시각: 2026-07-24 11:20 KST
  - 현재 get_throttled: 0x0
  - 현재 온도: 약 58~62도

- 전원 부족 여부:
  - 현재 부팅 이후에는 undervoltage/throttling 플래그 없음
  - get_throttled=0x0 이므로 현재 시점에서 전원 부족이 감지되지는 않음
  - 다만 이전 장애 시점 로그가 보존되지 않아 과거 순간 저전압 여부는 확정 불가

- 확인된 장애 패턴:
  - 카메라가 멈췄을 때 /dev/video0 에서 Input/output error 발생
  - 커널 로그에 uvcvideo/USB 오류 확인:
    - Failed to set UVC probe control : -71
    - Failed to suspend device, error -32
    - can't set config #1, error -71
  - 이는 애플리케이션 오류라기보다 USB UVC 카메라 또는 USB 버스가 꼬인 상태에 가까움
  - 재부팅 후 HD camera가 다시 /dev/video0, /dev/video1로 정상 인식됨

- 온도:
  - root watchdog 로그에서 전날 70~77도까지 상승한 이력 있음
  - throttled=0x0이라 온도 throttling은 기록되지 않았지만 장시간 운용에는 높은 편

- 조치:
  - root watchdog에 snapshot stale 감지 추가
  - /dev/video0 캡처가 멈추고 최신 snapshot이 3분 이상 오래되면 실패로 처리
  - 2회 연속 실패 시 reboot
  - systemd persistent journal 활성화
    - /etc/systemd/journald.conf.d/10-persistent.conf
    - /var/log/journal
    - SystemMaxUse=512M
  - 다음 장애부터 journalctl -b -1 로 직전 부팅 로그 확인 가능

- 권장 하드웨어 점검:
  - Raspberry Pi 5 공식 27W USB-C 전원 또는 5V 5A급 안정 전원 사용
  - USB 카메라는 가능하면 powered USB hub 사용
  - 짧고 품질 좋은 USB 케이블 사용
  - 카메라 USB 포트 변경 테스트
  - 팬/방열 강화

## 2026-07-25 06:31:26 +09:00ST - Raspberry Pi HALT 로그 점검 및 전원 그래프 동기화
- 리부팅 직전 로그 확인: journalctl -b -1은 
o persistent journal was found로 실패. 이전 부팅의 커널 로그가 보존되지 않아 HALT 순간의 직접 원인은 복구 불가.
- 파일 로그 기준 마지막 정상 캡처: 2026-07-24 12:52:12; 다음 부팅: 2026-07-25 06:27:35. 이 구간에 watchdog/capture 로그가 끊김.
- 현재 cgencmd get_throttled:  x0. 현재 샘플 기준 저전압/스로틀 플래그 없음.
- 방열판 부착 후 온도 샘플: 대략 45~53도 범위로 확인.
- 사진 저장 시점마다 /home/philip/.local/state/camera-snapshots/power-samples.log에 온도, 	hrottled, 코어전압, ARM clock, snapshot 파일명을 같은 타임스탬프로 저장하도록 동기화.
- 8080 웹 대시보드 Power/Thermal 그래프에 온도(red), core voltage(blue), ARM clock(green), throttled/undervoltage event shading을 표시하도록 수정.
- power_history API 정상 확인: 1408개 샘플 로드.
- persistent journal 설정 재적용: /etc/systemd/journald.conf.d/10-persistent.conf, Storage=persistent, SystemMaxUse=512M. 다음 장애부터 journalctl -b -1로 직전 부팅 로그 확인 가능.
- hardware watchdog 상태: RuntimeWatchdogUSec=1min, RebootWatchdogUSec=2min, camera-root-watchdog.timer enabled/active.
- ARM Clock은 항상 동일하지 않음. 예:  6:30:28 샘플에서 1.80GHz,  .7739V로 내려갔지만 	hrottled=0x0이므로 전원 부족보다는 DVFS 전력관리 동작으로 판단.

## 2026-07-25 06:37:52 +09:00ST - 캡처/YOLO/합성 분리 및 자동 리부트 강화
- camera_snapshot.sh를 경량화: 사진 저장, 전원 샘플 기록, detect queue 생성까지만 수행. YOLO/합성을 직접 기다리지 않음.
- fmpeg 캡처에 	imeout 12 적용. 카메라 캡처가 hang되면 캡처 서비스가 무한 대기하지 않도록 함.
- 새 YOLO worker 추가: /home/philip/bin/person_yolo_worker.py, systemd user service person-yolo-worker.service.
- 새 합성 worker 추가: /home/philip/bin/person_synthesis_worker.py, systemd user service person-synthesis-worker.service.
- 처리 흐름: snapshot 저장 -> /detect-queue -> YOLO worker -> 사람 60% 이상 감지 시 /synthesis-queue -> synthesis worker -> synthetic video/mail queue.
- person_detect.py에서 합성 직접 호출 제거. 감지와 합성이 서로 묶여 멈추는 구조를 해소.
- root watchdog 강화: 캡처 stale, 포트 22/8080/8081, camera timer, 8080/8081 웹 서비스, YOLO worker, synthesis worker를 감시. 첫 실패는 camera stack 재시작, 연속 2회 실패는 reboot.
- 검증: person-yolo-worker.service, person-synthesis-worker.service, camera-snapshot.timer, camera-snapshots-web.service, synthetic-grid-web.service 모두 active.
- 검증 시 최신 캡처: 20260725_063730.jpg, power sample count 1522개, 	emp=65.9C, core_volts=0.8564V, rm_clock=2.4GHz, 	hrottled=0x0.
- 큐 상태: detect queue는 최신 처리 중 1개 수준, synthesis queue 0개. 캡처와 YOLO 처리가 분리되어 캡처 루프가 후처리에 막히지 않음.

## 2026-07-27 14:51:31 +09:00ST - Raspberry Pi CPU 클럭 2GHz 상한 적용
- 요청: CPU 클럭을 2GHz 이하로 제한, 2GHz를 넘지 않도록 설정.
- 적용 방식: cpufreq에서 scaling_max_freq=2000000 설정. 고정 클럭이 아니라 최대 클럭 제한.
- 새 systemd 서비스: pi-cpu-max-2ghz.service enabled.
- helper: /usr/local/sbin/pi-set-cpu-max-2ghz.sh.
- 기존 고정형 pi-cpu-2ghz.service가 있으면 비활성/삭제하도록 처리.
- 적용 후 상태: governor=ondemand, min=1500000, max=2000000, cur=2000000.
- cgencmd: arm clock 약 2.0GHz, core voltage  .8007V, temp 약 51C, throttled= x0.
- 의미: 부하가 낮으면 내려갈 수 있고, 부하가 높아도 2GHz를 넘지 않음. 온도/전압 안정성 개선 목적.

## 2026-07-27 14:56:49 +09:00ST - 온도 기반 CPU 클럭 보호 적용
- 정책: 70C 이상이면 CPU 최대 클럭을 1GHz로 낮춤, 60C 이하로 식으면 최대 2GHz로 복구.
- 리부팅보다 클럭 제한을 우선 적용. 리부팅은 watchdog의 장애 복구 수단으로 유지.
- 새 helper: /usr/local/sbin/pi-thermal-clock-guard.sh.
- 새 systemd timer: pi-thermal-clock-guard.timer, 30초마다 실행, enabled/active.
- 현재 상태: temp 약 52.1C -> 
ormal, max=2000000, throttled= x0.
- 8080 대시보드에 Thermal guard 상태와 최근 로그 표시 추가.
- 의미: 70C 이상 과열 구간에서는 성능을 낮춰 안정성을 우선하고, 60C 이하로 내려오면 기존 2GHz 상한으로 정상화.

## 2026-07-27 15:06:22 +09:00ST - 라즈베리 사진 기반 가상 DVS raw 생성 추가
- 로컬 DVS 샘플 확인: events/*.npz는 x.npy, y.npy, 	.npy, p.npy 구조. x/y/t=float32, p=uint8.
- 로컬 CIS 이미지 확인: images/*.png, 1920x1080.  00000.png~ 00397.png는 DVS 이벤트와 1:1 매칭,  00398.png만 이벤트 없음.
- 라즈베리 합성 스크립트 /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 이제 라즈베리 사진 pair마다 실제 DVS raw 형태의 .npz 생성: /home/philip/synthetic_frames/{event_id}/virtual_dvs/{event_id}_pairXX.npz.
- 생성 포맷: 
pz:x(float32),y(float32),t(float32),p(uint8).
- 방식: 사진 간 grayscale delta + motion silhouette mask로 이벤트 좌표 생성, 밝기 증가/감소로 polarity p=1/0, chunk 시간은 20ms(20000us) 범위에 분산.
- grid 프레임은 이 .npz를 다시 읽어서 rasterize 후 사진 사이에 overlay. 즉 사진-raw DVS grid-사진 구조로 변경.
- 테스트 생성 성공: 20260727_150436, output frames 32, virtual DVS chunks 5개, 첫 chunk 이벤트 6428개.
- 8081 synthetic 페이지에 raw DVS 포맷과 chunk 정보를 표시하도록 수정.

## 2026-07-27 15:09:47 +09:00ST - 60프레임 합성 및 사람 감지 burst 간격 조정
- Synthetic DVS output frames를 32에서 60으로 변경.
- 테스트 생성 성공: 20260727_150741, output frames 60, grid distribution [11, 11, 11, 11, 10], virtual DVS chunks 5.
- 일반 카메라 캡처 timer는 원래대로 OnUnitActiveSec=3s, AccuracySec=1s로 복구.
- 사람 감지 burst 모드만 1.5배에 가깝게 늘림: BURST_FPS=10 -> 7, BURST_FRAMES=5 유지.
- 의미: 사람 감지 시 burst 간격은 약  .143s, 전체 burst 기간은 약  .714s. 기존 0.1초/0.5초보다 더 긴 움직임을 담아 DVS 보간에 활용.

## 2026-07-27 15:14:00 +09:00ST - 사진 사이 중간 프레임을 가상 DVS RAW 그리드로 변경
- 요청: 사진과 사진 사이에 사람/사진 보간 대신 가상의 DVS RAW 데이터가 들어가게 수정.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 기존: 사진 보간 프레임 위에 DVS 이벤트 heat overlay.
- 변경: 중간 프레임은 어두운 grid 배경 + 가상 DVS raw event만 표시. 원본 사진/사람 이미지는 섞지 않음.
- 시퀀스 구조: photo -> virtual DVS raw grid frames -> photo -> virtual DVS raw grid frames -> photo.
- .npz raw 생성은 유지: x/y/t=float32, p=uint8, 20ms chunk.
- DVS grid는 .npz를 시간 window별로 다시 읽어 polarity event를 표시.
- 테스트 생성 성공: 20260727_151308, mode=photo_virtual_dvs_raw_interleave, output frames=60, DVS chunks=5.
- 8081 synthetic web service 재시작 완료.

## 2026-07-27 15:18:42 +09:00ST - 사람 이동 동선 보강형 DVS 합성으로 수정
- 의도 정정: 사진 사이에 단순 DVS 화면을 넣는 것이 아니라, 사람이 지나가는 동선에서 캡처 간격 때문에 빠진 부분을 DVS raw event로 보강해야 함.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 가상 DVS raw .npz의 시간값을 사람 motion silhouette의 이동 경로를 따라 분산하도록 변경.
- 중간 프레임은 흐린 장면 배경 + grid + 해당 시간 window의 DVS polarity event를 표시. 실제 사람 사진을 보간해서 넣지 않고, 빠진 이동 경로를 DVS 이벤트로 표현.
- 새 mode: photo_virtual_dvs_missing_path_fusion.
- 테스트 생성 성공: 20260727_151728, output frames=60, grid distribution=[11,11,11,11,10], DVS chunks=5, event pixels=24176.
- 8081 synthetic web service 재시작 완료.

## 2026-07-27 15:23:17 +09:00ST - 원본 사람 사진 유지 + 사진 사이 DVS 사람 shape 보강 강화
- 의도 정정: 원본 사람 사진은 그대로 나오고, 캡처 간격 때문에 빠진 사람의 위치/동선을 DVS shape로 보강해야 함.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 원본 photo 프레임의 라벨/박스 제거. 실제 사진 프레임은 원본 그대로 저장.
- 중간 프레임에는 dense intermediate person shape를 생성해 가상 DVS polarity event로 표시.
- 사람 shape 보강 방식: motion silhouette를 close/dilate/convex hull로 두껍게 만들고, 사진 A/B 사이 예상 위치로 이동시킨 mask를 시간 window별 DVS 이벤트로 표시.
- 새 mode: photo_virtual_dvs_dense_person_shape_fusion.
- 테스트 생성 성공: 20260727_152229, output frames=60, DVS chunks=5, first frame=photo, second frame=DVS 보강.
- 8081 synthetic web service 재시작 완료.

## 2026-07-27 15:25:38 +09:00ST - 사람 사진 위 오버레이 제거, 동선 사이 DVS만 표시
- 의도 재정리: 원본 사람 사진은 그대로 보여주고, 사진과 사진 사이의 빠진 사람 위치/동선에만 DVS 보강 프레임을 삽입.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 중간 프레임 생성 시 before/after 사진의 사람 영역을 inpaint/blur로 제거한 context를 만든 뒤, 예상 중간 위치의 DVS person shape만 표시.
- DVS heat를 예상 person path mask 내부로 제한해 실제 사람 사진 위에 겹쳐 보이는 현상을 줄임.
- 새 mode: photo_clean_people_dvs_path_only_fusion.
- 테스트 생성 성공: 20260727_152449, output frames=60, distribution=[11,11,11,11,10], DVS chunks=5.
- 프레임 수 의미: 원본 사진 N장 사이에 DVS 보강 프레임을 추가하면 총 프레임은 증가. 현재는 6장 원본 사진 기준 총 60프레임으로, 사진 사이마다 약 10~11장의 DVS 보강 프레임이 들어감.

## 2026-07-27 15:30:55 +09:00ST - DVS가 실제 사람 위에 오버레이되지 않도록 강화
- 문제: 중간 프레임에서 before/after 사진 blend 때문에 실제 사람 잔상 위에 DVS가 겹쳐 보임.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 중간 프레임 생성 시 before/after 사람 위치와 예상 경로 전체를 큰 mask로 지우고(inpaint), 그 깨끗한 gap 영역 안에만 DVS heat를 표시.
- DVS heat도 erased_people/person path mask 내부로 constrain하여 실제 사람 사진 영역 위에 그려지는 것을 방지.
- 새 mode: photo_clean_gap_only_dvs_person_path_fusion.
- 테스트 생성 성공: 20260727_152806, output frames=60, DVS chunks=5, first frame=원본 photo, second frame=DVS gap 보강.
- 8081 synthetic web service 재시작 완료.

## 2026-07-27 16:11:26 +09:00ST - 참고 이미지 기준 DVS event plane 방식으로 변경
- 사용자가 제공한 예시: RGB 프레임은 원본 영상처럼 유지, DVS는 흰 배경에 red/blue event 점으로 별도 표시.
- /home/philip/bin/synthesize_virtual_dvs_grid.py 수정.
- 중간 DVS 프레임에서 scene/background overlay 제거. 이제 흰 배경 DVS plane 위에 event만 표시.
- 시퀀스: RGB photo -> white DVS event plane frames -> RGB photo.
- 새 mode: 
gb_photo_white_plane_cooperative_dvs_events.
- shape mask: white_dvs_plane_gap_events_between_rgb_people.
- 테스트 생성 성공: 20260727_155540, output frames=60, DVS chunks=5, event pixels=281689.
- 8081 synthetic web service 재시작 완료.

## 2026-07-27 16:24:51 - DVS 아키텍처 기획서 업데이트 및 메일 발송

- 문서 업데이트: C:\OSDA\회의록 정리\DVS_architecture_person_path_fusion.md
- 추가 내용: DVS 상시 이벤트 저장 구조, 이벤트 발생 시 RGB/CIS 동시 캡처, 실시간 합성 저장 파이프라인, 필요 성능/TOPS 산정, 경량화 전략, 2시간 단위 메일 배치 정책.
- 성능 기준 요약: Raspberry Pi 5 단독은 현재 파이프라인과 경량 합성 검증용으로 사용하고, 실시간 YOLO + DVS 이벤트 처리 + 영상 합성까지 안정 운용하려면 최소 10~15 TOPS급 가속기, 권장 20~40 TOPS급 보드/가속기, LLM/VLM 기반 의미 분석까지 포함하면 60 TOPS 이상 또는 별도 서버 오프로딩을 검토한다.
- Outlook 메일 발송: philip.de.kim@gmail.com 으로 발송 완료.


## 2026-07-27 16:37:27 - DVS 기획서 Qualcomm IQ8 최종 플랫폼 반영

- 수정 문서: `C:\OSDA\회의록 정리\DVS_architecture_person_path_fusion.md`
- Word 변환본: `C:\OSDA\회의록 정리\DVS_architecture_person_path_fusion_Qualcomm_IQ8.docx`
- 최종 플랫폼을 Qualcomm Dragonwing IQ8 Series, 우선 후보 IQ-8275 / QCS8275로 명시.
- 반영 근거: 40 TOPS급 엣지 AI 성능, 8코어 Kryo CPU, Adreno GPU, Hexagon DSP/NPU 계열, Ubuntu/Yocto 지원, 산업용 비전/로봇/엣지 AI 용도, Qualcomm AI Hub 기반 모델 최적화/프로파일링 가능성.


## 2026-07-27 16:43:53 - Qualcomm IQ8 PDF 확인 및 VENTUNO Q 기획서 반영

- 확인 PDF: `C:\Users\admin\OneDrive\문서\카카오톡 받은 파일\퀄컴IQ8 Arduino_VENTUNO_Q_사양_및_확보전략.pdf`
- 확인 결과: Arduino VENTUNO Q는 Qualcomm Dragonwing IQ8 IQ-8275, Hexagon 40 dense TOPS, Spectra 692 ISP, STM32H5F5 MCU, 16GB LPDDR5, 64GB eMMC, M.2 NVMe Gen.4, 3x MIPI CSI, 2.5GbE, Wi-Fi 6, CAN-FD, Ubuntu/Debian, Arduino Core on Zephyr를 지원하는 dual-brain edge AI/robotics 플랫폼.
- 기획서 반영: 최종 플랫폼을 Arduino VENTUNO Q / Qualcomm Dragonwing IQ8로 구체화하고, DVS 시스템 적합성 및 확보 전략을 추가.
- 수정 파일: `C:\OSDA\회의록 정리\DVS_architecture_person_path_fusion.md`
- Word 변환본: `C:\OSDA\회의록 정리\DVS_architecture_person_path_fusion_Qualcomm_IQ8.docx`


## 2026-07-28 07:33:40 - DVS 낙상 감지 별도 기획서 작성

- 작성 문서: `C:\OSDA\회의록 정리\DVS_only_fall_detection_vs_RGB_fusion_plan.md`
- 내용: DVS-only 낙상 감지 방안과 DVS + RGB/CIS 이미지센서 융합 방안을 비교.
- 결론: LLM은 raw DVS 직접 처리보다 event model/rule 결과를 설명하고 오탐을 줄이는 보조 reasoner로 사용하는 것이 현실적. 최종 구조는 `DVS trigger + RGB/CIS confirmation + LLM explanation` 권장.

## 2026-07-28 07:47:54 - DVS 낙상 감지 기획서 TOPS 산정 공식 추가

- 수정 문서: C:\OSDA\회의록 정리\DVS_only_fall_detection_vs_RGB_fusion_plan.md
- 추가 내용: Required_TOPS = Safety_Margin * (AI_TOPS + DVS_TOPS + Fusion_TOPS + Encode_TOPS) / Effective_Utilization 산정식 추가.
- 세부 항목: 모델 추론 연산량, DVS 이벤트율, 이벤트당 연산량, 합성 프레임 해상도/FPS, 인코딩 부하, NPU/GPU/DSP 실효 사용률, 안전 여유계수 반영.
- 결론: DVS-only는 이론적으로 1 TOPS 이하도 가능하지만 제품 기준 5~10 TOPS, DVS+RGB/CIS는 10~20 TOPS 이상, 실시간 합성/저장/웹까지 안정 운용은 20~40 TOPS 권장.

## 2026-07-28 09:02:29 - DVS 낙상 감지 기획서 HTML 웹서비스 추가

- 원본 Markdown: C:\OSDA\회의록 정리\DVS_only_fall_detection_vs_RGB_fusion_plan.md
- 라즈베리파이 HTML 배치: /home/philip/fall_detection_plan.html
- 웹 링크: http://192.168.0.100:8080/fall-plan
- 8080 메인 웹서비스 camera_gallery_server.py에 /fall-plan 라우팅과 상단 메뉴 Fall Plan 링크 추가.
- 서비스 재시작 확인: camera-snapshots-web.service active, /fall-plan HTTP 200 확인.

## 2026-07-28 10:56:17 - GitHub 백업 완료

- GitHub repo: https://github.com/philipdekim-OnD01/DVS.OnDevice.AI
- 로컬 백업 저장소: C:\Users\admin\dvs-rpi-backup-v3
- 브랜치: main
- 커밋: 5b8a2cfeaa3d57455495deb313efdaae76c3c2c9 (Initial Raspberry Pi DVS backup)
- 포함 범위: 라즈베리파이 /home/philip/bin, user systemd 서비스/타이머, camera-snapshots state/log/queue, camera/person snapshots, synthetic frames/virtual DVS chunks, 관련 Markdown/Word 문서 및 회의록.
- 참고: 현재 백업은 이미지/합성 프레임까지 포함한 snapshot 백업이며 Git pack 크기는 약 567MB. 장기 이력 관리는 Git LFS 또는 object storage 검토 필요.
