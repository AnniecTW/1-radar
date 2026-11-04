from .models import EventSave


def remove_saved_event(*, user, event_id) -> None:
    EventSave.objects.filter(user=user, event_id=event_id).delete()
