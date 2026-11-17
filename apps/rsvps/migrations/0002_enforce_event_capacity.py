from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION radar_check_event_capacity_on_event_update()
RETURNS trigger AS $$
DECLARE
    going_count bigint;
BEGIN
    IF NEW.capacity IS NOT DISTINCT FROM OLD.capacity OR NEW.capacity IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT COUNT(*) INTO going_count
    FROM rsvps_rsvp
    WHERE event_id = NEW.id AND status = 'going';

    IF going_count > NEW.capacity THEN
        RAISE EXCEPTION 'Capacity cannot be lower than the number of going RSVPs (%).', going_count
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_event_capacity_guard
BEFORE UPDATE OF capacity ON events_event
FOR EACH ROW EXECUTE FUNCTION radar_check_event_capacity_on_event_update();

CREATE OR REPLACE FUNCTION radar_check_event_capacity_on_rsvp_change()
RETURNS trigger AS $$
DECLARE
    event_capacity integer;
    going_count bigint;
BEGIN
    IF NEW.status <> 'going' THEN
        RETURN NEW;
    END IF;

    -- Serialize RSVP changes for an event with capacity changes on its event row.
    SELECT capacity INTO event_capacity
    FROM events_event
    WHERE id = NEW.event_id
    FOR UPDATE;

    SELECT COUNT(*) INTO going_count
    FROM rsvps_rsvp
    WHERE event_id = NEW.event_id
      AND status = 'going'
      AND (TG_OP = 'INSERT' OR id <> NEW.id);

    IF event_capacity IS NOT NULL AND going_count + 1 > event_capacity THEN
        RAISE EXCEPTION 'Event is full; capacity is %.', event_capacity
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER radar_rsvp_capacity_guard_insert
BEFORE INSERT ON rsvps_rsvp
FOR EACH ROW EXECUTE FUNCTION radar_check_event_capacity_on_rsvp_change();

CREATE TRIGGER radar_rsvp_capacity_guard_update
BEFORE UPDATE OF event_id, status ON rsvps_rsvp
FOR EACH ROW EXECUTE FUNCTION radar_check_event_capacity_on_rsvp_change();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS radar_rsvp_capacity_guard_insert ON rsvps_rsvp;
DROP TRIGGER IF EXISTS radar_rsvp_capacity_guard_update ON rsvps_rsvp;
DROP FUNCTION IF EXISTS radar_check_event_capacity_on_rsvp_change();
DROP TRIGGER IF EXISTS radar_event_capacity_guard ON events_event;
DROP FUNCTION IF EXISTS radar_check_event_capacity_on_event_update();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
        ("rsvps", "0001_initial"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
