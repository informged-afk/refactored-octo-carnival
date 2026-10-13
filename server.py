import os
import re
import time
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_from_directory, abort)
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mediaflex-dev-secret-change-me')
bcrypt = Bcrypt(app)

DB_FILE = 'users.db'
UPLOAD_FOLDER = 'uploads'
POSTER_FOLDER = os.path.join(UPLOAD_FOLDER, 'posters')
VIDEO_FOLDER = os.path.join(UPLOAD_FOLDER, 'videos')

os.makedirs(POSTER_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'webm'}

STATIC_MOVIES = [
    {
        'id': 1000001, 'title': 'Интерстеллар', 'year': 2014,
        'genre': 'Фантастика, Драма', 'rating': 8.6,
        'poster_url': 'https://avatars.mds.yandex.net/get-kinopoisk-image/1600647/430042eb-ee69-4818-aed0-a312400a26bf/220x330',
        'video_url': 'https://rutube.ru/play/embed/17465fc541700b94ebd5648423675100/',
        'description': 'Когда засуха, пыльные бури и вымирание растений приводят человечество к продовольственному кризису...',
        'is_static': True, 'poster_file': None, 'video_file': None,
    },
    {
        'id': 1000002, 'title': 'Начало', 'year': 2010,
        'genre': 'Боевик, Фантастика', 'rating': 8.7,
        'poster_url': 'https://avatars.mds.yandex.net/get-kinopoisk-image/1629390/8ab9a119-dd74-44f0-baec-0629797483d7/220x330',
        'video_url': 'https://rutube.ru/play/embed/b50bdec402cc216d1f19fe3fff830dd6/',
        'description': 'Кобб — талантливый вор, лучший в опасном искусстве извлечения...',
        'is_static': True, 'poster_file': None, 'video_file': None,
    },
    {
        'id': 1000003, 'title': 'Тёмный рыцарь', 'year': 2008,
        'genre': 'Триллер, Боевик', 'rating': 9.0,
        'poster_url': 'https://upload.wikimedia.org/wikipedia/ru/f/f4/%D0%A2%D1%91%D0%BC%D0%BD%D1%8B%D0%B9_%D1%80%D1%8B%D1%86%D0%B0%D1%80%D1%8C_%282008%29_%D0%BF%D0%BE%D1%81%D1%82%D0%B5%D1%80.jpg',
        'video_url': 'https://rutube.ru/play/embed/eeef5e15618da12dfa093a6a9ed15d0d/',
        'description': 'Бэтмен поднимает ставки в войне с криминалом...',
        'is_static': True, 'poster_file': None, 'video_file': None,
    },
    {
        'id': 1000004, 'title': 'Дюна: Часть вторая', 'year': 2024,
        'genre': 'Фантастика, Приключения', 'rating': 8.4,
        'poster_url': 'https://avatars.mds.yandex.net/get-kinopoisk-image/10953618/20f20a76-e8d8-4b04-9041-1f044d87e55a/600x900',
        'video_url': 'https://rutube.ru/play/embed/1442bf34b5b9cfc739c809cd19a6718f/',
        'description': 'Пол Атрейдес объединяется с Чани и фременами...',
        'is_static': True, 'poster_file': None, 'video_file': None,
    },
]


# ----------------------- Утилиты -----------------------
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def allowed_file(filename, extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in extensions


def get_embed_url(url):
    if not url:
        return None
    if 'rutube.ru' in url:
        m = re.search(r'embed/([a-zA-Z0-9]+)', url) or re.search(r'/video/([a-zA-Z0-9]+)', url)
        return f'https://rutube.ru/play/embed/{m.group(1)}' if m else url
    if 'youtube.com' in url or 'youtu.be' in url:
        vid = ''
        if 'youtu.be/' in url:
            vid = url.split('youtu.be/')[1].split('?')[0]
        elif 'watch?v=' in url:
            vid = url.split('watch?v=')[1].split('&')[0]
        elif 'embed/' in url:
            vid = url.split('embed/')[1].split('?')[0]
        return f'https://www.youtube.com/embed/{vid}' if vid else url
    return url


def find_movie(movie_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM movies WHERE id = ?', (movie_id,)).fetchone()
    conn.close()
    if row:
        m = dict(row)
        m['is_static'] = False
        return m
    for sm in STATIC_MOVIES:
        if sm['id'] == movie_id:
            return sm.copy()
    return None


def all_movies():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM movies ORDER BY id DESC').fetchall()
    conn.close()
    db_movies = [dict(r) for r in rows]
    for m in db_movies:
        m['is_static'] = False

    db_titles = {m['title'] for m in db_movies}
    combined = list(db_movies)
    for sm in STATIC_MOVIES:
        if sm['title'] not in db_titles:
            combined.append(sm.copy())
    return combined


def migrate_db(cursor):
    cursor.execute("PRAGMA table_info(movies)")
    columns = [c[1] for c in cursor.fetchall()]
    for col, ddl in [
        ('video_file', "ALTER TABLE movies ADD COLUMN video_file TEXT"),
        ('poster_file', "ALTER TABLE movies ADD COLUMN poster_file TEXT"),
        ('description', "ALTER TABLE movies ADD COLUMN description TEXT"),
        ('video_url', "ALTER TABLE movies ADD COLUMN video_url TEXT"),
        ('poster_url', "ALTER TABLE movies ADD COLUMN poster_url TEXT"),
    ]:
        if col not in columns:
            cursor.execute(ddl)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            year INTEGER NOT NULL,
            genre TEXT NOT NULL,
            rating REAL,
            description TEXT,
            video_url TEXT,
            poster_url TEXT,
            video_file TEXT,
            poster_file TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    migrate_db(cur)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
        first = cur.fetchone()
        if first:
            cur.execute("UPDATE users SET role = 'admin' WHERE id = ?", (first['id'],))
            conn.commit()

    conn.close()


init_db()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('user_id'):
            flash('Требуется вход в систему', 'error')
            return redirect(url_for('login', next=request.path))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get('user_id'):
            flash('Требуется вход в систему', 'error')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Доступ только для администраторов', 'error')
            return redirect(url_for('index'))
        return f(*a, **kw)
    return wrapper


@app.context_processor
def inject_user():
    if session.get('user_id'):
        return {'current_user': {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'email': session.get('email'),
            'role': session.get('role'),
        }}
    return {'current_user': None}


@app.template_filter('date_fmt')
def date_fmt_filter(value):
    if not value:
        return '—'
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.split('.')[0])
        else:
            dt = value
        return dt.strftime('%d.%m.%Y')
    except Exception:
        return value


@app.route('/')
def index():
    movies = all_movies()
    movies.sort(key=lambda m: m['id'], reverse=True)
    return render_template('index.html', movies=movies)


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    m = find_movie(movie_id)
    if not m:
        abort(404)

    embed_url = None
    if not m.get('video_file') and m.get('video_url'):
        embed_url = get_embed_url(m['video_url'])

    return render_template('movie.html', movie=m, embed_url=embed_url)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Заполните все поля', 'error')
            return render_template('login.html')

        conn = get_conn()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user['email']
            session['role'] = user['role']
            flash('Вы успешно вошли', 'success')
            nxt = request.args.get('next')
            if not nxt:
                nxt = url_for('admin_panel') if user['role'] == 'admin' else url_for('index')
            return redirect(nxt)

        flash('Неверный Email или пароль', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not all([username, email, password]):
            flash('Заполните все поля', 'error')
            return render_template('register.html')
        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'error')
            return render_template('register.html')

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        try:
            conn = get_conn()
            conn.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                         (username, email, hashed))
            conn.commit()
            conn.close()
            flash('Регистрация успешна! Войдите.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Этот Email уже зарегистрирован', 'error')
            return render_template('register.html')

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@admin_required
def admin_panel():
    tab = request.args.get('tab', 'users')

    conn = get_conn()
    users = [dict(r) for r in conn.execute(
        'SELECT id, username, email, role, created_at FROM users ORDER BY id DESC'
    ).fetchall()]
    conn.close()

    movies = all_movies()
    movies.sort(key=lambda m: m['id'], reverse=True)

    week_ago = datetime.now() - timedelta(days=7)
    recent = 0
    for u in users:
        try:
            if u['created_at']:
                dt = datetime.fromisoformat(str(u['created_at']).split('.')[0])
                if dt > week_ago:
                    recent += 1
        except Exception:
            pass

    return render_template('admin.html',
                           tab=tab,
                           users=users,
                           movies=movies,
                           total_users=len(users),
                           total_movies=len(movies),
                           total_admins=sum(1 for u in users if u['role'] == 'admin'),
                           recent_users=recent)


@app.route('/admin/movies/new', methods=['POST'])
@admin_required
def admin_add_movie():
    title = request.form.get('title', '').strip()
    year = request.form.get('year')
    genre = request.form.get('genre', '').strip()
    rating_raw = request.form.get('rating', '').strip()
    description = request.form.get('description', '').strip()
    video_url = request.form.get('video_url', '').strip()
    poster_url = request.form.get('poster_url', '').strip()

    if not title or not year or not genre:
        flash('Название, год и жанр обязательны', 'error')
        return redirect(url_for('admin_panel', tab='add-movie'))

    try:
        rating = float(rating_raw) if rating_raw else None
    except ValueError:
        rating = None

    poster_file = None
    f = request.files.get('poster_file')
    if f and f.filename:
        if not allowed_file(f.filename, ALLOWED_IMAGE_EXTENSIONS):
            flash('Недопустимый формат постера', 'error')
            return redirect(url_for('admin_panel', tab='add-movie'))
        fname = secure_filename(f"poster_{int(time.time())}_{f.filename}")
        f.save(os.path.join(POSTER_FOLDER, fname))
        poster_file = f"uploads/posters/{fname}"

    video_file = None
    f = request.files.get('video_file')
    if f and f.filename:
        if not allowed_file(f.filename, ALLOWED_VIDEO_EXTENSIONS):
            flash('Недопустимый формат видео', 'error')
            return redirect(url_for('admin_panel', tab='add-movie'))
        fname = secure_filename(f"video_{int(time.time())}_{f.filename}")
        f.save(os.path.join(VIDEO_FOLDER, fname))
        video_file = f"uploads/videos/{fname}"

    conn = get_conn()
    conn.execute('''
        INSERT INTO movies (title, year, genre, rating, description, video_url, poster_url, video_file, poster_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (title, year, genre, rating, description, video_url, poster_url, video_file, poster_file))
    conn.commit()
    conn.close()

    flash('Фильм добавлен!', 'success')
    return redirect(url_for('admin_panel', tab='movies'))


@app.route('/admin/movies/<int:movie_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_movie(movie_id):
    m = find_movie(movie_id)
    if not m:
        abort(404)
    is_static = m.get('is_static', False)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        year = request.form.get('year')
        genre = request.form.get('genre', '').strip()
        rating_raw = request.form.get('rating', '').strip()
        description = request.form.get('description', '').strip()
        video_url = request.form.get('video_url', '').strip()
        poster_url = request.form.get('poster_url', '').strip()

        if not title or not year or not genre:
            flash('Заполните обязательные поля', 'error')
            return redirect(url_for('admin_edit_movie', movie_id=movie_id))

        try:
            rating = float(rating_raw) if rating_raw else None
        except ValueError:
            rating = None

        conn = get_conn()
        if is_static:
            conn.execute('''
                INSERT INTO movies (title, year, genre, rating, description, video_url, poster_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, year, genre, rating, description, video_url, poster_url))
            flash('Создана копия статического фильма в БД', 'success')
        else:
            conn.execute('''
                UPDATE movies SET title=?, year=?, genre=?, rating=?, description=?, video_url=?, poster_url=?
                WHERE id=?
            ''', (title, year, genre, rating, description, video_url, poster_url, movie_id))
            flash('Фильм обновлён', 'success')
        conn.commit()
        conn.close()
        return redirect(url_for('admin_panel', tab='movies'))

    return render_template('admin_edit_movie.html', movie=m, is_static=is_static)


@app.route('/admin/movies/<int:movie_id>/delete', methods=['POST'])
@admin_required
def admin_delete_movie(movie_id):
    m = find_movie(movie_id)
    if m and m.get('is_static'):
        flash('Статический фильм нельзя удалить', 'error')
        return redirect(url_for('admin_panel', tab='movies'))

    conn = get_conn()
    row = conn.execute('SELECT poster_file, video_file FROM movies WHERE id=?', (movie_id,)).fetchone()
    if row:
        for key in ('poster_file', 'video_file'):
            if row[key]:
                path = row[key]
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
    conn.execute('DELETE FROM movies WHERE id=?', (movie_id,))
    conn.commit()
    conn.close()
    flash('Фильм удалён', 'success')
    return redirect(url_for('admin_panel', tab='movies'))


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    conn = get_conn()
    user = conn.execute(
        'SELECT id, username, email, role, created_at FROM users WHERE id=?', (user_id,)
    ).fetchone()
    if not user:
        conn.close()
        abort(404)
    user = dict(user)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        role = request.form.get('role', 'user')

        if not username or not email:
            flash('Заполните все поля', 'error')
            conn.close()
            return redirect(url_for('admin_edit_user', user_id=user_id))

        if user['role'] == 'admin' and role != 'admin':
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin'"
            ).fetchone()[0]
            if admin_count <= 1:
                flash('Нельзя разжаловать единственного администратора', 'error')
                conn.close()
                return redirect(url_for('admin_edit_user', user_id=user_id))

        try:
            conn.execute('UPDATE users SET username=?, email=?, role=? WHERE id=?',
                         (username, email, role, user_id))
            conn.commit()
            if session.get('user_id') == user_id:
                session['username'] = username
                session['email'] = email
                session['role'] = role
            conn.close()
            flash('Пользователь обновлён', 'success')
            return redirect(url_for('admin_panel', tab='users'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Этот Email уже используется', 'error')
            return redirect(url_for('admin_edit_user', user_id=user_id))

    conn.close()
    return render_template('admin_edit_user.html', user=user)


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    conn = get_conn()
    user = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        conn.close()
        flash('Пользователь не найден', 'error')
        return redirect(url_for('admin_panel', tab='users'))

    admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    if user['role'] == 'admin' and admin_count <= 1:
        conn.close()
        flash('Нельзя удалить единственного администратора', 'error')
        return redirect(url_for('admin_panel', tab='users'))

    conn.execute('DELETE FROM users WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    flash('Пользователь удалён', 'success')
    return redirect(url_for('admin_panel', tab='users'))


@app.route('/admin/users/<int:user_id>/promote', methods=['POST'])
@admin_required
def admin_promote_user(user_id):
    conn = get_conn()
    conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash('Пользователь повышен до администратора', 'success')
    return redirect(url_for('admin_panel', tab='users'))


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.errorhandler(404)
def not_found(e):
    return render_template('base.html'), 404


if __name__ == '__main__':
    print("=" * 50)
    print(f" Рабочая директория: {os.getcwd()}")
    print(f" База данных: {os.path.abspath(DB_FILE)}")
    print(f" Папка загрузок: {os.path.abspath(UPLOAD_FOLDER)}")
    print(f" Статических фильмов: {len(STATIC_MOVIES)}")
    print(" Сервер запущен на http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000, host='0.0.0.0', threaded=True)