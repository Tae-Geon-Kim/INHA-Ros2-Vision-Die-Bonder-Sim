# Robot Log Console

React + Vite 기반 로봇 로그 모니터링 대시보드입니다.

## 준비

Node.js와 npm은 Python `requirements.txt`가 아니라 Ubuntu 시스템에 설치하는 도구입니다.

```bash
sudo apt update
sudo apt install nodejs npm
node -v
npm -v
```

프론트엔드 라이브러리는 `package.json`에 정의되어 있고, 아래 명령으로 설치합니다.

```bash
npm install
```

`npm install`을 실행하면 `package-lock.json`이 생성됩니다. 이 파일은 팀원들의 설치 버전을 고정하기 위해 커밋하는 것이 좋고, `node_modules/`는 커밋하지 않습니다.

## 구조

```text
web_frontend
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
├── src
│   ├── api          # 백엔드 API 호출
│   ├── components   # 작은 UI 단위
│   ├── pages        # 라우트 단위 화면
│   ├── state        # Zustand 전역 상태
│   ├── styles
│   ├── App.jsx      # React Router 구성
│   └── main.jsx
```

```bash
npm install
npm run dev
```

백엔드는 별도 터미널에서 실행합니다.

```bash
uvicorn web_backend.main:app --reload
```

기본 API 주소는 `http://127.0.0.1:8000`입니다. 다른 주소로 백엔드를 띄운 경우 화면 좌측의 API Base 값을 바꾸면 됩니다.
