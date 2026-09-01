import re
import os
import hmac
import json
import secrets
import hashlib
import urllib.error
import urllib.request
from urllib.parse import urlencode
import yaml
import threading
from flask import Flask, request, jsonify, redirect
from email_sender import EmailSender
from rate_limit import RateLimiter

# ── 설정 로드 ─────────────────────────────────────────────────────────────────
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 환경변수로 민감 정보 덮어쓰기
if os.environ.get("GMAIL_APP_PASSWORD"):
    config["gmail"]["app_password"] = os.environ["GMAIL_APP_PASSWORD"]
if os.environ.get("GMAIL_SENDER"):
    config["gmail"]["sender_address"] = os.environ["GMAIL_SENDER"]
if os.environ.get("BREVO_API_KEY"):
    config.setdefault("brevo", {})["api_key"] = os.environ["BREVO_API_KEY"]
for _env, _key in (
    ("GOOGLE_CLIENT_ID", "client_id"),
    ("GOOGLE_CLIENT_SECRET", "client_secret"),
    ("GOOGLE_REFRESH_TOKEN", "refresh_token"),
):
    if os.environ.get(_env):
        config.setdefault("gmail_api", {})[_key] = os.environ[_env]

TRIGGER = config["bot"]["trigger_phrase"]
PORT = int(os.environ.get("PORT", config["bot"]["port"]))

# ── 스킬 서버 인증 ────────────────────────────────────────────────────────────
# 공개 URL 은 누구나 호출할 수 있으므로 시크릿으로 호출자를 검증한다. 두 가지를 모두 받는다.
#   1) 헤더 방식  : POST /kakao          + X-Skill-Secret 헤더
#   2) 경로 방식  : POST /kakao/<시크릿>  (헤더 설정을 지원하지 않는 클라이언트용)
# 환경변수가 비어 있으면 검증을 건너뛴다(로컬 개발용).
SECRET_HEADER = "X-Skill-Secret"
SKILL_SECRET = os.environ.get("KAKAO_SKILL_SECRET", "").strip()
if not SKILL_SECRET:
    print(
        f"[경고] {SECRET_HEADER} 검증이 꺼져 있습니다. "
        "공개 배포 시 KAKAO_SKILL_SECRET 환경변수를 반드시 설정하세요."
    )

sender = EmailSender(config)
limiter = RateLimiter(config.get("limits"))
app = Flask(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

LIMIT_MESSAGES = {
    "recipient": "📮 방금 같은 주소로 명함을 보내드렸습니다.\n\n"
                 "메일함을 확인해 주세요. 스팸함에 있을 수도 있습니다.",
    "hour": "⏳ 지금 요청이 많아 잠시 쉬어가는 중입니다.\n\n"
            "잠시 후 다시 시도해 주세요.",
    "day": "⏳ 오늘 발송 한도에 도달했습니다.\n\n"
           "내일 다시 시도해 주세요.",
}


def _kakao_text(text: str) -> dict:
    """Kakao i Open Builder SimpleText 응답 형식."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}]
        }
    }


def _authorized(req, token: str | None) -> bool:
    """헤더 또는 URL 경로의 시크릿을 검증. 환경변수 미설정 시에는 통과시킨다."""
    if not SKILL_SECRET:
        return True
    if hmac.compare_digest(req.headers.get(SECRET_HEADER, ""), SKILL_SECRET):
        return True
    return token is not None and hmac.compare_digest(token, SKILL_SECRET)


@app.route("/kakao", methods=["POST"])
@app.route("/kakao/<token>", methods=["POST"])
def kakao_skill(token: str | None = None):
    if not _authorized(request, token):
        print("[차단] 시크릿 헤더 불일치")
        return jsonify({"error": "unauthorized"}), 401

    body = request.get_json(force=True, silent=True) or {}
    utterance: str = (body.get("userRequest", {}).get("utterance") or "").strip()

    print(f"[수신] {utterance}")

    # 이메일 주소 추출
    match = EMAIL_PATTERN.search(utterance)
    if not match:
        return jsonify(_kakao_text(
            "📧 이메일 주소가 입력되지 않았습니다.\n\n"
            "이메일 주소를 함께 입력해 주세요.\n"
            f"예) hong@example.com {TRIGGER}"
        ))

    email_addr = match.group()

    blocked = limiter.check_and_record(email_addr)
    if blocked:
        print(f"[제한] {blocked} 한도 초과")
        return jsonify(_kakao_text(LIMIT_MESSAGES[blocked]))

    print(f"[발송 시도] → {email_addr}")

    # 백그라운드에서 이메일 발송 (카카오 5초 타임아웃 방지)
    def send_async():
        ok = sender.send(email_addr)
        print(f"[발송 {'완료' if ok else '실패'}] → {email_addr}")

    threading.Thread(target=send_async, daemon=True).start()

    reply = f"📨 {email_addr} 으로 명함을 발송 중입니다. 잠시 후 이메일을 확인해 주세요."
    return jsonify(_kakao_text(reply))


@app.route("/selftest/<token>", methods=["GET"])
def selftest(token: str):
    """Gmail 설정 진단용. 시크릿을 아는 경우에만 응답하고, 메일은 보내지 않는다."""
    if not _authorized(request, token):
        return jsonify({"error": "unauthorized"}), 401
    info = sender.check()
    # 지금 서버에 반영된 명함 문구. 내용 변경이 배포됐는지 확인용.
    info["usage"] = limiter.snapshot()
    info["card"] = {
        "name": config["card"]["name"],
        "lines": config["card"].get("lines") or [],
    }
    return jsonify(info)


# ── 안내 페이지 ───────────────────────────────────────────────────────
# 구글 OAuth 앱을 프로덕션으로 게시하려면 홈페이지·개인정보처리방침·이용약관
# 주소가 필요하다. 승인된 도메인이 이 서버이므로 여기서 함께 제공한다.
_PAGE_CSS = (
    "font-family:system-ui,'Malgun Gothic',sans-serif;max-width:720px;"
    "margin:48px auto;padding:0 20px;line-height:1.75;color:#222"
)


def _doc(title: str, body: str):
    return (
        f'<!doctype html><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        f'<body style="{_PAGE_CSS}">{body}'
        '<hr style="margin:40px 0 16px;border:none;border-top:1px solid #ddd">'
        '<p style="font-size:13px;color:#777">'
        '<a href="/" style="color:#0077cc">홈</a> · '
        '<a href="/privacy" style="color:#0077cc">개인정보처리방침</a> · '
        '<a href="/terms" style="color:#0077cc">이용약관</a></p>'
        "</body>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


@app.route("/", methods=["GET"])
def home():
    return _doc(
        "SendBizCard",
        "<h1>SendBizCard</h1>"
        "<p>카카오톡 챗봇으로 이메일 주소를 받아, 운영자의 명함(연락처) 정보를 "
        "해당 주소로 한 번 보내주는 개인용 서비스입니다.</p>"
        "<h2>이용 방법</h2>"
        "<p>카카오톡 챗봇에 받을 이메일 주소를 함께 입력하면, 그 주소로 명함 메일이 발송됩니다.</p>"
        "<h2>운영자</h2>"
        "<p>박순만 · <a href='mailto:soonman.park@gmail.com' style='color:#0077cc'>"
        "soonman.park@gmail.com</a></p>",
    )


@app.route("/privacy", methods=["GET"])
def privacy():
    return _doc(
        "개인정보처리방침 — SendBizCard",
        "<h1>개인정보처리방침</h1>"
        "<p>SendBizCard(이하 '서비스')는 운영자 개인이 명함 정보를 전달할 목적으로 "
        "운영하는 비영리 서비스입니다.</p>"
        "<h2>1. 수집하는 정보</h2>"
        "<p>이용자가 챗봇 대화에 직접 입력한 <b>수신 이메일 주소</b> 하나만 사용합니다. "
        "이름, 전화번호 등 다른 개인정보는 수집하지 않습니다.</p>"
        "<h2>2. 이용 목적</h2>"
        "<p>입력된 주소로 운영자의 명함(이름·소속·연락처) 메일을 <b>1회 발송</b>하는 "
        "목적으로만 사용합니다. 광고나 마케팅 메일을 보내지 않습니다.</p>"
        "<h2>3. 보관 및 파기</h2>"
        "<p>수신 주소를 데이터베이스에 저장하지 않습니다. 발송 처리 과정에서 서버 "
        "실행 로그에 일시적으로 기록될 수 있으며, 이 로그는 서버가 재시작되면 삭제됩니다.</p>"
        "<h2>4. 제3자 제공 및 처리 위탁</h2>"
        "<p>메일 발송을 위해 아래 서비스를 통해 전송됩니다. 발송 외의 목적으로 "
        "제3자에게 제공하지 않습니다.</p>"
        "<ul><li>Google LLC (Gmail API) — 메일 발송</li>"
        "<li>Sendinblue SAS(Brevo) — 대체 발송 수단으로 사용될 수 있음</li>"
        "<li>Render Services, Inc. — 서비스 호스팅</li></ul>"
        "<h2>5. 구글 계정 정보의 사용</h2>"
        "<p>이 서비스는 운영자 본인의 Gmail 계정으로 메일을 보내기 위해 "
        "<code>gmail.send</code> 권한만 사용합니다. 이 권한은 메일 발송에만 쓰이며, "
        "운영자의 메일을 읽거나 삭제하지 않고, 메일 내용을 제3자와 공유하지 않습니다. "
        "구글에서 받은 데이터는 다른 목적으로 사용하거나 전송하지 않습니다.</p>"
        "<h2>6. 문의</h2>"
        "<p><a href='mailto:soonman.park@gmail.com' style='color:#0077cc'>"
        "soonman.park@gmail.com</a></p>",
    )


@app.route("/terms", methods=["GET"])
def terms():
    return _doc(
        "이용약관 — SendBizCard",
        "<h1>이용약관</h1>"
        "<h2>1. 서비스 성격</h2>"
        "<p>SendBizCard는 운영자 개인이 무료로 제공하는 비영리 서비스입니다. "
        "운영자의 명함 정보를 요청한 이메일 주소로 전달합니다.</p>"
        "<h2>2. 이용자의 의무</h2>"
        "<p>이용자는 본인의 이메일 주소 또는 발송에 동의한 주소만 입력해야 합니다. "
        "타인에게 원치 않는 메일을 보내는 용도로 사용해서는 안 됩니다.</p>"
        "<h2>3. 서비스의 변경과 중단</h2>"
        "<p>운영자는 사전 통지 없이 서비스를 변경하거나 중단할 수 있습니다.</p>"
        "<h2>4. 책임의 한계</h2>"
        "<p>서비스는 있는 그대로 제공되며, 메일 발송의 지연이나 실패에 대해 "
        "법이 허용하는 범위에서 책임을 지지 않습니다.</p>"
        "<h2>5. 문의</h2>"
        "<p><a href='mailto:soonman.park@gmail.com' style='color:#0077cc'>"
        "soonman.park@gmail.com</a></p>",
    )


# ── Gmail API 인증 도우미 ─────────────────────────────────────────────
# 리프레시 토큰을 받기 위한 1회용 절차. 시크릿을 아는 경우에만 시작할 수 있다.
GOOGLE_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _oauth_state() -> str:
    """시크릿에서 파생한 고정 state. 시크릿 자체는 노출하지 않는다."""
    return hashlib.sha256(f"{SKILL_SECRET}:oauth".encode()).hexdigest()


def _page(title: str, body: str, code: int = 200):
    return (
        f'<!doctype html><meta charset="utf-8"><title>{title}</title>'
        '<body style="font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;'
        f'padding:0 20px;line-height:1.7;color:#222">{body}</body>',
        code,
        {"Content-Type": "text/html; charset=utf-8"},
    )


@app.route("/oauth/start/<token>", methods=["GET"])
def oauth_start(token: str):
    if not _authorized(request, token):
        return _page("권한 없음", "<h2>접근 권한이 없습니다.</h2>", 401)

    g = config.get("gmail_api") or {}
    if not g.get("client_id"):
        return _page(
            "설정 필요",
            "<h2>먼저 GOOGLE_CLIENT_ID 와 GOOGLE_CLIENT_SECRET 를 설정해 주세요.</h2>"
            "<p>Render 의 Environment 에 두 값을 넣고 저장한 뒤 다시 시도하세요.</p>",
            400,
        )

    params = {
        "client_id": g["client_id"],
        "redirect_uri": g.get("redirect_uri", ""),
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": _oauth_state(),
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    if request.args.get("state") != _oauth_state():
        return _page("요청 불일치", "<h2>요청이 올바르지 않습니다.</h2>", 400)

    err = request.args.get("error")
    if err:
        return _page("인증 취소됨", f"<h2>구글에서 인증이 취소되었습니다.</h2><p>{err}</p>", 400)

    code = request.args.get("code")
    g = config.get("gmail_api") or {}
    data = urlencode({
        "code": code or "",
        "client_id": g.get("client_id", ""),
        "client_secret": g.get("client_secret", ""),
        "redirect_uri": g.get("redirect_uri", ""),
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            payload = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        return _page("토큰 발급 실패", f"<h2>토큰 발급에 실패했습니다.</h2><pre>{detail}</pre>", 400)
    except Exception as e:
        return _page("토큰 발급 실패", f"<h2>토큰 발급에 실패했습니다.</h2><pre>{e}</pre>", 400)

    refresh = payload.get("refresh_token")
    if not refresh:
        return _page(
            "리프레시 토큰 없음",
            "<h2>리프레시 토큰이 오지 않았습니다.</h2>"
            "<p>이미 승인한 적이 있는 계정입니다. "
            "<a href='https://myaccount.google.com/permissions'>구글 계정의 앱 권한</a>에서 "
            "이 앱의 액세스를 삭제한 뒤 처음부터 다시 시도해 주세요.</p>",
            400,
        )

    return _page(
        "인증 완료",
        "<h2>✅ 인증이 완료되었습니다</h2>"
        "<p>아래 값을 복사해서 Render 의 Environment 에 "
        "<b>GOOGLE_REFRESH_TOKEN</b> 이라는 이름으로 넣고 저장하세요.</p>"
        f'<textarea readonly rows="4" style="width:100%;font-family:monospace;font-size:13px;'
        f'padding:10px">{refresh}</textarea>'
        "<p style='color:#a00'>이 값은 비밀번호와 같습니다. 다른 곳에 공유하지 마세요. "
        "이 화면을 닫으면 다시 볼 수 없으며, 필요하면 인증을 처음부터 다시 하면 됩니다.</p>",
    )


@app.route("/newsecret/<token>", methods=["GET"])
def new_secret(token: str):
    """새 시크릿 값을 만들어 보여준다. 서버 설정을 바꾸지는 않는다.

    현재 시크릿을 아는 경우에만 열리며, 교체는 환경변수와 카카오 설정을
    직접 바꿔야 완료된다.
    """
    if not _authorized(request, token):
        return _page("권한 없음", "<h2>접근 권한이 없습니다.</h2>", 401)

    value = secrets.token_urlsafe(32)
    return _page(
        "새 시크릿",
        "<h2>새 시크릿이 생성되었습니다</h2>"
        "<p>아래 값을 복사해 두 곳을 모두 바꾸면 교체가 끝납니다.</p>"
        f'<textarea readonly rows="3" style="width:100%;font-family:monospace;'
        f'font-size:14px;padding:10px">{value}</textarea>'
        "<ol><li>Render → Environment → <b>KAKAO_SKILL_SECRET</b> 값을 이 값으로 수정 → Save</li>"
        "<li>카카오 i 오픈빌더 → 스킬 서버 URL 끝부분을 이 값으로 수정 → 저장 → <b>배포</b></li></ol>"
        "<p style='color:#a00'>두 곳을 모두 바꿔야 챗봇이 정상 작동합니다. "
        "이 화면을 닫으면 값을 다시 볼 수 없으며, 필요하면 이 주소를 다시 열어 "
        "새 값을 만들면 됩니다.</p>",
    )


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    print(f"서버 시작: http://localhost:{PORT}")
    print(f"트리거 문구: '{TRIGGER}'")
    app.run(host="0.0.0.0", port=PORT)
