from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION radar_check_checkin_ticket_event()
RETURNS trigger AS $$
DECLARE
    ticket_event_id uuid;
BEGIN
    IF NEW.ticket_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT r.event_id INTO ticket_event_id
    FROM rsvps_ticket t
    JOIN rsvps_rsvp r ON r.id = t.rsvp_id
    WHERE t.id = NEW.ticket_id
    FOR UPDATE OF t, r;

    IF ticket_event_id IS NULL OR ticket_event_id <> NEW.event_id THEN
        RAISE EXCEPTION 'Check-in event must match the event associated with its ticket.'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_checkin_ticket_event_guard
BEFORE INSERT OR UPDATE ON attendance_checkin
FOR EACH ROW EXECUTE FUNCTION radar_check_checkin_ticket_event();

CREATE OR REPLACE FUNCTION radar_prevent_event_change_for_checked_ticket()
RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM rsvps_ticket t
        JOIN attendance_checkin c ON c.ticket_id = t.id
        WHERE t.rsvp_id = OLD.id AND c.event_id <> NEW.event_id
    ) THEN
        RAISE EXCEPTION 'Cannot change an RSVP event when its ticket has a check-in for another event.'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_rsvp_event_checkin_guard
BEFORE UPDATE OF event_id ON rsvps_rsvp
FOR EACH ROW EXECUTE FUNCTION radar_prevent_event_change_for_checked_ticket();

CREATE OR REPLACE FUNCTION radar_prevent_ticket_relink_for_checkin()
RETURNS trigger AS $$
DECLARE
    rsvp_event_id uuid;
BEGIN
    IF NEW.rsvp_id IS NOT DISTINCT FROM OLD.rsvp_id THEN
        RETURN NEW;
    END IF;
    SELECT event_id INTO rsvp_event_id FROM rsvps_rsvp WHERE id = NEW.rsvp_id;
    IF EXISTS (
        SELECT 1 FROM attendance_checkin c
        WHERE c.ticket_id = NEW.id AND c.event_id <> rsvp_event_id
    ) THEN
        RAISE EXCEPTION 'Cannot reassign a ticket to an RSVP for another checked-in event.'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_ticket_checkin_event_guard
BEFORE UPDATE OF rsvp_id ON rsvps_ticket
FOR EACH ROW EXECUTE FUNCTION radar_prevent_ticket_relink_for_checkin();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS radar_ticket_checkin_event_guard ON rsvps_ticket;
DROP FUNCTION IF EXISTS radar_prevent_ticket_relink_for_checkin();
DROP TRIGGER IF EXISTS radar_rsvp_event_checkin_guard ON rsvps_rsvp;
DROP FUNCTION IF EXISTS radar_prevent_event_change_for_checked_ticket();
DROP TRIGGER IF EXISTS radar_checkin_ticket_event_guard ON attendance_checkin;
DROP FUNCTION IF EXISTS radar_check_checkin_ticket_event();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0001_initial"),
        ("rsvps", "0001_initial"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
