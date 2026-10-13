from apps.core.conf import company_name, currency_symbol


def portal(request):
    return {"company_name": company_name(), "currency_symbol": currency_symbol()}
