import json

with open("data/products.json") as f:
    products = json.load(f)

def get_product(product_id):
    for product in products:
        if product["product_id"] == product_id:
            return product

    raise Exception("Product not found")