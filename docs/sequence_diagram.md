# 웹 기반 비전 적층 시스템 실행 흐름

웹의 Start에서 선택한 `stack_count` 하나가 Gazebo, joint bridge, 비전 적층 데모에 동일하게 적용된다. 웹 모드에서는 세 프로세스를 터미널에서 별도로 실행하지 않는다.

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant W as React Dashboard
    participant A as FastAPI
    participant G as Gazebo
    participant B as Joint Bridge
    participant V as Vision Stack Demo

    U->>W: Start 클릭 후 4~16개 선택
    W->>A: POST /robot-control/demo/start<br/>{ stack_count: N }
    activate A
    A->>A: 실행 중 프로세스와 수동 Gazebo 확인
    opt 다른 N의 웹 시스템이 실행 중
        A->>A: 기존 데모 → bridge → Gazebo 종료
    end
    A->>G: STACK_COUNT=N으로 시작

    loop 로봇과 N개 칩 모델 준비 확인
        A->>G: ign model --list
        G-->>A: 현재 모델 목록
    end

    A->>B: STACK_COUNT=N으로 시작
    A->>V: STACK_COUNT=N으로 시작
    V-->>A: 프로세스 실행 상태
    A-->>W: 202 Accepted + 전체 프로세스 상태
    deactivate A
    W-->>U: 실행 상태 표시

    Note over U,V: 같은 N으로 실행 중인 Start는 기존 상태 반환<br/>다른 N은 전체 자동 재시작 · 수동 ROS/Gazebo 충돌은 409 Conflict

    U->>W: Stop 클릭
    W->>A: POST /robot-control/demo/stop
    activate A
    A->>V: 데모 프로세스 그룹 종료
    A->>B: joint bridge 프로세스 그룹 종료
    A->>G: Gazebo 프로세스 그룹 종료
    A-->>W: 200 OK + 전체 종료 상태
    deactivate A
    W-->>U: 중지 상태 표시
```

상세 요청·응답과 오류 조건은 [API Specification](API%20Specification.md#10-robot-control-api)을 참고한다.
