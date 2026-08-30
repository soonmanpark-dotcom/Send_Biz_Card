import re
import os
import hmac
import yaml
import threading
from flask import Flask, request, jsonify
from email_sender import EmailSender

# ── 설정 로드 ─────────────────────────────────────────────────────────────────
with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 환경변수로 민감 정보 덮어쓰기
if os.environ.get("GMAIL_APP_PASSWORD"):
    config["gmail"]["app_password"] = os.environ["GMAIL_APP_PASSWORD"]
if os.environ.get("GMAIL_SENDER"):
    config["gmail"]["sender_address"] = os.environ["GMAIL_SENDER"]

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
app = Flask(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


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
    return jsonify(sender.check())


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    print(f"서버 시작: http://localhost:{PORT}")
    print(f"트리거 문구: '{TRIGGER}'")
    app.run(host="0.0.0.0", port=PORT)
