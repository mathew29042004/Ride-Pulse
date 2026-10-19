"""Search everything (Ctrl+K in the console): trips, drivers, riders, staff and support tickets,
limited to what the person's role may see. Pages are matched in the browser."""

from django.db.models import Q

from apps.accounts.roles import Cap


def search(user, q: str) -> list[dict]:
    from apps.accounts.models import StaffProfile
    from apps.drivers.models import DriverProfile
    from apps.riders.models import RiderProfile
    from apps.rides.models import Trip
    from apps.support.models import SupportTicket

    q = q.strip()
    if len(q) < 2:
        return []
    out: list[dict] = []
    people = Q(user__email__icontains=q) | Q(user__phone__icontains=q)
    parts = q.split()
    if len(parts) > 1:
        people |= Q(user__first_name__icontains=parts[0], user__last_name__icontains=parts[-1])
    else:
        people |= Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
    if user.has_capability(Cap.TRIPS_VIEW):
        for t in Trip.objects.filter(trip_number__icontains=q).select_related("city")[:5]:
            out.append(
                {
                    "kind": "Trip",
                    "title": t.trip_number,
                    "detail": f"{t.city.name} · {t.get_status_display()}",
                    "link": f"/ops/trips/{t.pk}",
                }
            )
    if user.has_capability(Cap.SUPPORT_VIEW):
        for t in SupportTicket.objects.filter(
            Q(ticket_number__icontains=q) | Q(subject__icontains=q)
        )[:5]:
            out.append(
                {
                    "kind": "Ticket",
                    "title": f"{t.ticket_number}: {t.subject}",
                    "detail": t.get_status_display(),
                    "link": f"/ops/support/{t.pk}",
                }
            )
    if user.has_capability(Cap.DRIVERS_VIEW):
        for d in DriverProfile.objects.filter(people).select_related("user", "city")[:5]:
            out.append(
                {
                    "kind": "Driver",
                    "title": d.user.get_full_name(),
                    "detail": f"{d.city.name} · {d.get_onboarding_status_display()}",
                    "link": f"/ops/drivers/{d.pk}",
                }
            )
    if user.has_capability(Cap.RIDERS_VIEW):
        for r in RiderProfile.objects.filter(people).select_related("user")[:5]:
            out.append(
                {
                    "kind": "Rider",
                    "title": r.user.get_full_name(),
                    "detail": r.user.email,
                    "link": "/ops/riders",
                }
            )
    staff = people | Q(title__icontains=q) | Q(employee_id__iexact=q)
    for p in StaffProfile.objects.filter(staff, user__is_active=True).select_related("user")[:5]:
        out.append(
            {
                "kind": "Colleague",
                "title": p.user.get_full_name(),
                "detail": p.title,
                "link": "/ops/company",
            }
        )
    return out
