# DVS 기반 사람 동선 보강 합성 아키텍처

작성일: 2026-07-27
최종 수정: 2026-07-27
최종 목표 플랫폼: Arduino VENTUNO Q, Qualcomm Dragonwing IQ8 Series IQ-8275 / QCS8275
대상 시스템: Raspberry Pi 카메라 감시 PoC, 사람 감지, 가상/실제 DVS 이벤트 합성 시스템

## 1. 목표

RGB/CIS 카메라는 사람의 실제 사진을 일정 간격으로 저장하고, DVS 센서는 그 사이의 움직임 이벤트를 지속적으로 기록한다. 최종 목표는 RGB 사진 사이에서 빠진 사람의 이동 동선을 DVS 이벤트로 보강하여 `RGB photo -> DVS event plane -> RGB photo` 구조의 영상을 실시간 생성, 저장, 표시하는 것이다.

핵심 원칙:

- 원본 사람 사진은 그대로 보여준다.
- RGB 사진 위에 DVS를 덮어씌우지 않는다.
- 사진과 사진 사이의 빠진 사람 위치와 동선만 DVS 이벤트로 표현한다.
- DVS 이벤트는 `x/y/t/p` raw event stream으로 저장한다.
- 실제 DVS 센서가 붙으면 현재 가상 DVS 생성부만 실제 event ingest로 교체한다.
- 최종 양산/실증 플랫폼은 Raspberry Pi가 아니라 Qualcomm Dragonwing IQ8 Series로 전환한다.

## 2. 현재 Raspberry Pi 구현 상태

라즈베리파이는 PoC와 알고리즘 검증용으로 유지한다.

- 일반 스냅샷: `/home/philip/camera_snapshots`
- 사람 감지 스냅샷: `/home/philip/person_snapshots`
- 합성 결과: `/home/philip/synthetic_frames`
- 합성 스크립트: `/home/philip/bin/synthesize_virtual_dvs_grid.py`
- 메인 대시보드: `http://192.168.0.100:8080/`
- Synthetic DVS 페이지: `http://192.168.0.100:8081/`
- 일반 캡처 주기: 3초
- 사람 감지 burst: 약 0.1~0.15초 단위 고속 캡처
- 합성 영상: 60프레임, RGB 원본 프레임과 DVS event plane 교차 구성
- DVS raw chunk: `npz:x(float32), y(float32), t(float32), p(uint8)`

현재 Pi는 카메라, YOLO, 합성, 웹 서버, 로그/그래프까지 모두 담당하고 있어 안정성 한계가 있다. 따라서 Pi는 개발/실험용으로 두고, 최종 플랫폼은 산업용 엣지 AI SoC로 전환한다.

## 3. 최종 플랫폼: Qualcomm Dragonwing IQ8 Series

### 3.1Arduino VENTUNO Q 사양

- MPU: Qualcomm Dragonwing IQ8, IQ-8275
- CPU: 8-core Qualcomm Kryo
- GPU: Qualcomm Adreno 623
- NPU: Qualcomm Hexagon, 40 dense TOPS
- ISP: Qualcomm Spectra 692 ISP
- MCU: STM32H5F5, Arm Cortex-M33 250MHz, 4MB Flash, 1.5MB RAM
- RAM: 16GB LPDDR5
- 기본 저장장치: 64GB eMMC
- 확장 저장장치: M.2 NVMe Gen.4 SSD
- 네트워크: Wi-Fi 6, Bluetooth 5.3, 2.5GbE RJ45
- 카메라: USB camera, 3x MIPI CSI connectors, JMEDIA header의 2x MIPI CSI mux 구성
- 디스플레이: HDMI, USB-C DisplayPort Alt Mode, MIPI DSI
- 산업용 I/O: CAN-FD, PWM, GPIO, deterministic industrial I/O
- OS/개발환경: Ubuntu 또는 Debian, Arduino Core on Zephyr, ROS 2, Docker, SSH, Python, Arduino Sketch, Qualcomm AI Hub, Edge Impulse
- 크기: 160 x 100 x 25.8mm

### 3.2 DVS 시스템 관점의 적합성

VENTUNO Q는 단순 SBC가 아니라 AI brain과 action brain이 분리된 구조다. DVS 시스템에서는 이 구조가 다음처럼 매핑된다.

- Qualcomm IQ8 MPU: YOLO/person detection, DVS event filtering, RGB-DVS 합성, 웹 서버, 저장 관리
- Hexagon NPU: 60% 이상 confidence 조건의 사람 감지 모델 추론
- Spectra ISP 및 MIPI CSI: RGB/CIS 카메라 입력과 향후 DVS 센서 입력 확장
- STM32H5F5 MCU: 외부 트리거, 센서 동기화, 실시간 GPIO/CAN-FD 제어, 장애 상태 신호 처리
- NVMe/eMMC: DVS event burst, 사람 이벤트 영상, synthetic video의 안정 저장
- 2.5GbE/Wi-Fi 6: 원격 모니터링, 대용량 로그/영상 전송, 대시보드 운용

### 3.3 확보 전략
1. Arduino VENTUNO Q 공식 페이지 waitlist 등록을 유지한다.
2. 출시 알림 수신 후 Arduino Store, DigiKey, Mouser, RS, Farnell 계열 공식 리셀러에서 견적을 확인한다.
 이 보드는 Qualcomm Dragonwing IQ8 Series IQ-8275 / QCS8275와 STM32H5F5 MCU를 결합한 dual-brain 구조이므로, DVS + RGB/CIS + 사람 인식 + 실시간 합성 + 로봇/산업용 I/O 확장까지 하나의 보드에서 검증하기에 가장 적합하다.

공식 자료 기준 주요 특성:
- AI 성능: IQ8 Series는 40 TOPS급 엣지 AI 성능 라인업으로 제시된다.
- CPU: Qualcomm Kryo Gen 6, 8코어, 최대 2.35GHz.
- GPU: Qualcomm Adreno 623.
- DSP/NPU 계열: Qualcomm Hexagon V66 및 V73.
- 메모리: LPDDR5x 지원.
- OS: Linux Yocto 및 Ubuntu 지원.
- 디스플레이/주변장치: 복수 디스플레이, DSI, DisplayPort, I2C, UART, SPI 등 산업용 인터페이스 지원.
- 적용 분야: Industrial Vision, Robotics, AMR, Drones, Industrial Edge AI.
- 장기 공급성: Dragonwing IQ8은 장기 수명주기 지원 대상으로 소개된다.

## 4. 왜 Qualcomm IQ8인가

### 4.1 현재 요구 성능과 맞는 40 TOPS급 플랫폼

이 시스템은 단순 카메라 저장 장치가 아니다. 동시에 다음 작업이 필요하다.

- DVS 이벤트의 지속 수집 및 timestamp 보존
- 이벤트 발생 시 RGB/CIS 센서 동기 캡처
- 사람 감지 모델 추론
- 사람 ROI 기반 이벤트 필터링
- RGB 프레임 사이의 누락 동선 추정
- DVS event plane 렌더링
- 합성 영상 생성 및 저장
- 웹 대시보드 표시
- 온도, 전압, 클럭, watchdog 모니터링

Raspberry Pi 5 단독 CPU/GPU로는 PoC는 가능하지만 장시간 안정 운용과 실시간 합성까지 한 장치에서 처리하기에는 여유가 작다. IQ8의 40 TOPS급 NPU/DSP/GPU/CPU 이기종 구조는 YOLO 계열 사람 감지, optical/event feature 처리, 영상 합성을 역할별로 분리하기에 적합하다.

### 4.2 카메라와 엣지 비전에 맞는 SoC 구조

DVS와 RGB/CIS를 함께 쓰려면 단순 TOPS보다 센서 입력, timestamp 동기화, ISP/영상 처리, 저지연 메모리 이동이 중요하다. Qualcomm IQ8은 산업용 비전과 엣지 AI 용도로 제시되는 플랫폼이며, CPU, NPU, GPU, DSP, MCU 성격의 이기종 코어를 활용해 다음 구조를 만들 수 있다.

- CPU: 시스템 제어, 파일 저장, 웹/API, watchdog
- NPU/Hexagon: YOLO/person detection, ROI feature extraction
- DSP/Hexagon: DVS event filtering, timestamp windowing, polarity map 생성
- GPU/Adreno: event plane 렌더링, 영상 합성, 웹 미리보기용 인코딩 보조
- MCU/저전력 코어: 센서 상태 감시, 이벤트 트리거, 장애 감지

### 4.3 Qualcomm AI Hub 활용 가능

Qualcomm AI Hub는 모델 최적화, 온디바이스 검증, 프로파일링, 배포 워크플로우를 제공한다. PyTorch, ONNX, TensorFlow Lite 모델을 Qualcomm AI Engine Direct, TensorFlow Lite, ONNX Runtime 등으로 변환/최적화하고 실제 장치에서 latency, memory, compute unit utilization을 확인할 수 있다.

따라서 현재 Pi에서 사용하는 YOLO 계열 모델을 다음 단계로 이전할 때 다음 절차를 적용한다.

1. YOLO nano/small 모델을 ONNX 또는 TFLite로 정리한다.
2. Qualcomm AI Hub Workbench에서 IQ8 계열 타깃으로 compile/profile한다.
3. INT8 quantization 적용 후 정확도와 latency를 검증한다.
4. 사람 감지 임계값 60% 이상 조건을 유지한다.
5. NPU/Hexagon 실행 모델과 CPU fallback 모델을 모두 준비한다.

## 5. DVS Raw 저장 및 이벤트 정책

DVS는 이벤트가 없으면 저장량이 매우 작고, 움직임이 발생하면 이벤트가 고속으로 증가한다. 따라서 모든 시간을 영상 프레임으로 저장하지 않고 sparse event stream을 chunk 단위로 저장한다.

권장 저장 정책:

- 평상시: 20ms 단위 sparse event chunk 저장
- 사람/움직임 이벤트 발생 시: 5~10ms 단위까지 세분화 가능
- 저장 포맷: `npz:x(float32), y(float32), t(float32), p(uint8)`
- 장기 저장은 압축 `.npz`
- 실시간 처리 전용은 ring buffer 또는 memory mapped event buffer
- 이벤트 chunk에는 센서 timestamp와 시스템 monotonic timestamp를 함께 기록
- RGB/CIS 프레임에는 동일 시간축의 timestamp를 기록

## 6. RGB-DVS 합성 방식

합성 결과는 RGB 사진 위에 DVS를 덮는 방식이 아니다. 사람 사진은 원본으로 표시하고, 사진과 사진 사이에 존재했을 것으로 추정되는 이동 구간만 DVS event plane으로 보강한다.

프레임 구성:

```text
RGB frame A
-> DVS event plane A+1
-> DVS event plane A+2
-> DVS event plane A+3
-> RGB frame B
-> DVS event plane B+1
-> DVS event plane B+2
-> DVS event plane B+3
-> RGB frame C
```

DVS event plane 표현:

- 배경은 흰색 또는 저채도 단색
- positive polarity는 빨강 계열
- negative polarity는 파랑 계열
- 이벤트는 사람 ROI와 이동 추정 경로 안에서만 생성/표시
- RGB 원본 프레임에는 DVS 오버레이 금지

실제 DVS 센서 장착 후에는 가상 DVS 생성부를 실제 event stream ingest로 교체하고, 현재의 합성/렌더링/웹 표시 구조는 유지한다.

## 7. 필요 성능 산정

### 7.1 처리 부하 구성

실시간 운용 시 주요 부하는 다음과 같다.

- RGB 카메라 입력: 1080p 기준 캡처 및 JPEG/비디오 인코딩
- 사람 감지: YOLO nano/small급 모델 5~15fps 또는 이벤트 발생 시 burst 추론
- DVS 이벤트 처리: 초당 수만~수십만 이벤트 필터링 및 chunk 저장
- ROI 추적: 사람 bounding box 사이 보간, 이동 경로 예측
- DVS plane 렌더링: 20~60fps 표시용 synthetic frame 생성
- 저장/웹: 최근 이벤트 영상, 썸네일, 로그, 상태 그래프 제공

### 7.2 TOPS 기준

권장 성능 기준:

- Raspberry Pi 5 단독: PoC, 저속 검증, 웹 대시보드, 단순 합성 가능. 안정적 실시간 제품용으로는 부족.
- 10~15 TOPS: 경량 YOLO + DVS 필터링 + 저해상도 합성의 최소선.
- 20~40 TOPS: 실시간 사람 감지, DVS ROI 처리, 합성 영상 저장까지 한 장치에서 안정 운용 가능한 권장 범위.
- 40 TOPS급 Qualcomm IQ8: 본 시스템의 최종 엣지 플랫폼으로 적합한 1차 후보.
- 60 TOPS 이상: LLM/VLM 기반 장면 이해, 복수 카메라, 고해상도 다중 스트림, 더 복잡한 행동 분석까지 로컬에서 처리할 때 필요.

### 7.3 메모리/스토리지 기준

권장 최소 구성:

- RAM: 8GB 이상 권장. 이벤트 ring buffer, 모델 로딩, 영상 합성을 동시에 수행하기 위함.
- 스토리지: 산업용 eMMC/UFS 또는 고내구성 NVMe/SD. 이벤트 burst와 영상 저장이 반복되므로 일반 SD 단독은 비권장.
- 저장 정책: 디스크 사용량 70% 이상이면 오래된 일반 사진부터 삭제하고, 사람 이벤트/합성 결과는 별도 retention 정책 적용.

## 8. 경량화 전략

### 8.1 센서/이벤트 단계

- 전체 프레임을 처리하지 않고 DVS 이벤트만 sparse하게 저장한다.
- 이벤트가 적을 때는 chunk metadata 중심으로 저장한다.
- 사람 ROI 밖의 이벤트는 낮은 우선순위로 처리하거나 폐기한다.
- polarity, timestamp, 좌표를 구조화된 배열로 유지해 문자열 로그 변환을 피한다.
- 최근 1~2분은 RAM ring buffer, 장기 보관은 압축 파일로 분리한다.

### 8.2 인식 모델 단계

- YOLO nano/small 계열을 기본으로 사용한다.
- confidence 60% 이상일 때만 사람 이벤트로 확정한다.
- INT8 quantization을 기본 적용한다.
- 매 프레임 추론하지 않고 이벤트 발생/움직임 증가 시 burst 추론한다.
- 동일 ROI가 연속될 때는 tracking으로 보완하고 추론 빈도를 줄인다.

### 8.3 합성 단계

- RGB 원본은 key frame으로만 사용한다.
- 중간 프레임은 RGB 보간이 아니라 DVS event plane으로 표현한다.
- 렌더링 해상도는 표시용과 저장용을 분리한다.
- 웹 미리보기는 낮은 bitrate/해상도, 원본 보관은 이벤트 단위로 유지한다.
- 합성 영상은 이벤트 발생 1회당 1개만 생성하고, 2시간 단위 메일 배치에 포함한다.

### 8.4 시스템 안정화

- 카메라 캡처, YOLO 추론, DVS 합성, 웹 서버를 별도 서비스로 분리한다.
- 각 서비스는 systemd watchdog 및 root watchdog에서 상태 확인한다.
- 캡처가 180초 이상 멈추면 서비스 재시작, 연속 실패 시 재부팅한다.
- 온도 70도 이상이면 클럭을 낮추고, 60도 이하에서 정상화한다.
- 전압, ARM clock, throttled 상태를 캡처 주기와 동기화해 기록한다.

## 9. 최종 시스템 아키텍처

```text
DVS sensor
    -> event ingest
    -> event chunk writer
    -> ring buffer
    -> ROI/event activity map

RGB/CIS camera
    -> periodic capture
    -> event-triggered burst capture
    -> timestamped key frame archive

AI inference
    -> Qualcomm NPU/Hexagon YOLO person detection
    -> confidence >= 60%
    -> ROI tracking

Fusion
    -> align RGB timestamp and DVS timestamp
    -> estimate missing path between person frames
    -> render DVS event plane only between RGB frames
    -> generate synthetic 20~60 frame video

Storage/Web
    -> snapshots
    -> person events
    -> DVS raw chunks
    -> synthetic videos
    -> dashboard
    -> 2-hour email batch

Stability
    -> service split
    -> watchdog
    -> thermal/voltage/clock graph
    -> retention policy
```

## 10. 개발 단계 제안

1. Raspberry Pi에서 현재 가상 DVS 합성 구조를 안정화한다.
2. 실제 DVS 센서 입력 포맷을 `x/y/t/p` chunk로 맞춘다.
3. RGB/CIS 프레임과 DVS timestamp alignment를 구현한다.
4. YOLO 모델을 Qualcomm AI Hub에서 IQ8 타깃으로 compile/profile한다.
5. INT8 모델로 정확도와 latency를 검증한다.
6. Pi의 서비스 구조를 Qualcomm Ubuntu/Yocto 환경으로 이식한다.
7. DVS ingest, person detection, fusion, web, mail batcher를 독립 서비스로 배치한다.
8. 열/전압/클럭/디스크 retention 정책을 제품 운용 기준으로 고정한다.

## 11. 참고 자료

- Arduino VENTUNO Q 공식 제품 페이지: https://www.arduino.cc/product-ventuno-q
- Qualcomm Arduino VENTUNO Q 발표자료: https://www.qualcomm.com/news/releases/2026/03/arduino-announces-arduino-ventuno-q----powered-by-qualcomm-drago
- Qualcomm Dragonwing IQ8 Series 공식 제품 페이지: https://www.qualcomm.com/internet-of-things/products/iq8-series
- Qualcomm AI Hub 공식 문서: https://app.aihub.qualcomm.com/docs/index.html
- Qualcomm AI Hub Workbench 개요: https://workbench.aihub.qualcomm.com/docs/hub/howitworks.html
- Qualcomm AI Hub 시작 가이드: https://aihub.qualcomm.com/get-started
- Stereo DVS 참고 논문: Dynamic stereo vision system for real-time tracking
- Cooperative stereo DVS 참고 논문: Cooperative method for stereo vision with dynamic vision sensors

## 12. 결론

Raspberry Pi는 현재 시스템을 빠르게 검증하기 위한 PoC 장치로 적합하다. 그러나 DVS 이벤트 지속 저장, RGB/CIS 동기 캡처, 사람 인식, 동선 보강 합성, 영상 저장, 웹 표시를 동시에 안정적으로 수행하려면 최종 플랫폼은 20~40 TOPS급 산업용 엣지 AI SoC가 필요하다.

Qualcomm Dragonwing IQ8 Series는 40 TOPS급 AI 성능, 산업용 비전/로봇/엣지 AI 지향성, Ubuntu/Yocto 지원, AI Hub 기반 모델 최적화/프로파일링 흐름을 제공하므로 본 시스템의 최종 플랫폼 후보로 가장 적합하다.

---

## 2026-07-28 추가 기록: CIS-DVS Event Synthesis 실험

### 오늘의 목표

CIS 이미지와 DVS 이벤트 데이터를 이용해, CIS 프레임 사이의 비어 있는 timestamp에 해당하는 중간 이미지를 이벤트 데이터로 생성하는 5초 데모 영상을 만들고 Raspberry Pi 실시간 가능성을 평가했다.

### 로컬 데이터 구조

```text
C:\temp\images
C:\temp\events
```

확인된 구조:

```text
images/
  000000.png ... 000398.png
  timestamp.txt

events/
  000000.npz ... 000397.npz
```

확인 결과:

```text
이미지 수: 399
이벤트 파일 수: 398
이미지 해상도: 1920 x 1080
CIS timestamp 간격: 약 20000 us
CIS FPS: 약 50 FPS
이벤트 NPZ 키: x, y, t, p
```

해석:

```text
events/000000.npz = images/000000.png 와 images/000001.png 사이 이벤트
events/000001.npz = images/000001.png 와 images/000002.png 사이 이벤트
...
```

### 이벤트 데이터 특성

5초 구간, 250개 interval 기준:

```text
총 이벤트 수: 20,325,269
평균 이벤트율: 약 4.1M events/sec
20ms interval 평균: 81,301 events
20ms interval median: 20,288 events
20ms interval max: 760,950 events
순간 피크 이벤트율: 약 38M events/sec
```

### 합성 방식

단순히 CIS 프레임 위에 이벤트를 overlay하는 것이 아니라, 출력 timestamp마다 이벤트를 누적해 중간 이미지를 생성하는 방식으로 구현했다.

기본 모델:

```text
log I(t) = log I(t0) + C * accumulated_polarity_events
```

실제 구현 흐름:

```text
1. 출력 FPS 기준으로 target timestamp 생성
2. target timestamp가 속한 CIS interval 찾기
3. 해당 interval의 events/NNNNNN.npz 로드
4. t <= target timestamp 이벤트만 누적
5. polarity p=1은 양의 밝기 변화, p=0은 음의 밝기 변화로 반영
6. CIS base frame 위에 이벤트 기반 intensity update 적용
7. 다음 CIS frame을 약하게 blend해 drift 완화
8. red/blue event overlay를 추가해 DVS cue를 시각화
```

### 생성된 로컬 5초 샘플

결과 파일:

```text
C:\temp\event_synth_5s.mp4
```

검증 결과:

```text
길이: 5초
프레임: 300
FPS: 60
해상도: 960 x 540
파일 크기: 약 30 MB
첫 프레임 mean/std 확인 완료
```

관련 스크립트:

```text
C:\Users\admin\make_event_synth_5s.py
C:\Users\admin\prepare_raspi_event_demo.py
C:\Users\admin\event_synthesis_demo_pi.py
C:\Users\admin\raspi_exec.py
C:\Users\admin\raspi_sync.py
```

### Raspberry Pi 서비스 확인

Raspberry Pi 정보:

```text
Hostname: PhilipRP5
OS: Linux 6.12.47+rpt-rpi-2712, aarch64
```

실행 중인 주요 서비스:

```text
/home/philip/bin/camera_gallery_server.py       port 8080
/home/philip/bin/synthetic_grid_server.py       port 8081
/home/philip/bin/person_synthesis_worker.py
/home/philip/bin/person_yolo_worker.py
```

웹서비스 후보:

```text
http://192.168.0.100:8080/
http://192.168.0.100:8081/
```

8081 synthetic grid 서버가 기존 데모 성격과 맞아, Event Synthesis 페이지를 붙이기에 가장 적합하다.

### Pi용 테스트 데이터

Pi에 업로드한 5초 샘플:

```text
/home/philip/event_synthesis_demo/data
```

구성:

```text
images: 251장
 events: 250개
duration: 5초
image format: 960px width JPEG
event format: 원본 NPZ 유지
```

### Raspberry Pi 벤치마크 결과

첫 테스트 결과:

```text
resolution: 960x540
target_output_fps: 60
frames_written: 300
source_seconds: 5.0
wall_seconds: 16.89
achieved_fps: 17.76
realtime_factor: 0.296
events_processed: 6,005,003
events_per_second_processed: 355,526
mean_frame_ms: 56.29
p95_frame_ms: 105.89
slowest_frame_ms: 164.23
cpu_percent_during_run: 50.1%
temperature_before: 64.45 C
temperature_after: 66.65 C
```

해석:

```text
960x540 @ 60FPS는 Raspberry Pi 5 CPU/Python 구현에서 실시간 불가
현재 속도는 목표 60FPS 대비 약 0.296x realtime
실시간 60FPS에는 약 3.4배 개선 필요
```

추가로 발견한 수정 사항:

```text
원본 이벤트 좌표는 1920x1080 기준
다운스케일 출력에서는 x, y 좌표도 해상도 비율에 맞춰 스케일링해야 함
```

좌표 스케일링 수정은 로컬 스크립트에 반영했으나, 사용자가 성능 공식 설명을 요청하면서 추가 벤치마크는 중단했다.

### 1000프레임 실시간 성능 공식

1000프레임을 실시간으로 만들기 위한 기본 조건:

```text
T_process <= T_video
```

1000프레임이 D초짜리 영상이면 필요한 FPS:

```text
required_fps = 1000 / D
```

예:

```text
1000 frames / 5 sec = 200 FPS 필요
1000 frames / 1 sec = 1000 FPS 필요
```

필요 연산량 근사:

```text
OPS = Fout * (W * H * Cpix) + Esec * Cevent
```

변수:

```text
Fout   = 출력 FPS
W,H    = 출력 해상도
Cpix   = 픽셀당 연산 수
Esec   = 초당 이벤트 수
Cevent = 이벤트 하나당 연산 수
```

TOPS 변환:

```text
TOPS_required = OPS / 1e12 / efficiency
```

실제 하드웨어 효율:

```text
CPU/메모리 기반 이벤트 누적 처리: efficiency 약 0.05 ~ 0.3로 보수 추정
```

네 데이터 기준, 960x540에서 1000FPS 목표:

```text
W * H = 518,400 pixels
Cpix ≈ 50 ops/pixel
Cevent ≈ 20~50 ops/event
Esec ≈ 4.1M events/sec

pixel_ops = 1000 * 518,400 * 50
          ≈ 25.9 GOPS

event_ops = 4,100,000 * 50
          ≈ 0.2 GOPS

total ≈ 26.1 GOPS
theoretical ≈ 0.026 TOPS
realistic with 10% efficiency ≈ 0.26 TOPS effective
```

주의점:

```text
이 작업의 병목은 딥러닝 TOPS가 아니라 메모리 대역폭, random scatter write, 이미지 디코딩, 비디오 인코딩, Python overhead임
```

Raspberry Pi 5 기준 추정:

```text
960x540 @ 60FPS: 현재 Python 구현으로 실시간 불가
480x270 @ 60FPS: 최적화하면 가능성 있음
320x180 @ 200FPS: C++/NEON 최적화 시 가능성 있음
960x540 @ 200FPS: 어려움
960x540 @ 1000FPS: 불가능에 가까움
```

### 다음 작업

```text
1. Pi에서 좌표 스케일링 수정 버전 재벤치마크
2. 480x270 @ 30FPS, 480x270 @ 60FPS, 320x180 @ 200FPS 테스트
3. 8081 웹서비스에 Event Synthesis 설명/데모 페이지 추가
4. 실시간 목표 시 Python 핵심 루프를 C++/OpenCV/NEON으로 이식
5. np.add.at 제거, binary event stream, tile accumulation, LUT 기반 contrast update 검토
```

---

## 2026-07-28 추가 기록: 고품질 보간 한계와 IQ8 적용 판단

### 결론

고품질 보간은 가능하지만, `1000 frames / 5s = 200 synthesis FPS` 목표에서는 전체 프레임 대형 neural interpolation을 그대로 실시간 처리하기 어렵다. IQ8은 Raspberry Pi보다 훨씬 적합한 후보지만, TimeLens-XL급 큰 모델을 그대로 200FPS 이상으로 돌리는 방식은 현실성이 낮다.

현실적인 구조는 다음과 같다.

```text
1. 경량 event accumulation으로 실시간 preview 생성
2. 작은 neural refinement model로 움직이는 ROI만 보정
3. 전체 프레임 고품질 보간은 저장 후처리 또는 낮은 FPS에서 수행
```

### 경량 합성과 고품질 보간의 차이

```text
경량 합성:
CIS frame + DVS polarity accumulation
-> 빠름
-> 실시간 가능성 높음
-> 품질 제한 있음

고품질 보간:
CIS frame pair + event voxel + neural network
-> 품질 좋음
-> 연산량 큼
-> latency, 메모리, 모델 변환 이슈 있음
```

현재 웹 데모는 고품질 딥러닝 보간이 아니라, 온디바이스 실시간 가능성을 확인하기 위한 lightweight event-based reconstruction이다.

### 필요한 synthesis FPS

여기서 FPS는 playback FPS가 아니라, 온디바이스가 실제 시간 1초 동안 생성하는 synthesis FPS다.

```text
required_synthesis_fps = output_frames / video_seconds
```

예:

```text
1000 frames / 5s = 200 synthesis FPS
2000 frames / 5s = 400 synthesis FPS
1000 frames / 1s = 1000 synthesis FPS
```

고품질 보간 모델이 실시간이 되려면 다음 조건을 만족해야 한다.

```text
model_latency_ms <= 1000 / required_synthesis_fps
```

예:

```text
200 FPS 목표 -> frame당 5 ms 이하
400 FPS 목표 -> frame당 2.5 ms 이하
1000 FPS 목표 -> frame당 1 ms 이하
```

즉 `1000 frames / 5s` 목표에서는 다음 전체 작업이 5ms 안에 끝나야 한다.

```text
neural inference
+ event preprocessing
+ frame postprocessing
+ video encode handoff
<= 5 ms
```

### IQ8 적용 판단

Qualcomm Dragonwing IQ8 / IQ-8275는 Raspberry Pi보다 이 구조에 더 적합한 후보로 판단된다. 이유는 AI TOPS 하나 때문이 아니라, heterogeneous compute 구조 때문이다.

IQ8 계열의 장점:

```text
CPU
GPU
NPU
DSP
real-time MCU subsystem
multi-camera input
hardware video encode/decode
industrial temperature range
```

판단 공식:

```text
IQ8_is_suitable_for_realtime_fusion if:
  camera_input >= 2 synchronized streams
  and hardware_encoder_fps >= output_stream_fps
  and fusion_kernel_fps >= required_synthesis_fps
  and event_ingest_rate >= peak_event_rate
  and memory_bandwidth has enough headroom
```

1000프레임/5초 목표:

```text
required_synthesis_fps = 200
frame_budget = 5 ms
```

2000프레임/5초 목표:

```text
required_synthesis_fps = 400
frame_budget = 2.5 ms
```

### IQ8에서 가능한 수준의 현실적 판단

```text
320x180 ~ 480x270 경량 neural model:
  IQ8에서 가능성 있음

960x540 고품질 neural interpolation @ 200FPS:
  매우 어려움

1080p 고품질 neural interpolation @ 200FPS 이상:
  비현실적에 가까움

TimeLens-XL급 큰 모델 그대로 실시간:
  IQ8에서도 어려움

작은 모델 + distillation + INT8 quantization + ROI processing:
  가능성 있음
```

### 추천 제품 구조

```text
CIS camera -> ISP / DMA buffer
DVS sensor -> packed event stream ring buffer
Time sync -> trigger/PPS/GPIO timestamp
Fusion core -> C++/NEON/GPU/DSP tile accumulator
Optional AI -> small INT8 ROI refinement model on NPU
Output -> hardware H.264/H.265 encoder
Web -> preview stream + latest generated MP4
```

핵심 방향:

```text
전체 프레임 대형 AI 보간이 아니라,
경량 실시간 합성 + 선택적 AI refinement
```

### 최종 판단

IQ8은 이 프로젝트의 최종 후보로 적합하다. 다만 목표가 `1000 frames / 5s = 200FPS`이면, 고품질 보간은 전체 프레임 대형 모델이 아니라 작은 모델, ROI, INT8/NPU, GPU/DSP 전처리를 결합한 구조로 설계해야 한다.

---

## 2026-07-28 추가 기록: Lightweight Event-Based Reconstruction 설명

### 쉽게 말하면

`lightweight event-based reconstruction`은 딥러닝으로 새 이미지를 상상해서 만드는 방식이 아니다. 이미 있는 CIS 이미지 한 장을 기준 화면으로 두고, DVS 이벤트가 알려주는 밝아짐/어두워짐 정보를 그 위에 빠르게 더해서 중간 timestamp의 이미지를 만드는 방식이다.

```text
CIS frame = 색, 질감, 배경을 제공
DVS event = 어느 위치가 언제 밝아졌는지/어두워졌는지 제공
합성 결과 = CIS frame + target timestamp까지의 DVS 변화량
```

즉 다음과 같은 구조다.

```text
I0 = 현재 CIS 프레임
I1 = 다음 CIS 프레임
E(t0 -> t) = I0 이후 target time t까지 발생한 DVS 이벤트

synthetic_frame(t) = I0 + accumulated_event_change(t0 -> t)
```

현재 데모에서는 drift를 줄이기 위해 다음 CIS 프레임도 아주 약하게 섞는다.

```text
anchor = I0 * (1 - 0.12 * alpha) + I1 * (0.12 * alpha)
synth  = anchor + polarity_count * gain
```

### DVS 이벤트의 의미

DVS 이벤트는 보통 다음 4개 값으로 저장된다.

```text
x = 이벤트가 발생한 가로 위치
y = 이벤트가 발생한 세로 위치
t = 이벤트가 발생한 시간
p = polarity, 밝아짐/어두워짐
```

polarity 해석:

```text
p = 1 -> 해당 픽셀이 밝아짐
p = 0 -> 해당 픽셀이 어두워짐
```

### 핵심 코드 예시

아래 코드는 현재 데모의 핵심 개념만 줄인 버전이다.

```python
import cv2
import numpy as np

# CIS 프레임 두 장
I0 = cv2.imread("images/000000.jpg").astype(np.float32)
I1 = cv2.imread("images/000001.jpg").astype(np.float32)

# I0와 I1 사이의 DVS 이벤트
z = np.load("events/000000.npz")
x = z["x"].astype(np.int32)
y = z["y"].astype(np.int32)
t = z["t"]
p = z["p"]

# 만들고 싶은 중간 timestamp
target_t = 10_000.0  # microsecond, 예: 10ms

# target_t 이전 이벤트만 사용
mask = t <= target_t
x = x[mask]
y = y[mask]
p = p[mask]

# 이벤트 누적 버퍼
h, w = I0.shape[:2]
event_memory = np.zeros((h, w), np.float32)

# p=1은 +1, p=0은 -1로 누적
pos = p > 0
np.add.at(event_memory, (y[pos], x[pos]), 1.0)
np.add.at(event_memory, (y[~pos], x[~pos]), -1.0)

# CIS frame 위에 이벤트 변화량을 반영
contrast_gain = 4.8
synth = I0 + event_memory[:, :, None] * contrast_gain
synth = np.clip(synth, 0, 255).astype(np.uint8)

cv2.imwrite("synthetic_10ms.jpg", synth)
```

### 실시간 데모에서 추가한 요소

실시간 데모는 위 코드에 다음 요소를 더했다.

```text
1. target timestamp를 60FPS 간격으로 계속 생성
2. 프레임마다 event_memory에 decay 적용
3. I0와 I1을 약하게 blend해서 drift 완화
4. 출력 해상도에 맞춰 DVS x/y 좌표 scale 보정
5. 5초 동안 실제 몇 프레임을 만드는지 측정
```

실시간 루프 개념:

```python
event_memory *= 0.70  # 오래된 이벤트를 서서히 지움

new_events = events[(last_t < events.t) & (events.t <= target_t)]
accumulate(new_events, event_memory)

alpha = (target_t - t0) / (t1 - t0)
anchor = I0 * (1 - 0.12 * alpha) + I1 * (0.12 * alpha)

synth = anchor + event_memory[..., None] * contrast_gain
```

### 장점과 한계

장점:

```text
빠르다
딥러닝 모델이 없어도 된다
라즈베리파이 같은 작은 장비에서도 동작한다
DVS의 시간 정보를 직접 사용한다
```

한계:

```text
새로운 texture를 만들어내지는 못한다
큰 움직임이나 occlusion에서 품질이 떨어진다
이벤트가 없는 영역은 CIS frame에 의존한다
오래 누적하면 밝기 drift가 생길 수 있다
```

따라서 이 방식은 최종 고품질 생성기라기보다, 실시간 preview 또는 AI refinement 전 단계로 보는 것이 맞다.
