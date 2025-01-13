from flask import Flask

app = Flask(__name__)

#Create all the routes.
@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/login")
def login():
    return "<p>Hello, World!</p>"

@app.route("/redirect")
def redirect():
    return "<p>Hello, World!</p>"

@app.route("/stats")
def stats():
    return "<p>Hello, World!</p>"
