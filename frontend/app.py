
import os
import requests
import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import date

API = os.getenv("SMARTSPEND_API", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="SmartSpend",
    page_icon="💰",
    layout="wide",
)

st.markdown("""
<style>
.stApp { background: #0b1120; color: #f1f5f9; }
[data-testid="stMetric"] {
    background: #172033;
    padding: 18px;
    border-radius: 12px;
    border: 1px solid #29364d;
}
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


def request(method, path, **kwargs):
    headers = kwargs.pop("headers", {})
    if st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state.token}"

    try:
        response = requests.request(
            method, f"{API}{path}", headers=headers,
            timeout=10, **kwargs
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Request failed")
            except ValueError:
                detail = "Request failed"
            st.error(str(detail))
            return None
        return response.json()
    except requests.RequestException:
        st.error("Cannot connect to the backend. Start FastAPI first.")
        return None


def money(value):
    return f"₹{float(value):,.2f}"


def show_auth():
    st.title("💰 SmartSpend")
    st.caption("Your money. Your goals. Your control.")

    tab_login, tab_register = st.tabs(["Login", "Create account"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            result = request(
                "POST", "/api/login",
                json={"email": email, "password": password}
            )
            if result and result.get("access_token"):
                st.session_state.token = result["access_token"]
                st.rerun()

    with tab_register:
        with st.form("register_form"):
            email = st.text_input("Email address", key="reg_email")
            password = st.text_input(
                "Password (at least 8 characters)",
                type="password", key="reg_password"
            )
            submitted = st.form_submit_button(
                "Register", use_container_width=True
            )

        if submitted:
            result = request(
                "POST", "/api/register",
                json={"email": email, "password": password}
            )
            if result:
                st.success("Account created! Go to Login.")


if not st.session_state.get("token"):
    show_auth()
    st.stop()


with st.sidebar:
    st.title("💰 SmartSpend")
    page = st.radio(
        "Navigation",
        ["Dashboard", "Transactions", "Budgets"]
    )
    st.divider()
    st.caption("Personal Finance Manager")
    if st.button("Logout", use_container_width=True):
        st.session_state.pop("token", None)
        st.rerun()


st.title(page)
st.caption("Track your finances, build better habits.")

if page == "Dashboard":
    selected_month = st.date_input(
        "Select month",
        value=date.today().replace(day=1),
    ).strftime("%Y-%m")

    summary = request(
        "GET", "/api/summary", params={"month": selected_month}
    )

    if summary:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Income", money(summary["income"]))
        c2.metric("Expenses", money(summary["expense"]))
        c3.metric("Balance", money(summary["balance"]))
        c4.metric("Budget left", money(summary["budget_remaining"]))

        st.subheader("Monthly spending by category")
        categories = summary["category_spending"]

        if categories:
            df = pd.DataFrame(categories)
            fig = px.pie(
                df, names="category", values="total",
                hole=0.55, title="Expense breakdown"
            )
            fig.update_layout(
                paper_bgcolor="#0b1120",
                plot_bgcolor="#0b1120",
                font_color="#f1f5f9",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No expenses recorded for this month.")

        st.subheader("Recent transactions")
        transactions = request("GET", "/api/transactions")
        if transactions:
            st.dataframe(
                pd.DataFrame(transactions).head(10),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Add your first transaction to get started.")


elif page == "Transactions":
    st.subheader("Add a transaction")

    with st.form("transaction_form"):
        kind = st.selectbox("Type", ["Expense", "Income"])

        categories = (
            ["Food", "Transport", "Shopping", "Bills",
             "Health", "Education", "Entertainment", "Other"]
            if kind == "Expense"
            else ["Salary", "Freelance", "Business", "Gift", "Other"]
        )

        category = st.selectbox("Category", categories)
        amount = st.number_input(
            "Amount (₹)", min_value=0.01,
            max_value=1_000_000_000.0, value=100.0, step=50.0
        )
        note = st.text_input("Description")
        transaction_date = st.date_input("Date", value=date.today())

        submitted = st.form_submit_button(
            "Save transaction", use_container_width=True
        )

    if submitted:
        result = request(
            "POST", "/api/transactions",
            json={
                "kind": kind,
                "category": category,
                "amount": amount,
                "note": note,
                "date": transaction_date.isoformat(),
            },
        )
        if result:
            st.success("Transaction saved!")
            st.rerun()

    st.divider()
    st.subheader("All transactions")

    transactions = request("GET", "/api/transactions")
    if transactions:
        df = pd.DataFrame(transactions)
        st.dataframe(df, use_container_width=True, hide_index=True)

        ids = {f'{t["id"]} · {t["date"]} · {t["category"]} · {money(t["amount"])}': t["id"]
               for t in transactions}
        selected = st.selectbox(
            "Select a transaction to delete", list(ids.keys())
        )

        if st.button("Delete selected transaction"):
            result = request(
                "DELETE", f"/api/transactions/{ids[selected]}"
            )
            if result:
                st.success("Transaction deleted.")
                st.rerun()
    else:
        st.info("No transactions yet.")


elif page == "Budgets":
    st.subheader("Set a monthly category budget")

    with st.form("budget_form"):
        month = st.date_input(
            "Budget month",
            value=date.today().replace(day=1),
        ).strftime("%Y-%m")

        category = st.selectbox(
            "Category",
            ["Food", "Transport", "Shopping", "Bills",
             "Health", "Education", "Entertainment", "Other"],
        )
        amount = st.number_input(
            "Budget amount (₹)", min_value=1.0,
            max_value=1_000_000_000.0, value=5000.0, step=500.0
        )
        submitted = st.form_submit_button(
            "Save budget", use_container_width=True
        )

    if submitted:
        result = request(
            "POST", "/api/budgets",
            json={"month": month, "category": category, "amount": amount},
        )
        if result:
            st.success("Budget saved.")
            st.rerun()

    st.divider()
    st.subheader("Your budgets")

    budgets = request("GET", "/api/budgets")
    if budgets:
        for b in budgets:
            st.markdown(f"**{b['category']} — {b['month']}**")
            st.progress(
                min(b["spent"] / b["amount"], 1.0)
            )
            st.caption(
                f"Spent {money(b['spent'])} of {money(b['amount'])}"
                f" · Remaining {money(b['remaining'])}"
            )
    else:
        st.info("No budgets set yet.")
