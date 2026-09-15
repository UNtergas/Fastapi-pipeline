from router.schema import Category

CATEGORY_INTENTS: dict[Category, set[str]] = {
    Category.banking:      {"transfer", "balance", "bill_balance", "pay_bill",
                            "account_blocked", "routing", "order_checks", "pin_change"},
    Category.credit_cards: {"card_declined", "credit_limit", "report_lost_card", "new_card",
                            "credit_score", "apr", "redeem_rewards", "damaged_card"},
    Category.travel:       {"book_flight", "book_hotel", "flight_status", "car_rental",
                            "travel_alert", "exchange_rate", "carry_on", "international_visa"},
    Category.dining:       {"restaurant_reservation", "restaurant_reviews", "recipe",
                            "meal_suggestion", "cook_time", "nutrition_info", "calories"},
    Category.calendar:     {"schedule_meeting", "calendar", "calendar_update", "reminder",
                            "alarm", "time", "date", "next_holiday"},
    Category.home:         {"smart_home", "todo_list", "todo_list_update", "shopping_list",
                            "shopping_list_update"},
}

_INTENT_TO_CATEGORY: dict[str, Category] = {
    intent: cat for cat, intents in CATEGORY_INTENTS.items() for intent in intents
}
MAPPED_INTENTS = set(_INTENT_TO_CATEGORY)


def true_category(intent: str) -> Category:
    return _INTENT_TO_CATEGORY.get(intent, Category.other)