import os
from flask import (Blueprint, render_template, request, session, redirect,
                   url_for, jsonify, current_app, flash)
from app.extensions import db
from app.models import Menu, Pelanggan, Pesanan
from app.utils import UploadError, save_image, delete_upload, normalize_table

customer_bp = Blueprint('customer', __name__)

MAX_QTY_PER_ITEM = 20   # per drink
MAX_TOTAL_QTY = 50      # per order
MAX_NOTE_LENGTH = 255   # matches Pesanan.nota_tambahan
VALID_ORDER_TYPES = ('Dine-In', 'Takeaway')


def food_folder():
    return os.path.join(current_app.static_folder, 'uploads', 'food')


@customer_bp.route('/')
def welcome():
    raw_table = request.args.get('table')
    if raw_table is not None:
        table_no = normalize_table(raw_table)
        if table_no:
            session['table_number'] = table_no
        else:
            flash('Nombor meja tidak sah. Sila imbas semula kod QR meja anda.', 'warning')
    current_table = normalize_table(session.get('table_number'))
    return render_template('customer/welcome.html', table_number=current_table)

@customer_bp.route('/select_type', methods=['POST'])
def select_type():
    jenis = request.form.get('jenis_sajian')
    session['jenis_sajian'] = jenis

    if jenis == 'Minum Sahaja':
        # A drinks-only order has no food photo; drop any photo left over from an earlier step
        delete_upload(food_folder(), session.pop('food_image', None))
        return redirect(url_for('customer.view_menu'))
    return redirect(url_for('customer.upload_food'))

@customer_bp.route('/upload_food', methods=['GET', 'POST'])
def upload_food():
    if request.method == 'POST':
        file = request.files.get('food_image')
        if file and file.filename:
            try:
                filename = save_image(file, food_folder())
            except UploadError as error:
                flash(str(error), 'danger')
                return redirect(url_for('customer.upload_food'))

            # The order (Pelanggan row) does not exist yet, so the filename waits in the
            # session until place_order saves it to the database. Replace any earlier photo.
            delete_upload(food_folder(), session.get('food_image'))
            session['food_image'] = filename
        if session.get('jenis_sajian') == 'Makan Sahaja' and session.get('food_image'):
            return redirect(url_for('customer.view_menu', cart=1))
        return redirect(url_for('customer.view_menu'))
    return render_template('customer/uploadFood.html')

@customer_bp.route('/menu')
def view_menu():
    raw_table = request.args.get('table')
    if raw_table is not None:
        table_no = normalize_table(raw_table)
        if table_no:
            session['table_number'] = table_no
        else:
            flash('Nombor meja tidak sah. Sila imbas semula kod QR meja anda.', 'warning')
    current_table = normalize_table(session.get('table_number'))
    drinks = Menu.query.filter_by(status_menu=True).all()
    open_cart = request.args.get('cart') == '1'

    active_customer_id = None
    existing_id = session.get('customer_id')
    if existing_id:
        existing = Pelanggan.query.get(existing_id)
        if existing and existing.no_meja == current_table and existing.status_bayaran != 'Sudah Bayar':
            active_customer_id = existing.id_pelanggan

    return render_template('customer/menu.html', drinks=drinks, table_number=current_table,
                           has_food=bool(session.get('food_image')),
                           open_cart=open_cart,
                           active_customer_id=active_customer_id,
                           max_qty=MAX_QTY_PER_ITEM, max_total=MAX_TOTAL_QTY)

@customer_bp.route('/order', methods=['POST'])
def place_order():
    table_no = normalize_table(session.get('table_number'))
    if not table_no:
        flash('Nombor meja tidak sah atau belum ditetapkan. Sila imbas kod QR meja anda.', 'danger')
        return redirect(url_for('customer.welcome'))
    jenis_pesanan = request.form.get('jenis_pesanan', 'Dine-In')
    if jenis_pesanan not in VALID_ORDER_TYPES:
        jenis_pesanan = 'Dine-In'
    drinks = Menu.query.filter_by(status_menu=True).all()

    # Read and validate the whole form first. Nothing is written to the database
    # unless there is at least one valid item.
    lines = []
    total_qty = 0
    for drink in drinks:
        raw_qty = (request.form.get(f'qty_{drink.id_menu}') or '0').strip()
        try:
            qty = int(raw_qty)
        except ValueError:
            flash('Kuantiti tidak sah.', 'danger')
            return redirect(url_for('customer.view_menu'))

        if qty < 0 or qty > MAX_QTY_PER_ITEM:
            flash(f'Kuantiti maksimum bagi setiap minuman ialah {MAX_QTY_PER_ITEM}.', 'danger')
            return redirect(url_for('customer.view_menu'))
        if qty == 0:
            continue

        notes = (request.form.get(f'notes_{drink.id_menu}') or '').strip()[:MAX_NOTE_LENGTH]
        lines.append((drink, qty, notes))
        total_qty += qty

    # A food-only order ("Makan Sahaja") has no drinks, but it does have an uploaded food photo.
    # Without a photo, an order with no drinks is still rejected.
    food_image = session.get('food_image')
    if total_qty == 0 and not food_image:
        flash('Sila pilih sekurang-kurangnya satu minuman.', 'warning')
        return redirect(url_for('customer.view_menu'))
    if total_qty > MAX_TOTAL_QTY:
        flash(f'Jumlah maksimum ialah {MAX_TOTAL_QTY} cawan bagi satu pesanan.', 'danger')
        return redirect(url_for('customer.view_menu'))

    existing_id = session.get('customer_id')
    customer = None
    if existing_id:
        existing = Pelanggan.query.get(existing_id)
        if existing and existing.no_meja == table_no and existing.status_bayaran != 'Sudah Bayar':
            customer = existing

    old_food_image = None
    if customer is None:
        customer = Pelanggan(no_meja=table_no, jenis_pesanan=jenis_pesanan,
                             status_bayaran='Belum Bayar', gambar_makanan=food_image)
        db.session.add(customer)
        db.session.flush()  # assigns id_pelanggan without committing yet
    elif food_image:
        if customer.gambar_makanan and customer.gambar_makanan != food_image:
            old_food_image = customer.gambar_makanan
        customer.gambar_makanan = food_image

    for drink, qty, notes in lines:
        db.session.add(Pesanan(
            id_pelanggan=customer.id_pelanggan,
            id_menu=drink.id_menu,
            kuantiti=qty,
            harga_semasa=drink.harga,
            nota_tambahan=notes,
            status_pesanan='Baru'
        ))
    db.session.commit()  # customer and items are saved together or not at all

    if old_food_image:
        delete_upload(food_folder(), old_food_image)

    # The food photo now lives on the Pelanggan row; the order owner is remembered for /status
    session.pop('food_image', None)
    session['customer_id'] = customer.id_pelanggan
    return redirect(url_for('customer.order_status', customer_id=customer.id_pelanggan))

@customer_bp.route('/status/<int:customer_id>')
def order_status(customer_id):
    # Only the browser session that placed the order may view it. The check runs before
    # any database lookup, so unknown ids and other tables' ids get the same response.
    if session.get('customer_id') != customer_id:
        return redirect(url_for('customer.welcome'))

    customer = Pelanggan.query.get_or_404(customer_id)
    orders = Pesanan.query.filter_by(id_pelanggan=customer_id).all()
    food_price = customer.harga_makanan or 0
    total_price = sum(o.kuantiti * o.unit_price for o in orders) + food_price

    return render_template('customer/success.html',
                           table_number=customer.no_meja,
                           jenis_pesanan=customer.jenis_pesanan,
                           orders=orders,
                           total_price=total_price,
                           has_food=bool(customer.gambar_makanan),
                           food_price=food_price,
                           customer_id=customer_id,
                           order_time=customer.tarikh_masa)

@customer_bp.route('/api/status/<int:customer_id>')
def api_order_status(customer_id):
    if session.get('customer_id') != customer_id:
        return jsonify({'error': 'Akses ditolak'}), 403

    customer = Pelanggan.query.get_or_404(customer_id)
    orders = Pesanan.query.filter_by(id_pelanggan=customer_id).all()
    data = [{
        'id_pesanan': o.id_pesanan,
        'nama_minuman': o.menu.nama_minuman if o.menu else '',
        'kuantiti': o.kuantiti,
        'status': o.status_pesanan
    } for o in orders]
    return jsonify({
        'orders': data,
        'food_price': float(customer.harga_makanan or 0),
        'status_bayaran': customer.status_bayaran,
    })
