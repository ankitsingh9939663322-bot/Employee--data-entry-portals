import os
import datetime
import secrets
from io import BytesIO
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_KEY"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    if os.environ.get("RENDER") == "true" or os.environ.get("APP_ENV") == "production":
        raise RuntimeError("DATABASE_URL is required in production. Configure PostgreSQL/Supabase in Render environment variables.")
    DATABASE_URL = "sqlite:///nexora.db"
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

IST = ZoneInfo("Asia/Kolkata")
DAILY_TARGET = 250
TOTAL_UNIQUE_RECORDS = 100000
SUNDAY_WEEKDAY = 6
MIN_ACCURACY = 80.0
MAX_ACCURACY = 90.0


def now_ist():
    return datetime.datetime.now(IST)


def today_ist():
    return now_ist().date()


def is_sunday(day=None):
    return (day or today_ist()).weekday() == SUNDAY_WEEKDAY


def is_working_day(day=None):
    return not is_sunday(day)


def holiday_label(day):
    return "Sunday — Holiday" if is_sunday(day) else ""


def normalize_text(value):
    return " ".join(str(value or "").strip().split())


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_iso_date(value):
    try:
        return datetime.date.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def display_accuracy(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = MIN_ACCURACY
    return round(max(MIN_ACCURACY, min(MAX_ACCURACY, value)), 1)


def month_bounds(month_value=None):
    today = today_ist()
    if month_value:
        parsed = parse_iso_date(str(month_value) + "-01")
        if parsed:
            year, month = parsed.year, parsed.month
        else:
            year, month = today.year, today.month
    else:
        year, month = today.year, today.month
    first = datetime.date(year, month, 1)
    next_first = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    return first, next_first - datetime.timedelta(days=1)


def month_label(first):
    return first.strftime("%B %Y")


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_name = db.Column(db.String(150), nullable=False)
    employee_code = db.Column(db.String(20), unique=True, nullable=True)
    dob = db.Column(db.Date, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    current_index = db.Column(db.Integer, default=0, nullable=False)
    last_active = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now_ist, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    approved = db.Column(db.Boolean, default=False, nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_role = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(120), nullable=False)
    employee_id = db.Column(db.Integer, nullable=True)
    audit_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=now_ist, nullable=False)


class DailyResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    completed = db.Column(db.Integer, default=0, nullable=False)
    correct = db.Column(db.Integer, default=0, nullable=False)
    wrong = db.Column(db.Integer, default=0, nullable=False)
    seconds = db.Column(db.Integer, default=0, nullable=False)
    __table_args__ = (db.UniqueConstraint("employee_id", "work_date", name="uq_employee_day"),)


def audit(action, actor_role=None, actor_id=None, employee_id=None, metadata=None):
    try:
        db.session.add(AuditLog(
            actor_role=actor_role or session.get("role", "system"),
            actor_id=actor_id,
            action=action,
            employee_id=employee_id,
            audit_metadata=metadata,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def setup_database():
    db.create_all()
    try:
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        if "employee" not in tables:
            return
        columns = {c["name"] for c in inspector.get_columns("employee")}
        dialect = db.engine.dialect.name
        with db.engine.begin() as connection:
            if "employee_name" not in columns:
                connection.exec_driver_sql("ALTER TABLE employee ADD COLUMN employee_name VARCHAR(150)")
                if dialect == "postgresql":
                    connection.exec_driver_sql("UPDATE employee SET employee_name = 'Employee ' || id::text WHERE employee_name IS NULL")
                else:
                    connection.exec_driver_sql("UPDATE employee SET employee_name = 'Employee ' || CAST(id AS VARCHAR) WHERE employee_name IS NULL")
            if "employee_code" not in columns:
                connection.exec_driver_sql("ALTER TABLE employee ADD COLUMN employee_code VARCHAR(20)")
            if "current_index" not in columns:
                connection.exec_driver_sql("ALTER TABLE employee ADD COLUMN current_index INTEGER DEFAULT 0")
            if "last_active" not in columns:
                connection.exec_driver_sql("ALTER TABLE employee ADD COLUMN last_active TIMESTAMP")
            if "approved" not in columns:
                connection.exec_driver_sql("ALTER TABLE employee ADD COLUMN approved BOOLEAN DEFAULT FALSE")
                connection.exec_driver_sql("UPDATE employee SET approved = TRUE WHERE approved IS NULL")
        employees = Employee.query.order_by(Employee.id.asc()).all()
        changed = False
        for employee in employees:
            if not employee.employee_code:
                employee.employee_code = f"EMP{employee.id:04d}"
                changed = True
        if changed:
            db.session.commit()
    except Exception as exc:
        print("Database migration warning:", exc)


INDIAN_MALE_NAMES = "Aarav Aditya Akash Aman Ankit Arjun Ayush Deepak Karan Manish Mohit Naman Nikhil Prakash Rahul Raj Rakesh Rohan Sachin Sanjay Shivam Suresh Varun Vikas Vikram Yash Rajat Ravi Amit Abhishek Anurag Harsh Rishabh Ritvik Sameer Siddharth Vivek Tarun Pankaj Gaurav Naveen Rohit Sumit Vishal Kunal Dev Dhruv Kabir Arnav".split()
INDIAN_FEMALE_NAMES = "Aanya Ananya Divya Isha Kavya Meera Neha Pooja Priya Riya Sakshi Shreya Simran Sneha Sonam Tanvi Zoya Aditi Anushka Bhavna Deepika Diya Ishita Jhanvi Kajal Komal Kriti Mansi Muskan Nandini Navya Nikita Palak Pallavi Payal Radhika Rashmi Ritika Sana Sapna Shivani Shruti Sonia Swati Trisha Vandana Vidhi Ira Myra Avni".split()
FOREIGN_MALE_NAMES = "Liam Noah Oliver James William Henry Lucas Benjamin Theodore Jack Alexander Daniel Michael Ethan Jacob Logan Jackson Sebastian Mateo Leo Owen Samuel Matthew Joseph David John Wyatt Carter Julian Grayson Levi Isaac Gabriel Anthony Dylan Luke Jayden Asher Ezra Hudson Thomas Charles Christopher Jaxon Mason Elias Nathan Adam Ryan Nathaniel".split()
FOREIGN_FEMALE_NAMES = "Olivia Emma Amelia Charlotte Mia Sophia Isabella Evelyn Ava Luna Harper Camila Sofia Eleanor Elizabeth Gianna Violet Ella Hazel Lily Aurora Nora Ellie Chloe Aria Scarlett Layla Mila Nina Grace Hannah Zoey Victoria Riley Lillian Penelope Elena Naomi Claire Lucy Alice Ruby Stella Ivy Maya Leah Eliana Sarah Madeline Eva".split()

INDIAN_SURNAMES = "Sharma Verma Singh Kumar Gupta Yadav Patel Jain Mehta Agarwal Mishra Tiwari Pandey Chauhan Rathore Joshi Malhotra Kapoor Saxena Srivastava Das Roy Chatterjee Bose Reddy Rao Nair Iyer Pillai Shah Bansal Saini Thakur Tripathi Dubey Khan Ansari Sheikh Menon Mukherjee".split()
FOREIGN_SURNAMES = "Smith Johnson Williams Brown Jones Miller Davis Wilson Taylor Anderson Thomas Moore Martin Jackson Thompson White Harris Clark Lewis Robinson Walker Young Allen King Wright Scott Green Baker Adams Nelson Hill Campbell Mitchell Roberts Carter Phillips Evans Turner Parker Collins".split()
INDIAN_CITIES = "Delhi|New Delhi|Mumbai|Pune|Jaipur|Lucknow|Kanpur|Agra|Noida|Gurugram|Ghaziabad|Faridabad|Chandigarh|Amritsar|Ludhiana|Dehradun|Haridwar|Patna|Ranchi|Kolkata|Bhopal|Indore|Jabalpur|Ahmedabad|Surat|Vadodara|Rajkot|Hyderabad|Bengaluru|Chennai|Kochi|Coimbatore|Bhubaneswar|Visakhapatnam|Nagpur|Nashik|Varanasi|Prayagraj|Meerut|Mysuru".split("|")
FOREIGN_CITIES = "London|Manchester|Birmingham|Liverpool|New York|Los Angeles|Chicago|Houston|Toronto|Vancouver|Montreal|Sydney|Melbourne|Brisbane|Auckland|Dublin|Paris|Berlin|Munich|Amsterdam|Madrid|Barcelona|Rome|Milan|Vienna|Zurich|Singapore|Tokyo|Osaka|Seoul|Dubai|Abu Dhabi|Doha|Cape Town|Johannesburg|São Paulo|Mexico City|Copenhagen|Stockholm|Oslo".split("|")
EMAIL_DOMAINS = ["gmail.com", "outlook.com", "yahoo.com", "icloud.com", "hotmail.com"]

NAME_MASTER = ([{"first": n, "gender": "male", "origin": "indian"} for n in INDIAN_MALE_NAMES] +
               [{"first": n, "gender": "female", "origin": "indian"} for n in INDIAN_FEMALE_NAMES] +
               [{"first": n, "gender": "male", "origin": "foreign"} for n in FOREIGN_MALE_NAMES] +
               [{"first": n, "gender": "female", "origin": "foreign"} for n in FOREIGN_FEMALE_NAMES])


def name_profile(index):
    return NAME_MASTER[index % len(NAME_MASTER)]


def surname_for_profile(profile, index):
    pool = INDIAN_SURNAMES if profile["origin"] == "indian" else FOREIGN_SURNAMES
    multiplier = 7 if profile["origin"] == "indian" else 11
    divisor = 31 if profile["origin"] == "indian" else 29
    return pool[(index * multiplier + index // divisor) % len(pool)]


def city_for_profile(profile, index):
    if profile["origin"] == "foreign":
        return FOREIGN_CITIES[(index * 13 + index // 17) % len(FOREIGN_CITIES)]
    if index % 17 == 0:
        return FOREIGN_CITIES[(index * 5 + index // 19) % len(FOREIGN_CITIES)]
    return INDIAN_CITIES[(index * 9 + index // 23) % len(INDIAN_CITIES)]


def build_unique_records():
    records, seen = [], set()
    previous_name = None
    candidate_index = 0
    while len(records) < TOTAL_UNIQUE_RECORDS:
        profile = name_profile(candidate_index)
        first = profile["first"]
        if first == previous_name:
            candidate_index += 1
            continue
        last = surname_for_profile(profile, candidate_index)
        city = city_for_profile(profile, candidate_index)
        age = 18 + candidate_index % 43
        phone = str(6 + candidate_index % 4) + f"{candidate_index:09d}"
        email = f"{first.lower()}.{last.lower()}.{candidate_index + 1:06d}@{EMAIL_DOMAINS[candidate_index % len(EMAIL_DOMAINS)]}"
        record = {"name": f"{first} {last}", "age": age, "city": city, "phone": phone, "email": email}
        key = tuple(record.values())
        if key not in seen:
            seen.add(key)
            records.append(record)
            previous_name = first
        candidate_index += 1
    return records


UNIQUE_RECORD_POOL = build_unique_records()


def working_day_number(day):
    start = datetime.date(2026, 1, 1)
    if day < start:
        return 0
    count, current = 0, start
    while current < day:
        if is_working_day(current):
            count += 1
        current += datetime.timedelta(days=1)
    return count


def daily_records(day):
    if is_sunday(day):
        return []
    total_batches = TOTAL_UNIQUE_RECORDS // DAILY_TARGET
    batch = working_day_number(day) % total_batches
    start = batch * DAILY_TARGET
    return UNIQUE_RECORD_POOL[start:start + DAILY_TARGET]


def get_or_create_daily_result(employee_id, work_date):
    result = DailyResult.query.filter_by(employee_id=employee_id, work_date=work_date).first()
    if not result:
        result = DailyResult(employee_id=employee_id, work_date=work_date)
        db.session.add(result)
        db.session.commit()
    return result


def employee_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "employee" or not session.get("employee_id"):
            return redirect(url_for("login"))
        employee = db.session.get(Employee, session.get("employee_id"))
        if not employee or not employee.active:
            session.clear()
            return redirect(url_for("login"))
        if not employee.approved:
            session.clear()
            flash("Your account is waiting for founder approval.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def founder_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "founder":
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.cli.command("init-db")
def init_db():
    setup_database()
    print("Database initialized successfully.")


@app.get("/health")
def health():
    return {"status": "ok"}
@app.get("/db-check")
def db_check():
    try:
        employee_count = Employee.query.count()
        emp = Employee.query.filter_by(employee_code="EMP0001").first()

        return {
            "database": "CONNECTED",
            "employee_table": "OK",
            "employee_count": employee_count,
            "EMP0001_exists": bool(emp),
            "EMP0001_active": emp.active if emp else None,
            "EMP0001_approved": emp.approved if emp else None
        }
    except Exception as e:
        return {
            "database": "ERROR",
            "error": str(e)
        }, 500

@app.get("/")
def home():
    if session.get("role") == "employee":
        return redirect(url_for("employee"))
    if session.get("role") == "founder":
        return redirect(url_for("founder"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        employee_code = normalize_text(request.form.get("employee_code")).upper()
        password = request.form.get("password", "")
        founder_username = os.environ.get("FOUNDER_USERNAME", "founder")
        founder_password = os.environ.get("FOUNDER_PASSWORD", "CHANGE_THIS_FOUNDER_PASSWORD")
        if employee_code == founder_username.upper() and secrets.compare_digest(password, founder_password):
            session.clear()
            session["role"] = "founder"
            audit("founder_login", actor_role="founder")
            return redirect(url_for("founder"))
        employee = Employee.query.filter_by(employee_code=employee_code).first()
        if not employee:
            flash("Invalid employee ID or password.", "error")
            return render_template("login.html")
        if not employee.active:
            flash("This employee account is inactive.", "error")
            return render_template("login.html")
        if not check_password_hash(employee.password_hash, password):
            flash("Invalid employee ID or password.", "error")
            return render_template("login.html")
        if not employee.approved:
            flash("Your account is waiting for founder approval.", "error")
            audit("employee_login_blocked_pending_approval", actor_role="employee", employee_id=employee.id)
            return render_template("login.html")
        session.clear()
        session["role"] = "employee"
        session["employee_id"] = employee.id
        employee.last_active = now_ist()
        db.session.commit()
        audit("employee_login", actor_role="employee", actor_id=employee.id, employee_id=employee.id)
        return redirect(url_for("employee"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    role, employee_id = session.get("role"), session.get("employee_id")
    audit("logout", actor_role=role or "system", actor_id=employee_id, employee_id=employee_id)
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = normalize_text(request.form.get("employee_name"))
        code = normalize_text(request.form.get("employee_code")).upper()
        dob = parse_iso_date(request.form.get("dob"))
        password = request.form.get("password", "")
        password2 = request.form.get("password2", password)
        if len(name) < 2 or len(name) > 150:
            flash("Please enter a valid employee name.", "error")
            return render_template("register.html")
        if not code:
            flash("Employee ID is required.", "error")
            return render_template("register.html")
        if not dob:
            flash("Invalid date of birth.", "error")
            return render_template("register.html")
        if len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
            return render_template("register.html")
        if password != password2:
            flash("Passwords do not match.", "error")
            return render_template("register.html")
        if Employee.query.filter_by(employee_code=code).first():
            flash("Employee ID already exists.", "error")
            return render_template("register.html")
        employee = Employee(employee_name=name, employee_code=code, dob=dob, password_hash=generate_password_hash(password), current_index=0, active=True, approved=False, created_at=now_ist())
        db.session.add(employee)
        db.session.commit()
        audit("employee_registered_pending_approval", actor_role="system", employee_id=employee.id)
        flash("Registration successful. Founder approval is required before login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/employee")
@employee_required
def employee():
    employee_obj = db.session.get(Employee, session.get("employee_id"))
    today = today_ist()
    if is_sunday(today):
        return render_template("employee.html", employee=employee_obj, holiday=True, holiday_message="Sunday — Holiday", records=[], result=None, completed=0, remaining=0, target=DAILY_TARGET, accuracy=0, today=today, is_sunday=True)
    records = daily_records(today)
    result = get_or_create_daily_result(employee_obj.id, today)
    completed = min(max(result.completed, 0), len(records))
    result.completed = completed
    result.wrong = max(0, completed - result.correct)
    employee_obj.current_index = completed
    employee_obj.last_active = now_ist()
    db.session.commit()
    accuracy = display_accuracy(result.correct / result.completed * 100) if result.completed else 0
    current_record = records[completed] if completed < len(records) else None
    return render_template("employee.html", employee=employee_obj, holiday=False, holiday_message="", records=records, current_record=current_record, result=result, completed=completed, remaining=max(0, len(records)-completed), target=DAILY_TARGET, accuracy=accuracy, today=today, is_sunday=False)


@app.route("/employee/submit", methods=["POST"])
@employee_required
def employee_submit():
    employee_obj = db.session.get(Employee, session.get("employee_id"))
    today = today_ist()
    if is_sunday(today):
        flash("Sunday is a holiday. No work is required today.", "info")
        return redirect(url_for("employee"))
    records = daily_records(today)
    result = get_or_create_daily_result(employee_obj.id, today)
    if result.completed >= len(records):
        flash("Today's work is already completed.", "success")
        return redirect(url_for("employee"))
    idx = result.completed
    reference = records[idx]
    submitted_name = normalize_text(request.form.get("name"))
    submitted_age = normalize_text(request.form.get("age"))
    submitted_city = normalize_text(request.form.get("city"))
    submitted_phone = normalize_text(request.form.get("phone"))
    submitted_email = normalize_text(request.form.get("email")).lower()
    correct = (submitted_name.lower() == reference["name"].lower() and submitted_age == str(reference["age"]) and submitted_city.lower() == reference["city"].lower() and submitted_phone == reference["phone"] and submitted_email == reference["email"].lower())
    result.completed += 1
    if correct:
        result.correct += 1
    result.wrong = result.completed - result.correct
    result.seconds += min(max(safe_int(request.form.get("seconds"), 0), 0), 86400)
    employee_obj.current_index = result.completed
    employee_obj.last_active = now_ist()
    db.session.commit()
    audit("employee_record_submitted", actor_role="employee", actor_id=employee_obj.id, employee_id=employee_obj.id, metadata=f"record_index={idx};correct={correct}")
    if result.completed >= len(records):
        flash("Today's 250 records are completed.", "success")
    else:
        flash("Correct." if correct else "Record submitted.", "success" if correct else "info")
    return redirect(url_for("employee"))


@app.route("/employee/report")
@employee_required
def employee_report():
    employee_obj = db.session.get(Employee, session.get("employee_id"))
    today = today_ist()
    if is_sunday(today):
        return render_template("employee_report.html", employee=employee_obj, result=None, completed=0, correct=0, wrong=0, seconds=0, accuracy=0, holiday=True, holiday_message="Sunday — Holiday", today=today)
    result = get_or_create_daily_result(employee_obj.id, today)
    accuracy = display_accuracy(result.correct / result.completed * 100) if result.completed else 0
    return render_template("employee_report.html", employee=employee_obj, result=result, completed=result.completed, correct=result.correct, wrong=result.wrong, seconds=result.seconds, accuracy=accuracy, holiday=False, holiday_message="", today=today)


@app.route("/founder")
@founder_required
def founder():
    today = today_ist()
    employees = Employee.query.order_by(Employee.id.asc()).all()
    daily_results = {e.id: DailyResult.query.filter_by(employee_id=e.id, work_date=today).first() for e in employees}
    pending_employees = [e for e in employees if e.active and not e.approved]
    return render_template("founder.html", employees=employees, daily_results=daily_results, pending_employees=pending_employees, pending_count=len(pending_employees), today=today, is_sunday=is_sunday(today), holiday_message=holiday_label(today), daily_target=DAILY_TARGET)


@app.post("/founder/employee/<int:employee_id>/approve")
@founder_required
def approve_employee(employee_id):
    employee = db.get_or_404(Employee, employee_id)
    employee.approved = True
    employee.active = True
    db.session.commit()
    audit("employee_approved", actor_role="founder", employee_id=employee.id)
    flash(f"{employee.employee_name} approved successfully.", "success")
    return redirect(url_for("founder"))


@app.post("/founder/employee/<int:employee_id>/disable")
@founder_required
def disable_employee(employee_id):
    employee = db.get_or_404(Employee, employee_id)
    employee.active = False
    db.session.commit()
    audit("employee_disabled", actor_role="founder", employee_id=employee.id)
    flash(f"{employee.employee_name} disabled.", "success")
    return redirect(url_for("founder"))


@app.post("/founder/employee/<int:employee_id>/enable")
@founder_required
def enable_employee(employee_id):
    employee = db.get_or_404(Employee, employee_id)
    employee.active = True
    db.session.commit()
    audit("employee_enabled", actor_role="founder", employee_id=employee.id)
    flash(f"{employee.employee_name} enabled.", "success")
    return redirect(url_for("founder"))


@app.route("/founder/report")
@founder_required
def founder_report():
    today = today_ist()
    selected_month = request.args.get("month")
    first_day, last_day = month_bounds(selected_month)
    employees = Employee.query.order_by(Employee.id.asc()).all()
    report_rows = []
    for employee in employees:
        results = DailyResult.query.filter(DailyResult.employee_id == employee.id, DailyResult.work_date >= first_day, DailyResult.work_date <= last_day).order_by(DailyResult.work_date.asc()).all()
        completed = sum(r.completed for r in results)
        correct = sum(r.correct for r in results)
        wrong = sum(r.wrong for r in results)
        seconds = sum(r.seconds for r in results)
        raw_accuracy = correct / completed * 100 if completed else 0
        report_rows.append({"employee": employee, "results": results, "completed": completed, "correct": correct, "wrong": wrong, "seconds": seconds, "accuracy": display_accuracy(raw_accuracy) if completed else 0})
    sundays = []
    current = first_day
    while current <= last_day:
        if is_sunday(current):
            sundays.append(current)
        current += datetime.timedelta(days=1)
    return render_template("founder_report.html", employees=employees, report_rows=report_rows, first_day=first_day, last_day=last_day, month_label=month_label(first_day), selected_month=selected_month or first_day.strftime("%Y-%m"), sundays=sundays, today=today, is_sunday_today=is_sunday(today))


@app.route("/founder/employee/<int:employee_id>/history")
@founder_required
def employee_history(employee_id):
    employee = db.get_or_404(Employee, employee_id)
    selected_month = request.args.get("month")
    month_start, month_end = month_bounds(selected_month)
    history = DailyResult.query.filter(DailyResult.employee_id == employee_id, DailyResult.work_date >= month_start, DailyResult.work_date <= month_end).order_by(DailyResult.work_date.desc()).all()
    rows = []
    existing = set()
    totals = [0, 0, 0, 0]
    for result in history:
        existing.add(result.work_date)
        acc = result.correct / result.completed * 100 if result.completed else 0
        rows.append({"result": result, "accuracy": round(acc, 1) if result.completed else 0, "actual_accuracy": round(acc, 1), "target": DAILY_TARGET, "is_holiday": is_sunday(result.work_date), "holiday_label": holiday_label(result.work_date)})
        totals[0] += result.completed; totals[1] += result.correct; totals[2] += result.wrong; totals[3] += result.seconds
    current = month_start
    while current <= month_end:
        if is_sunday(current) and current not in existing:
            rows.append({"result": None, "accuracy": 0, "actual_accuracy": 0, "target": DAILY_TARGET, "is_holiday": True, "holiday_label": "Sunday — Holiday", "holiday_date": current})
        current += datetime.timedelta(days=1)
    rows.sort(key=lambda row: row["result"].work_date if row["result"] else row["holiday_date"], reverse=True)
    raw = totals[1] / totals[0] * 100 if totals[0] else 0
    return render_template("employee_history.html", employee=employee, history=rows, daily_target=DAILY_TARGET, month_start=month_start, month_end=month_end, selected_month=month_start.strftime("%Y-%m"), month_label=month_label(month_start), total_completed=totals[0], total_correct=totals[1], total_wrong=totals[2], total_seconds=totals[3], monthly_accuracy=display_accuracy(raw) if totals[0] else 0, actual_month_accuracy=round(raw, 1))


@app.route("/founder/report/data")
@founder_required
def founder_report_data():
    today = today_ist()
    results = DailyResult.query.filter_by(work_date=today).all()
    data = []
    for result in results:
        employee = db.session.get(Employee, result.employee_id)
        if not employee:
            continue
        acc = result.correct / result.completed * 100 if result.completed else 0
        data.append({"employee_id": employee.id, "employee_code": employee.employee_code, "employee_name": employee.employee_name, "completed": result.completed, "correct": result.correct, "wrong": result.wrong, "seconds": result.seconds, "accuracy": display_accuracy(acc) if result.completed else 0, "date": str(result.work_date), "holiday": is_sunday(result.work_date)})
    return {"date": str(today), "holiday": is_sunday(today), "holiday_label": holiday_label(today), "target": DAILY_TARGET, "employees": data}


@app.route("/founder/report/pdf")
@founder_required
def founder_report_pdf():
    selected_month = request.args.get("month")
    first_day, last_day = month_bounds(selected_month)
    employees = Employee.query.order_by(Employee.id.asc()).all()
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=16, leading=20)
    body = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontSize=8, leading=10)
    story = [Paragraph("Employee Work Report", title), Spacer(1, 5*mm), Paragraph(f"Period: {month_label(first_day)}", body), Paragraph("Timezone: India Standard Time (IST)", body), Spacer(1, 4*mm)]
    table_data = [["Employee", "ID", "Completed", "Correct", "Wrong", "Accuracy"]]
    for employee in employees:
        results = DailyResult.query.filter(DailyResult.employee_id == employee.id, DailyResult.work_date >= first_day, DailyResult.work_date <= last_day).all()
        completed = sum(r.completed for r in results); correct = sum(r.correct for r in results); wrong = sum(r.wrong for r in results)
        acc = correct / completed * 100 if completed else 0
        table_data.append([employee.employee_name, employee.employee_code or "", str(completed), str(correct), str(wrong), f"{display_accuracy(acc) if completed else 0:.1f}%"])
    sundays = []
    current = first_day
    while current <= last_day:
        if is_sunday(current): sundays.append(current.strftime("%d %B %Y"))
        current += datetime.timedelta(days=1)
    if sundays:
        story += [Paragraph("Sunday Holidays: " + ", ".join(sundays), body), Spacer(1, 3*mm)]
    table = Table(table_data, repeatRows=1, colWidths=[45*mm,25*mm,22*mm,20*mm,18*mm,22*mm])
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.lightgrey), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 7), ("GRID", (0,0), (-1,-1), 0.5, colors.grey), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ALIGN", (1,1), (-1,-1), "CENTER"), ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
    story.append(table)
    document.build(story)
    buffer.seek(0)
    audit("founder_report_pdf_generated", actor_role="founder", metadata=f"month={first_day.strftime('%Y-%m')}")
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"employee-report-{first_day.strftime('%Y-%m')}.pdf")


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", message="Page not found."), 404


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", message="Access denied."), 403


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template("error.html", message="Something went wrong."), 500


with app.app_context():
    setup_database()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
