from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, current_user, login_required, logout_user, UserMixin
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FloatField, SelectField
from wtforms.fields import DateField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, extract
import datetime
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    category = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# Forms
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField('Confirm', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class TransactionForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    amount = FloatField('Amount', validators=[DataRequired()])
    type = SelectField('Type', choices=[('expense','Expense'),('income','Income')], validators=[DataRequired()])
    category = StringField('Category', validators=[DataRequired()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    submit = SubmitField('Save')

class FilterForm(FlaskForm):
    category = StringField('Category')
    start_date = DateField('Start Date', format='%Y-%m-%d', validators=[])
    end_date = DateField('End Date', format='%Y-%m-%d', validators=[])
    sort_by = SelectField('Sort By', choices=[('date','Date'), ('amount','Amount')])
    submit = SubmitField('Filter')

# User loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def home():
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET','POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter((User.username==form.username.data)|(User.email==form.email.data)).first():
            flash('Username or email already exists', 'danger')
            return redirect(url_for('register'))
        user = User(username=form.username.data, email=form.email.data,
                    password_hash=generate_password_hash(form.password.data))
        db.session.add(user)
        db.session.commit()
        flash('Registered. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            flash('Login successful', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    total_income = db.session.query(func.coalesce(func.sum(Transaction.amount),0.0))\
                  .filter_by(user_id=current_user.id, type='income').scalar()
    total_expense = db.session.query(func.coalesce(func.sum(Transaction.amount),0.0))\
                  .filter_by(user_id=current_user.id, type='expense').scalar()
    balance = total_income - total_expense

    # Monthly totals
    monthly_totals = db.session.query(extract('month', Transaction.date).label('month'),
                                      func.sum(Transaction.amount).label('total'))\
                       .filter_by(user_id=current_user.id)\
                       .group_by('month').all()
    
    # Category-wise totals
    category_totals = db.session.query(Transaction.category, func.sum(Transaction.amount))\
                          .filter_by(user_id=current_user.id, type='expense')\
                          .group_by(Transaction.category).all()

    return render_template('dashboard.html', 
                           total_income=total_income, 
                           total_expense=total_expense, 
                           balance=balance,
                           monthly_totals=monthly_totals,
                           category_totals=category_totals)

@app.route('/transactions', methods=['GET','POST'])
@login_required
def transactions():
    form = FilterForm()
    query = Transaction.query.filter_by(user_id=current_user.id)
    
    if form.validate_on_submit():
        if form.category.data:
            query = query.filter(Transaction.category.ilike(f"%{form.category.data}%"))
        if form.start_date.data:
            query = query.filter(Transaction.date >= form.start_date.data)
        if form.end_date.data:
            query = query.filter(Transaction.date <= form.end_date.data)
        if form.sort_by.data == 'amount':
            query = query.order_by(Transaction.amount.desc())
        else:
            query = query.order_by(Transaction.date.desc())
    else:
        query = query.order_by(Transaction.date.desc())
    
    txs = query.all()
    return render_template('transactions.html', transactions=txs, form=form)

@app.route('/transactions/add', methods=['GET','POST'])
@login_required
def add_transaction():
    form = TransactionForm()
    if form.validate_on_submit():
        tx = Transaction(user_id=current_user.id,
                         date=form.date.data,
                         title=form.title.data,
                         amount=form.amount.data,
                         type=form.type.data,
                         category=form.category.data)
        try:
            db.session.add(tx)
            db.session.commit()
            flash('Transaction added', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('transactions'))
    return render_template('add_transaction.html', form=form)

@app.route('/transactions/<int:tx_id>/edit', methods=['GET','POST'])
@login_required
def edit_transaction(tx_id):
    tx = Transaction.query.get_or_404(tx_id)
    if tx.user_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('transactions'))
    form = TransactionForm(obj=tx)
    if form.validate_on_submit():
        tx.title = form.title.data
        tx.amount = form.amount.data
        tx.type = form.type.data
        tx.category = form.category.data
        tx.date = form.date.data
        try:
            db.session.commit()
            flash('Updated', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('transactions'))
    return render_template('edit_transaction.html', form=form)

@app.route('/transactions/<int:tx_id>/delete', methods=['POST'])
@login_required
def delete_transaction(tx_id):
    tx = Transaction.query.get_or_404(tx_id)
    if tx.user_id != current_user.id:
        flash('Not authorized', 'danger')
        return redirect(url_for('transactions'))
    try:
        db.session.delete(tx)
        db.session.commit()
        flash('Deleted', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('transactions'))

if __name__ == '__main__':
    app.run(debug=True)
