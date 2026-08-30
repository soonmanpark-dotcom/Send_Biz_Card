# Send_Biz_Card

카카오톡 챗봇으로 이메일 주소를 받아, 명함(연락처) HTML 메일을 발송하는 스킬 서버.

- `app.py` — Flask 스킬 서버 (`/kakao` 스킬 엔드포인트, `/health` 헬스체크)
- `email_sender.py` — Gmail SMTP 발송 + 명함 HTML 생성
- `config.yaml` — 명함 내용 / 트리거 문구 (민감 정보는 환경변수로 주입)

---

## 클라우드 배포 (Render 무료 플랜)

### 1. 사전 준비: Gmail 앱 비밀번호

일반 Gmail 비밀번호로는 SMTP 로그인이 안 됩니다. 2단계 인증을 켠 뒤
[Google 계정 > 앱 비밀번호](https://myaccount.google.com/apppasswords)에서 16자리를 발급받습니다.

### 2. 시크릿 값 생성

`/kakao` 는 공개 URL이 되므로, 카카오 서버에서 온 요청만 받도록 시크릿을 만듭니다.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

출력된 문자열을 복사해 둡니다.

### 3. Render 배포

1. [render.com](https://render.com) 가입 후 **New → Blueprint** 선택
2. 이 GitHub 저장소를 연결 → `render.yaml` 을 자동으로 읽습니다
3. 환경변수 3개를 입력합니다 (저장소에는 값이 저장되지 않습니다)

   | 키 | 값 |
   |---|---|
   | `GMAIL_SENDER` | 보내는 Gmail 주소 |
   | `GMAIL_APP_PASSWORD` | 2단계에서 발급한 앱 비밀번호 16자리 |
   | `KAKAO_SKILL_SECRET` | 2번에서 생성한 시크릿 |

4. 배포가 끝나면 `https://send-biz-card-xxxx.onrender.com` 형태의 URL이 나옵니다
5. 확인: `curl https://<주소>/health` → `OK`

### 4. 콜드 스타트 방지 (중요)

Render 무료 플랜은 **15분간 요청이 없으면 서버가 잠듭니다.** 깨어나는 데 30~60초가
걸리는데, 카카오 챗봇은 5초 안에 응답이 없으면 오류를 띄웁니다. 그래서 주기적으로
서버를 깨워 두어야 합니다.

[cron-job.org](https://cron-job.org) (무료) 에서:

- URL: `https://<주소>/health`
- 실행 주기: **10분마다**

`/health` 는 인증이 필요 없으므로 헤더 설정 없이 바로 등록하면 됩니다.
등록 후 첫 응답이 `200 OK` 인지 확인하세요.

### 5. 카카오 i 오픈빌더 연결

1. 스킬 → **스킬 서버 URL**: `https://<주소>/kakao`
2. 같은 화면의 **헤더 추가**에서

   | 헤더 이름 | 값 |
   |---|---|
   | `X-Skill-Secret` | 2번에서 생성한 시크릿 |

3. 스킬을 블록에 연결하고 배포

> 이 헤더가 없거나 값이 다르면 서버는 `401` 을 돌려주고 메일을 보내지 않습니다.
> 헤더 설정을 빠뜨리면 챗봇이 계속 오류를 내므로, 값을 정확히 붙여넣었는지 확인하세요.

---

## 로컬 실행

```bash
pip install -r requirements.txt
export GMAIL_SENDER="you@gmail.com"
export GMAIL_APP_PASSWORD="앱비밀번호16자리"
python app.py            # http://localhost:5000
```

로컬에서는 `KAKAO_SKILL_SECRET` 을 설정하지 않으면 헤더 검증을 건너뛰므로,
기존처럼 ngrok 등으로 바로 테스트할 수 있습니다. 다만 시작 시 경고가 출력됩니다.

---

## 환경변수 정리

| 키 | 필수 | 설명 |
|---|---|---|
| `GMAIL_SENDER` | 배포 시 필수 | 보내는 Gmail 주소. `config.yaml` 값을 덮어씀 |
| `GMAIL_APP_PASSWORD` | 배포 시 필수 | Gmail 앱 비밀번호 |
| `KAKAO_SKILL_SECRET` | 배포 시 필수 | `X-Skill-Secret` 헤더 검증값. 미설정 시 검증 생략 |
| `PORT` | 자동 | 클라우드 플랫폼이 주입. 로컬은 `config.yaml` 의 5000 |

---

## 다른 플랫폼으로 배포할 경우

`Procfile` 과 환경변수만 있으면 되므로 Railway, Fly.io, Cloud Run 에서도 그대로 동작합니다.
Railway 는 콜드 스타트가 없어 4번(핑 설정)을 건너뛸 수 있지만 유료입니다.
