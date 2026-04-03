import os
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///forgetmenot.db"
)
db = SQLAlchemy(app)


FREQUENCY_HOURS = {
    "1x/day": 24,
    "2x/day": 12,
    "3x/day": 8,
    "4x/day": 6,
    "as_needed": None,
}

FREQUENCY_LABELS = {
    "1x/day": "1x / day",
    "2x/day": "2x / day",
    "3x/day": "3x / day",
    "4x/day": "4x / day",
    "as_needed": "As needed",
}


class Med(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    frequency = db.Column(db.String(20), nullable=False, default="as_needed")
    # DB values: "1x/day", "2x/day", "3x/day", "4x/day", "as_needed"
    color = db.Column(db.String(7), nullable=False, default="#4A90D9")
    active = db.Column(db.Boolean, default=True)
    logs = db.relationship("MedLog", backref="med", lazy=True, order_by="MedLog.taken_at.desc()")

    @property
    def last_taken(self):
        if self.logs:
            return self.logs[0].taken_at
        return None

    @property
    def next_dose_at(self):
        hours = FREQUENCY_HOURS.get(self.frequency)
        if hours is None or not self.logs:
            return None
        return self.logs[0].taken_at + timedelta(hours=hours)

    @property
    def is_overdue(self):
        nxt = self.next_dose_at
        if nxt is None:
            return False
        now = datetime.now(timezone.utc)
        # Handle naive datetimes from DB
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return now > nxt

    @property
    def frequency_label(self):
        return FREQUENCY_LABELS.get(self.frequency, self.frequency)


class MedLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    med_id = db.Column(db.Integer, db.ForeignKey("med.id"), nullable=False)
    taken_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


with app.app_context():
    db.create_all()
    # Migrate: add frequency column if missing
    with db.engine.connect() as conn:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [c["name"] for c in inspector.get_columns("med")]
        if "frequency" not in columns:
            conn.execute(db.text("ALTER TABLE med ADD COLUMN frequency VARCHAR(20) NOT NULL DEFAULT 'as_needed'"))
            conn.commit()


# --- Pages ---

@app.route("/")
def index():
    meds = Med.query.filter_by(active=True).all()
    return render_template("index.html", meds=meds)


@app.route("/med/<int:med_id>")
def med_detail(med_id):
    med = Med.query.get_or_404(med_id)
    logs = MedLog.query.filter_by(med_id=med.id).order_by(MedLog.taken_at.desc()).limit(50).all()
    return render_template("detail.html", med=med, logs=logs, frequency_labels=FREQUENCY_LABELS)


@app.route("/history")
def history():
    logs = (
        MedLog.query
        .join(Med)
        .order_by(MedLog.taken_at.desc())
        .limit(200)
        .all()
    )
    grouped = {}
    for log in logs:
        day = log.taken_at.strftime("%A, %b %d")
        grouped.setdefault(day, []).append(log)
    return render_template("history.html", grouped=grouped)


# --- Actions ---

@app.route("/log/<int:med_id>", methods=["POST"])
def log_med(med_id):
    med = Med.query.get_or_404(med_id)
    taken_at_str = request.form.get("taken_at", "").strip()
    if taken_at_str:
        taken_at = datetime.fromisoformat(taken_at_str).replace(tzinfo=timezone.utc)
        entry = MedLog(med_id=med.id, taken_at=taken_at)
    else:
        entry = MedLog(med_id=med.id)
    db.session.add(entry)
    db.session.commit()
    redirect_to = request.form.get("redirect", "index")
    if redirect_to == "detail":
        return redirect(url_for("med_detail", med_id=med.id))
    return redirect(url_for("index"))


@app.route("/log/<int:log_id>/edit", methods=["POST"])
def edit_log(log_id):
    log = MedLog.query.get_or_404(log_id)
    taken_at_str = request.form.get("taken_at", "").strip()
    if taken_at_str:
        log.taken_at = datetime.fromisoformat(taken_at_str).replace(tzinfo=timezone.utc)
        db.session.commit()
    return redirect(url_for("med_detail", med_id=log.med_id))


@app.route("/undo/<int:log_id>", methods=["POST"])
def undo_log(log_id):
    log = MedLog.query.get_or_404(log_id)
    med_id = log.med_id
    db.session.delete(log)
    db.session.commit()
    redirect_to = request.form.get("redirect", "index")
    if redirect_to == "detail":
        return redirect(url_for("med_detail", med_id=med_id))
    return redirect(url_for("index"))


@app.route("/med/add", methods=["POST"])
def add_med():
    name = request.form.get("name", "").strip()
    frequency = request.form.get("frequency", "as_needed")
    color = request.form.get("color", "#4A90D9")
    if name:
        med = Med(name=name, frequency=frequency, color=color)
        db.session.add(med)
        db.session.commit()
    return redirect(url_for("index"))


@app.route("/med/<int:med_id>/edit", methods=["POST"])
def edit_med(med_id):
    med = Med.query.get_or_404(med_id)
    name = request.form.get("name", "").strip()
    frequency = request.form.get("frequency", med.frequency)
    color = request.form.get("color", med.color)
    if name:
        med.name = name
    med.frequency = frequency
    med.color = color
    db.session.commit()
    return redirect(url_for("med_detail", med_id=med.id))


@app.route("/med/<int:med_id>/toggle", methods=["POST"])
def toggle_med(med_id):
    med = Med.query.get_or_404(med_id)
    med.active = not med.active
    db.session.commit()
    redirect_to = request.form.get("redirect", "index")
    if redirect_to == "detail":
        return redirect(url_for("med_detail", med_id=med.id))
    return redirect(url_for("index"))


@app.route("/med/<int:med_id>/delete", methods=["POST"])
def delete_med(med_id):
    med = Med.query.get_or_404(med_id)
    MedLog.query.filter_by(med_id=med.id).delete()
    db.session.delete(med)
    db.session.commit()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
