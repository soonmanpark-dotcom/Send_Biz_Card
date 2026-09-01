# Send_Biz_Card

카카오톡 챗봇으로 이메일 주소를 받아, 명함(연락처) HTML 메일을 발송하는 스킬 서버.

- `app.py` — Flask 스킬 서버 (`/kakao` 스킬 엔드포인트, `/health` 헬스체크)
- `email_sender.py` — Gmail SMTP 발송 + 명함 HTML 생성
- `config.yaml` — 명함 내용 / 트리거 문구 (민감 정보는 환경변수로 주입)

---

## 클라우드 배포 (Render 무료 플랜)

### 1. 사전 준비: Brevo API 키

**Render 는 아웃바운드 SMTP(465/587) 를 차단합니다.** 같은 인스턴스에서 443 포트는
정상 연결되지만 메일 포트는 패킷이 조용히 버려집니다(timeout). 그래서 클라우드에서는
SMTP 대신 **HTTPS 로 보내는 메일 API** 를 써야 합니다.

[Brevo](https://www.brevo.com) 무료 플랜(하루 300통)을 씁니다.

1. 가입 후 **Senders** 에 발신 주소(`soonman.park@gmail.com`)를 등록하고 인증 메일 확인
2. **SMTP & API → API Keys** 에서 키를 발급 (`xkeysib-` 로 시작)

`BREVO_API_KEY` 환경변수가 설정되면 자동으로 Brevo 로 발송하고, 없으면 기존 SMTP 를
그대로 씁니다. 로컬처럼 SMTP 가 열린 환경에서는 키 없이 예전 방식으로 동작합니다.

> SMTP 방식을 계속 쓰려면 Gmail 2단계 인증을 켜고
> [앱 비밀번호](https://myaccount.google.com/apppasswords) 16자리를 발급해
> `GMAIL_APP_PASSWORD` 에 넣으면 됩니다.

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
   | `GMAIL_SENDER` | 보내는 주소 (Brevo 에 등록·인증한 주소여야 함) |
   | `BREVO_API_KEY` | 1번에서 발급한 Brevo API 키 |
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

시크릿을 전달하는 방법이 두 가지 있습니다. **둘 중 편한 쪽 하나만** 쓰면 됩니다.

**방법 A — 경로에 시크릿 (헤더 설정이 없어도 됨, 간단)**

스킬 서버 URL 에 시크릿을 그대로 붙입니다.

```
https://<주소>/kakao/<시크릿>
```

**방법 B — 헤더에 시크릿 (URL 에 시크릿이 노출되지 않음)**

- 스킬 서버 URL: `https://<주소>/kakao`
- 헤더 추가: `X-Skill-Secret` = 2번에서 생성한 시크릿

둘 중 어느 것도 맞지 않으면 서버는 `401` 을 돌려주고 메일을 보내지 않습니다.
설정 후 스킬을 블록에 연결하고 **봇을 배포**해야 실제 대화에 반영됩니다.

> 방법 A 는 시크릿이 URL 에 들어가므로 접근 로그에 남습니다. 헤더 설정이 가능하다면
> 방법 B 가 더 안전합니다. 시크릿이 노출되었다고 판단되면 `KAKAO_SKILL_SECRET` 을
> 새 값으로 바꾸고 오픈빌더 설정도 함께 갱신하세요.

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
| `GMAIL_SENDER` | 배포 시 필수 | 보내는 주소. `config.yaml` 값을 덮어씀 |
| `BREVO_API_KEY` | 배포 시 필수 | Brevo API 키. 있으면 Brevo(HTTPS), 없으면 SMTP 로 발송 |
| `GMAIL_APP_PASSWORD` | SMTP 사용 시 | Gmail 앱 비밀번호 (SMTP 가 열린 환경에서만 유효) |
| `KAKAO_SKILL_SECRET` | 배포 시 필수 | `X-Skill-Secret` 헤더 검증값. 미설정 시 검증 생략 |
| `PORT` | 자동 | 클라우드 플랫폼이 주입. 로컬은 `config.yaml` 의 5000 |

---

## 다른 플랫폼으로 배포할 경우

`Procfile` 과 환경변수만 있으면 되므로 Railway, Fly.io, Cloud Run 에서도 그대로 동작합니다.
Railway 는 콜드 스타트가 없어 4번(핑 설정)을 건너뛸 수 있지만 유료입니다.

---

## 발송 설정 진단

메일이 도착하지 않을 때, 원인을 구분하는 진단 경로가 있습니다. **메일은 보내지 않습니다.**

```
GET https://<주소>/selftest/<시크릿>
```

- Brevo 모드: API 키 유효성, 계정 메일, **발신 주소 등록·인증 여부**(`sender_is_registered`)
- SMTP 모드: 465/587 주소별 TCP 연결 결과와 로그인 결과

비밀번호와 API 키 자체는 응답에 포함되지 않고 길이만 표시됩니다.
`sender_is_registered` 가 `false` 면 Brevo 에서 발신 주소 인증을 마치지 않은 것입니다.

---

## Gmail API 로 발송하기 (보낸사람을 실제 Gmail 주소로)

Brevo 는 무료 메일 도메인(gmail.com 등)을 발신 주소로 쓰면 DMARC 때문에
보낸사람을 `@<id>.brevosend.com` 으로 바꿔서 내보낸다. 실제 Gmail 주소를
그대로 보이게 하려면 Gmail API 를 쓴다. HTTPS 를 쓰므로 SMTP 가 막힌
호스팅에서도 동작한다.

### 1. 구글 클라우드 설정

1. [console.cloud.google.com](https://console.cloud.google.com) 에서 프로젝트 생성
2. **API 및 서비스 → 라이브러리** 에서 **Gmail API** 사용 설정
3. **OAuth 동의 화면**: External, 테스트 사용자에 본인 Gmail 추가
4. **사용자 인증 정보 → OAuth 클라이언트 ID → 웹 애플리케이션**
   - 승인된 리디렉션 URI: `https://<주소>/oauth/callback`
5. 클라이언트 ID 와 보안 비밀번호를 Render 환경변수에 넣는다
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

### 2. 리프레시 토큰 받기

브라우저로 아래 주소에 접속해 구글 로그인·동의를 마치면 화면에 값이 나온다.

```
https://<주소>/oauth/start/<시크릿>
```

그 값을 `GOOGLE_REFRESH_TOKEN` 환경변수로 넣고 저장하면 자동으로 Gmail API 로 전환된다.

### 발송 방식 우선순위

| 조건 | 사용 방식 |
|---|---|
| `GOOGLE_*` 세 값이 모두 있음 | Gmail API (보낸사람 = 실제 Gmail 주소) |
| `BREVO_API_KEY` 있음 | Brevo |
| 둘 다 없음 | SMTP |

`/selftest/<시크릿>` 이 현재 어떤 방식인지와 인증 상태를 알려준다.
