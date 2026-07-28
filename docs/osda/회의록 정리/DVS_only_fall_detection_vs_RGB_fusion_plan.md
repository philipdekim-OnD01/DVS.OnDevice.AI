# DVS 기반 낙상 감지 기획서

작성일: 2026-07-27
문서 목적: DVS 센서만으로 들어오는 이벤트 기반 영상을 이용해 낙상을 감지하는 방안과, 일반 RGB/CIS 이미지센서를 추가하는 방안을 비교한다.
최종 후보 플랫폼: Arduino VENTUNO Q / Qualcomm Dragonwing IQ8 IQ-8275

## 1. 목표

사람의 이동을 DVS 이벤트 스트림으로 지속 관찰하고, 낙상으로 의심되는 급격한 자세 변화나 바닥 방향 이동을 실시간 감지한다. 감지 결과는 웹 대시보드에 표시하고, 이벤트 발생 시 관련 DVS raw chunk, 합성 영상, 판단 로그를 저장한다.

비교 대상은 두 가지다.

- 방안 1: DVS-only 낙상 감지
- 방안 2: DVS + RGB/CIS 이미지센서 융합 낙상 감지

## 2. 중요한 전제

DVS raw data는 일반 카메라 이미지가 아니다. `x/y/t/p` 형태의 비동기 이벤트 스트림이며, 밝기 변화가 있는 픽셀만 기록된다. 따라서 LLM이나 VLM에 raw DVS 이벤트를 그대로 넣는 구조는 비효율적이다.

현실적인 구조는 다음과 같다.

1. DVS raw event를 10~20ms 단위 event frame, time surface, voxel grid, event count map으로 변환한다.
2. 경량 시계열/비전 모델이 자세 변화, 속도, 방향, 바닥 접촉 패턴을 감지한다.
3. LLM은 최종 판단 보조, 상황 설명, 오탐 억제 규칙, 알림 문구 생성, 로그 요약에 사용한다.

즉, LLM을 낙상 감지의 1차 센서 모델로 쓰는 것이 아니라, `event model + rule engine + LLM reasoning` 구조로 쓰는 것이 맞다.

## 3. 방안 1: DVS-only 낙상 감지

### 3.1 개념

DVS 센서만 사용한다. 일반 RGB 이미지를 저장하지 않으므로 프라이버시가 높고, 이벤트가 없을 때 저장량과 연산량이 작다. 사람이 움직일 때만 이벤트가 증가하며, 낙상처럼 급격한 이동이 발생하면 이벤트 밀도와 방향성이 크게 변한다.

### 3.2 처리 흐름

```text
DVS sensor
    -> x/y/t/p event stream
    -> event chunk buffer
    -> event denoise/filter
    -> person activity ROI
    -> time surface / voxel grid
    -> fall candidate detector
    -> temporal confirmation
    -> LLM-based event explanation
    -> dashboard / storage / email batch
```

### 3.3 낙상 후보 특징

낙상은 단순히 사람이 보이는 것이 아니라 움직임의 시계열 패턴이다. DVS-only에서는 다음 특징을 본다.

- 짧은 시간 내 큰 수직 방향 이동
- 사람 ROI의 중심점이 급격히 아래로 이동
- 서 있는 세로형 shape가 가로형 shape로 변함
- 이벤트 밀도가 순간적으로 증가했다가 바닥 부근에서 급감
- 바닥 근처에서 일정 시간 이상 움직임이 작아짐
- 동일 위치에서 미세 움직임만 지속됨
- 사람이 앉거나 숙이는 동작보다 속도와 가속도가 큼

### 3.4 모델 구조

권장 모델은 LLM 단독이 아니라 3단 구조다.

- 1차: DVS event feature extractor
- 2차: fall action classifier
- 3차: LLM reasoner

세부 모델 후보:

- Event count map + MobileNetV3/YOLO-nano classifier
- Event voxel grid + Tiny 3D CNN
- ROI trajectory + GRU/TCN
- Skeleton 없이 shape centroid, bounding box, aspect ratio, velocity만 쓰는 경량 모델
- LLM은 `fall_candidate=true`, `confidence`, `duration`, `movement_summary`를 입력받아 최종 설명 생성

### 3.5 LLM 적용 위치

LLM은 다음 역할에 적합하다.

- 이벤트 로그 요약: “16:42:10에 빠른 하강 후 8초간 움직임 없음”
- 오탐 판단 보조: “앉기/물건 줍기/카메라 흔들림 가능성”
- 사용자 알림 문구 생성
- 여러 센서 상태를 종합한 판단
- 낙상 이벤트 보고서 작성

LLM이 직접 담당하지 않는 것이 좋은 역할:

- raw DVS 이벤트 픽셀 단위 처리
- 2000fps급 이벤트 전체를 매번 추론
- 실시간 1차 안전 판단

낙상 감지의 1차 판단은 반드시 경량 deterministic 모델과 rule engine이 맡아야 한다.

### 3.6 장점

- 프라이버시가 높다.
- 어두운 환경이나 빠른 움직임에 강하다.
- 이벤트가 없으면 저장량이 작다.
- 낙상 순간처럼 빠른 변화에 민감하다.
- RGB 이미지 저장에 따른 개인정보 부담이 작다.

### 3.7 한계

- 정지 상태 사람의 자세 정보가 부족하다.
- 실제 사람이 누워 있는지, 물체가 움직였는지 구분이 어려울 수 있다.
- DVS event만으로는 얼굴, 옷, 주변 사물 맥락을 보기 어렵다.
- 낙상 후 완전히 정지하면 추가 이벤트가 줄어든다.
- 학습 데이터셋 확보가 어렵다.

### 3.8 권장 사용 조건

DVS-only는 다음 환경에 적합하다.

- 프라이버시가 가장 중요한 공간
- 움직임 기반 이상 감지가 핵심인 공간
- 조도 변화가 크거나 어두운 공간
- 낙상 후보를 빠르게 감지하고 후속 확인은 다른 센서/알림으로 처리하는 구조

## 4. 방안 2: DVS + RGB/CIS 이미지센서 융합 낙상 감지

### 4.1 개념

DVS는 빠른 움직임과 이벤트 발생 시점을 잡고, RGB/CIS는 자세와 장면 맥락을 확인한다. 평상시에는 DVS 중심으로 저전력 감시를 하고, 낙상 후보가 발생할 때 RGB/CIS를 짧게 작동시켜 증거 프레임을 저장한다.

### 4.2 처리 흐름

```text
DVS sensor
    -> continuous event monitoring
    -> fall candidate trigger

RGB/CIS camera
    -> event-triggered burst capture
    -> person pose / scene context

Fusion
    -> DVS trajectory
    -> RGB posture confirmation
    -> fall confidence score
    -> LLM event explanation
    -> storage / dashboard / email batch
```

### 4.3 RGB/CIS가 추가로 주는 정보

- 사람이 실제로 바닥에 있는지 확인
- 의자에 앉은 것인지, 쓰러진 것인지 구분
- 바닥, 침대, 의자, 문턱 등 주변 맥락 확인
- DVS 오탐 원인 확인
- 낙상 전후 key frame 확보
- 보호자/관리자에게 설명 가능한 증거 제공

### 4.4 권장 동작 방식

- 평상시 RGB 저장은 하지 않거나 저주기로만 수행한다.
- DVS가 낙상 후보를 감지하면 RGB/CIS burst를 0.1초 단위로 1~2초 촬영한다.
- RGB 원본은 낙상 후보 이벤트에만 저장한다.
- DVS raw chunk는 낙상 전후 5~10초를 저장한다.
- 합성 영상은 `RGB key frame -> DVS event plane -> RGB key frame` 구조로 생성한다.
- LLM은 DVS trajectory와 RGB 확인 결과를 함께 받아 최종 설명을 만든다.

## 5. 두 방안 비교

| 항목 | 방안 1: DVS-only | 방안 2: DVS + RGB/CIS |
|---|---|---|
| 프라이버시 | 매우 높음 | 중간, 이벤트 때만 RGB 저장하면 완화 |
| 빠른 움직임 감지 | 매우 좋음 | 매우 좋음 |
| 낙상 후 정지 상태 확인 | 약함 | 좋음 |
| 장면 맥락 이해 | 약함 | 좋음 |
| 오탐 억제 | 중간 | 좋음 |
| 저장 용량 | 작음 | 중간 |
| 모델 복잡도 | 중간 | 높음 |
| 설명 가능성 | 중간 | 좋음 |
| 제품화 안정성 | 후보 감지용 적합 | 최종 낙상 판단용 적합 |

## 6. 권장 결론

최종 제품 구조는 방안 2가 더 안전하다.

DVS-only는 낙상 후보를 빠르게 잡는 1차 트리거로 매우 적합하다. 그러나 낙상은 안전 관련 이벤트이므로 오탐과 미탐을 줄이는 것이 중요하다. 따라서 실제 서비스 또는 실증 단계에서는 DVS가 낙상 후보를 감지하고, RGB/CIS가 짧게 켜져 자세와 장면 맥락을 확인하는 구조가 더 적절하다.

단, 프라이버시가 매우 중요한 환경에서는 방안 1을 기본으로 하고, RGB/CIS 저장을 끄거나 로컬 일시 버퍼만 사용하는 옵션을 제공한다.

## 7. Qualcomm VENTUNO Q 적용 구조

VENTUNO Q의 dual-brain 구조는 낙상 감지에 잘 맞는다.

- Qualcomm IQ8 MPU: DVS event 처리, RGB/CIS 처리, AI 추론, 웹 서버, 저장
- Hexagon NPU 40 dense TOPS: YOLO/person detector, fall classifier, pose/action model
- Spectra 692 ISP: RGB/CIS 이미지 처리
- 3x MIPI CSI: DVS 센서와 RGB/CIS 센서 동시 연결 후보
- STM32H5F5 MCU: 센서 트리거, GPIO, CAN-FD, 실시간 알림, watchdog 보조
- 16GB LPDDR5: event buffer, 모델, 합성 영상 처리
- 64GB eMMC + NVMe Gen.4: 이벤트 영상 및 raw chunk 저장
- 2.5GbE/Wi-Fi 6: 대시보드 및 원격 확인

## 8. 필요 성능

### 8.1 DVS-only

권장 최소 성능:

- NPU: 5~10 TOPS 이상
- CPU: 4~8코어급
- RAM: 4~8GB
- 저장장치: eMMC 또는 NVMe 권장

권장 성능:

- NPU: 10~20 TOPS
- RAM: 8GB 이상
- 이벤트 처리 전용 ring buffer

### 8.2 DVS + RGB/CIS + LLM 보조

권장 최소 성능:

- NPU: 15~20 TOPS 이상
- RAM: 8GB 이상
- 저장장치: eMMC + NVMe 권장

권장 성능:

- NPU: 20~40 TOPS
- RAM: 16GB
- RGB/CIS와 DVS를 동시에 처리 가능한 카메라 인터페이스
- 경량 LLM/VLM은 이벤트 설명과 보고서 생성 중심으로 제한

### 8.3 LLM 로컬 실행

낙상 감지에서 LLM은 작은 모델을 써야 한다.

- 1~3B급 경량 LLM: 이벤트 요약, 알림 문구, rule reasoning에 적합
- 4B급 이상 VLM: RGB key frame까지 같이 보고 설명 가능하지만 지연과 메모리 부담 증가
- 7B 이상: VENTUNO Q 단독 실시간 안전 판단에는 비권장, 필요 시 서버 오프로딩 검토

LLM은 실시간 1차 낙상 판단 루프 밖에 둔다. 안전 판단은 100~300ms 안에 끝나는 경량 모델/rule이 담당하고, LLM은 1~3초 늦어도 되는 설명/보고 단계에서 사용한다.

### 8.4 필요 TOPS 산정 공식

필요 TOPS는 단일 숫자로 고정하기보다, 센서 입력률, 모델 연산량, 목표 FPS, NPU 사용률, 실시간 여유계수를 반영해 산정한다.

기본 식:

```text
Required_TOPS =
    Safety_Margin *
    (AI_TOPS + DVS_TOPS + Fusion_TOPS + Encode_TOPS)
    / Effective_Utilization
```

각 항목:

```text
AI_TOPS =
    Model_OPs_per_Inference * Inference_FPS / 10^12

DVS_TOPS =
    Event_Rate * Ops_per_Event / 10^12

Fusion_TOPS =
    Output_Width * Output_Height * Output_FPS * Ops_per_Pixel / 10^12

Encode_TOPS =
    Output_Width * Output_Height * Output_FPS * Encode_Ops_per_Pixel / 10^12
```

변수 의미:

- `Model_OPs_per_Inference`: 사람 감지/낙상 분류 모델 1회 추론 연산량. 예: 1~20 GOPS급 경량 모델
- `Inference_FPS`: 초당 추론 횟수. DVS trigger 기반이면 평상시 낮고 이벤트 때만 증가
- `Event_Rate`: 초당 DVS 이벤트 수. 평상시는 낮고 낙상/움직임 순간에는 급증
- `Ops_per_Event`: 이벤트 1개를 필터링, ROI 누적, time surface/voxel grid에 반영하는 연산량
- `Ops_per_Pixel`: 합성 프레임 1픽셀당 렌더링/색상/마스크 처리 연산량
- `Effective_Utilization`: 실제 NPU/GPU/DSP 사용 효율. 일반적으로 0.3~0.6으로 잡는 것이 안전
- `Safety_Margin`: 발열, 동시 서비스, OS jitter, 모델 교체 여유. 보통 2~3배 적용

예시 1: DVS-only 낙상 후보 감지

```text
Model_OPs_per_Inference = 2 GOPS
Inference_FPS = 20
AI_TOPS = 2 * 20 / 1000 = 0.04 TOPS

Event_Rate = 300,000 events/s
Ops_per_Event = 200 ops
DVS_TOPS = 300,000 * 200 / 10^12 = 0.00006 TOPS

Fusion_TOPS = 낮음, 표시용 event plane 중심
Encode_TOPS = 낮음

Raw_Total ~= 0.1 TOPS 미만
Effective_Utilization = 0.4
Safety_Margin = 3
Required_TOPS ~= 0.75 TOPS
```

수식상 DVS-only 자체는 TOPS보다 메모리 이동, timestamp 정렬, 이벤트 버퍼 설계가 더 중요하다. 다만 모델 교체, 다중 카메라, 실시간 웹/저장, 발열 여유를 고려해 제품 기준은 최소 5~10 TOPS로 잡는다.

예시 2: DVS + RGB/CIS + YOLO + 합성

```text
YOLO_Model_OPs = 10 GOPS
YOLO_FPS = 15
AI_TOPS = 10 * 15 / 1000 = 0.15 TOPS

Fall_Classifier_OPs = 2 GOPS
Fall_Classifier_FPS = 30
Classifier_TOPS = 2 * 30 / 1000 = 0.06 TOPS

RGB_DVS_Fusion =
    1280 * 720 * 30 * 50 / 10^12
    ~= 0.0014 TOPS

Raw_Total ~= 0.3 TOPS 전후
Effective_Utilization = 0.3~0.5
Safety_Margin = 5~10
Required_TOPS ~= 3~10 TOPS
```

연산량만 보면 10 TOPS 이하도 가능해 보이지만, 실제 제품에서는 카메라 입력, ISP, NPU scheduling, 저장, 웹 표시, watchdog, 발열 제한, 모델 업그레이드 여유가 동시에 필요하다. 그래서 안정 운용 기준은 20~40 TOPS가 적절하다.

예시 3: LLM/VLM을 로컬에 포함하는 경우

```text
LLM_Required_TOPS ~= 2 * Parameters * Tokens_per_Second / 10^12
```

예를 들어 3B 모델을 10 tokens/s로 실행하면:

```text
LLM_Required_TOPS ~= 2 * 3,000,000,000 * 10 / 10^12
                  ~= 0.06 TOPS
```

하지만 이 값은 순수 matrix multiply의 이론값에 가깝다. 실제로는 메모리 대역폭, quantization 방식, KV cache, 런타임 오버헤드, CPU fallback 때문에 훨씬 큰 여유가 필요하다. 따라서 VENTUNO Q에서는 LLM을 낙상 1차 판단에 쓰지 않고, 구조화된 이벤트 요약을 받아 1~3초 지연 허용 범위에서 설명/보고서를 생성하는 용도로 제한한다.

최종 산정 기준:

- DVS-only 후보 감지: 이론 1 TOPS 이하 가능, 제품 기준 5~10 TOPS 권장
- DVS + RGB/CIS 확인: 제품 기준 10~20 TOPS 이상
- DVS + RGB/CIS + 실시간 합성 + 웹/저장 안정 운용: 20~40 TOPS 권장
- 경량 LLM/VLM 로컬 설명까지 포함: 40 TOPS급 VENTUNO Q가 적정 출발점
- 7B 이상 LLM/VLM, 복수 카메라, 고해상도 장면 이해: 60 TOPS 이상 또는 서버 오프로딩 권장

## 9. 데이터 저장 정책

평상시:

- DVS event chunk만 저장
- 이벤트가 거의 없으면 metadata 중심 저장
- RGB/CIS는 저장하지 않거나 저주기 상태 확인만 수행

낙상 후보 발생 시:

- 낙상 전 5초 DVS ring buffer 보존
- 낙상 후 10~20초 DVS raw chunk 저장
- RGB/CIS burst frame 저장
- 합성 영상 생성
- fall_event.json 생성
- 웹 대시보드와 2시간 메일 배치에 포함

저장 예시:

```text
/fall_events/20260727_164500/
    dvs_raw/
        000000.npz
        000001.npz
    rgb/
        20260727_164500_100.jpg
        20260727_164500_200.jpg
    synthetic/
        fall_summary.mp4
        fall_event_plane.gif
    fall_event.json
    llm_summary.txt
```

## 10. 경량화 전략

- DVS 전체 이벤트를 모두 모델에 넣지 않는다.
- 사람 ROI와 바닥 방향 이동 후보만 추출한다.
- event voxel grid 해상도를 낮춘다.
- 10~20ms event frame을 기본으로 하고, 낙상 후보 때만 5ms로 세분화한다.
- YOLO/person detector는 매 프레임이 아니라 DVS activity trigger 기반으로 실행한다.
- 낙상 후보가 없으면 LLM을 호출하지 않는다.
- LLM 입력은 raw 이미지가 아니라 구조화 요약으로 제한한다.
- RGB/CIS는 낙상 후보 발생 시에만 burst 저장한다.
- 저장은 raw event + key frame 중심으로 하고, 영상은 필요할 때 생성한다.

## 11. 낙상 판단 예시 로직

```text
if person_activity_detected:
    update_roi_track()
    compute_velocity()
    compute_aspect_ratio_change()
    compute_floor_proximity()

if rapid_downward_motion and vertical_to_horizontal_change:
    fall_candidate = true
    trigger_rgb_burst()
    preserve_dvs_ring_buffer()

if fall_candidate and low_motion_after_impact:
    fall_confirmed = true
    save_event()
    create_synthetic_video()
    run_llm_summary()
    show_dashboard_alert()
```

## 12. 최종 제안

1차 개발은 DVS-only로 시작한다. 먼저 DVS event stream에서 사람 이동, 급격한 하강, 정지 패턴을 잡는 모델과 rule을 만든다.

2차 개발에서는 RGB/CIS 이미지센서를 추가한다. RGB/CIS는 항상 저장하지 않고, DVS가 낙상 후보를 감지한 경우에만 짧게 켜서 낙상 여부를 확인한다.

최종 제품은 `DVS trigger + RGB/CIS confirmation + LLM explanation` 구조가 가장 현실적이다. 이 방식은 DVS의 빠른 반응성과 프라이버시 장점을 살리면서, RGB/CIS의 맥락 정보로 오탐을 줄이고, LLM으로 사람이 이해 가능한 설명과 보고서를 만들 수 있다.
