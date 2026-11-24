import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
from app.extensions import db
from app.models import Admin, Dapur
from app.utils import MAX_IMAGE_MB

# Load environment variables from .env file
load_dotenv()

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    # SECRET_KEY and DATABASE_URL come from the environment (.env); see .env.example
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key:
        secret_key = 'dev-secret-key-123'
        app.logger.warning('SECRET_KEY is not set. Using an insecure development key. Set it in .env before deploying.')
    app.config['SECRET_KEY'] = secret_key

    default_db = f"sqlite:///{os.path.join(app.instance_path, 'database.db')}"
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL') or default_db
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Reject oversized requests early (a little above the per-image limit to allow for form overhead)
    app.config['MAX_CONTENT_LENGTH'] = (MAX_IMAGE_MB + 1) * 1024 * 1024

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            role = request.form.get('role')
            username = request.form.get('username')
            password = request.form.get('password')

            if role == 'admin':
                user = Admin.query.filter_by(nama_admin=username).first()
                if user and check_password_hash(user.kata_laluan, password):
                    session['user_role'] = 'admin'
                    return redirect(url_for('admin.dashboard'))
            elif role == 'dapur':
                user = Dapur.query.filter_by(nama_pengguna=username).first()
                if user and check_password_hash(user.kata_laluan, password):
                    if not user.status:
                        return render_template('login.html', error='Akaun dapur tidak aktif.')
                    session['user_role'] = 'dapur'
                    return redirect(url_for('kitchen.live_orders'))

            return render_template('login.html', error='Nama pengguna atau kata laluan salah.')

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.errorhandler(RequestEntityTooLarge)
    def file_too_large(error):
        flash(f'Saiz fail terlalu besar. Maksimum {MAX_IMAGE_MB} MB.', 'danger')
        if request.path.startswith('/admin'):
            return redirect(url_for('admin.dashboard'))
        if request.path.startswith('/upload_food'):
            return redirect(url_for('customer.upload_food'))
        return redirect(url_for('customer.welcome'))

    from app.customer.routes import customer_bp
    from app.kitchen.routes import kitchen_bp
    from app.admin.routes import admin_bp

    app.register_blueprint(customer_bp)
    app.register_blueprint(kitchen_bp, url_prefix='/kitchen')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app
