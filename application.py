import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd


# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
# CREATE TABLE users (id INTEGER, username TEXT NOT NULL, hash TEXT NOT NULL, cash NUMERIC NOT NULL DEFAULT 10000.00, email TEXT NOT NULL, PRIMARY KEY(id));
# CREATE TABLE IF NOT EXISTS 'holdings' ('user_id' INTEGER NOT NULL, 'symbol' TEXT NOT NULL, 'quantity' INTEGER NOT NULL,'total_cost' DECIMAL NOT NULL);
# CREATE TABLE IF NOT EXISTS 'transactions' ('id' INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, 'user_id' INTEGER NOT NULL, 'action' BOOLEAN NOT NULL, 'symbol' TEXT NOT NULL, 'quantity' INTEGER NOT NULL, 'cost' DECIMAL NOT NULL, 'date' DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);
db = SQL("sqlite:///finance.db")


# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # get holdings and user
    holdings = db.execute("SELECT * FROM holdings WHERE user_id = :user_id ORDER BY symbol ASC", user_id=session["user_id"])
    user = db.execute("SELECT * FROM users WHERE id = :id", id=session["user_id"])
    total_worth = 0.0

    # get total value of portfolio
    for i in range(len(holdings)):
        stock = lookup(holdings[i]["symbol"])

        # add additional attributes to holdings
        holdings[i]["company_name"] = stock["name"]
        holdings[i]["price_per_share"] = "{:,}".format(round(stock["price"], 2))
        holdings[i]["worth"] = "{:,}".format(round(float(stock["price"]) * float(holdings[i]["quantity"]), 2))

        total_worth += round(float(stock["price"]) * float(holdings[i]["quantity"]), 2)

    total_worth += float(user[0]["cash"])

    return render_template("index.html", holdings=holdings, cash=usd(user[0]["cash"]), total_worth=usd(total_worth))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":
        # POST requests
        # check if symbol is provided
        symbol = request.form.get("symbol").upper()
        if not symbol:
            return apology("must provide symbol", 400)

        # check if share quantity is provided
        quantity = request.form.get("shares")
        if not quantity:
            return apology("must provide quantity", 400)

        # check if share quantity is int
        try:
            quantity = int(request.form.get("shares"))
        except ValueError:
            return apology("invalid quantity type", 400)

        # check if share quantity is positive
        if quantity <= 0:
            return apology("invalid quantity", 400)

        # check if symbol exists
        stock = lookup(symbol)
        if not stock:
            return apology("invalid symbol", 400)

        stock_name = stock["name"]
        stock_symbol = stock["symbol"]
        stock_price = stock["price"]
        cost = round(float(stock_price) * float(quantity), 2)

        users = db.execute("SELECT * FROM users WHERE id = :id", id=session["user_id"])

        # check if the total cost is bigger than user's cash
        if float(users[0]["cash"]) < float(cost):
            # set output
            output = f"Not enough cash to buy {quantity} shares of {stock_name} ({stock_symbol}) for {usd(cost)}."

        else:
            # update user's cash
            new_cash_amount = round(float(users[0]["cash"]) - float(cost), 2)
            db.execute("UPDATE users SET cash = :new_cash_amount WHERE id = :user_id;",
                       new_cash_amount=new_cash_amount, user_id=session["user_id"])

            # check if symbol already exists in user's holdings
            holdings_for_symbol = db.execute("SELECT * FROM holdings WHERE symbol = :symbol AND user_id = :user_id;",
                                             symbol=stock_symbol, user_id=session["user_id"])
            if holdings_for_symbol:
                # if holdings exists then update the amount and cost
                new_quantity = int(holdings_for_symbol[0]["quantity"]) + quantity
                new_total_cost = round(float(holdings_for_symbol[0]["total_cost"]) + float(cost), 2)
                db.execute("UPDATE holdings SET quantity = :new_quantity, total_cost = :new_total_cost WHERE user_id = :user_id;",
                           new_quantity=new_quantity, new_total_cost=new_total_cost, user_id=session["user_id"])
            else:
                # if holdings doesn't exist then insert it into user's holdings
                db.execute("INSERT INTO holdings (user_id, symbol, quantity, total_cost) VALUES (:user_id, :symbol, :quantity, :total_cost)",
                           user_id=session["user_id"], symbol=stock_symbol, quantity=quantity, total_cost=cost)

            # insert into transactions
            db.execute("INSERT INTO transactions (user_id, action, symbol, quantity, cost) VALUES (:user_id, :action, :symbol, :quantity, :cost)",
                       user_id=session["user_id"], action=1, symbol=stock_symbol, quantity=quantity, cost=cost)

            # set output
            users = db.execute("SELECT * FROM users WHERE id = :id", id=session["user_id"])
            remaining_cash = usd(users[0]["cash"])
            output = f"Bought {quantity} shares of {stock_name} ({stock_symbol}) for ${usd(cost)}.\nRemaining cash is {remaining_cash}."

        return render_template("buy.html", output=output)
    else:
        # GET requests
        return render_template("buy.html", output="")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # get all transactions from user
    transactions = db.execute("SELECT * FROM transactions WHERE user_id = :user_id ORDER BY date DESC;", user_id=session["user_id"])

    # format transaction costs
    for i in range(len(transactions)):
        transactions[i]["cost"] = "{:,}".format(transactions[i]["cost"])

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/delete_account")
def delete_account():
    """Delete user's account"""

    # Delete user from database
    db.execute("DELETE FROM users WHERE id = :user_id;", user_id=session["user_id"])

    # delete entries from other tables
    db.execute("DELETE FROM holdings WHERE user_id = :user_id;", user_id=session["user_id"])
    db.execute("DELETE FROM transactions WHERE user_id = :user_id;", user_id=session["user_id"])

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        # POST request
        # check if symbol is provided
        symbol = request.form.get("symbol").upper()
        if not symbol:
            return apology("must provide symbol", 400)

        # check if symbol exists
        stock = lookup(symbol)
        if not stock:
            return apology("invalid symbol", 400)

        stock_name = stock["name"]
        stock_symbol = stock["symbol"]
        stock_price = stock["price"]

        # set output message
        output = f"A share of {stock_name} ({stock_symbol}) costs {usd(stock_price)}."

        return render_template("quote.html", output=output)
    else:
        # GET request
        return render_template("quote.html", output="")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":
        # POST request

        # if not request.form.get("email"):
        #     return apology("must provide email")

        # check if username is provided
        if not request.form.get("username"):
            return apology("must provide username")

        # check if password and confirmation are provided
        elif not request.form.get("password") or not request.form.get("confirmation"):
            return apology("must provide password")

        # check if password is same as confirmation
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords do not match")

        # check if username is unique
        rows = db.execute("SELECT * FROM users WHERE username = :username;", username=request.form.get("username"))
        if len(rows) >= 1:
            return apology("username already exists")

        # check if email is unique
        # rows = db.execute("SELECT * FROM users WHERE email = :email;", email=request.form.get("email"))
        # if len(rows) >= 1:
        #     return apology("email already exists")

        # encrypt password
        encypted_password = generate_password_hash(request.form.get("password"), "sha256")
        # check_password_hash("sha256$lTsEjTVv$c794661e2c734903267fbc39205e53eca607f9ca2f85812c95020fe8afb3bc62", "P1ain-text-user-passw@rd")

        # add user to database
        db.execute("INSERT INTO users (username, hash, email) VALUES (:username, :hash, :email);",
                   username=request.form.get("username"),
                   hash=encypted_password,
                   email="default@email.com")
        # db.execute("INSERT INTO users (username, hash, email) VALUES (:username, :hash, :email);",
        #           username=request.form.get("username"),
        #           hash=encypted_password,
        #           email=request.form.get("email"))

        return redirect("/")
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":

        # check if symbol is provided
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must provide symbol", 400)

        # check if share quantity is provided
        quantity = int(request.form.get("shares"))
        if not quantity:
            return apology("must provide quantity", 400)

        # check if share quantity is positive
        if quantity <= 0:
            return apology("invalid quantity", 400)

        # check if symbol exists
        stock = lookup(symbol)
        if not stock:
            return apology("invalid symbol", 400)

        stock_name = stock["name"]
        stock_symbol = stock["symbol"]
        stock_price = stock["price"]
        cost = round(float(stock_price) * float(quantity), 2)

        # get current holdings for symbol
        holdings_for_symbol = db.execute("SELECT * FROM holdings WHERE symbol = :symbol AND user_id = :user_id;",
                                         symbol=stock_symbol, user_id=session["user_id"])
        new_quantity = int(holdings_for_symbol[0]["quantity"]) - quantity

        # check if new amount is valid
        if new_quantity < 0:
            return apology(f"Not enough shares of {stock_name} ({stock_symbol}) to sell.", 400)

        if new_quantity == 0:
            # if new amount is 0 then delete symbol for user's holdings
            db.execute("DELETE FROM holdings WHERE symbol = :symbol AND user_id = :user_id;",
                       symbol=stock_symbol, user_id=session["user_id"])
        else:
            # if new amount is above 0 then update user's holdings for symbol and its total cost
            new_total_cost = round(float(holdings_for_symbol[0]["total_cost"]) - float(cost), 2)
            db.execute("UPDATE holdings SET quantity = :new_quantity, total_cost = :new_total_cost WHERE user_id = :user_id;",
                       new_quantity=new_quantity, new_total_cost=new_total_cost, user_id=session["user_id"])

        # insert transaction
        db.execute("INSERT INTO transactions (user_id, action, symbol, quantity, cost) VALUES (:user_id, :action, :symbol, :quantity, :cost)",
                   user_id=session["user_id"], action=0, symbol=stock_symbol, quantity=quantity, cost=cost)

        # update user's cash
        users = db.execute("SELECT * FROM users WHERE id = :id;", id=session["user_id"])
        new_cash = round(float(users[0]["cash"]) + float(cost), 2)
        db.execute("UPDATE users SET cash = :new_cash WHERE id = :user_id;", new_cash=new_cash, user_id=session["user_id"])

        output = f"Sold {quantity} shares of {stock_name} ({stock_symbol}) for {usd(cost)}. Current cash is {usd(new_cash)}"

        holdings = db.execute("SELECT * FROM holdings WHERE user_id = :id", id=session["user_id"])
        return render_template("sell.html", output=output, stocks=holdings)

    else:
        # GET request
        holdings = db.execute("SELECT * FROM holdings WHERE user_id = :id", id=session["user_id"])
        return render_template("sell.html", output="", stocks=holdings)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)