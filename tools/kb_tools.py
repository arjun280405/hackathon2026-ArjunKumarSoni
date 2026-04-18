import json

with open("data/faq.json") as f:
    faqs = json.load(f)

def search_knowledge_base(query):
    query = query.lower()

    for faq in faqs:
        if query in faq["question"].lower():
            return faq["answer"]

    return "Sorry, no relevant information found."