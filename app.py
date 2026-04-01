import os
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///forgetmenot.db"
)
db = SQLAlchemy(app)


class Med(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    dosage = db.Column(db.String(60), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#4A90D9")
    active = db.Column(db.Boolean, default=True)
    logs = db.relationship("MedLog", backref="med", lazy=True, order_by="MedLog.taken_at.desc()")


class MedLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    med_id = db.Column(db.Integer, db.ForeignKey("med.id"), nullable=False)
    taken_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


with app.app_context():
    db.create_all()


# --- Pages ---

@app.route("/")
def index():
    meds = Med.query.filter_by(active=True).all()
    return render_template("index.html", meds=meds)


@app.route("/history")
def history():
    logs = (
        MedLog.query
        .join(Med)
        .order_by(MedLog.taken_at.desc())
        .limit(200)
        .all()
    )
    # Group by date
    grouped = {}
    for log in logs:
        day = log.taken_at.strftime("%A, %b %d")
        grouped.setdefault(day, []).append(log)
    return render_template("history.html", grouped=grouped)


@app.route("/manage")
def manage():
    meds = Med.query.all()
    return render_template("manage.html", meds=meds)


# --- Actions ---

@app.route("/log/<int:med_id>", methods=["POST"])
def log_med(med_id):
    med = Med.query.get_or_404(med_id)
    entry = MedLog(med_id=med.id)
    db.session.add(entry)
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/undo/<int:log_id>", methods=["POST"])
def undo_log(log_id):
    log = MedLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/med/add", methods=["POST"])
def add_med():
    name = request.form.get("name", "").strip()
    dosage = request.form.get("dosage", "").strip()
    color = request.form.get("color", "#4A90D9")
    if name and dosage:
        med = Med(name=name, dosage=dosage, color=color)
        db.session.add(med)
        db.session.commit()
    return redirect(url_for("manage"))


@app.route("/med/<int:med_id>/toggle", methods=["POST"])
def toggle_med(med_id):
    med = Med.query.get_or_404(med_id)
    med.active = not med.active
    db.session.commit()
    return redirect(url_for("manage"))


@app.route("/med/<int:med_id>/delete", methods=["POST"])
def delete_med(med_id):
    med = Med.query.get_or_404(med_id)
    MedLog.query.filter_by(med_id=med.id).delete()
    db.session.delete(med)
    db.session.commit()
    return redirect(url_for("manage"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
