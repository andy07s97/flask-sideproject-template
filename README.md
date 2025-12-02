## YouTube → Transcript (Flask)

### Dev
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export FLASK_ENV=development
python -c "from app import create_app; app=create_app(); app.run(port=8080, debug=True)"

### Production (Gunicorn)
gunicorn -c gunicorn_conf.py wsgi:app
