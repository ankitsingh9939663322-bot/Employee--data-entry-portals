import os
import random
import datetime
import secrets
from io import BytesIO

from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_file,
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


app = Flask(__name__)


# =========================================================
# CONFIG
# =========================================================

app.config["SECRET_KEY"] = (
    os.environ.get("SECRET_KEY")
    or "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET_KEY"
)

database_url = os.environ.get("DATABASE_URL")

# Production must use a persistent external PostgreSQL database (e.g. Supabase).
# Keep SQLite only for local development; never silently fall back on Render.
if not database_url:
    if os.environ.get("RENDER") == "true" or os.environ.get("APP_ENV") == "production":
        raise RuntimeError(
            "DATABASE_URL is required in production. Configure Supabase/PostgreSQL in Render environment variables."
        )
    database_url = "sqlite:///nexora.db"

database_url = database_url.replace(
    "postgres://",
    "postgresql://",
    1
)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "0") == "1"
)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# =========================================================
# CONSTANTS / TIMEZONE
# =========================================================

IST = ZoneInfo("Asia/Kolkata")

DAILY_TARGET = 250
MIN_ACCURACY = 80.0
MAX_ACCURACY = 90.0


def display_accuracy(actual_accuracy):
    """Founder-facing monthly accuracy is always constrained to 80–90%."""
    try:
        value = float(actual_accuracy)
    except (TypeError, ValueError):
        value = MIN_ACCURACY
    return round(max(MIN_ACCURACY, min(MAX_ACCURACY, value)), 1)


def month_bounds(month_value=None):
    """Return first/last date for YYYY-MM in IST."""
    today = today_ist()

    if not month_value:
        year, month = today.year, today.month
    else:
        try:
            parsed = datetime.date.fromisoformat(month_value + "-01")
            year, month = parsed.year, parsed.month
        except ValueError:
            year, month = today.year, today.month

    first = datetime.date(year, month, 1)

    if month == 12:
        next_first = datetime.date(year + 1, 1, 1)
    else:
        next_first = datetime.date(year, month + 1, 1)

    last = next_first - datetime.timedelta(days=1)

    return first, last


def month_label(first):
    return first.strftime("%B %Y")


def now_ist():
    """Current Indian Standard Time."""
    return datetime.datetime.now(IST)


def today_ist():
    """Current date according to India timezone."""
    return now_ist().date()


# =========================================================
# EMPLOYEE MODEL
# =========================================================

class Employee(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_name = db.Column(
        db.String(150),
        nullable=False
    )

    employee_code = db.Column(
        db.String(20),
        unique=True,
        nullable=True
    )

    dob = db.Column(
        db.Date,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    # Today's saved position.
    # Database me save hota hai, isliye logout/browser
    # close hone par submitted progress lost nahi hoti.
    current_index = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    last_active = db.Column(
        db.DateTime,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=now_ist,
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )
    approval_status = db.Column(
        db.String(20),
        default="approved",
        nullable=False
    )
    approval_status = db.Column(
    db.String(20),
    default="pending",
    nullable=False
)

# =========================================================
# DAILY RESULT MODEL
# =========================================================

class AuditLog(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    actor_role = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(120), nullable=False)
    employee_id = db.Column(db.Integer, nullable=True)
    audit_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=now_ist, nullable=False)


class DailyResult(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=False
    )

    work_date = db.Column(
        db.Date,
        nullable=False
    )

    completed = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    correct = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    wrong = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    seconds = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "employee_id",
            "work_date",
            name="uq_employee_day"
        ),
    )


# =========================================================
# DATABASE SETUP / MIGRATION
# =========================================================

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

        columns = [
            column["name"]
            for column in inspector.get_columns("employee")
        ]

        # -------------------------------------------------
        # OLD DATABASE: employee_name
        # -------------------------------------------------

        if "employee_name" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE employee
                    ADD COLUMN employee_name VARCHAR(150)
                    """
                )

                connection.exec_driver_sql(
                    """
                    UPDATE employee
                    SET employee_name =
                        'Employee ' || CAST(id AS VARCHAR)
                    WHERE employee_name IS NULL
                    """
                )

        # -------------------------------------------------
        # OLD DATABASE: employee_code
        # -------------------------------------------------

        if "employee_code" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE employee
                    ADD COLUMN employee_code VARCHAR(20)
                    """
                )

            db.session.commit()

        # -------------------------------------------------
        # OLD DATABASE: current_index
        # -------------------------------------------------

        if "current_index" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE employee
                    ADD COLUMN current_index INTEGER
                    DEFAULT 0
                    """
                )

        # -------------------------------------------------
        # OLD DATABASE: last_active
        # -------------------------------------------------

        if "last_active" not in columns:

            with db.engine.begin() as connection:

                connection.exec_driver_sql(
                    """
                    ALTER TABLE employee
                    ADD COLUMN last_active TIMESTAMP
                    """
                )

        db.session.commit()

        # -------------------------------------------------
        # GENERATE MISSING EMPLOYEE CODES
        # -------------------------------------------------

        employees = Employee.query.order_by(
            Employee.id.asc()
        ).all()

        changed = False

        for employee in employees:

            if not employee.employee_code:

                employee.employee_code = (
                    f"EMP{employee.id:04d}"
                )

                changed = True

        if changed:
            db.session.commit()

    except Exception as error:

        print(
            "Database migration warning:",
            error
        )


# =========================================================
# REALISTIC SYNTHETIC DAILY DATA
# =========================================================

def daily_records(day):

    # Same date = same dataset.
    # Isse employee logout/login ke baad same record
    # sequence par resume kar sakta hai.
    rnd = random.Random(
        int(day.strftime("%Y%m%d"))
    )

    first_names = [
        "Aarav",
        "Aanya",
        "Aditya",
        "Akash",
        "Aman",
        "Ananya",
        "Ankit",
        "Arjun",
        "Ayush",
        "Deepak",
        "Divya",
        "Isha",
        "Karan",
        "Kavya",
        "Manish",
        "Meera",
        "Mohit",
        "Naman",
        "Neha",
        "Nikhil",
        "Pooja",
        "Prakash",
        "Priya",
        "Rahul",
        "Raj",
        "Rakesh",
        "Riya",
        "Rohan",
        "Sachin",
        "Sakshi",
        "Sanjay",
        "Shivam",
        "Shreya",
        "Simran",
        "Sneha",
        "Sonam",
        "Suresh",
        "Tanvi",
        "Varun",
        "Vikas",
        "Vikram",
        "Yash",
        "Zoya",
    ]

    last_names = [
        "Sharma",
        "Verma",
        "Singh",
        "Kumar",
        "Gupta",
        "Yadav",
        "Patel",
        "Jain",
        "Mehta",
        "Agarwal",
        "Mishra",
        "Tiwari",
        "Pandey",
        "Chauhan",
        "Rathore",
        "Joshi",
        "Malhotra",
        "Kapoor",
        "Saxena",
        "Srivastava",
        "Das",
        "Roy",
        "Chatterjee",
        "Bose",
        "Reddy",
        "Rao",
        "Nair",
        "Iyer",
        "Pillai",
        "Shah",
        "Bansal",
        "Saini",
        "Thakur",
        "Tripathi",
        "Dubey",
        "Khan",
        "Ansari",
        "Sheikh",
    ]

    cities = [
        "Delhi",
        "New Delhi",
        "Mumbai",
        "Pune",
        "Jaipur",
        "Lucknow",
        "Kanpur",
        "Agra",
        "Noida",
        "Gurugram",
        "Ghaziabad",
        "Faridabad",
        "Chandigarh",
        "Amritsar",
        "Ludhiana",
        "Dehradun",
        "Haridwar",
        "Patna",
        "Ranchi",
        "Kolkata",
        "Bhopal",
        "Indore",
        "Jabalpur",
        "Ahmedabad",
        "Surat",
        "Vadodara",
        "Rajkot",
        "Hyderabad",
        "Bengaluru",
        "Chennai",
        "Kochi",
        "Coimbatore",
        "Bhubaneswar",
        "Visakhapatnam",
        "Nagpur",
        "Nashik",
        "Varanasi",
        "Prayagraj",
        "Meerut",
    ]

    email_domains = [
        "gmail.com",
        "outlook.com",
        "yahoo.com",
        "icloud.com",
        "rediffmail.com",
    ]

    out = []

    for _ in range(DAILY_TARGET):

        first = rnd.choice(first_names)
        last = rnd.choice(last_names)

        name = f"{first} {last}"

        city = rnd.choice(cities)

        # Valid Indian-style 10 digit mobile number.
        phone = (
            rnd.choice(
                [
                    "6",
                    "7",
                    "8",
                    "9",
                ]
            )
            + "".join(
                str(rnd.randrange(10))
                for _ in range(9)
            )
        )

        # Realistic-looking synthetic email.
        # These are generated training records, not
        # guaranteed to belong to a real person.
        email = (
            f"{first.lower()}"
            f"."
            f"{last.lower()}"
            f"{rnd.randint(10, 9999)}"
            f"@"
            f"{rnd.choice(email_domains)}"
        )

        out.append(
            {
                "name": name,
                "age": rnd.randint(18, 60),
                "city": city,
                "phone": phone,
                "email": email,
            }
        )

    return out


# =========================================================
# DAILY RESULT HELPER
# =========================================================

def get_or_create_daily_result(
    employee_id,
    work_date
):

    result = DailyResult.query.filter_by(
        employee_id=employee_id,
        work_date=work_date
    ).first()

    if not result:

        result = DailyResult(
            employee_id=employee_id,
            work_date=work_date,
            completed=0,
            correct=0,
            wrong=0,
            seconds=0
        )

        db.session.add(result)

        db.session.commit()

    return result


# =========================================================
# EMPLOYEE PROGRESS SYNC
# =========================================================

def sync_employee_progress(
    employee,
    result
):

    employee.current_index = result.completed

    employee.last_active = now_ist()

    db.session.commit()


# =========================================================
# LOGIN PROTECTION
# =========================================================

def employee_required(f):

    @wraps(f)
    def w(*args, **kwargs):

        if session.get("role") != "employee":

            return redirect(
                url_for("login")
            )

        if not session.get("employee_id"):

            session.clear()

            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return w


def founder_required(f):

    @wraps(f)
    def w(*args, **kwargs):

        if session.get("role") != "founder":

            return redirect(
                url_for("login")
            )

        return f(*args, **kwargs)

    return w


# =========================================================
# INIT DATABASE COMMAND
# =========================================================

@app.cli.command("init-db")
def init_db():

    setup_database()

    print(
        "Database initialized successfully."
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "ok"
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    if session.get("role") == "employee":

        return redirect(
            url_for("employee")
        )

    if session.get("role") == "founder":

        return redirect(
            url_for("founder")
        )

    return redirect(
        url_for("login")
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        role = request.form.get(
            "role",
            "employee"
        ).strip().lower()

        # =================================================
        # FOUNDER / ADMIN LOGIN
        # =================================================

        if role == "founder":

            try:

                dob = datetime.date.fromisoformat(
                    request.form.get(
                        "dob",
                        ""
                    )
                )

            except ValueError:

                flash(
                    "Please enter a valid date of birth.",
                    "error"
                )

                return render_template(
                    "login.html"
                )

            password = request.form.get(
                "password",
                ""
            )

            founder_pw = os.environ.get(
                "FOUNDER_PASSWORD"
            )
            founder_dob = os.environ.get(
                "FOUNDER_DOB"
            )

            if (
                founder_pw
                and founder_dob
                and secrets.compare_digest(
                    dob.isoformat(),
                    founder_dob
                )
                and secrets.compare_digest(
                    password,
                    founder_pw
                )
            ):

                session.clear()

                session["role"] = "founder"
                audit("founder_login", "founder")

                return redirect(
                    url_for("founder")
                )

            flash(
                "The credentials provided could not be verified.",
                "error"
            )

            return render_template(
                "login.html"
            )

        # =================================================
        # EMPLOYEE LOGIN
        # =================================================

        employee_code = (
            request.form
            .get("employee_code", "")
            .strip()
            .upper()
        )

        password = request.form.get(
            "password",
            ""
        )

        employee = None

        # -------------------------------------------------
        # PRIMARY LOGIN: EMPLOYEE CODE
        # -------------------------------------------------

        if employee_code:

            employee = Employee.query.filter_by(
                employee_code=employee_code,
                active=True
            ).first()

        # -------------------------------------------------
        # OLD LOGIN FALLBACK: DOB
        # -------------------------------------------------

        if not employee:

            dob_value = (
                request.form
                .get("dob", "")
                .strip()
            )

            if dob_value:

                try:

                    dob = datetime.date.fromisoformat(
                        dob_value
                    )

                    employee = Employee.query.filter_by(
                        dob=dob,
                        active=True
                    ).first()

                except ValueError:

                    employee = None

        # -------------------------------------------------
        # PASSWORD CHECK
        # -------------------------------------------------

        if (
            employee
            and check_password_hash(
                employee.password_hash,
                password
            )
        ):

            session.clear()

            session["role"] = "employee"

            session["employee_id"] = employee.id

            # -------------------------------------------------
            # TODAY'S SAVED PROGRESS
            # -------------------------------------------------

            today = today_ist()

            result = get_or_create_daily_result(
                employee.id,
                today
            )

            employee.current_index = (
                result.completed
            )

            employee.last_active = now_ist()

            db.session.commit()

            return redirect(
                url_for("employee")
            )

        flash(
            "The credentials provided could not be verified.",
            "error"
        )

    return render_template(
        "login.html"
    )


# =========================================================
# EMPLOYEE REGISTRATION
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        employee_name = (
            request.form
            .get("employee_name", "")
            .strip()
        )

        dob_value = (
            request.form
            .get("dob", "")
            .strip()
        )

        password = request.form.get(
            "password",
            ""
        )

        password2 = request.form.get(
            "password2",
            ""
        )

        # =================================================
        # NAME VALIDATION
        # =================================================

        if not employee_name:

            flash(
                "Employee name is required.",
                "error"
            )

            return render_template(
                "register.html"
            )

        if len(employee_name) < 2:

            flash(
                "Please enter a valid employee name.",
                "error"
            )

            return render_template(
                "register.html"
            )

        if len(employee_name) > 150:

            flash(
                "Employee name is too long.",
                "error"
            )

            return render_template(
                "register.html"
            )

        # =================================================
        # DOB VALIDATION
        # =================================================

        try:

            dob = datetime.date.fromisoformat(
                dob_value
            )

        except ValueError:

            flash(
                "Please enter a valid date of birth.",
                "error"
            )

            return render_template(
                "register.html"
            )

        # =================================================
        # PASSWORD VALIDATION
        # =================================================

        if len(password) < 10:

            flash(
                "Password must be at least 10 characters.",
                "error"
            )

            return render_template(
                "register.html"
            )

        if password != password2:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template(
                "register.html"
            )

        # =================================================
        # CREATE EMPLOYEE
        # =================================================

        employee = Employee(
            employee_name=employee_name,
            dob=dob,
            password_hash=generate_password_hash(
                password
            ),
            current_index=0,
            last_active=now_ist(),
            active=True
        )

        db.session.add(employee)

        # ID generate karne ke liye flush.
        db.session.flush()

        # -------------------------------------------------
        # EMPLOYEE CODE
        # -------------------------------------------------
        #
        # Example:
        # EMP0001
        # EMP0002
        # EMP0003
        #
        # Existing database IDs bhi preserve rahenge.
        # -------------------------------------------------

        employee.employee_code = (
            f"EMP{employee.id:04d}"
        )

        db.session.commit()

        # =================================================
        # CREATE TODAY'S DAILY RESULT
        # =================================================

        today = today_ist()

        get_or_create_daily_result(
            employee.id,
            today
        )

        # =================================================
        # AUTO LOGIN
        # =================================================

        session.clear()

        session["role"] = "employee"

        session["employee_id"] = employee.id

        return redirect(
            url_for("employee")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# EMPLOYEE DASHBOARD
# =========================================================

@app.get("/employee")
@employee_required
def employee():

    today = today_ist()

    employee_id = session.get(
        "employee_id"
    )

    current_employee = Employee.query.get(
        employee_id
    )

    if not current_employee:

        session.clear()

        return redirect(
            url_for("login")
        )

    # =================================================
    # TODAY'S RESULT
    # =================================================

    result = get_or_create_daily_result(
        employee_id,
        today
    )

    # =================================================
    # IMPORTANT:
    # DATABASE IS SOURCE OF TRUTH
    # =================================================

    completed = max(
        0,
        min(
            result.completed,
            DAILY_TARGET
        )
    )

    current_employee.current_index = (
        completed
    )

    current_employee.last_active = now_ist()

    db.session.commit()

    # =================================================
    # TODAY'S FIXED DATASET
    # =================================================

    records = daily_records(
        today
    )

    # =================================================
    # EMPLOYEE PAGE
    # =================================================

    return render_template(
        "employee.html",
        records=records,
        completed=completed,
        current_index=completed,
        daily_target=DAILY_TARGET,
        employee=current_employee,
        today=today
    )


# =========================================================
# EMPLOYEE SUBMIT
# =========================================================

@app.post("/employee/submit")
@employee_required
def submit():

    today = today_ist()

    employee_id = session.get(
        "employee_id"
    )

    employee_obj = Employee.query.get(
        employee_id
    )

    if not employee_obj:

        session.clear()

        return redirect(
            url_for("login")
        )

    # =================================================
    # TODAY'S RESULT
    # =================================================

    result = get_or_create_daily_result(
        employee_id,
        today
    )

    # =================================================
    # INDEX VALIDATION
    # =================================================

    try:

        idx = int(
            request.form.get(
                "index",
                "-1"
            )
        )

    except (ValueError, TypeError):

        return redirect(
            url_for("employee")
        )

    # =================================================
    # DAILY LIMIT
    # =================================================

    if result.completed >= DAILY_TARGET:

        employee_obj.current_index = (
            DAILY_TARGET
        )

        employee_obj.last_active = now_ist()

        db.session.commit()

        # FIXED: use today's actual date variable.
        audit(
            "daily_entry_saved",
            "employee",
            employee_id,
            employee_id,
            f"date={today.isoformat()}"
        )

        return redirect(
            url_for("employee")
        )

    # =================================================
    # ANTI-SKIP CHECK
    # =================================================

    if idx != result.completed:

        return redirect(
            url_for("employee")
        )

    # =================================================
    # GET TODAY'S REFERENCE DATA
    # =================================================

    records = daily_records(
        today
    )

    if (
        idx < 0
        or idx >= len(records)
    ):

        return redirect(
            url_for("employee")
        )

    reference = records[idx]

    # =================================================
    # USER INPUT
    # =================================================

    name = (
        request.form
        .get("name", "")
        .strip()
    )

    city = (
        request.form
        .get("city", "")
        .strip()
    )

    phone = (
        request.form
        .get("phone", "")
        .strip()
    )

    email = (
        request.form
        .get("email", "")
        .strip()
        .lower()
    )

    try:

        age = int(
            request.form.get(
                "age",
                ""
            )
        )

    except (ValueError, TypeError):

        age = -1

    # =================================================
    # ANSWER CHECK
    # =================================================

    correct = (
        name == reference["name"]
        and age == reference["age"]
        and city == reference["city"]
        and phone == reference["phone"]
        and email == reference["email"].lower()
    )

    # =================================================
    # UPDATE RESULT
    # =================================================

    result.completed += 1

    if correct:

        result.correct += 1

    result.wrong = (
        result.completed
        - result.correct
    )

    # =================================================
    # TIME
    # =================================================

    try:

        submitted_seconds = int(
            request.form.get(
                "seconds",
                "0"
            )
        )

    except (ValueError, TypeError):

        submitted_seconds = 0

    result.seconds += max(
        0,
        min(
            submitted_seconds,
            3600
        )
    )

    # =================================================
    # SAVE PROGRESS
    # =================================================

    employee_obj.current_index = (
        result.completed
    )

    employee_obj.last_active = now_ist()

    # Single commit = durable progress.
    db.session.commit()

    return redirect(
        url_for("employee")
    )


# =========================================================
# FOUNDER DASHBOARD
# =========================================================

@app.get("/founder")
@founder_required
def founder():

    # Founder can inspect any saved month. Current month is the default.
    selected_month = request.args.get("month", "")
    month_start, month_end = month_bounds(selected_month)
    selected_month_value = month_start.strftime("%Y-%m")

    employees = (
        Employee.query
        .filter_by(active=True)
        .order_by(Employee.id.asc())
        .all()
    )

    rows = []
    total_entries = total_correct = total_wrong = total_seconds = 0

    for employee in employees:

        results = (
            DailyResult.query
            .filter(
                DailyResult.employee_id == employee.id,
                DailyResult.work_date >= month_start,
                DailyResult.work_date <= month_end
            )
            .order_by(DailyResult.work_date.asc())
            .all()
        )

        completed = sum(r.completed for r in results)
        correct = sum(r.correct for r in results)
        wrong = sum(r.wrong for r in results)
        seconds = sum(r.seconds for r in results)

        actual_accuracy = (
            (correct / completed * 100)
            if completed else 0
        )

        accuracy = (
            display_accuracy(actual_accuracy)
            if completed else 0
        )

        total_entries += completed
        total_correct += correct
        total_wrong += wrong
        total_seconds += seconds

        rows.append({
            "employee": employee,
            "result": results[-1] if results else None,
            "completed": completed,
            "correct": correct,
            "wrong": wrong,
            "accuracy": accuracy,
            "actual_accuracy": round(actual_accuracy, 1),
            "seconds": seconds,
            "last_active": employee.last_active,
            "target": DAILY_TARGET,
        })

    overall_actual_accuracy = (
        total_correct / total_entries * 100
        if total_entries else 0
    )

    overall_accuracy = (
        display_accuracy(overall_actual_accuracy)
        if total_entries else 0
    )

    return render_template(
        "founder.html",
        rows=rows,
        day=month_start,
        month_start=month_start,
        month_end=month_end,
        selected_month=selected_month_value,
        month_label=month_label(month_start),
        daily_target=DAILY_TARGET,
        total_entries=total_entries,
        total_correct=total_correct,
        total_wrong=total_wrong,
        total_seconds=total_seconds,
        overall_accuracy=overall_accuracy,
        overall_actual_accuracy=round(
            overall_actual_accuracy,
            1
        ),
    )


# =========================================================
# FOUNDER EMPLOYEE HISTORY
# =========================================================

@app.get("/founder/employee/<int:employee_id>/history")
@founder_required
def employee_history(employee_id):

    employee = Employee.query.get_or_404(
        employee_id
    )

    selected_month = request.args.get(
        "month",
        ""
    )

    month_start, month_end = month_bounds(
        selected_month
    )

    selected_month_value = (
        month_start.strftime("%Y-%m")
    )

    history = (
        DailyResult.query
        .filter(
            DailyResult.employee_id == employee_id,
            DailyResult.work_date >= month_start,
            DailyResult.work_date <= month_end
        )
        .order_by(
            DailyResult.work_date.desc()
        )
        .all()
    )

    history_rows = []

    total_completed = (
        total_correct
    ) = (
        total_wrong
    ) = (
        total_seconds
    ) = 0

    for result in history:

        actual_accuracy = (
            result.correct / result.completed * 100
            if result.completed else 0
        )

        history_rows.append({
            "result": result,
            "accuracy": (
                round(actual_accuracy, 1)
                if result.completed else 0
            ),
            "actual_accuracy": round(
                actual_accuracy,
                1
            ),
            "target": DAILY_TARGET,
        })

        total_completed += result.completed
        total_correct += result.correct
        total_wrong += result.wrong
        total_seconds += result.seconds

    actual_month_accuracy = (
        total_correct / total_completed * 100
        if total_completed else 0
    )

    monthly_accuracy = (
        display_accuracy(actual_month_accuracy)
        if total_completed else 0
    )

    return render_template(
        "employee_history.html",
        employee=employee,
        history=history_rows,
        daily_target=DAILY_TARGET,
        month_start=month_start,
        month_end=month_end,
        selected_month=selected_month_value,
        month_label=month_label(month_start),
        total_completed=total_completed,
        total_correct=total_correct,
        total_wrong=total_wrong,
        total_seconds=total_seconds,
        monthly_accuracy=monthly_accuracy,
        actual_month_accuracy=round(
            actual_month_accuracy,
            1
        ),
    )


@app.get("/founder/employee/<int:employee_id>")
@founder_required
def founder_employee(employee_id):

    employee = Employee.query.get_or_404(
        employee_id
    )

    selected_month = request.args.get(
        "month",
        ""
    )

    month_start, month_end = month_bounds(
        selected_month
    )

    selected_month_value = (
        month_start.strftime("%Y-%m")
    )

    results = (
        DailyResult.query
        .filter(
            DailyResult.employee_id == employee_id,
            DailyResult.work_date >= month_start,
            DailyResult.work_date <= month_end
        )
        .order_by(
            DailyResult.work_date.asc()
        )
        .all()
    )

    completed = sum(
        r.completed for r in results
    )

    correct = sum(
        r.correct for r in results
    )

    wrong = sum(
        r.wrong for r in results
    )

    seconds = sum(
        r.seconds for r in results
    )

    days_recorded = len(results)

    monthly_target = (
        days_recorded * DAILY_TARGET
    )

    actual_accuracy = (
        correct / completed * 100
        if completed else 0
    )

    accuracy = (
        display_accuracy(actual_accuracy)
        if completed else 0
    )

    return render_template(
        "founder_employee.html",
        employee=employee,
        result=results[-1] if results else None,
        results=results,
        completed=completed,
        correct=correct,
        wrong=wrong,
        seconds=seconds,
        accuracy=accuracy,
        actual_accuracy=round(
            actual_accuracy,
            1
        ),
        daily_target=DAILY_TARGET,
        days_recorded=days_recorded,
        monthly_target=monthly_target,
        total_month_days=max(
            (month_end - month_start).days + 1,
            1
        ),
        day=month_start,
        month_start=month_start,
        month_end=month_end,
        selected_month=selected_month_value,
        month_label=month_label(month_start),
    )


# =========================================================
# FOUNDER-ONLY PDF REPORT
# =========================================================

@app.get(
    "/founder/employee/<int:employee_id>/report.pdf"
)
@founder_required
def founder_employee_report(employee_id):

    employee = Employee.query.get_or_404(
        employee_id
    )

    selected_month = request.args.get(
        "month",
        ""
    )

    month_start, month_end = month_bounds(
        selected_month
    )

    selected_month_value = (
        month_start.strftime("%Y-%m")
    )

    results = (
        DailyResult.query
        .filter(
            DailyResult.employee_id == employee_id,
            DailyResult.work_date >= month_start,
            DailyResult.work_date <= month_end
        )
        .order_by(
            DailyResult.work_date.asc()
        )
        .all()
    )

    total_completed = sum(
        r.completed for r in results
    )

    total_correct = sum(
        r.correct for r in results
    )

    total_wrong = sum(
        r.wrong for r in results
    )

    total_seconds = sum(
        r.seconds for r in results
    )

    actual = (
        total_correct / total_completed * 100
        if total_completed else 0
    )

    accuracy = (
        display_accuracy(actual)
        if total_completed else 0
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{employee.employee_name} - {month_start:%B %Y}"
    )

    styles = getSampleStyleSheet()

    title = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=20,
        leading=24,
        spaceAfter=6
    )

    subtitle = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=9,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=16
    )

    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=12,
        spaceAfter=7
    )

    small = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11
    )

    story = [
        Paragraph(
            "NEXORA DATA SOLUTIONS",
            title
        ),

        Paragraph(
            "Employee Monthly Performance Report",
            subtitle
        ),

        Table(
            [
                [
                    "Employee",
                    employee.employee_name
                ],
                [
                    "Employee ID",
                    employee.employee_code or "—"
                ],
                [
                    "Report Month",
                    month_start.strftime("%B %Y")
                ],
                [
                    "Generated",
                    now_ist().strftime(
                        "%d %B %Y, %I:%M %p IST"
                    )
                ]
            ],
            colWidths=[
                38 * mm,
                132 * mm
            ],
            style=[
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f1f5f9")
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (0, -1),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.35,
                    colors.HexColor("#cbd5e1")
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    7
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    7
                ),
            ]
        )
    ]

    story.append(
        Spacer(
            1,
            5 * mm
        )
    )

    story.append(
        Paragraph(
            "Monthly Summary",
            section
        )
    )

    summary = [
        [
            "Completed",
            "Correct",
            "Wrong",
            "Total Time",
            "Accuracy"
        ],
        [
            str(total_completed),
            str(total_correct),
            str(total_wrong),
            f"{total_seconds // 60}m {total_seconds % 60}s",
            f"{accuracy:.1f}%"
        ]
    ]

    story.append(
        Table(
            summary,
            colWidths=[33 * mm] * 5,
            style=[
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#0f172a")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.35,
                    colors.HexColor("#cbd5e1")
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    9
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),
            ]
        )
    )

    story.append(
        Paragraph(
            "Daily Performance",
            section
        )
    )

    data = [
        [
            "Date",
            "Completed",
            "Correct",
            "Wrong",
            "Time",
            "Accuracy"
        ]
    ]

    for r in results:

        daily_actual = (
            r.correct / r.completed * 100
            if r.completed else 0
        )

        data.append(
            [
                r.work_date.strftime(
                    "%d %b %Y"
                ),
                str(r.completed),
                str(r.correct),
                str(r.wrong),
                f"{r.seconds // 60}m {r.seconds % 60}s",
                (
                    f"{daily_actual:.1f}%"
                    if r.completed
                    else "—"
                )
            ]
        )

    if len(data) == 1:

        data.append(
            [
                "No entries",
                "—",
                "—",
                "—",
                "—",
                "—"
            ]
        )

    story.append(
        Table(
            data,
            repeatRows=1,
            colWidths=[
                32 * mm,
                24 * mm,
                24 * mm,
                22 * mm,
                28 * mm,
                28 * mm
            ],
            style=[
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#e2e8f0")
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.3,
                    colors.HexColor("#cbd5e1")
                ),
                (
                    "ALIGN",
                    (1, 1),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6
                ),
            ]
        )
    )

    story.append(
        Spacer(
            1,
            8 * mm
        )
    )

    story.append(
        Paragraph(
            "Confidential — Founder/Admin report",
            small
        )
    )

    doc.build(story)

    buffer.seek(0)

    audit(
        "monthly_report_downloaded",
        "founder",
        None,
        employee.id,
        f"month={selected_month_value}"
    )

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"{employee.employee_code or employee.id}"
            f"_{selected_month_value}_report.pdf"
        )
    )


# =========================================================
# LOGOUT
# =========================================================

@app.get("/logout")
def logout():

    employee_id = session.get(
        "employee_id"
    )

    # -----------------------------------------------------
    # SAVE LAST ACTIVE TIME
    # -----------------------------------------------------

    if (
        session.get("role") == "employee"
        and employee_id
    ):

        employee = Employee.query.get(
            employee_id
        )

        if employee:

            employee.last_active = now_ist()

            db.session.commit()

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# STARTUP
# =========================================================

with app.app_context():

    setup_database()


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":

    app.run()
        
   
  

  
