from flask import render_template, request, flash, redirect, url_for
from flask_login import login_user, current_user, login_required, logout_user
import pandas as pd
from datetime import datetime, timedelta
from flask import current_app
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from sqlalchemy import func, and_
import schedule
import time
from threading import Thread
import calendar
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')
import re



app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance.db'
app.secret_key = 'personal_finance_tracker'

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

bcrypt = Bcrypt(app)
migrate = Migrate(app, db)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

    transactions = db.relationship('Transaction', backref='user', lazy=True)

    budget = db.Column(db.Float, default=0.0, nullable=False)

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

    def get_id(self):
        return str(self.id)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Add ForeignKey constraint
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False, default=2024)
    amount = db.Column(db.Float, nullable=False)
    budget_start_month = db.Column(db.String(50), nullable=True)  


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    billing_amount = db.Column(db.Float, nullable=False)
    billing_date = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref='subscriptions', lazy=True)

def calculate_remaining_budget(user_id):
    # Get the current month
    current_month = datetime.now().month

    # Retrieve the user's transactions for the current month
    transactions = Transaction.query.filter(
        Transaction.user_id == user_id,
        func.extract('month', Transaction.date) == current_month
    ).all()

    # Calculate total spending for the month
    total_spending = sum(transaction.amount for transaction in transactions)

    # Retrieve the user's budget
    user_budget = User.query.get(user_id).budget

    # Calculate remaining budget for the month
    remaining_budget = user_budget - total_spending

    return remaining_budget

def check_password_strength(password):
    
    if re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$', password):
        return True
    else:
        return False

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Process registration form data
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # Check if the username is already taken
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username is already taken. Please choose another one.', 'error')
            return redirect(url_for('register'))

        # Check if passwords match
        if password != confirm_password:
            flash('Passwords do not match. Please enter matching passwords.', 'error')
            return redirect(url_for('register'))

        # Check password strength
        if not check_password_strength(password):
            flash('Password does not meet the strength requirements.', 'error')
            return redirect(url_for('register'))

        # Create a new user with a unique ID and hashed password
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('login'))

    return render_template('registration.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Validate user credentials and log in
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user:
            if user.check_password(password):
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Incorrect password. Please try again.', 'error')
        else:
            flash('Username not found. Please check your username or register if you are a new user.', 'error')

    return render_template('login.html')


@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST':
        # Handle any POST requests related to the dashboard here
        if request.form.get('clear_history'):
            # Handle clearing transaction history
            current_user.transactions.clear()
            db.session.commit()

    # Retrieve the user's transactions and create a sorted list based on the date
    transactions = sorted(current_user.transactions, key=lambda x: x.date, reverse=True)

    remaining_budget = calculate_remaining_budget(current_user.id)

    return render_template('dashboard.html', transactions=transactions, remaining_budget=remaining_budget)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        
        new_username = request.form.get('new_username')

        current_user.username = new_username
        
        db.session.commit()

        flash('Profile updated successfully!', 'success')

        return redirect(url_for('profile'))

   
    return render_template('profile.html', user=current_user)


@app.route('/profile/edit')
@login_required
def profile_edit():
    
    return render_template('profile_edit.html', user=current_user)


def plot_spending_by_category(transactions):
    if not transactions:
        return None

    # Calculate total spending for the month
    total_spending = sum(transaction.amount for transaction in transactions)

    # Create a dictionary to store spending by category
    spending_by_category = {}
    for transaction in transactions:
        if transaction.category in spending_by_category:
            spending_by_category[transaction.category] += transaction.amount
        else:
            spending_by_category[transaction.category] = transaction.amount

    # Check if there is no data to plot
    if not spending_by_category:
        return None

    # Generate a pie chart for spending by category
    labels = list(spending_by_category.keys())
    values = list(spending_by_category.values())

    plt.figure(figsize=(8, 8))
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140)
    plt.title('Spending by Category')

    # Save the plot to a BytesIO object
    plot_image = BytesIO()
    plt.savefig(plot_image, format='png')
    plot_image.seek(0)

    # Encode the plot image in base64 for HTML embedding
    plot_data = base64.b64encode(plot_image.read()).decode('utf-8')

    # Close the plot to release resources
    plt.close()

    return plot_data

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')

        # Check if current password is correct
        if not current_user.check_password(current_password):
            flash('Current password is incorrect. Please try again.', 'error')
            return redirect(url_for('change_password'))

        # Check if new passwords match
        if new_password != confirm_new_password:
            flash('New passwords do not match. Please enter matching passwords.', 'error')
            return redirect(url_for('change_password'))

        # Check new password strength
        if not check_password_strength(new_password):
            flash('New password does not meet the strength requirements.', 'error')
            return redirect(url_for('change_password'))

        # Set the new password
        current_user.set_password(new_password)
        db.session.commit()

        flash('Password changed successfully!', 'success')

    return render_template('change_password.html')

def get_first_and_last_date_of_month(year, month):
    _, last_day = calendar.monthrange(year, month)
    first_date = datetime(year, month, 1).date()
    last_date = datetime(year, month, last_day).date()
    return first_date, last_date

def calculate_remaining_and_total_budget_for_month(user_id, target_month, target_year):
    # Retrieve the user's transactions for the target month and year
    first_date, last_date = get_first_and_last_date_of_month(target_year, target_month)
    transactions = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.date >= first_date,
        Transaction.date <= last_date
    ).all()

    # Calculate total spending for the target month
    total_spending = sum(transaction.amount for transaction in transactions)

    # Retrieve the user's budget
    user_budget = User.query.get(user_id).budget

    # Calculate remaining budget for the target month
    remaining_budget = user_budget - total_spending

    return remaining_budget, user_budget


@app.route('/budget_info', methods=['GET'])
@login_required
def budget_info():
    # Calculate remaining and total budget for the current month
    now = datetime.now()
    current_month = now.month
    current_year = now.year
    remaining_budget, total_budget = calculate_remaining_and_total_budget_for_month(current_user.id, current_month, current_year)

    transactions = Transaction.query.filter(
        Transaction.user_id == current_user.id,
        func.extract('month', Transaction.date) == current_month,
        func.extract('year', Transaction.date) == current_year
    ).all()

    plot_data_by_category = plot_spending_by_category(transactions)

    # Calculate remaining and total budget for previous months
    previous_months_budgets = {}

    for month in range(1, current_month):
        month_name = calendar.month_name[month]

    # Retrieve the budget entry for the current month
    budget_entry = Budget.query.filter(and_(
    Budget.user_id == current_user.id,
    Budget.month == current_month,
    Budget.year == current_year
)).first()

    if budget_entry:
        # Budget entry exists for the current month
        remaining, total = calculate_remaining_and_total_budget_for_month(current_user.id, month, current_year)
        if total != remaining:
            previous_months_budgets[month_name] = {'remaining': remaining, 'total': budget_entry.amount, 'year': current_year}
    else:
        # Budget entry does not exist, use the previous logic
        remaining, total = calculate_remaining_and_total_budget_for_month(current_user.id, month, current_year)
        if total != remaining:
            previous_months_budgets[month_name] = {'remaining': remaining, 'total': total, 'year': current_year}

    # Generate a plot of remaining budget over the previous months
    months = list(previous_months_budgets.keys())
    remaining_budgets = [data['remaining'] for data in previous_months_budgets.values()]

    plt.figure(figsize=(10, 6))
    plt.plot(months, remaining_budgets, marker='o', linestyle='-', color='b')
    plt.title('Remaining Budget Over Previous Months')
    plt.xlabel('Month')
    plt.ylabel('Remaining Budget')
    plt.grid(True)

    # Save the plot to a BytesIO object
    plot_image = BytesIO()
    plt.savefig(plot_image, format='png')
    plot_image.seek(0)

    # Encode the plot image in base64 for HTML embedding
    plot_data = base64.b64encode(plot_image.read()).decode('utf-8')

    # Close the plot to release resources
    plt.close()

    # Render a template to display budget information and the plot
    return render_template('budget_info.html', remaining_budget=remaining_budget, total_budget=total_budget,
                           previous_months_budgets=previous_months_budgets, plot_data=plot_data, 
                           plot_data_by_category=plot_data_by_category)


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except ValueError:
        return None


@app.route('/', methods=['GET', 'POST'])
def index():
    print("Form submitted to /set_budget")
    # If the user is already authenticated, redirect to the main page (e.g., dashboard)
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))  # Adjust 'dashboard' to the route for adding transactions

    if request.method == 'POST':
        # Validate user credentials and log in
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))  # Adjust 'dashboard' to the route for adding transactions

    return render_template('login.html')

@app.route('/index', methods=['GET'])
def render_index():
    return render_template('index.html')


@login_required
@app.route('/set_budget', methods=['POST'])
def set_budget():
    try:
        new_budget = float(request.form.get('budget', 0.0))
        if new_budget < 0:
            raise ValueError("Budget cannot be negative.")

        # Get the current month and year
        now = datetime.now()
        current_month = now.month
        current_year = now.year

        # Check if there's already a budget entry for the current month
        existing_budget = Budget.query.filter(and_(
            Budget.user_id == current_user.id,
            Budget.month == current_month,
            Budget.year == current_year
        )).first()

        if existing_budget:
            # Update the existing budget entry for the current month
            existing_budget.amount = new_budget
        else:
            # Create a new budget entry for the current month
            new_budget_entry = Budget(user_id=current_user.id, month=current_month, year=current_year, amount=new_budget)
            db.session.add(new_budget_entry)

        # Update the current_user.budget attribute
        current_user.budget = new_budget

        db.session.commit()
        flash('Monthly budget set successfully!', 'success')
    except ValueError as e:
        flash(f'Error: {str(e)}', 'error')

    return redirect(url_for('dashboard'))


@app.route('/transactions')
@login_required
def transactions():
    if request.method == 'POST':
        # Handle POST request for transactions, if needed
        pass

    # Retrieve the user's transactions
    transactions = current_user.transactions

    return render_template('transactions.html', transactions=transactions)


@app.route('/add_transactions', methods=['GET', 'POST'])
@login_required
def add_transactions():
    if request.method == 'POST':
        # Sample data with empty lists
        sample_data = {
            'category': request.form.getlist('category'),  # Use request.form to get form data
            'amount': request.form.getlist('amount'),
            'date': request.form.getlist('date')
        }

       
        with current_app.test_request_context():
            user = User.query.get(current_user.id)

            # Create a Pandas DataFrame from the sample data
            df = pd.DataFrame(sample_data)

            # Iterate over the DataFrame rows and add transactions to the database
            for _, row in df.iterrows():
                new_transaction = Transaction(
                    user_id=user.id,
                    category=row['category'],
                    amount=row['amount'],
                    date=datetime.strptime(row['date'], '%Y-%m-%d').date()
                )
                db.session.add(new_transaction)

            # Commit the changes to the database
            db.session.commit()

            flash('Transactions added successfully!', 'success')

   
    transactions = current_user.transactions

   
    return render_template('index.html', transactions=transactions)


@app.route('/delete_transaction/<int:transaction_id>', methods=['POST'])
@login_required
def delete_transaction(transaction_id):
    if request.method == 'POST':
        
        transaction = Transaction.query.get_or_404(transaction_id)

        
        if transaction.user_id == current_user.id:
            db.session.delete(transaction)
            db.session.commit()
            flash('Transaction deleted successfully!', 'success')
        else:
            flash('You are not authorized to delete this transaction.', 'error')

   
    return redirect(url_for('transactions'))


def monthly_subscription_billing(user, db):
    # Get the current date
    current_date = datetime.now()

    # Check if it's the first day of the month
    if current_date.day == 1:
        # Retrieve all active subscriptions for the user
        active_subscriptions = Subscription.query.filter_by(
            user_id=user.id,
            is_active=True
        ).all()

        # Iterate over active subscriptions and add transactions
        for subscription in active_subscriptions:
            
            if subscription.billing_date == current_date.day:
                # Add a transaction for the subscription amount
                new_transaction = Transaction(
                    user_id=user.id,
                    category='Subscription',
                    amount=subscription.billing_amount,
                    date=current_date.date()
                )
                db.session.add(new_transaction)

        # Commit the changes to the database
        db.session.commit()
        flash('Monthly subscription billing completed successfully!', 'success')


@app.route('/add_subscription', methods=['GET', 'POST'])
@login_required
def add_subscription():
    # Retrieve existing subscriptions for the current user
    existing_subscriptions = Subscription.query.filter_by(user_id=current_user.id, is_active=True).all()

    if request.method == 'POST':
        # Handle the form submission for adding and canceling subscriptions
        new_subscription_name = request.form.get('name')
        new_billing_amount = float(request.form.get('billing_amount'))
        new_billing_date = int(request.form.get('billing_date'))

        # Your logic for adding a new subscription
        new_subscription = Subscription(
            user_id=current_user.id,
            name=new_subscription_name,
            billing_amount=new_billing_amount,
            billing_date=new_billing_date,
            is_active=True  # Assuming a new subscription is active by default
        )
        db.session.add(new_subscription)
        db.session.commit()
        flash(f'Subscription "{new_subscription_name}" added successfully!', 'success')

        # Check if any subscriptions need to be canceled
        subscriptions_to_cancel = request.form.getlist('cancel_subscriptions[]')
        for subscription_id in subscriptions_to_cancel:
            subscription = Subscription.query.get(subscription_id)
            if subscription:
                subscription.is_active = False
                db.session.commit()
                flash(f'Subscription "{subscription.name}" canceled successfully!', 'success')

        return redirect(url_for('add_subscription'))

    # Render the add_subscriptions.html template with existing subscriptions
    return render_template('add_subscription.html', existing_subscriptions=existing_subscriptions)


@app.route('/cancel_subscription', methods=['POST'])
@login_required
def cancel_subscription():
    subscriptions_to_cancel = request.form.getlist('cancel_subscriptions[]')

    if not subscriptions_to_cancel:
        flash('Please select subscriptions to cancel.', 'error')
        return redirect(url_for('add_subscription'))

    try:
        # Convert subscription IDs to integers
        subscriptions_to_cancel = [int(sub_id) for sub_id in subscriptions_to_cancel]

        # Get the subscriptions to cancel
        subscriptions = Subscription.query.filter(Subscription.id.in_(subscriptions_to_cancel)).all()

        
        for subscription in subscriptions:
            subscription.is_active = False

        # Commit changes to the database
        db.session.commit()

        flash('Subscriptions canceled successfully!', 'success')
    except Exception as e:
        # Handle exceptions, log the error, and display an error message
        flash(f'Error canceling subscriptions: {str(e)}', 'error')

    # Redirect to the dashboard or another appropriate route
    return redirect(url_for('add_subscription'))



@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


def reset_budgets():
    current_date = datetime.now()

    # Check if it's the first day of the month
    if current_date.day == 1:
        # Reset the budget for all users
        users = User.query.all()
        for user in users:
            user.budget = 0.0
        db.session.commit()

schedule.every().day.at("00:00").do(reset_budgets)

def run_scheduled_jobs():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    job_thread = Thread(target=run_scheduled_jobs)
    job_thread.start()

    # Run the Flask app
    app.run(debug=True)