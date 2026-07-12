# INHA ROS 2 Vision Die-Bonder Simulator

비전 AI 기반 반도체 다이 본더 갠트리 로봇 정밀 정렬 시뮬레이션 프로젝트입니다.

ROS 2 Humble/Gazebo 환경에서 로봇 시뮬레이션을 실행하고, FastAPI 백엔드가 작업 이력과 로봇 로그를 PostgreSQL에 저장하며, React + Vite 프론트엔드가 로그 대시보드를 제공합니다.

## 전체 구조

```text
ros2_vision_ws
├── src
│   ├── robot_system_description   # URDF, Gazebo world, launch files
│   ├── vision_core                # ROS bridge, pose adapter, motion utilities
│   └── robot_control_pkg          # main_controller 데모/명령 노드
├── vision_node                    # 비전 정렬 로직 실험 코드
├── web_backend                    # FastAPI API 서버
├── web_frontend                   # React + Vite 대시보드
├── docs                           # DB 문서
├── requirements.txt               # 백엔드 Python 의존성
├── .env.example                   # 백엔드 환경변수 예시
└── README.md
```

## 실행 흐름

```text
React/Vite Web
  -> FastAPI Backend
      -> PostgreSQL(team05 DB)
      -> ROS demo process 실행 요청

ROS/Gazebo
  -> gazebo_camera.launch.py
      -> Gazebo GUI + camera world 실행
      -> robot_system spawn
  -> joint_bridge.launch.py
      -> /robot/command_pose 구독
      -> joint command로 변환
      -> ros_gz_bridge로 Gazebo joint topic 전달
  -> main_controller
      -> pick_place_demo / range_demo / joint_demo 명령 발행
```

웹 대시보드는 백엔드의 `/robot-logs/*`, `/users/*`, `/robot-control/*` API를 사용합니다.

## 버전 기준

```text
OS: Ubuntu 22.04 LTS
ROS 2: Humble
Gazebo: Fortress / Ignition Gazebo
Python: 3.10
Node.js: 20.x 권장
npm: 10.x 권장
Database: PostgreSQL
```

Node가 12.x이면 Vite가 실행되지 않습니다. 팀원은 nvm으로 Node 20 계열을 맞추는 것을 권장합니다.

## Git 작업 순서

팀원이 올린 작업을 가져올 때:

```bash
git checkout develop
git pull origin develop
```

본인 작업 브랜치에 develop 변경 반영:

```bash
git checkout feature/내브랜치명
git merge develop
```

백엔드/프론트 브랜치를 둘 다 관리하는 경우 각각 반영합니다.

```bash
git checkout feature/web-backend
git merge develop

git checkout feature/web-frontend
git merge develop
```

작업 완료 후:

```bash
git add .
git commit -m "feat: 작업 내용 요약"
git push origin feature/브랜치명
```

GitHub에서 `develop` 브랜치로 Pull Request를 생성합니다.

## 백엔드 환경 설정

### 1. Python 가상환경 생성

```bash
cd ~/ros2_vision_ws
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

이미 `.venv`가 있으면 activate 후 의존성만 설치합니다.

```bash
cd ~/ros2_vision_ws
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. 환경변수 파일 생성

```bash
cd ~/ros2_vision_ws
cp .env.example .env
```

`.env`의 DB 비밀번호, JWT secret, 초기 관리자 계정 값은 팀 공유 값으로 수정합니다.

```env
DB_USER=team05_db
DB_PASSWORD=팀_공유_DB_비밀번호
DB_NAME=team05_db
DB_HOST=127.0.0.1
DB_PORT=54320

SECRET_KEY=팀_공유_SECRET_KEY

INITIAL_USER_ID=admin_team05
INITIAL_USER_PASSWORD=ChangeThis05!
```

`.env`는 개인 환경 파일이므로 커밋하지 않습니다.

### 3. PostgreSQL SSH 터널 실행

로컬 백엔드가 GPU 서버 PostgreSQL을 사용하려면 별도 터미널에서 SSH 터널을 먼저 켭니다.

```bash
ssh -N -L 54320:127.0.0.1:54320 team05@165.246.170.53
```

터미널이 멈춘 것처럼 보이면 정상입니다. 이 터미널은 백엔드를 사용하는 동안 닫지 않습니다.

터널을 사용하는 경우 `.env`는 아래처럼 둡니다.

```env
DB_HOST=127.0.0.1
DB_PORT=54320
```

로컬 54320 포트가 이미 사용 중이면 다른 로컬 포트를 사용합니다.

```bash
ssh -N -L 15432:127.0.0.1:54320 team05@165.246.170.53
```

이 경우 `.env`도 바꿉니다.

```env
DB_HOST=127.0.0.1
DB_PORT=15432
```

### 4. DB 테이블 생성 및 초기 계정 동기화

터널이 켜진 상태에서 실행합니다.

```bash
cd ~/ros2_vision_ws
source .venv/bin/activate
python -m web_backend.db.init_db
python -m web_backend.db.register_user
```

`register_user`는 `.env`의 `INITIAL_USER_ID`, `INITIAL_USER_PASSWORD` 기준으로 계정을 생성하거나 기존 계정 비밀번호를 갱신합니다.

### 5. 백엔드 실행

```bash
cd ~/ros2_vision_ws
source .venv/bin/activate
python -m uvicorn web_backend.main:app --reload --host 127.0.0.1 --port 8000
```

`uvicorn ...` 대신 `python -m uvicorn ...`을 권장합니다. 이렇게 실행하면 현재 `.venv`의 패키지를 확실히 사용합니다.

Swagger:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

## 프론트엔드 환경 설정

### 1. Node.js 설치

Ubuntu 기본 저장소의 `nodejs`, `npm`은 버전이 낮을 수 있습니다. nvm 사용을 권장합니다.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
node -v
npm -v
```

### 2. 프론트 의존성 설치

```bash
cd ~/ros2_vision_ws/web_frontend
npm ci
```

`package-lock.json` 기준으로 동일한 버전을 설치합니다. `node_modules/`는 커밋하지 않습니다.

### 3. 프론트 환경변수

필요하면 `web_frontend/.env`를 생성합니다.

```bash
cd ~/ros2_vision_ws/web_frontend
cp .env.example .env
```

기본값:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 4. 프론트 실행

```bash
cd ~/ros2_vision_ws/web_frontend
npm run dev
```

Vite:

```text
http://127.0.0.1:5173
```

## 웹 로그인

백엔드와 프론트가 모두 실행 중이어야 로그인할 수 있습니다.

```text
ID: .env의 INITIAL_USER_ID
PW: .env의 INITIAL_USER_PASSWORD
```

예시:

```text
ID: admin_team05
PW: ChangeThis05!
```

프론트는 로그인 요청을 `/users/login`으로 보내고, 백엔드는 JWT access/refresh token을 HTTP-only cookie로 설정합니다.

## 주요 API

### 인증

```text
POST /users/login
POST /users/logout
POST /users/refresh
```

### 로봇 로그

```text
POST  /robot-logs/work-history
PATCH /robot-logs/work-history/{history_id}
GET   /robot-logs/work-history
GET   /robot-logs/work-history/{history_id}

POST  /robot-logs/errors
GET   /robot-logs/errors

POST  /robot-logs/vision-align
GET   /robot-logs/vision-align
```

### 로봇 데모 제어

```text
GET  /robot-control/demo/status
POST /robot-control/demo/start
POST /robot-control/demo/stop
```

`/robot-control/demo/start`는 FastAPI 서버가 실행 중인 환경에서 아래 명령을 별도 프로세스로 실행합니다.

```bash
ros2 run robot_control_pkg main_controller pick_place_demo
```

Gazebo와 bridge가 먼저 실행되어 있어야 실제 시뮬레이션이 움직입니다.

## ROS/Gazebo 실행

### 1. ROS 환경 source

```bash
source /opt/ros/humble/setup.bash
```

OpenCV 브리지를 실행하려면 시스템 Python에 OpenCV/Numpy가 필요합니다.

```bash
sudo apt update
sudo apt install python3-opencv python3-numpy
```

### 2. 워크스페이스 빌드

```bash
cd ~/ros2_vision_ws
colcon build --symlink-install
source install/setup.bash
```

### 3. Gazebo 시뮬레이션 실행

터미널 1:

```bash
cd ~/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch robot_system_description gazebo_camera.launch.py
```

학교 서버처럼 SSH로 접속한 환경에서는 Gazebo 창을 전달하지 않고 서버 모드로 실행합니다.

```bash
ros2 launch robot_system_description gazebo_camera.launch.py gui:=false
```

카메라 센서 렌더링도 서버에서 수행되므로 `nvidia-smi`에서 Gazebo 프로세스가 GPU를
사용하는지 확인합니다. `ssh -X`로 Gazebo GUI를 띄우면 네트워크 전송 때문에 오히려
느려질 수 있습니다.

### 4. ROS-Gazebo bridge 및 pose adapter 실행

터미널 2:

```bash
cd ~/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_core joint_bridge.launch.py
```

### 5. 카메라/OpenCV 정렬 브리지 실행

터미널 3:

```bash
cd ~/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=pick
```

이 launch는 Gazebo 카메라 이미지 토픽을 ROS `sensor_msgs/Image`로 bridge하고, OpenCV 정렬 오차를 `/vision/alignment_result`에 JSON 문자열로 publish합니다.

자동 로봇 보정 명령까지 발행하려면 `auto_command:=true`를 명시합니다.

```bash
ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=pick auto_command:=true
```

보정 명령은 `/robot/command_pose`로 발행되고, `joint_bridge.launch.py`의 `pose_command_adapter`가 Gazebo joint command로 변환합니다.

캘리브레이션 값이 정해지면 `pixel_size_x_mm`, `pixel_size_y_mm`를 실제 mm/pixel 값으로 지정합니다.

```bash
ros2 launch vision_core vision_alignment_bridge.launch.py \
  alignment_process:=pick \
  auto_command:=true \
  pixel_size_x_mm:=0.005 \
  pixel_size_y_mm:=0.005
```

백엔드 `vision_align_logs`에 정렬값을 기록하려면 작업 이력 `history_id`와 API URL을 같이 지정합니다.

```bash
ros2 launch vision_core vision_alignment_bridge.launch.py \
  alignment_process:=pick \
  backend_log_url:=http://127.0.0.1:8000/robot-logs/vision-align \
  history_id:=1
```

### 6. 로봇 데모 실행

터미널 4:

```bash
cd ~/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run robot_control_pkg main_controller pick_place_demo
```

다른 데모:

```bash
ros2 run robot_control_pkg main_controller joint_demo
ros2 run robot_control_pkg main_controller range_demo
ros2 run robot_control_pkg main_controller theta_demo
```

웹 대시보드의 `Start Gazebo Demo` 버튼도 백엔드 API를 통해 `pick_place_demo`를 실행합니다.

## DB 테이블

백엔드는 아래 테이블을 사용합니다.

```text
"user"              # 로그인 사용자
user_logs           # 로그인/로그아웃 이력
work_history        # 작업 이력
robot_error_logs    # 로봇 에러 로그
vision_align_logs   # 비전 정렬 로그
```

테이블 상세 구조는 [docs/db_table.md](docs/db_table.md)를 참고합니다.

## 실행 순서 요약

웹 기능만 확인:

```text
1. SSH 터널 실행
2. .env 설정
3. python -m web_backend.db.init_db
4. python -m web_backend.db.register_user
5. python -m uvicorn web_backend.main:app --reload --host 127.0.0.1 --port 8000
6. web_frontend에서 npm ci
7. npm run dev
8. http://127.0.0.1:5173 접속
```

ROS/Gazebo까지 확인:

```text
1. colcon build --symlink-install
2. ros2 launch robot_system_description gazebo_camera.launch.py
3. ros2 launch vision_core joint_bridge.launch.py
4. ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=pick
5. 백엔드 실행
6. 프론트 실행
7. Dashboard에서 Start Gazebo Demo 클릭
```

## 학교 GPU 서버(team05)에서 실행

서버가 Ubuntu 22.04, ROS 2 Humble, Gazebo Fortress를 제공한다는 전제의 절차입니다.
최초 한 번 서버에 접속해 `team05`가 사용하는 작업 디렉터리에서 저장소를 복제합니다.

```bash
ssh team05@<학교-GPU-서버>
mkdir -p ~/team05
cd ~/team05
git clone https://github.com/Tae-Geon-Kim/INHA-Ros2-Vision-Die-Bonder-Sim.git ros2_vision_ws
cd ros2_vision_ws
git checkout develop
```

의존성을 설치하고 빌드합니다. 서버에서 `sudo` 권한이 없다면 아래 패키지는 서버
관리자에게 설치를 요청해야 합니다.

```bash
source /opt/ros/humble/setup.bash
sudo rosdep init  # 서버에서 rosdep을 처음 사용하는 경우에만 실행
rosdep update
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
```

이후 SSH 터미널 세 개에서 각각 실행합니다. 모든 터미널에서 같은 워크스페이스를
source해야 합니다.

터미널 1 — Gazebo 서버 모드:

```bash
cd ~/team05/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch robot_system_description gazebo_camera.launch.py gui:=false
```

터미널 2 — 조인트/접촉 센서 bridge:

```bash
cd ~/team05/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_core joint_bridge.launch.py
```

터미널 3 — 카메라/OpenCV bridge:

```bash
cd ~/team05/ros2_vision_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch vision_core vision_alignment_bridge.launch.py alignment_process:=pick
```

다른 팀원이 올린 변경을 서버에 반영할 때는 실행 중인 노드를 종료한 뒤 다음을
실행합니다. 서버에서 직접 코드를 수정하기보다는 각자 브랜치에서 작업하고 Git으로
동기화하는 것을 권장합니다.

```bash
cd ~/team05/ros2_vision_ws
git checkout develop
git pull --ff-only origin develop
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

GPU 및 headless 실행 확인:

```bash
nvidia-smi
ros2 topic list
ros2 topic hz /camera/macro/image
```

마지막 카메라 토픽 이름은 환경에 따라 다를 수 있으므로 먼저
`ros2 topic list | grep image`로 실제 이름을 확인합니다. 카메라 토픽이 없고 Gazebo에
EGL/OGRE 렌더링 오류가 나타나면 서버 GPU 드라이버 또는 headless 렌더링 설정이 필요한
상태이므로 관리자에게 해당 오류 로그와 함께 문의합니다.

## 문제 해결

### DB 연결 실패

에러:

```text
ConnectionRefusedError: Connect call failed ('127.0.0.1', 54320)
```

원인: PostgreSQL SSH 터널이 꺼져 있거나 `.env`의 `DB_PORT`가 터널 포트와 다릅니다.

해결:

```bash
ssh -N -L 54320:127.0.0.1:54320 team05@165.246.170.53
```

### uvicorn이 전역 Python으로 실행됨

로그 경로에 아래처럼 `.local`이 보이면 전역 패키지를 사용 중입니다.

```text
/home/사용자/.local/lib/python3.10/site-packages
```

해결:

```bash
cd ~/ros2_vision_ws
source .venv/bin/activate
python -m uvicorn web_backend.main:app --reload --host 127.0.0.1 --port 8000
```

### uvicorn 옵션 인식 실패

에러:

```text
Got unexpected extra arguments (—reload —host ...)
```

원인: `--`가 일반 하이픈 두 개가 아니라 긴 대시 문자 `—`로 입력되었습니다.

해결:

```bash
python -m uvicorn web_backend.main:app --reload --host 127.0.0.1 --port 8000
```

### Vite 실행 오류

에러:

```text
SyntaxError: Unexpected reserved word
```

원인: Node.js 버전이 낮습니다.

해결:

```bash
nvm install 20
nvm use 20
cd ~/ros2_vision_ws/web_frontend
npm ci
npm run dev
```

### 프론트 로그인에서 Failed to fetch

원인 후보:

```text
1. 백엔드가 실행 중이 아님
2. VITE_API_BASE_URL이 실제 백엔드 주소와 다름
3. FRONTEND_ORIGINS에 프론트 origin이 없음
```

확인:

```text
http://127.0.0.1:8000/health
```

정상 응답:

```json
{"status":"ok"}
```

## 커밋 메시지 규칙

```text
feat: 새로운 기능
fix: 버그 수정
docs: 문서 수정
refactor: 구조 개선
chore: 설정/빌드/기타 작업
```

예시:

```bash
git commit -m "docs: 프로젝트 실행 README 통합"
```
