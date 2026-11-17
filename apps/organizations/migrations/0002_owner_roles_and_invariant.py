from django.db import migrations, models


OWNER_INVARIANT_SQL = """
CREATE OR REPLACE FUNCTION radar_assert_organization_has_one_owner()
RETURNS trigger AS $$
DECLARE
    target_org_id uuid;
    owner_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'organizations_organization' THEN
        IF TG_OP = 'DELETE' THEN
            target_org_id := OLD.id;
        ELSE
            target_org_id := NEW.id;
        END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN
            target_org_id := OLD.organization_id;
        ELSE
            target_org_id := NEW.organization_id;
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM organizations_organization WHERE id = target_org_id) THEN
        SELECT COUNT(*) INTO owner_count
        FROM organizations_organizationmembership
        WHERE organization_id = target_org_id AND role = 'owner';

        IF owner_count <> 1 THEN
            RAISE EXCEPTION 'Organization % must have exactly one Owner (found %).', target_org_id, owner_count
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER radar_organization_owner_on_create
AFTER INSERT OR UPDATE OR DELETE ON organizations_organization
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION radar_assert_organization_has_one_owner();

CREATE CONSTRAINT TRIGGER radar_organization_membership_owner_guard
AFTER INSERT OR UPDATE OR DELETE ON organizations_organizationmembership
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION radar_assert_organization_has_one_owner();
"""

REVERSE_OWNER_SQL = """
DROP TRIGGER IF EXISTS radar_organization_membership_owner_guard ON organizations_organizationmembership;
DROP TRIGGER IF EXISTS radar_organization_owner_on_create ON organizations_organization;
DROP FUNCTION IF EXISTS radar_assert_organization_has_one_owner();
"""


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="organizationmembership",
            name="role",
            field=models.CharField(
                choices=[("owner", "Owner"), ("admin", "Admin"), ("checkin_staff", "Check-in staff")],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.UniqueConstraint(
                condition=models.Q(role="owner"),
                fields=("organization",),
                name="unique_organization_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationmembership",
            constraint=models.CheckConstraint(
                condition=models.Q(role__in=["owner", "admin", "checkin_staff"]),
                name="organization_membership_valid_role",
            ),
        ),
        migrations.RunSQL(OWNER_INVARIANT_SQL, REVERSE_OWNER_SQL),
    ]
