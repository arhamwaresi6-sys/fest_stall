POS_CATEGORY_LABELS = (
    "Burgers",
    "Pizza",
    "Sandwiches",
    "Meals",
    "Drinks",
    "Snacks",
    "Desserts",
    "Sides",
    "Bakery",
    "Salads",
    "Noodles",
)

CATEGORY_GROUPS = {
    "burger": "Burgers",
    "burgers": "Burgers",
    "pizza": "Pizza",
    "pizzas": "Pizza",
    "sandwich": "Sandwiches",
    "sandwiches": "Sandwiches",
    "meal": "Meals",
    "meals": "Meals",
    "drink": "Drinks",
    "drinks": "Drinks",
    "beverage": "Drinks",
    "beverages": "Drinks",
    "snack": "Snacks",
    "snacks": "Snacks",
    "dessert": "Desserts",
    "desserts": "Desserts",
    "sweet": "Desserts",
    "sweets": "Desserts",
    "side": "Sides",
    "sides": "Sides",
    "bakery": "Bakery",
    "baked goods": "Bakery",
    "salad": "Salads",
    "salads": "Salads",
    "noodle": "Noodles",
    "noodles": "Noodles",
    "ramen": "Noodles",
    "pasta": "Noodles",
}

GROUP_ICONS = {
    "Burgers": "burger",
    "Pizza": "pizza",
    "Sandwiches": "sandwich",
    "Meals": "meal",
    "Drinks": "drink",
    "Snacks": "fries",
    "Desserts": "cake",
    "Sides": "salad",
    "Bakery": "croissant",
    "Salads": "salad",
    "Noodles": "noodles",
    "Others": "other",
}


def category_group(category):
    return CATEGORY_GROUPS.get((category or "").strip().casefold(), "Others")


def food_icon_filename(category):
    return f"{GROUP_ICONS[category_group(category)]}.svg"
