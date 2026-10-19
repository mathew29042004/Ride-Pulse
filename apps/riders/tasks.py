from celery import shared_task


@shared_task(name="riders.book_commutes")
def book_commutes() -> dict:
    """Each evening: book tomorrow's office commute rides."""
    from .commute import book_tomorrow

    return book_tomorrow()
