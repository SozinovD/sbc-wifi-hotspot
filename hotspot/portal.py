import logging

from flask import Flask, jsonify, redirect, render_template, request

log = logging.getLogger(__name__)


def create_app(supervisor):
    cfg = supervisor.cfg
    app = Flask(__name__)
    app.json.ensure_ascii = False

    @app.get("/")
    def index():
        return render_template("index.html", ap_ssid=cfg.ap_ssid, ap_ip=cfg.ap_ip)

    @app.get("/api/networks")
    def networks():
        return jsonify({"networks": supervisor.api_scan()})

    @app.get("/api/status")
    def status():
        return jsonify({"mode": "ap", "attempt": supervisor.last_attempt()})

    @app.post("/api/connect")
    def connect():
        data = request.get_json(silent=True) or {}
        ssid = (data.get("ssid") or "").strip()
        password = data.get("password") or ""
        if not ssid:
            return jsonify(error="укажите имя сети"), 400
        if password and len(password) < 8:
            return jsonify(error="пароль WPA2 — минимум 8 символов"), 400
        if not supervisor.request_connect(ssid, password):
            return jsonify(error="подключение уже выполняется"), 409
        log.info("connect request: ssid=%s", ssid)
        return jsonify(status="started")

    @app.route("/<path:_any>")
    def captive(_any):
        return redirect(f"http://{cfg.ap_ip}/", code=302)

    return app
