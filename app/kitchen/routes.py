from flask import Blueprint, render_template, request, redirect, url_for, session
from sqlalchemy import or_
from app.extensions import db
from app.models import Pesanan
from app.utils import utc_now, myt_start_of_today_utc

kitchen_bp = Blueprint('kitchen', __name__)

VALID_STATUSES = ('Baru', 'Diproses', 'Selesai')


@kitchen_bp.before_request
def restrict_to_kitchen():
    if session.get('user_role') not in ['dapur', 'admin']:
        return redirect(url_for('login'))

@kitchen_bp.route('/orders')
def live_orders():
    # Show all active orders plus today's completed orders so the 'Siap' tab works
    start_of_today = myt_start_of_today_utc()
    orders = (Pesanan.query
              .filter(or_(Pesanan.status_pesanan != 'Selesai', Pesanan.tarikh_masa >= start_of_today))
              .order_by(Pesanan.tarikh_masa.desc())
              .all())
    now = utc_now()
    return render_template('kitchen/dashboardDapur.html', orders=orders, now=now)

@kitchen_bp.route('/order/<int:order_id>/status', methods=['POST'])
def update_status(order_id):
    order = Pesanan.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in VALID_STATUSES:
        order.status_pesanan = new_status
        db.session.commit()
    return redirect(url_for('kitchen.live_orders'))
