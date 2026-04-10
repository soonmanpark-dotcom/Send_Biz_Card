import re
import os
import yaml
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


@app.route("/kakao", methods=["POST"])
def kakao_skill():
    body = request.get_json(force=True, silent=True) or {}
    utterance: str = (body.get("userRequest", {}).get("utterance") or "").strip()

    print(f"[수신] {utterance}")

    # 트리거 문구 확인
    if TRIGGER not in utterance:
        return jsonify(_kakao_text(
            f"'{TRIGGER}' 문구와 이메일 주소를 함께 입력해 주세요.\n"
            f"예) hong@example.com {TRIGGER}"
        ))

    # 이메일 주소 추출
    match = EMAIL_PATTERN.search(utterance)
    if not match:
        return jsonify(_kakao_text(
            "이메일 주소를 찾을 수 없습니다.\n"
            f"예) hong@example.com {TRIGGER}"
        ))

    email_addr = match.group()
    print(f"[발송 시도] → {email_addr}")

    if sender.send(email_addr):
        reply = f"✅ {email_addr} 으로 명함을 보냈습니다."
        print(f"[발송 완료] → {email_addr}")
    else:
        reply = f"❌ 이메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요."
        print(f"[발송 실패] → {email_addr}")

    return jsonify(_kakao_text(reply))


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    print(f"서버 시작: http://localhost:{PORT}")
    print(f"트리거 문구: '{TRIGGER}'")
    app.run(host="0.0.0.0", port=PORT)
