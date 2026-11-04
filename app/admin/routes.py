import os
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from app.extensions import db
from app.models import Menu, Pesanan, Pelanggan
from app.utils import UploadError, save_image, delete_upload, parse_price

admin_bp = Blueprint('admin', __name__)

VALID_CATEGORIES = ('Panas', 'Sejuk')


def drinks_folder():
    return os.path.join(current_app.static_folder, 'uploads', 'drinks')

@admin_bp.before_request
def restrict_to_admin():
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))

@admin_bp.route('/dashboard')
def dashboard():
    drinks = Menu.query.all()
    completed_orders = Pesanan.query.filter_by(status_pesanan='Selesai').all()

    # Sales metrics
    total_sales = sum(order.kuantiti * order.menu.harga for order in completed_orders if order.menu)
    total_orders = len(completed_orders)
    total_drinks_sold = sum(order.kuantiti for order in completed_orders)

    # Dynamic 7-Day Sales Calculation
    today = datetime.utcnow().date()
    chart_days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    sales_by_date = {d: 0.0 for d in chart_days}

    for order in completed_orders:
        if order.tarikh_masa and order.menu:
            order_date = order.tarikh_masa.date()
            if order_date in sales_by_date:
                sales_by_date[order_date] += float(order.kuantiti * order.menu.harga)

    max_sale = max(sales_by_date.values()) if sales_by_date and max(sales_by_date.values()) > 0 else 1.0
    chart_data = []
    for d in chart_days:
        amount = sales_by_date[d]
        pct = int((amount / max_sale) * 100) if max_sale > 0 else 0
        chart_data.append({
            'date_str': d.strftime('%d/%m'),
            'day_name': d.strftime('%a'),
            'amount': amount,
            'height_pct': max(pct, 6) if amount > 0 else 6
        })

    # Table Status & Payment Calculation (Meja A1 - A10)
    table_list = [f"A{i}" for i in range(1, 11)]
    table_data = []

    for t in table_list:
        cust = Pelanggan.query.filter_by(no_meja=t).order_by(Pelanggan.id_pelanggan.desc()).first()
        if cust and cust.pesanan:
            drinks_total = sum((p.kuantiti * p.menu.harga for p in cust.pesanan if p.menu), Decimal('0'))
            food_price = cust.harga_makanan or Decimal('0')
            table_data.append({
                'table_name': t,
                'customer_id': cust.id_pelanggan,
                'status_bayaran': getattr(cust, 'status_bayaran', 'Belum Bayar'),
                'drinks_total': float(drinks_total),
                'food_price': float(food_price),
                'total_due': float(drinks_total + food_price),
                'food_image': cust.gambar_makanan,
                'has_orders': True
            })
        else:
            table_data.append({
                'table_name': t,
                'customer_id': None,
                'status_bayaran': 'Tiada Pesanan',
                'drinks_total': 0.0,
                'food_price': 0.0,
                'total_due': 0.0,
                'food_image': None,
                'has_orders': False
            })

    transactions = Pesanan.query.order_by(Pesanan.tarikh_masa.desc()).limit(15).all()

    return render_template('admin/dashboardAdmin.html',
                           drinks=drinks,
                           total_sales=total_sales,
                           total_orders=total_orders,
                           total_drinks_sold=total_drinks_sold,
                           chart_data=chart_data,
                           table_data=table_data,
                           transactions=transactions)

@admin_bp.route('/table/<int:customer_id>/toggle_payment', methods=['POST'])
def toggle_payment(customer_id):
    customer = Pelanggan.query.get_or_404(customer_id)
    # Payment only changes the payment status. Kitchen status (Baru/Diproses/Selesai)
    # is updated by the kitchen, so unfinished drinks stay on the kitchen dashboard.
    if customer.status_bayaran == 'Sudah Bayar':
        customer.status_bayaran = 'Belum Bayar'
    else:
        customer.status_bayaran = 'Sudah Bayar'
    db.session.commit()
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/table/<int:customer_id>/food_price', methods=['POST'])
def update_food_price(customer_id):
    customer = Pelanggan.query.get_or_404(customer_id)

    if not customer.gambar_makanan:
        flash('Pesanan ini tiada gambar makanan untuk dinilai.', 'warning')
        return redirect(url_for('admin.dashboard'))
    if customer.status_bayaran == 'Sudah Bayar':
        flash('Tukar status kepada Belum Bayar sebelum mengubah harga makanan.', 'warning')
        return redirect(url_for('admin.dashboard'))

    price = parse_price(request.form.get('harga_makanan'))
    if price is None:
        flash('Harga makanan tidak sah. Masukkan nilai antara 0 dan 9999.99.', 'danger')
        return redirect(url_for('admin.dashboard'))

    customer.harga_makanan = price
    db.session.commit()
    flash(f'Harga makanan Meja {customer.no_meja} dikemaskini kepada RM {price:.2f}.', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/menu/add', methods=['POST'])
def add_menu():
    nama = (request.form.get('nama_minuman') or '').strip()
    kategori = request.form.get('kategori', 'Panas')
    harga = parse_price(request.form.get('harga'))

    # Validate every field before saving any file, so a bad form leaves nothing behind
    if not nama or len(nama) > 100:
        flash('Nama minuman diperlukan (maksimum 100 aksara).', 'danger')
        return redirect(url_for('admin.dashboard'))
    if kategori not in VALID_CATEGORIES:
        flash('Kategori tidak sah.', 'danger')
        return redirect(url_for('admin.dashboard'))
    if harga is None or harga <= 0:
        flash('Harga tidak sah. Masukkan nilai lebih daripada 0.', 'danger')
        return redirect(url_for('admin.dashboard'))

    gambar = None
    file = request.files.get('gambar_minuman')
    if file and file.filename:
        try:
            gambar = save_image(file, drinks_folder())
        except UploadError as error:
            flash(str(error), 'danger')
            return redirect(url_for('admin.dashboard'))

    try:
        db.session.add(Menu(nama_minuman=nama, harga=harga, kategori=kategori,
                            status_menu=True, gambar_minuman=gambar))
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_upload(drinks_folder(), gambar)
        raise

    flash(f'{nama} ditambah ke menu.', 'success')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/menu/<int:drink_id>/toggle', methods=['POST'])
def toggle_menu(drink_id):
    drink = Menu.query.get_or_404(drink_id)
    drink.status_menu = not drink.status_menu
    db.session.commit()
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/menu/<int:drink_id>/delete', methods=['POST'])
def delete_menu(drink_id):
    drink = Menu.query.get_or_404(drink_id)
    image = drink.gambar_minuman
    db.session.delete(drink)
    db.session.commit()
    delete_upload(drinks_folder(), image)
    return redirect(url_for('admin.dashboard'))
