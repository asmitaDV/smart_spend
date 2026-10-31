# SmartSpend – Personal Finance Manager

SmartSpend is a personal finance management application to track income, manage expenses, set budgets, and analyze spending patterns.

## Features
- User registration and login
- Add, view, and delete transactions
- Create and manage budgets
- Monthly financial summaries
- Category-wise spending charts

## Tech Stack
- **Frontend:** Streamlit
- **Backend:** Python, FastAPI
- **Database:** SQLite
- **Authentication:** JWT
- **Visualization:** Pandas, Plotly

## Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the backend:

```bash
python -m uvicorn backend.main:app --reload
```

Start the frontend in a separate terminal:

```bash
python -m streamlit run frontend/app.py
```

