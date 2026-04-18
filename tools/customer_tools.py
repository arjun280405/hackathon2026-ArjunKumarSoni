import json
import random
import time

with open("data/customers.json") as f:
    customers = json.load(f)

def get_customer(customer_email):
    customer_email = customer_email.lower()

    for customer in customers:
        if customer.get("email", "").lower() == customer_email:
            return customer

    raise Exception("Customer not found")