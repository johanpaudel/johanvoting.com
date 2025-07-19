from flask import Flask, render_template, request, redirect, session, flash, send_file, url_for
import sqlite3, os, pandas as pd
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'voting_secret'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(fname):
    return '.' in fname and fname.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect('voting.db')
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE,
      password TEXT,
      name TEXT,
      dob TEXT,
      citizenship_id TEXT,
      citizenship_photo TEXT,
      personal_photo TEXT,
      verified INTEGER DEFAULT 0,
      role TEXT DEFAULT 'user'
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS elections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT,
      start_date TEXT,
      end_date TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,
      party TEXT,
      election_id INTEGER,
      FOREIGN KEY(election_id) REFERENCES elections(id)
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS votes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      candidate_id INTEGER,
      election_id INTEGER
    )""")
    c.execute("INSERT OR IGNORE INTO users(username,password,role,verified) VALUES('admin','admin123','admin',1)")
    conn.commit()
    conn.close()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']
        name = request.form['name']
        dob = request.form['dob']
        cid = request.form['citizenship_id']
        cit = request.files.get('citizenship_photo')
        per = request.files.get('personal_photo')

        if not (cit and per and allowed_file(cit.filename) and allowed_file(per.filename)):
            flash("Please upload two valid image files.")
            return redirect('/register')

        cit_name = secure_filename(f"cit_{u}_{cit.filename}")
        per_name = secure_filename(f"per_{u}_{per.filename}")
        cit.save(os.path.join(UPLOAD_FOLDER, cit_name))
        per.save(os.path.join(UPLOAD_FOLDER, per_name))

        try:
            conn = sqlite3.connect('voting.db')
            conn.execute("""
            INSERT INTO users(username,password,name,dob,citizenship_id,citizenship_photo,personal_photo)
            VALUES(?,?,?,?,?,?,?)""",
                         (u,p,name,dob,cid,cit_name,per_name))
            conn.commit()
            flash("Registered! Await admin approval.")
            return redirect('/login')
        except sqlite3.IntegrityError:
            flash("Username already exists.")
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form['username']
        p = request.form['password']
        conn = sqlite3.connect('voting.db')
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p)).fetchone()
        conn.close()
        if not user:
            flash("Invalid credentials.")
            return redirect('/login')

        (uid, uname, pwd, name, dob, cid, cit_photo,
         per_photo, verified, role) = user

        if role != 'admin' and verified == 0:
            flash("Awaiting admin approval.")
            return redirect('/login')

        session['user_id'] = uid
        session['username'] = uname
        session['role'] = role
        session['logged_in'] = True
        return redirect('/dashboard')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'role' not in session:
        return redirect('/login')
    return redirect('/admin') if session['role']=='admin' else redirect('/user')

@app.route('/admin')
def admin_dashboard():
    if session.get('role')!='admin':
        return redirect('/login')
    return render_template('admin_dashboard.html')

@app.route('/admin/manage_election', methods=['GET', 'POST'])
def manage_election():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect('voting.db')
    cursor = conn.cursor()

    # Handle creating a new election
    if request.method == 'POST' and 'create_election' in request.form:
        title = request.form['title']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        cursor.execute("INSERT INTO elections(title, start_date, end_date) VALUES (?, ?, ?)",
                       (title, start_date, end_date))
        conn.commit()
        flash("Election created.")

    # Handle adding a candidate
    if request.method == 'POST' and 'add_candidate' in request.form:
        name = request.form['candidate_name']
        party = request.form['party']
        election_id = request.form['election_id']
        cursor.execute("INSERT INTO candidates(name, party, election_id) VALUES (?, ?, ?)",
                       (name, party, election_id))
        conn.commit()
        flash("Candidate added.")

    # Fetch elections and candidates
    cursor.execute("SELECT * FROM elections")
    elections = cursor.fetchall()

    cursor.execute("""
        SELECT c.id, c.name, c.party, c.election_id, e.title
        FROM candidates c
        LEFT JOIN elections e ON c.election_id = e.id
    """)
    candidates = cursor.fetchall()

    conn.close()

    return render_template('manage_election.html', elections=elections, candidates=candidates)

@app.route('/admin/delete_election/<int:election_id>', methods=['POST'])
def delete_election(election_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = sqlite3.connect('voting.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM candidates WHERE election_id=?", (election_id,))
    cursor.execute("DELETE FROM votes WHERE election_id=?", (election_id,))
    cursor.execute("DELETE FROM elections WHERE id=?", (election_id,))
    conn.commit()
    conn.close()
    flash("Election and related data deleted.")
    return redirect(url_for('manage_election'))

@app.route('/admin/delete_candidate/<int:candidate_id>', methods=['POST'])
def delete_candidate(candidate_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = sqlite3.connect('voting.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM votes WHERE candidate_id=?", (candidate_id,))
    cursor.execute("DELETE FROM candidates WHERE id=?", (candidate_id,))
    conn.commit()
    conn.close()
    flash("Candidate deleted.")
    return redirect(url_for('manage_election'))

@app.route('/admin/verify_users')
def verify_users():
    if session.get('role')!='admin':
        return redirect('/login')
    conn = sqlite3.connect('voting.db')
    users = conn.execute("""
        SELECT id,username,name,dob,citizenship_id,citizenship_photo,personal_photo
        FROM users WHERE verified=0 AND role='user'
    """).fetchall()
    conn.close()
    return render_template('verify_users.html', users=users)

@app.route('/admin/approve_user/<int:user_id>')
def approve_user(user_id):
    if session.get('role')!='admin':
        return redirect('/login')
    conn = sqlite3.connect('voting.db')
    conn.execute("UPDATE users SET verified=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User approved.")
    return redirect('/admin/verify_users')

@app.route('/user')
def user_dashboard():
    if session.get('role')!='user':
        return redirect('/login')
    now = datetime.now().isoformat()
    conn = sqlite3.connect('voting.db')
    ongoing = conn.execute("SELECT * FROM elections WHERE start_date<=? AND end_date>=?", (now,now)).fetchall()
    expired = conn.execute("SELECT * FROM elections WHERE end_date<?", (now,)).fetchall()
    voted = conn.execute("SELECT election_id FROM votes WHERE user_id=?", (session['user_id'],)).fetchall()
    voted_ids = {v[0] for v in voted}
    conn.close()
    return render_template('user_dashboard.html', ongoing=ongoing, expired=expired, voted=voted_ids)

@app.route('/vote/<int:election_id>', methods=['GET','POST'])
def vote(election_id):
    if session.get('role')!='user':
        return redirect('/login')
    conn = sqlite3.connect('voting.db')
    verified = conn.execute("SELECT verified FROM users WHERE id=?", (session['user_id'],)).fetchone()[0]
    if verified == 0:
        conn.close()
        flash("Awaiting admin approval.")
        return redirect('/user')
    now = datetime.now().isoformat()
    election = conn.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    if not (election[2] <= now <= election[3]):
        conn.close()
        flash("Election not active.")
        return redirect('/user')
    if conn.execute("SELECT * FROM votes WHERE user_id=? AND election_id=?", (session['user_id'], election_id)).fetchone():
        conn.close()
        flash("Already voted.")
        return redirect('/user')
    candidates = conn.execute("SELECT * FROM candidates WHERE election_id=?", (election_id,)).fetchall()
    if request.method=='POST':
        cid = request.form['candidate']
        conn.execute("INSERT INTO votes(user_id,candidate_id,election_id) VALUES(?,?,?)",
                     (session['user_id'], cid, election_id))
        conn.commit()
        conn.close()
        flash("Vote cast!")
        return redirect('/user')
    conn.close()
    return render_template('vote.html', election=election, candidates=candidates)

@app.route('/result/<int:election_id>')
def result(election_id):
    conn = sqlite3.connect('voting.db')
    election = conn.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    now = datetime.now().isoformat()
    if now <= election[3]:
        conn.close()
        flash("Wait for results.")
        return redirect('/user')
    results = conn.execute("""
      SELECT c.name, COUNT(v.id)
      FROM votes v
      JOIN candidates c ON v.candidate_id=c.id
      WHERE v.election_id=?
      GROUP BY c.name
    """, (election_id,)).fetchall()
    conn.close()
    return render_template('result.html', election=election, results=results)

@app.route('/export')
def export():
    if not session.get('logged_in') or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect('voting.db')
    df = pd.read_sql_query("SELECT * FROM votes", conn)
    conn.close()

    file_path = "votes_export.xlsx"
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)

@app.route('/export/<int:election_id>')
def export_election(election_id):
    conn = sqlite3.connect('voting.db')
    results = conn.execute("""
      SELECT c.name AS Candidate, COUNT(v.id) AS Votes
      FROM votes v
      JOIN candidates c ON v.candidate_id=c.id
      WHERE v.election_id=?
      GROUP BY c.name
    """, (election_id,)).fetchall()
    df = pd.DataFrame(results, columns=['Candidate', 'Votes'])
    file_path = os.path.join(UPLOAD_FOLDER, f"election_{election_id}_results.xlsx")
    df.to_excel(file_path, index=False)
    conn.close()
    return send_file(file_path, as_attachment=True)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
