import os
import threading

from flask import Flask, request

import bot as botmod

app = Flask(__name__)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")

_started = False
_lock = threading.Lock()

def _startup_once():
    global _started
    with _lock:
        if _started:
            return
        _started = True
        botmod.migrate_legacy_json_if_present()
        botmod.register_commands()
        threading.Thread(target=botmod.scanner_loop, daemon=True).start()
        print("Bot started (webhook mode).", flush=True)

@app.route("/")
def health():
    _startup_once()
    return "ok", 200

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    _startup_once()
    update = request.get_json(force=True, silent=True) or {}
    threading.Thread(target=botmod.dispatch, args=(update,), daemon=True).start()
    return "ok", 200

if __name__ == "__main__":
    _startup_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
