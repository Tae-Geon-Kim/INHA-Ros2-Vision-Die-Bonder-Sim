# 🤖 INHA ROS 2 Vision Die-Bonder Simulator

![ROS 2](https://img.shields.io/badge/ROS%202-Humble-blue.svg) ![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04-orange.svg) ![Gazebo](https://img.shields.io/badge/Gazebo-Fortress-brightgreen.svg) ![Python](https://img.shields.io/badge/Python-3.10-yellow.svg)

인하대학교 **비전 AI 기반 반도체 다이 본더(Die Bonder) 갠트리 로봇 정밀 정렬 시뮬레이션** 프로젝트입니다.

ROS 2 Humble 및 Gazebo Fortress 환경에서 가상 카메라의 비전 데이터를 받아 YOLO 모델로 칩의 오차를 계산하고, 갠트리 로봇을 제어하여 반도체를 정밀 압착(Place)하는 전체 파이프라인을 시뮬레이션합니다.

---

## 🎯 Target Tech Stack (버전 엄수)
* **OS:** `Ubuntu 22.04 LTS`
* **ROS 2:** `ROS 2 Humble Hawksbill` (Desktop)
* **Simulator:** `Gazebo Fortress` (v6.18.0+)
* **Language:** `Python 3.10` / `C++17`
* **AI & Vision:** `OpenCV` / `YOLO (PyTorch)`
* **Database:** `PostgreSQL`

---

## 🗄️ 테이블 구조
- [DB 테이블 구조도](docs/db_table.md)

## 🛡️ Git & GitHub 협업 수칙

본 프로젝트는 코드의 꼬임과 빌드 에러를 방지하기 위해 **엄격한 브랜치 보호 규칙과 역할별 커밋 룰**을 적용합니다. 

### 👨‍💻 Repository Owner
1. **`main` 브랜치 직접 Push 제한:** 전역 설정이나 긴급한 인프라 핫픽스를 제외한 모든 기능 개발 시, 소유자 역시 `main`에 직접 코드를 밀어넣지 않습니다.
2. **작업 프로세스 (소유자 자체 PR 생성):**
   * 팀원들과 동일하게 최신 상태의 `main`을 동기화한 후 본인의 작업 브랜치를 파서 이동합니다.
     ```bash
     git checkout main
     git pull origin main
     git checkout -b feature/방장작업명
     ```
   * 코딩 완료 후 원격 저장소에 밀어 올립니다.
     ```bash
     git add .
     git commit -m "feat: 방장 커밋 내용 요약"
     git push origin feature/방장작업명
     ```
   * 깃허브에서 직접 **Pull Request(PR)**를 생성하고, 스스로 최종 검토를 거친 후 `main`에 병합(Merge)합니다.


### 👥 Contributors
1. **`main` 브랜치 직접 Push 절대 금지:** `main` 브랜치는 시스템적으로 보호되어 있어 직접 커밋이 불가능합니다.
2. **작업 프로세스 (1 Task = 1 Branch):**
   * 작업 시작 전 항상 최신 상태의 `main`을 동기화합니다.
     ```bash
     git checkout main
     git pull origin main
     ```
   * **본인의 작업 이름으로 브랜치를 생성하고 이동합니다.** (형식: `분야/기능명`)
     ```bash
     git checkout -b feature/본인작업명
     ```
   * 내 브랜치에서 코딩을 완료하고 원격 저장소에 밀어 올립니다.
     ```bash
     git add .
     git commit -m "feat: 커밋 내용 요약"
     git push origin feature/본인작업명
     ```
   * 깃허브 웹사이트에 접속하여 `main` 브랜치로 **Pull Request(PR)**를 신청합니다.
3. **리뷰어 지정:** PR 작성 시 우측의 `Reviewers`에 소유자를 반드시 지정하고, 본문 내용에 **'어떤 부분을 수정했고, 어떤 테스트를 거쳤는지'** 명확히 기재합니다.
4. **브랜치 폐기:** PR이 성공적으로 `main`에 Merge되어 닫히면, 작업이 끝난 해당 브랜치는 깃허브 상에서 `Delete branch` 버튼을 눌러 깔끔하게 정리합니다.

### 📝 Commit Message Convention
커밋 메시지는 작업 내용을 직관적으로 파악할 수 있도록 **[태그: 제목]** 형태의 규격을 준수합니다.

* `feat:` 새로운 기능 추가 (예: `feat: YOLO 중심 좌표 추출 함수 구현`)
* `fix:` 버그 및 에러 수정 (예: `fix: 카메라 토픽 수신 멈춤 현상 해결`)
* `docs:` 문서 수정 (예: `docs: README 실행 방법 업데이트`)
* `style:` 코드 포맷팅, 주석 정리 (코드 로직 변경 없음)
* `refactor:` 코드 구조 개선 (기능적 변화 없음)
* `chore:` 패키지 설정, 빌드 환경, `.gitignore` 등의 수정

---

## 📁 Repository Structure
```text

```