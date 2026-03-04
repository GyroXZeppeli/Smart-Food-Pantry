from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb
import MySQLdb.cursors
from functools import wraps
from datetime import date, timedelta
import random
import json

app = Flask(__name__)
app.secret_key = "1234"

# --- Database connection ---
def get_db_connection():
    return MySQLdb.connect(
        host="localhost",
        user="root",
        passwd="12345",
        db="food_expiry"
    )


def ensure_db_schema():
    """Ensure required columns and tables exist. Runs safely at startup."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Ensure columns on food_items
        cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='food_items' AND COLUMN_NAME='quantity'", ('food_expiry',))
        if cur.fetchone()[0] == 0:
            cur.execute("ALTER TABLE food_items ADD COLUMN quantity DECIMAL(10,2) DEFAULT 1")
        cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='food_items' AND COLUMN_NAME='unit'", ('food_expiry',))
        if cur.fetchone()[0] == 0:
            cur.execute("ALTER TABLE food_items ADD COLUMN unit VARCHAR(20) DEFAULT 'units'")
        cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='food_items' AND COLUMN_NAME='added_date'", ('food_expiry',))
        if cur.fetchone()[0] == 0:
            cur.execute("ALTER TABLE food_items ADD COLUMN added_date DATE DEFAULT (CURRENT_DATE())")

        # Ensure consumption_logs table exists
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME='consumption_logs'", ('food_expiry',))
        if cur.fetchone()[0] == 0:
            cur.execute("""
            CREATE TABLE consumption_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                entry_id INT NOT NULL,
                type ENUM('consumed','wasted') NOT NULL,
                quantity DECIMAL(10,2) NOT NULL,
                date DATE DEFAULT (CURRENT_DATE())
            )
            """)

        conn.commit()
    except Exception as e:
        # Do not crash the app on schema migration failure; print for debug
        print("[schema migration] warning:", e)
    finally:
        if conn:
            conn.close()

# run schema ensure at import time so missing columns won't crash routes
ensure_db_schema()

# --- Login required decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Auto update food status ---
def update_food_status():
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    today = date.today()
    cur.execute("SELECT id, expiry_date, status FROM food_items")
    foods = cur.fetchall()

    for food in foods:
        fid = food['id']
        exp_date = food['expiry_date']
        status = food['status']
        if status not in ['Consumed', 'Wasted']:
            # calculate days remaining
            days_left = (exp_date - today).days
            if days_left < 0:
                new_status = 'Wasted'
            elif 0 <= days_left <= 2:
                new_status = 'Expiring Soon'
            else:
                new_status = 'Fresh'
            cur.execute("UPDATE food_items SET status=%s WHERE id=%s", (new_status, fid))
    conn.commit()
    conn.close()

# --- Fun Facts ---
FUN_FACTS = [
    "Apples float in water because they are 25% air!",
    "Carrots were originally purple, not orange.",
    "Honey never spoils — archaeologists found edible honey in ancient Egyptian tombs.",
    "Cucumbers are 96% water.",
    "Tomatoes were once thought to be poisonous.",
    "Bananas are berries, but strawberries are not.",
    "Potatoes were the first vegetable grown in space.",
    "The world’s most expensive pizza costs over $12,000.",
    "Watermelons are both a fruit and a vegetable.",
    "Cheese is the most stolen food in the world.",
    "Peanuts are not nuts; they’re legumes.",
    "Broccoli contains more protein than steak (per calorie)!",
    "Ketchup was once sold as medicine.",
    "Avocados never ripen on the tree; only after being picked.",
    "There are over 7,500 varieties of apples worldwide.",
    "Chili peppers can trick your brain into feeling heat.",
    "White chocolate isn’t real chocolate.",
    "Popcorn has been around for thousands of years — even Aztecs ate it.",
    "Pineapples take about two years to grow.",
    "Coffee beans are actually seeds inside red berries.",
    "The smell of fresh-cut grass is actually a plant distress signal.",
    "Egg yolk color depends on the chicken’s diet.",
    "Wasabi paste in most restaurants is actually horseradish dyed green.",
    "Lettuce was once considered sacred by ancient Egyptians.",
    "A group of bananas is called a ‘hand’.",
    "Garlic can help repel mosquitoes.",
    "Onions make you cry because they release sulfuric acid vapors.",
    "Dark chocolate improves brain function.",
    "Coconut water can be used as emergency blood plasma.",
    "Ripe cranberries bounce like rubber balls.",
    "Vanilla flavoring sometimes comes from orchids.",
    "Frozen vegetables can be more nutritious than fresh ones.",
    "Saffron is the most expensive spice in the world.",
    "Applesauce was the first food eaten in space by astronauts.",
    "Mango is the national fruit of India.",
    "Bread was once used as an eraser.",
    "Oranges are not always orange — some are green when ripe.",
    "Cashews grow on the bottom of cashew apples.",
    "Honeybees must visit 2 million flowers to make one pound of honey.",
    "You can’t overripe bananas easily — they just get sweeter."
]

# --- Dashboard ---
@app.route('/')
@login_required
def dashboard():
    update_food_status()
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)

    # Fetch categorized foods for the logged-in user including quantities and added_date
    cur.execute("SELECT id, name, expiry_date, status, quantity, unit, added_date FROM food_items WHERE user_id=%s ORDER BY expiry_date ASC", (user_id,))
    all_foods = cur.fetchall()

    # Separate lists based on status
    fresh_foods = [f for f in all_foods if f['status'] == 'Fresh']
    expiring_foods = [f for f in all_foods if f['status'] == 'Expiring Soon']
    expired_foods = [f for f in all_foods if f['status'] == 'Wasted']
    consumed_foods = [f for f in all_foods if f['status'] == 'Consumed']

    # Inventory aggregates
    total_left = sum([float(f['quantity'] or 0) for f in all_foods if f['status'] not in ('Wasted', 'Consumed')])
    to_use_soon = sum([float(f['quantity'] or 0) for f in all_foods if f['status'] == 'Expiring Soon'])
    total_spoiled = sum([float(f['quantity'] or 0) for f in all_foods if f['status'] == 'Wasted'])

    # Total consumed from logs (all-time)
    cur.execute("SELECT IFNULL(SUM(quantity),0) AS total FROM consumption_logs WHERE user_id=%s AND type='consumed'", (user_id,))
    total_consumed = float(cur.fetchone()['total']) if cur.rowcount else 0.0

    # Reminders: expiring in 2 or fewer days
    today = date.today()
    reminders = []
    for f in all_foods:
        if f['status'] not in ('Consumed', 'Wasted'):
            days_left = (f['expiry_date'] - today).days
            if 0 <= days_left <= 2:
                reminders.append({'id': f['id'], 'name': f['name'], 'days_left': days_left, 'quantity': float(f['quantity'] or 0), 'unit': f['unit']})

    # Pick several fun facts for the sidebar
    fun_facts = random.sample(FUN_FACTS, min(4, len(FUN_FACTS)))

    # Fetch username from DB to ensure latest value and pass to template
    cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    user_row = cur.fetchone()
    # DictCursor returns a dict; handle both dict and tuple just in case
    if user_row:
        if isinstance(user_row, dict):
            username = user_row.get('username')
        else:
            username = user_row[0]
    else:
        username = session.get('username')
    # keep session username in sync
    session['username'] = username

    conn.close()
    # current date for header
    current_date = date.today().strftime('%B %d, %Y')
    return render_template(
        'dashboard.html',
        fresh_foods=fresh_foods,
        expiring_foods=expiring_foods,
        expired_foods=expired_foods,
        consumed_foods=consumed_foods,
        fun_facts=fun_facts,
        current_date=current_date,
        username=username,
        total_left=total_left,
        to_use_soon=to_use_soon,
        total_spoiled=total_spoiled,
        total_consumed=total_consumed,
        reminders=reminders
    )

# --- Food management routes ---
@app.route('/add', methods=['POST'])
@login_required
def add_food():
    name = request.form['name']
    expiry_date = request.form['expiry_date']
    quantity = request.form.get('quantity', 1)
    unit = request.form.get('unit', 'units')
    added_date = request.form.get('added_date') or date.today().isoformat()
    user_id = session.get('user_id')  # Associate food with logged-in user
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO food_items (name, expiry_date, status, user_id, quantity, unit, added_date) VALUES (%s, %s, 'Fresh', %s, %s, %s, %s)",
        (name, expiry_date, user_id, quantity, unit, added_date)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/edit/<int:id>', methods=['POST'])
@login_required
def edit_food(id):
    name = request.form['name']
    expiry_date = request.form['expiry_date']
    quantity = request.form.get('quantity')
    unit = request.form.get('unit')
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor()
    # Only allow editing your own food
    cur.execute(
        "UPDATE food_items SET name=%s, expiry_date=%s, quantity=%s, unit=%s WHERE id=%s AND user_id=%s",
        (name, expiry_date, quantity or 1, unit or 'units', id, user_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:id>')
@login_required
def delete_food(id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor()
    # Only allow deleting your own food
    cur.execute("DELETE FROM food_items WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/consume/<int:id>')
@login_required
def consume_food(id):
    # convenience endpoint: consume entire remaining quantity
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT quantity, expiry_date FROM food_items WHERE id=%s AND user_id=%s", (id, user_id))
    row = cur.fetchone()
    if row:
        qty = float(row['quantity'] or 0)
        if qty > 0:
            cur.execute("UPDATE food_items SET quantity=0, status='Consumed' WHERE id=%s AND user_id=%s", (id, user_id))
            cur.execute("INSERT INTO consumption_logs (user_id, entry_id, type, quantity, date) VALUES (%s, %s, 'consumed', %s, %s)", (user_id, id, qty, date.today()))
            conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/consume_partial/<int:id>', methods=['POST'])
@login_required
def consume_partial(id):
    qty_to_consume = float(request.form.get('quantity', 0))
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT quantity, expiry_date FROM food_items WHERE id=%s AND user_id=%s", (id, user_id))
    row = cur.fetchone()
    if row and qty_to_consume > 0:
        cur_qty = float(row['quantity'] or 0)
        consumed_amount = min(cur_qty, qty_to_consume)
        remaining = cur_qty - consumed_amount
        if remaining <= 0:
            cur.execute("UPDATE food_items SET quantity=0, status='Consumed' WHERE id=%s AND user_id=%s", (id, user_id))
        else:
            # keep status based on expiry
            today = date.today()
            days_left = (row['expiry_date'] - today).days
            new_status = 'Expiring Soon' if 0 <= days_left <= 2 else 'Fresh'
            cur.execute("UPDATE food_items SET quantity=%s, status=%s WHERE id=%s AND user_id=%s", (remaining, new_status, id, user_id))
        cur.execute("INSERT INTO consumption_logs (user_id, entry_id, type, quantity, date) VALUES (%s, %s, 'consumed', %s, %s)", (user_id, id, consumed_amount, date.today()))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/waste/<int:id>')
@login_required
def waste_food(id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT quantity FROM food_items WHERE id=%s AND user_id=%s", (id, user_id))
    row = cur.fetchone()
    if row:
        qty = float(row['quantity'] or 0)
        cur.execute("UPDATE food_items SET status='Wasted' WHERE id=%s AND user_id=%s", (id, user_id))
        cur.execute("INSERT INTO consumption_logs (user_id, entry_id, type, quantity, date) VALUES (%s, %s, 'wasted', %s, %s)", (user_id, id, qty, date.today()))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/waste_partial/<int:id>', methods=['POST'])
@login_required
def waste_partial(id):
    qty_to_waste = float(request.form.get('quantity', 0))
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT quantity, expiry_date FROM food_items WHERE id=%s AND user_id=%s", (id, user_id))
    row = cur.fetchone()
    if row and qty_to_waste > 0:
        cur_qty = float(row['quantity'] or 0)
        wasted_amount = min(cur_qty, qty_to_waste)
        remaining = cur_qty - wasted_amount
        if remaining <= 0:
            cur.execute("UPDATE food_items SET quantity=0, status='Wasted' WHERE id=%s AND user_id=%s", (id, user_id))
        else:
            # keep status based on expiry
            today = date.today()
            days_left = (row['expiry_date'] - today).days
            new_status = 'Expiring Soon' if 0 <= days_left <= 2 else 'Fresh'
            cur.execute("UPDATE food_items SET quantity=%s, status=%s WHERE id=%s AND user_id=%s", (remaining, new_status, id, user_id))
        cur.execute("INSERT INTO consumption_logs (user_id, entry_id, type, quantity, date) VALUES (%s, %s, 'wasted', %s, %s)", (user_id, id, wasted_amount, date.today()))
        conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/shift_to_wasted/<int:id>')
@login_required
def shift_to_wasted(id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE food_items SET status='Wasted' WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/shift_to_consumed/<int:id>')
@login_required
def shift_to_consumed(id):
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE food_items SET status='Consumed' WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/update_quantity/<int:id>', methods=['POST'])
@login_required
def update_quantity(id):
    user_id = session.get('user_id')
    new_qty = float(request.form.get('quantity', 0))
    conn = get_db_connection()
    cur = conn.cursor()
    # Update quantity and adjust status if needed
    new_status = 'Wasted' if new_qty <= 0 else 'Fresh'
    cur.execute("UPDATE food_items SET quantity=%s, status=%s WHERE id=%s AND user_id=%s", (new_qty, new_status, id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/stats')
@login_required
def stats():
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor()
    cutoff = date.today() - timedelta(days=29)
    # Aggregate by date for consumed and wasted
    cur.execute("SELECT date, type, SUM(quantity) as total FROM consumption_logs WHERE user_id=%s AND date >= %s GROUP BY date, type ORDER BY date ASC", (user_id, cutoff))
    rows = cur.fetchall()
    # build map of date -> {consumed: x, wasted: y}
    stats_map = {}
    for r in rows:
        d = r[0].isoformat()
        t = r[1]
        total = float(r[2] or 0)
        if d not in stats_map:
            stats_map[d] = {'consumed': 0.0, 'wasted': 0.0}
        stats_map[d][t] = total

    # Ensure continuous date labels for the last 30 days
    labels = []
    consumed = []
    wasted = []
    for i in range(29, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        labels.append(d)
        consumed.append(stats_map.get(d, {}).get('consumed', 0.0))
        wasted.append(stats_map.get(d, {}).get('wasted', 0.0))

    conn.close()
    return jsonify({'labels': labels, 'consumed': consumed, 'wasted': wasted})


@app.route('/reports')
@login_required
def reports():
    """Render a nicer reports page with monthly aggregates for current month + past 5 months."""
    user_id = session.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)

    today = date.today()
    months = []
    labels = []
    # compute last 6 months (including current)
    for i in range(5, -1, -1):
        year = (today.year if today.month - i > 0 else today.year - 1)
        month = ((today.month - i - 1) % 12) + 1
        # compute a date representing this month
        dt = date(year, month, 1)
        labels.append(dt.strftime('%b %Y'))
        months.append((year, month))

    # compute start as first day of earliest month
    start_year, start_month = months[0]
    start = date(start_year, start_month, 1)

    cur.execute(
        "SELECT YEAR(date) AS y, MONTH(date) AS m, type, SUM(quantity) AS total FROM consumption_logs WHERE user_id=%s AND date >= %s GROUP BY y,m,type ORDER BY y,m",
        (user_id, start)
    )
    rows = cur.fetchall()
    agg = {}
    for r in rows:
        key = (r['y'], r['m'])
        if key not in agg:
            agg[key] = {'consumed': 0.0, 'wasted': 0.0}
        agg[key][r['type']] = float(r['total'] or 0.0)

    consumed = []
    wasted = []
    for (y, m) in months:
        consumed.append(agg.get((y, m), {}).get('consumed', 0.0))
        wasted.append(agg.get((y, m), {}).get('wasted', 0.0))

    conn.close()
    return render_template('reports.html', labels=labels, consumed=consumed, wasted=wasted)
# --- Authentication routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, password FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid username or password"
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_pw))
            conn.commit()
            flash("Registered successfully, please log in")
            return redirect(url_for('login'))
        except MySQLdb.IntegrityError:
            error = "Username already exists"
        finally:
            conn.close()
    return render_template('register.html', error=error)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
