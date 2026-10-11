BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ownership_one_active_per_vehicle
    ON ownership_records (vehicle_id)
    WHERE ownership_status = 'ACTIVE';

CREATE OR REPLACE FUNCTION transfer_ownership(
    p_vehicle_id INTEGER,
    p_new_owner_id INTEGER,
    p_transfer_date DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    current_record ownership_records%ROWTYPE;
    new_ownership_id INTEGER;
BEGIN
    PERFORM vehicle_id
      FROM vehicles
     WHERE vehicle_id = p_vehicle_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Vehicle % does not exist', p_vehicle_id
            USING ERRCODE = '23503';
    END IF;

    PERFORM owner_id
      FROM owners
     WHERE owner_id = p_new_owner_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Owner % does not exist', p_new_owner_id
            USING ERRCODE = '23503';
    END IF;

    SELECT *
      INTO current_record
      FROM ownership_records
     WHERE vehicle_id = p_vehicle_id
       AND ownership_status = 'ACTIVE'
     FOR UPDATE;

    IF FOUND THEN
        IF current_record.owner_id = p_new_owner_id THEN
            RAISE EXCEPTION 'Owner % already owns vehicle %', p_new_owner_id, p_vehicle_id
                USING ERRCODE = '23514';
        END IF;
        IF p_transfer_date < current_record.start_date THEN
            RAISE EXCEPTION 'Transfer date cannot precede current ownership start date'
                USING ERRCODE = '23514';
        END IF;

        UPDATE ownership_records
           SET end_date = p_transfer_date,
               ownership_status = 'TRANSFERRED'
         WHERE ownership_id = current_record.ownership_id;
    END IF;

    INSERT INTO ownership_records (vehicle_id, owner_id, start_date, ownership_status)
    VALUES (p_vehicle_id, p_new_owner_id, p_transfer_date, 'ACTIVE')
    RETURNING ownership_id INTO new_ownership_id;

    RETURN new_ownership_id;
END;
$$;

COMMIT;