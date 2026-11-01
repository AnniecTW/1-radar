def user_can_manage_rsvp(user, rsvp):
    return bool(getattr(user, 'is_authenticated', False) and rsvp.user_id == user.pk)
