import os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.abspath(os.path.dirname(__file__))
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
ALLOWED = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "studyhub-demo-key-change-for-real-use"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE, "studyhub.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOADS
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(300), default="")
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    teacher = db.relationship("User", backref="notes")

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def teacher_only(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "teacher":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

@app.route("/")
def home():
    latest = Note.query.order_by(Note.uploaded_at.desc()).limit(6).all()
    return render_template("index.html", latest=latest,
        note_count=Note.query.count(),
        teacher_count=User.query.filter_by(role="teacher").count(),
        student_count=User.query.filter_by(role="student").count())

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")
        if not name or not email or len(password) < 8:
            flash("Fill in every field. Password must have at least 8 characters.", "error")
        elif role not in ("student", "teacher"):
            flash("Choose Student or Teacher.", "error")
        elif User.query.filter_by(email=email).first():
            flash("This email is already registered. Please log in.", "error")
        else:
            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Account created! You can log in now.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back, " + user.name + "!", "success")
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password. Try the email you registered with.", "error")
    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "teacher":
        notes = Note.query.filter_by(teacher_id=current_user.id).order_by(Note.uploaded_at.desc()).all()
    else:
        notes = Note.query.order_by(Note.uploaded_at.desc()).all()
    return render_template("dashboard.html", notes=notes)

@app.route("/notes")
def notes():
    subject = request.args.get("subject", "").strip()
    search = request.args.get("q", "").strip()
    query = Note.query
    if subject:
        query = query.filter_by(subject=subject)
    if search:
        query = query.filter(Note.title.ilike(f"%{search}%") |
                             Note.subject.ilike(f"%{search}%") |
                             Note.description.ilike(f"%{search}%"))
    all_notes = query.order_by(Note.uploaded_at.desc()).all()
    subjects = [row[0] for row in db.session.query(Note.subject).distinct().order_by(Note.subject).all()]
    return render_template("notes.html", notes=all_notes, subjects=subjects, selected_subject=subject, q=search)

@app.route("/upload", methods=["GET", "POST"])
@teacher_only
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        file = request.files.get("file")
        if not title or not subject or not file or not file.filename:
            flash("Enter a title and subject, then choose a file.", "error")
        elif "." not in file.filename or file.filename.rsplit(".", 1)[1].lower() not in ALLOWED:
            flash("Allowed files: PDF, DOC/DOCX, PPT/PPTX, TXT, PNG and JPG.", "error")
        else:
            original = secure_filename(file.filename)
            stored = datetime.utcnow().strftime("%Y%m%d%H%M%S%f") + "_" + original
            file.save(os.path.join(UPLOADS, stored))
            note = Note(title=title, subject=subject, description=description,
                        filename=stored, original_filename=original, teacher_id=current_user.id)
            db.session.add(note)
            db.session.commit()
            flash("Note uploaded successfully!", "success")
            return redirect(url_for("dashboard"))
    return render_template("upload.html")

@app.route("/download/<int:note_id>")
def download(note_id):
    note = db.session.get(Note, note_id)
    if note is None:
        abort(404)
    return send_from_directory(UPLOADS, note.filename, as_attachment=True,
                               download_name=note.original_filename)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You are logged out.", "success")
    return redirect(url_for("home"))

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="Only a teacher account can upload notes."), 403

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="That page or note was not found."), 404

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
