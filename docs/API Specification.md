# Backend API 상세 명세서

작성 기준: `develop` 브랜치 현재 구현
대상 소스: `web_backend/main.py`, `web_backend/api/*`, `web_backend/schemas/*`, `web_backend/services/*`

## 1. 개요

이 백엔드는 ROS 2 Vision Die-Bonder Simulator의 웹 대시보드를 위한 FastAPI 서버이다. 주요 기능은 사용자 인증, 로봇 작업 이력/로그 저장 및 조회, 4~16개 비전 적층 데모 프로세스 제어이다.

- 기본 실행 URL: `http://127.0.0.1:8000`
- Swagger UI: `GET /docs`
- OpenAPI JSON: `GET /openapi.json`
- 기본 프론트엔드 origin: `http://localhost:5173`, `http://127.0.0.1:5173`
- 응답 데이터의 시간 값은 JSON 직렬화 시 ISO 8601 문자열로 반환된다.
- 서버가 자동 생성하는 시간은 KST 기준 현재 시각을 사용하며, DB에는 timezone 없는 timestamp로 저장된다.

## 2. 공통 응답 형식

대부분의 API는 아래 `CommonResponse` 형식을 사용한다.

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": null
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `success` | boolean | 성공 여부. 구현상 성공 응답 기본값은 `true`이다. |
| `message` | string | 처리 결과 메시지. 별도 지정이 없으면 기본 메시지가 반환된다. |
| `data` | any/null | API별 반환 데이터. |

예외 응답은 FastAPI 기본 형식을 따른다.

```json
{
  "detail": "에러 메시지"
}
```

유효성 검증 실패는 `422 Unprocessable Entity`와 함께 FastAPI/Pydantic의 `detail` 배열이 반환된다.

## 3. 인증 및 쿠키

인증은 JWT를 HttpOnly 쿠키에 저장하는 방식이다.

| 쿠키 | 발급 API | 용도 | 기본 만료 |
| --- | --- | --- | --- |
| `access_token` | `POST /users/login`, `POST /users/refresh` | 인증이 필요한 API 접근 | `.env`의 `ACCESS_TOKEN_EXPIRE_MINUTES`, 기본 30분 |
| `refresh_token` | `POST /users/login` | Access Token 재발급 | `.env`의 `REFRESH_TOKEN_EXPIRE_DAYS`, 기본 30일 |

쿠키 옵션:

- `httponly=true`
- `samesite=lax`

현재 구현상 인증이 필요한 API는 `POST /users/logout`뿐이다. `robot-logs`, `robot-control`, `health` API에는 인증 의존성이 붙어 있지 않다.

## 4. Rate Limit

아래 사용자 인증 API에는 클라이언트 IP, HTTP method, path 기준으로 60초에 3회 제한이 적용된다.

- `POST /users/login`
- `POST /users/refresh`
- `POST /users/logout`

초과 시:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 12
```

```json
{
  "detail": "요청이 너무 많습니다. 12초 후 다시 시도해주세요."
}
```

## 5. 엔드포인트 요약

| Method | Path | 인증 | 설명 |
| --- | --- | --- | --- |
| `GET` | `/health` | 없음 | 서버 상태 확인 |
| `POST` | `/users/login` | 없음 | 로그인 및 JWT 쿠키 발급 |
| `POST` | `/users/refresh` | `refresh_token` 쿠키 | Access Token 재발급 |
| `POST` | `/users/logout` | `access_token` 쿠키 | 로그아웃 및 쿠키 삭제 |
| `POST` | `/robot-logs/work-history` | 없음 | 작업 이력 생성 |
| `PATCH` | `/robot-logs/work-history/{history_id}` | 없음 | 작업 이력 상태/종료 시간 수정 |
| `GET` | `/robot-logs/work-history` | 없음 | 작업 이력 목록 조회 |
| `GET` | `/robot-logs/work-history/{history_id}` | 없음 | 작업 이력 상세 조회 |
| `POST` | `/robot-logs/errors` | 없음 | 로봇 에러 로그 생성 |
| `GET` | `/robot-logs/errors` | 없음 | 로봇 에러 로그 목록 조회 |
| `POST` | `/robot-logs/vision-align` | 없음 | 비전 정렬 로그 생성 |
| `GET` | `/robot-logs/vision-align` | 없음 | 비전 정렬 로그 목록 조회 |
| `GET` | `/robot-control/demo/status` | 없음 | Gazebo·bridge·데모 실행 상태 조회 |
| `POST` | `/robot-control/demo/start` | 없음 | 선택한 4~16개 값으로 전체 시스템 시작 |
| `POST` | `/robot-control/demo/stop` | 없음 | 웹에서 시작한 전체 시스템 중지 |

## 6. 공통 데이터 타입

### WorkStatus

```text
START | RUNNING | DONE | FAIL | STOP
```

### ErrorLevel

```text
INFO | WARN | ERROR | FATAL
```

### ProcessStep

```text
PICK | PLACE
```

### Pagination

목록 조회 API는 공통으로 다음 쿼리 파라미터를 사용한다.

| 파라미터 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `limit` | integer | `50` | `1 <= limit <= 200` | 반환 개수 |
| `offset` | integer | `0` | `offset >= 0` | 건너뛸 개수 |

페이지네이션 응답:

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "items": [],
    "total": 0,
    "limit": 50,
    "offset": 0
  }
}
```

## 7. Health API

### 7.1 서버 상태 확인

```http
GET /health
```

인증: 없음

성공 응답: `200 OK`

주의: 이 API는 `CommonResponse`를 사용하지 않는다.

```json
{
  "status": "ok"
}
```

## 8. Users API

### 8.1 로그인

```http
POST /users/login
Content-Type: application/json
```

인증: 없음  
Rate Limit: 60초 3회

요청 본문:

```json
{
  "id": "admin_team05",
  "password": "ChangeThis05!"
}
```

| 필드 | 타입 | 필수 | 제약 |
| --- | --- | --- | --- |
| `id` | string | 예 | 5~30자, 영문자와 숫자를 각각 1개 이상 포함. 허용 특수문자: `$!%*#?&._-` |
| `password` | string | 예 | 8~30자, 영문자/숫자/특수문자를 각각 1개 이상 포함. 허용 특수문자: `@$!%*#?&._-` |

성공 응답: `201 Created`

Set-Cookie:

- `access_token=<jwt>; HttpOnly; SameSite=Lax`
- `refresh_token=<jwt>; HttpOnly; SameSite=Lax`

```json
{
  "success": true,
  "message": "로그인에 성공하였습니다.",
  "data": null
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `401` | 아이디가 없거나 비밀번호가 일치하지 않음 |
| `422` | 요청 본문 검증 실패 |
| `429` | Rate Limit 초과 |
| `500` | DB pool 미초기화 또는 DB 오류 |

### 8.2 Access Token 재발급

```http
POST /users/refresh
Cookie: refresh_token=<jwt>
```

인증: `refresh_token` 쿠키  
Rate Limit: 60초 3회

요청 본문: 없음

성공 응답: `201 Created`

Set-Cookie:

- `access_token=<new_jwt>; HttpOnly; SameSite=Lax`

```json
{
  "success": true,
  "message": "토큰이 성공적으로 재발급 되었습니다.",
  "data": null
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `401` | `refresh_token` 쿠키 없음 |
| `401` | 만료된 refresh token |
| `401` | 유효하지 않은 refresh token |
| `401` | 토큰의 사용자 정보가 DB에 없음 |
| `429` | Rate Limit 초과 |

### 8.3 로그아웃

```http
POST /users/logout
Cookie: access_token=<jwt>
```

인증: `access_token` 쿠키  
Rate Limit: 60초 3회

요청 본문: 없음

성공 응답: `200 OK`

동작:

- 현재 사용자의 로그아웃 기록을 `user_logs`에 저장한다.
- `access_token`, `refresh_token` 쿠키를 삭제한다.

```json
{
  "success": true,
  "message": "성공적으로 로그아웃 되었습니다.",
  "data": null
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `401` | `access_token` 쿠키 없음 |
| `401` | 유효하지 않은 access token |
| `401` | 토큰의 사용자 정보가 DB에 없음 |
| `429` | Rate Limit 초과 |

## 9. Robot Logs API

### 9.1 작업 이력 생성

```http
POST /robot-logs/work-history
Content-Type: application/json
```

인증: 없음

요청 본문:

```json
{
  "die_serial_number": "DIE-2026-0001",
  "status": "START",
  "start_time": "2026-07-12T10:30:00"
}
```

| 필드 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `die_serial_number` | string | 예 | 없음 | 1~100자. 앞뒤 공백은 제거된다. |
| `status` | WorkStatus | 아니오 | `START` | `START`, `RUNNING`, `DONE`, `FAIL`, `STOP` |
| `start_time` | datetime/null | 아니오 | 서버 KST 현재 시각 | timezone이 있으면 KST로 변환 후 저장 |

성공 응답: `201 Created`

```json
{
  "success": true,
  "message": "작업 이력이 생성되었습니다.",
  "data": {
    "history_id": 1,
    "die_serial_number": "DIE-2026-0001",
    "start_time": "2026-07-12T10:30:00",
    "end_time": null,
    "status": "START"
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `422` | 요청 본문 검증 실패 |
| `500` | DB pool 미초기화 또는 DB 오류 |

### 9.2 작업 이력 수정

```http
PATCH /robot-logs/work-history/{history_id}
Content-Type: application/json
```

인증: 없음

Path:

| 파라미터 | 타입 | 설명 |
| --- | --- | --- |
| `history_id` | integer | 수정할 작업 이력 ID |

요청 본문:

```json
{
  "status": "DONE",
  "end_time": "2026-07-12T10:45:00"
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `status` | WorkStatus/null | 아니오 | 변경할 작업 상태 |
| `end_time` | datetime/null | 아니오 | 종료 시간 |

`end_time`이 없고 `status`가 `DONE`, `FAIL`, `STOP` 중 하나이면 서버가 KST 현재 시각을 종료 시간으로 저장한다.

성공 응답: `200 OK`

```json
{
  "success": true,
  "message": "작업 이력이 수정되었습니다.",
  "data": {
    "history_id": 1,
    "die_serial_number": "DIE-2026-0001",
    "start_time": "2026-07-12T10:30:00",
    "end_time": "2026-07-12T10:45:00",
    "status": "DONE"
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `404` | 존재하지 않는 작업 이력 |
| `422` | Path 또는 요청 본문 검증 실패 |

### 9.3 작업 이력 목록 조회

```http
GET /robot-logs/work-history?limit=50&offset=0&status=START&die_serial_number=DIE
```

인증: 없음

Query:

| 파라미터 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `limit` | integer | 아니오 | `50` | 1~200 |
| `offset` | integer | 아니오 | `0` | 0 이상 |
| `status` | WorkStatus | 아니오 | 없음 | 정확히 일치하는 상태 필터 |
| `die_serial_number` | string | 아니오 | 없음 | 부분 일치 검색. DB에서는 `ILIKE '%값%'`로 조회 |

정렬: `start_time DESC`, `history_id DESC`

성공 응답: `200 OK`

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "items": [
      {
        "history_id": 1,
        "die_serial_number": "DIE-2026-0001",
        "start_time": "2026-07-12T10:30:00",
        "end_time": null,
        "status": "START"
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

### 9.4 작업 이력 상세 조회

```http
GET /robot-logs/work-history/{history_id}
```

인증: 없음

Path:

| 파라미터 | 타입 | 설명 |
| --- | --- | --- |
| `history_id` | integer | 조회할 작업 이력 ID |

성공 응답: `200 OK`

연결된 에러 로그와 비전 정렬 로그는 각각 최대 200개까지 함께 조회된다.

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "history_id": 1,
    "die_serial_number": "DIE-2026-0001",
    "start_time": "2026-07-12T10:30:00",
    "end_time": null,
    "status": "START",
    "error_logs": [
      {
        "log_id": 10,
        "error_time": "2026-07-12T10:35:00",
        "error_level": "WARN",
        "error_code": "ALIGN_WARN",
        "detail": "Offset threshold warning",
        "history_id": 1
      }
    ],
    "vision_align_logs": [
      {
        "align_id": 20,
        "history_id": 1,
        "process_step": "PICK",
        "camera_type": "MACRO",
        "offset_x": 0.12,
        "offset_y": -0.04,
        "offset_theta": 0.01,
        "created_at": "2026-07-12T10:34:00"
      }
    ]
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `404` | 존재하지 않는 작업 이력 |
| `422` | Path 검증 실패 |

### 9.5 로봇 에러 로그 생성

```http
POST /robot-logs/errors
Content-Type: application/json
```

인증: 없음

요청 본문:

```json
{
  "error_level": "WARN",
  "error_code": "ALIGN_WARN",
  "detail": "Offset threshold warning",
  "history_id": 1,
  "error_time": "2026-07-12T10:35:00"
}
```

| 필드 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `error_level` | ErrorLevel | 예 | 없음 | `INFO`, `WARN`, `ERROR`, `FATAL` |
| `error_code` | string/null | 아니오 | `null` | 최대 50자. 값이 있으면 앞뒤 공백 제거 |
| `detail` | string/null | 아니오 | `null` | 상세 메시지 |
| `history_id` | integer/null | 아니오 | `null` | 1 이상. 값이 있으면 해당 작업 이력이 존재해야 함 |
| `error_time` | datetime/null | 아니오 | 서버 KST 현재 시각 | timezone이 있으면 KST로 변환 후 저장 |

성공 응답: `201 Created`

```json
{
  "success": true,
  "message": "로봇 에러 로그가 저장되었습니다.",
  "data": {
    "log_id": 10,
    "error_time": "2026-07-12T10:35:00",
    "error_level": "WARN",
    "error_code": "ALIGN_WARN",
    "detail": "Offset threshold warning",
    "history_id": 1
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `404` | `history_id`가 존재하지 않는 작업 이력 |
| `422` | 요청 본문 검증 실패 |

### 9.6 로봇 에러 로그 목록 조회

```http
GET /robot-logs/errors?limit=50&offset=0&history_id=1&error_level=WARN
```

인증: 없음

Query:

| 파라미터 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `limit` | integer | 아니오 | `50` | 1~200 |
| `offset` | integer | 아니오 | `0` | 0 이상 |
| `history_id` | integer | 아니오 | 없음 | 1 이상 |
| `error_level` | ErrorLevel | 아니오 | 없음 | 정확히 일치하는 레벨 필터 |

정렬: `error_time DESC`, `log_id DESC`

성공 응답: `200 OK`

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "items": [
      {
        "log_id": 10,
        "error_time": "2026-07-12T10:35:00",
        "error_level": "WARN",
        "error_code": "ALIGN_WARN",
        "detail": "Offset threshold warning",
        "history_id": 1
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

### 9.7 비전 정렬 로그 생성

```http
POST /robot-logs/vision-align
Content-Type: application/json
```

인증: 없음

요청 본문:

```json
{
  "history_id": 1,
  "process_step": "PICK",
  "camera_type": "MACRO",
  "offset_x": 0.12,
  "offset_y": -0.04,
  "offset_theta": 0.01,
  "created_at": "2026-07-12T10:34:00"
}
```

| 필드 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `history_id` | integer | 예 | 없음 | 1 이상. 해당 작업 이력이 존재해야 함 |
| `process_step` | ProcessStep | 예 | 없음 | `PICK`, `PLACE` |
| `camera_type` | string | 예 | 없음 | 1~50자. 앞뒤 공백 제거 |
| `offset_x` | number | 아니오 | `0.0` | X 방향 보정값 |
| `offset_y` | number | 아니오 | `0.0` | Y 방향 보정값 |
| `offset_theta` | number | 아니오 | `0.0` | 회전 보정값 |
| `created_at` | datetime/null | 아니오 | 서버 KST 현재 시각 | timezone이 있으면 KST로 변환 후 저장 |

성공 응답: `201 Created`

```json
{
  "success": true,
  "message": "비전 정렬 로그가 저장되었습니다.",
  "data": {
    "align_id": 20,
    "history_id": 1,
    "process_step": "PICK",
    "camera_type": "MACRO",
    "offset_x": 0.12,
    "offset_y": -0.04,
    "offset_theta": 0.01,
    "created_at": "2026-07-12T10:34:00"
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `404` | `history_id`가 존재하지 않는 작업 이력 |
| `422` | 요청 본문 검증 실패 |

### 9.8 비전 정렬 로그 목록 조회

```http
GET /robot-logs/vision-align?limit=50&offset=0&history_id=1&process_step=PICK&camera_type=MACRO
```

인증: 없음

Query:

| 파라미터 | 타입 | 필수 | 기본값 | 제약/설명 |
| --- | --- | --- | --- | --- |
| `limit` | integer | 아니오 | `50` | 1~200 |
| `offset` | integer | 아니오 | `0` | 0 이상 |
| `history_id` | integer | 아니오 | 없음 | 1 이상 |
| `process_step` | ProcessStep | 아니오 | 없음 | 정확히 일치하는 공정 단계 필터 |
| `camera_type` | string | 아니오 | 없음 | 정확히 일치하는 카메라 타입 필터 |

정렬: `created_at DESC`, `align_id DESC`

성공 응답: `200 OK`

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "items": [
      {
        "align_id": 20,
        "history_id": 1,
        "process_step": "PICK",
        "camera_type": "MACRO",
        "offset_x": 0.12,
        "offset_y": -0.04,
        "offset_theta": 0.01,
        "created_at": "2026-07-12T10:34:00"
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

## 10. Robot Control API

로봇 제어 API는 웹에서 받은 `stack_count` 하나를 Gazebo, joint bridge, 비전 적층 데모에 동일하게 적용하여 전체 시스템을 관리한다. 현재 구현상 인증은 적용되어 있지 않다.

Start의 기본 실행 순서는 다음과 같다.

1. `make gazebo-camera STACK_COUNT=<요청값>`
2. Gazebo에서 로봇과 요청 개수만큼의 칩 모델이 준비될 때까지 대기
3. `make joint-bridge STACK_COUNT=<요청값>`
4. `make vision-stack-demo STACK_COUNT=<요청값>`

각 명령은 다음 환경변수로 교체할 수 있다.

| 환경변수 | 기본 명령 |
| --- | --- |
| `ROBOT_GAZEBO_COMMAND` | `make gazebo-camera` |
| `ROBOT_JOINT_BRIDGE_COMMAND` | `make joint-bridge` |
| `ROBOT_DEMO_COMMAND` | `make vision-stack-demo` |

Gazebo 모델 준비 제한 시간은 `ROBOT_GAZEBO_READY_TIMEOUT_SEC`로 조정할 수 있으며 기본값은 60초다.

세 프로세스에는 동일한 `STACK_COUNT`와 로컬 Gazebo Transport 설정이 전달된다. 웹 모드에서는 위 명령들을 터미널에서 별도로 실행하지 않는다. 수동으로 실행한 Gazebo, joint bridge 또는 비전 데모가 감지되면 중복 실행을 막기 위해 Start가 거부된다.

로그 파일:

```text
<PROJECT_ROOT>/log/web_gazebo.log
<PROJECT_ROOT>/log/web_joint_bridge.log
<PROJECT_ROOT>/log/robot_demo.log
```

### 10.1 데모 상태 조회

```http
GET /robot-control/demo/status
```

인증: 없음

성공 응답: `200 OK`

```json
{
  "success": true,
  "message": "사용자의 요청이 성공적으로 수행되었습니다.",
  "data": {
    "running": false,
    "pid": null,
    "returncode": null,
    "command": "make vision-stack-demo STACK_COUNT=4",
    "stack_count": 4,
    "infrastructure_running": false,
    "processes": {
      "gazebo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make gazebo-camera STACK_COUNT=4"
      },
      "joint_bridge": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make joint-bridge STACK_COUNT=4"
      },
      "demo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make vision-stack-demo STACK_COUNT=4"
      }
    },
    "log_paths": {
      "gazebo": "/path/to/project/log/web_gazebo.log",
      "joint_bridge": "/path/to/project/log/web_joint_bridge.log",
      "demo": "/path/to/project/log/robot_demo.log"
    }
  }
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `running` | boolean | 데모 프로세스 실행 여부. 기존 API 소비자를 위한 최상위 필드 |
| `pid` | integer/null | 데모 프로세스 PID |
| `returncode` | integer/null | 데모 프로세스 종료 코드. 실행 중이거나 아직 시작하지 않았으면 `null` |
| `command` | string | 데모 실행 명령 |
| `stack_count` | integer | 현재 또는 마지막으로 요청한 칩 적층 개수 |
| `infrastructure_running` | boolean | Gazebo와 joint bridge가 모두 실행 중인지 여부 |
| `processes` | object | `gazebo`, `joint_bridge`, `demo` 각각의 `running`, `pid`, `returncode`, `command` |
| `log_paths` | object | `gazebo`, `joint_bridge`, `demo` 로그의 절대 경로 |

### 10.2 데모 시작

```http
POST /robot-control/demo/start
```

인증: 없음

요청 본문:

```json
{
  "stack_count": 8
}
```

| 필드 | 타입 | 필수 | 기본값 | 제한 | 설명 |
| --- | --- | --- | --- | --- | --- |
| `stack_count` | integer | 아니요 | `4` | `4`~`16` | 적층할 칩 개수 |

요청 본문을 생략하면 기본값 `4`를 사용한다.

성공 응답: `202 Accepted`

시스템이 실행 중이 아니면 요청한 `stack_count`로 Gazebo를 시작하고 모델 준비를 확인한 뒤, 같은 값으로 joint bridge와 비전 데모를 차례로 시작하여 상태를 반환한다.

```json
{
  "success": true,
  "message": "웹 설정값 8개로 Gazebo, joint bridge, 비전 적층 데모를 시작했습니다.",
  "data": {
    "running": true,
    "pid": 12347,
    "returncode": null,
    "command": "make vision-stack-demo STACK_COUNT=8",
    "stack_count": 8,
    "infrastructure_running": true,
    "processes": {
      "gazebo": {
        "running": true,
        "pid": 12345,
        "returncode": null,
        "command": "make gazebo-camera STACK_COUNT=8"
      },
      "joint_bridge": {
        "running": true,
        "pid": 12346,
        "returncode": null,
        "command": "make joint-bridge STACK_COUNT=8"
      },
      "demo": {
        "running": true,
        "pid": 12347,
        "returncode": null,
        "command": "make vision-stack-demo STACK_COUNT=8"
      }
    },
    "log_paths": {
      "gazebo": "/path/to/project/log/web_gazebo.log",
      "joint_bridge": "/path/to/project/log/web_joint_bridge.log",
      "demo": "/path/to/project/log/robot_demo.log"
    }
  }
}
```

같은 개수의 데모가 현재 실행 중이면 새 프로세스를 만들지 않고 현재 상태를 반환한다. 그 외에는 이전 데모가 완료되었더라도 칩이 이동한 월드를 재사용하지 않으며, 기존 데모, joint bridge, Gazebo를 종료한 뒤 요청한 값으로 전체 시스템을 자동 재시작한다. 두 경우 모두 상태 코드는 `202 Accepted`이다. 아래 예시는 중첩 필드를 생략한 축약 표현이다.

```json
{
  "success": true,
  "message": "8개 칩 적층 데모가 이미 실행 중입니다.",
  "data": {
    "running": true,
    "pid": 12345,
    "returncode": null,
    "command": "make vision-stack-demo STACK_COUNT=8",
    "stack_count": 8
  }
}
```

에러:

| 상태 코드 | 조건 |
| --- | --- |
| `422` | `stack_count`가 4~16 범위를 벗어나거나 정수가 아님 |
| `409` | 터미널에서 수동 실행한 Gazebo, joint bridge 또는 비전 데모가 감지됨 |
| `500` | 실행 파일을 찾지 못했거나 OS 레벨 프로세스 시작에 실패함 |
| `500` | Gazebo 또는 joint bridge가 준비 중 종료됨 |
| `500` | 제한 시간 안에 요청한 개수의 Gazebo 모델을 확인하지 못함 |
| `500` | 비전 적층 데모 프로세스가 시작 직후 종료됨 |

Start 준비 과정에서 `500` 오류가 발생하면 API가 시작한 세 프로세스를 모두 정리한다. 오류 응답의 `detail`에는 `<PROJECT_ROOT>/log` 경로가 포함된다.

### 10.3 데모 중지

```http
POST /robot-control/demo/stop
```

인증: 없음

요청 본문: 없음

성공 응답: `200 OK`

웹에서 실행한 프로세스가 있으면 데모 → joint bridge → Gazebo 순서로 각 프로세스 그룹을 종료한다. 먼저 `SIGINT`를 보내고 제한 시간 안에 끝나지 않으면 `SIGTERM`, 마지막으로 `SIGKILL`을 사용한다.

```json
{
  "success": true,
  "message": "Gazebo, joint bridge, 비전 적층 데모를 모두 중지했습니다.",
  "data": {
    "running": false,
    "pid": null,
    "returncode": null,
    "command": "make vision-stack-demo STACK_COUNT=8",
    "stack_count": 8,
    "infrastructure_running": false,
    "processes": {
      "gazebo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make gazebo-camera STACK_COUNT=8"
      },
      "joint_bridge": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make joint-bridge STACK_COUNT=8"
      },
      "demo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make vision-stack-demo STACK_COUNT=8"
      }
    },
    "log_paths": {
      "gazebo": "/path/to/project/log/web_gazebo.log",
      "joint_bridge": "/path/to/project/log/web_joint_bridge.log",
      "demo": "/path/to/project/log/robot_demo.log"
    }
  }
}
```

웹에서 실행한 시스템이 없으면:

```json
{
  "success": true,
  "message": "웹에서 실행한 비전 적층 시스템이 없습니다.",
  "data": {
    "running": false,
    "pid": null,
    "returncode": null,
    "command": "make vision-stack-demo STACK_COUNT=4",
    "stack_count": 4,
    "infrastructure_running": false,
    "processes": {
      "gazebo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make gazebo-camera STACK_COUNT=4"
      },
      "joint_bridge": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make joint-bridge STACK_COUNT=4"
      },
      "demo": {
        "running": false,
        "pid": null,
        "returncode": null,
        "command": "make vision-stack-demo STACK_COUNT=4"
      }
    },
    "log_paths": {
      "gazebo": "/path/to/project/log/web_gazebo.log",
      "joint_bridge": "/path/to/project/log/web_joint_bridge.log",
      "demo": "/path/to/project/log/robot_demo.log"
    }
  }
}
```

## 11. DB 반환 필드 기준

### work_history

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `history_id` | integer | 작업 이력 PK |
| `die_serial_number` | string | 다이 시리얼 번호 |
| `start_time` | datetime | 작업 시작 시간 |
| `end_time` | datetime/null | 작업 종료 시간 |
| `status` | string | 작업 상태 |

### robot_error_logs

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `log_id` | integer | 에러 로그 PK |
| `error_time` | datetime | 에러 발생 시간 |
| `error_level` | string | 에러 레벨 |
| `error_code` | string/null | 에러 코드 |
| `detail` | string/null | 상세 메시지 |
| `history_id` | integer/null | 연결된 작업 이력 ID |

### vision_align_logs

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `align_id` | integer | 비전 정렬 로그 PK |
| `history_id` | integer | 연결된 작업 이력 ID |
| `process_step` | string | `PICK` 또는 `PLACE` |
| `camera_type` | string | 카메라 타입 |
| `offset_x` | number | X 방향 보정값 |
| `offset_y` | number | Y 방향 보정값 |
| `offset_theta` | number | 회전 보정값 |
| `created_at` | datetime | 생성 시각 |

## 12. 구현상 주의사항

- `POST /users/logout`만 access token 인증을 요구한다. 로그/제어 API 보호가 필요하면 `Depends(get_current_user)`를 라우터나 엔드포인트에 추가해야 한다.
- 인증 토큰은 Authorization 헤더가 아니라 쿠키에서 읽는다. 프론트엔드 fetch는 `credentials: "include"`를 사용한다.
- `POST /users/refresh`는 refresh token만 검증하고 DB 사용자 존재 여부를 확인한 뒤 새 access token을 발급한다.
- `robot-control` 상태는 서버 메모리의 Gazebo, joint bridge, 데모 프로세스 객체에 의존한다. FastAPI가 정상 종료되면 lifespan 정리 단계에서 세 프로세스를 모두 종료한다.
- 웹 모드에서는 Gazebo, joint bridge 또는 비전 데모를 터미널에서 먼저 실행하지 않는다. 수동 프로세스가 감지되면 Start는 `409 Conflict`를 반환한다.
- `robot-control`의 Start API는 기본 Make target 안에서 ROS 2 workspace를 source한다. 명령을 환경변수로 교체할 경우 해당 명령이 필요한 ROS 환경을 직접 준비해야 한다.
- `robot-control` API는 OS 프로세스를 실행하므로 운영 환경에서는 인증, 권한, 명령 allowlist 정책을 추가하는 것이 안전하다.
