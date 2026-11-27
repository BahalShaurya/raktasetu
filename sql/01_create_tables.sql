-- =====================================================================
-- RaktaSetu : Blood Donation Data Management System (College Rotaract Club)
-- 01_create_tables.sql : all base tables, keys, check constraints, indexes
-- PostgreSQL 16.  Run on an empty database:  createdb raktasetu
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- needed for the exclusion constraint on event

-- ---------- 1-8 : lookup tables ----------
CREATE TABLE department (
    dept_id    SERIAL PRIMARY KEY,
    dept_name  VARCHAR(100) NOT NULL,
    UNIQUE (dept_name)
);

CREATE TABLE blood_group (
    bg_id       SERIAL PRIMARY KEY,
    group_name  VARCHAR(3) NOT NULL,
    UNIQUE (group_name),
    CHECK (group_name IN ('A+','A-','B+','B-','AB+','AB-','O+','O-'))
);

-- recursive M:N : which blood group can be given to which (donor -> recipient)
CREATE TABLE blood_compatibility (
    donor_bg      INT NOT NULL,
    recipient_bg  INT NOT NULL,
    PRIMARY KEY (donor_bg, recipient_bg),
    FOREIGN KEY (donor_bg)     REFERENCES blood_group(bg_id) ON DELETE CASCADE,
    FOREIGN KEY (recipient_bg) REFERENCES blood_group(bg_id) ON DELETE CASCADE
);

CREATE TABLE venue (
    venue_id    SERIAL PRIMARY KEY,
    venue_name  VARCHAR(100) NOT NULL,
    address     VARCHAR(200),
    city        VARCHAR(50)  NOT NULL DEFAULT 'Bengaluru',
    capacity    INT NOT NULL,
    UNIQUE (venue_name),
    CHECK (capacity > 0)
);

CREATE TABLE blood_bank (
    bank_id     SERIAL PRIMARY KEY,
    bank_name   VARCHAR(100) NOT NULL,
    city        VARCHAR(50)  NOT NULL,
    phone       VARCHAR(15),
    license_no  VARCHAR(30)  NOT NULL,
    UNIQUE (bank_name),
    UNIQUE (license_no)
);

CREATE TABLE hospital (
    hospital_id    SERIAL PRIMARY KEY,
    hospital_name  VARCHAR(100) NOT NULL,
    city           VARCHAR(50)  NOT NULL,
    phone          VARCHAR(15),
    UNIQUE (hospital_name, city)
);

-- why a donor was turned away; defer_days is NULL only for permanent reasons
CREATE TABLE deferral_reason (
    reason_id     SERIAL PRIMARY KEY,
    code          VARCHAR(20)  NOT NULL,
    reason        VARCHAR(100) NOT NULL,
    defer_days    INT,
    is_permanent  BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (code),
    UNIQUE (reason),
    CHECK ((is_permanent AND defer_days IS NULL) OR (NOT is_permanent AND defer_days > 0))
);

CREATE TABLE sponsor (
    sponsor_id      SERIAL PRIMARY KEY,
    sponsor_name    VARCHAR(100) NOT NULL,
    contact_person  VARCHAR(100),
    phone           VARCHAR(15),
    email           VARCHAR(100),
    UNIQUE (sponsor_name)
);

-- ---------- 9-10 : people ----------
CREATE TABLE member (                      -- Rotaract club members and the admin
    member_id      SERIAL PRIMARY KEY,
    usn            VARCHAR(15)  NOT NULL,
    fname          VARCHAR(50)  NOT NULL,
    lname          VARCHAR(50),
    email          VARCHAR(100) NOT NULL,
    phone          VARCHAR(15),
    role           VARCHAR(12)  NOT NULL DEFAULT 'VOLUNTEER',
    dept_id        INT NOT NULL,
    joined_on      DATE NOT NULL DEFAULT CURRENT_DATE,
    password_hash  TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (usn),
    UNIQUE (email),
    FOREIGN KEY (dept_id) REFERENCES department(dept_id),
    CHECK (role IN ('ADMIN', 'COORDINATOR', 'VOLUNTEER'))
);

CREATE TABLE donor (                       -- anybody who donates or may donate
    donor_id       SERIAL PRIMARY KEY,
    fname          VARCHAR(50)  NOT NULL,
    lname          VARCHAR(50),
    gender         CHAR(1)      NOT NULL,
    dob            DATE         NOT NULL,
    bg_id          INT          NOT NULL,
    phone          VARCHAR(15)  NOT NULL,
    email          VARCHAR(100),
    city           VARCHAR(50)  NOT NULL DEFAULT 'Bengaluru',
    donor_type     VARCHAR(10)  NOT NULL DEFAULT 'STUDENT',
    usn            VARCHAR(15),
    dept_id        INT,
    registered_on  DATE         NOT NULL DEFAULT CURRENT_DATE,
    consent_contact BOOLEAN     NOT NULL DEFAULT true,
    is_active      BOOLEAN      NOT NULL DEFAULT true,
    UNIQUE (phone),
    UNIQUE (usn),
    CONSTRAINT donor_phone_digits CHECK (phone ~ '^[0-9]{10}$'),
    FOREIGN KEY (bg_id)   REFERENCES blood_group(bg_id),
    FOREIGN KEY (dept_id) REFERENCES department(dept_id),
    CHECK (gender IN ('M', 'F', 'O')),
    CHECK (donor_type IN ('STUDENT', 'STAFF', 'ALUMNI', 'PUBLIC')),
    CHECK (dob < DATE '2010-01-01'),
    CHECK (donor_type <> 'STUDENT' OR (usn IS NOT NULL AND dept_id IS NOT NULL))
);
CREATE INDEX idx_donor_bg   ON donor (bg_id);
CREATE INDEX idx_donor_city ON donor (city);

-- ---------- 11-14 : events and drives ----------
CREATE TABLE event (                       -- every activity the club organises
    event_id        SERIAL PRIMARY KEY,
    title           VARCHAR(150) NOT NULL,
    event_type      VARCHAR(12)  NOT NULL DEFAULT 'BLOOD_DRIVE',
    description     TEXT,
    venue_id        INT NOT NULL,
    starts_at       TIMESTAMP NOT NULL,
    ends_at         TIMESTAMP NOT NULL,
    status          VARCHAR(10) NOT NULL DEFAULT 'PLANNED',
    coordinator_id  INT NOT NULL,
    budget          NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (venue_id)       REFERENCES venue(venue_id),
    FOREIGN KEY (coordinator_id) REFERENCES member(member_id),
    CHECK (event_type IN ('BLOOD_DRIVE', 'AWARENESS', 'TRAINING', 'FUNDRAISER', 'SOCIAL')),
    CHECK (status IN ('PLANNED', 'ONGOING', 'COMPLETED', 'CANCELLED')),
    CHECK (ends_at > starts_at),
    CHECK (budget >= 0)
);
-- a venue cannot host two live events at the same time
ALTER TABLE event ADD CONSTRAINT no_venue_clash
    EXCLUDE USING gist (venue_id WITH =, tsrange(starts_at, ends_at) WITH &&)
    WHERE (status <> 'CANCELLED');
CREATE INDEX idx_event_status ON event (status, starts_at);

CREATE TABLE blood_drive (                 -- specialisation (ISA) of EVENT
    event_id           INT PRIMARY KEY,
    bank_id            INT NOT NULL,
    target_units       INT NOT NULL,
    max_donors         INT NOT NULL,
    registration_open  BOOLEAN NOT NULL DEFAULT true,
    FOREIGN KEY (event_id) REFERENCES event(event_id) ON DELETE CASCADE,
    FOREIGN KEY (bank_id)  REFERENCES blood_bank(bank_id),
    CHECK (target_units > 0),
    CHECK (max_donors >= target_units)
);

CREATE TABLE event_volunteer (             -- M:N MEMBER - EVENT
    event_id   INT NOT NULL,
    member_id  INT NOT NULL,
    duty       VARCHAR(40) NOT NULL DEFAULT 'General help',
    hours      NUMERIC(4,1) NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, member_id),
    FOREIGN KEY (event_id)  REFERENCES event(event_id)   ON DELETE CASCADE,
    FOREIGN KEY (member_id) REFERENCES member(member_id),
    CHECK (hours >= 0)
);

CREATE TABLE event_sponsor (               -- M:N SPONSOR - EVENT
    event_id     INT NOT NULL,
    sponsor_id   INT NOT NULL,
    amount       NUMERIC(10,2) NOT NULL,
    received_on  DATE,
    PRIMARY KEY (event_id, sponsor_id),
    FOREIGN KEY (event_id)   REFERENCES event(event_id)     ON DELETE CASCADE,
    FOREIGN KEY (sponsor_id) REFERENCES sponsor(sponsor_id),
    CHECK (amount >= 0)
);

-- ---------- 15-17 : the donation flow ----------
CREATE TABLE registration (
    reg_id         SERIAL PRIMARY KEY,
    drive_id       INT NOT NULL,
    donor_id       INT NOT NULL,
    slot_time      TIME,
    registered_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status         VARCHAR(10) NOT NULL DEFAULT 'REGISTERED',
    registered_by  INT,                    -- NULL = donor used the public form
    UNIQUE (drive_id, donor_id),
    FOREIGN KEY (drive_id)      REFERENCES blood_drive(event_id),
    FOREIGN KEY (donor_id)      REFERENCES donor(donor_id),
    FOREIGN KEY (registered_by) REFERENCES member(member_id),
    CHECK (status IN ('REGISTERED', 'SCREENED', 'DEFERRED', 'DONATED', 'NO_SHOW', 'CANCELLED'))
);
CREATE INDEX idx_reg_donor ON registration (donor_id);
CREATE INDEX idx_reg_drive ON registration (drive_id, status);

CREATE TABLE screening (                   -- 1:1 with registration; reason_id NULL = fit to donate
    reg_id         INT PRIMARY KEY,
    screened_by    INT NOT NULL,
    screened_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hemoglobin     NUMERIC(4,1) NOT NULL,
    weight_kg      NUMERIC(5,1) NOT NULL,
    bp_systolic    INT NOT NULL,
    bp_diastolic   INT NOT NULL,
    pulse          INT NOT NULL,
    temperature_c  NUMERIC(3,1) NOT NULL,
    reason_id      INT,
    remarks        VARCHAR(200),
    FOREIGN KEY (reg_id)      REFERENCES registration(reg_id) ON DELETE CASCADE,
    FOREIGN KEY (screened_by) REFERENCES member(member_id),
    FOREIGN KEY (reason_id)   REFERENCES deferral_reason(reason_id),
    CHECK (hemoglobin    BETWEEN 5 AND 20),
    CHECK (weight_kg     BETWEEN 20 AND 200),
    CHECK (bp_systolic   BETWEEN 60 AND 260),
    CHECK (bp_diastolic  BETWEEN 30 AND 160),
    CHECK (bp_systolic > bp_diastolic),
    CHECK (pulse         BETWEEN 30 AND 200),
    CHECK (temperature_c BETWEEN 34 AND 42)
);

CREATE TABLE donation (
    donation_id    SERIAL PRIMARY KEY,
    reg_id         INT NOT NULL,
    bag_no         VARCHAR(20) NOT NULL,
    volume_ml      INT NOT NULL,
    collected_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    collected_by   INT NOT NULL,
    status         VARCHAR(12) NOT NULL DEFAULT 'COLLECTED',
    handed_over_at TIMESTAMP,
    UNIQUE (reg_id),                       -- one donation per registration (1:1)
    UNIQUE (bag_no),
    FOREIGN KEY (reg_id)       REFERENCES registration(reg_id),
    FOREIGN KEY (collected_by) REFERENCES member(member_id),
    CHECK (volume_ml IN (350, 450)),
    CHECK (status IN ('COLLECTED', 'HANDED_OVER', 'DISCARDED')),
    CHECK (status <> 'HANDED_OVER' OR handed_over_at IS NOT NULL)
);
CREATE INDEX idx_donation_status ON donation (status);

-- ---------- 18-19 : emergency requests ----------
CREATE TABLE blood_request (
    request_id     SERIAL PRIMARY KEY,
    hospital_id    INT NOT NULL,
    patient_name   VARCHAR(100) NOT NULL,
    bg_id          INT NOT NULL,
    units_needed   INT NOT NULL,
    required_by    DATE NOT NULL,
    urgency        VARCHAR(10) NOT NULL DEFAULT 'NORMAL',
    status         VARCHAR(10) NOT NULL DEFAULT 'OPEN',
    contact_phone  VARCHAR(15),
    note           VARCHAR(200),
    raised_by      INT NOT NULL,
    raised_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hospital_id) REFERENCES hospital(hospital_id),
    FOREIGN KEY (bg_id)       REFERENCES blood_group(bg_id),
    FOREIGN KEY (raised_by)   REFERENCES member(member_id),
    CHECK (units_needed > 0),
    CHECK (urgency IN ('NORMAL', 'URGENT', 'CRITICAL')),
    CHECK (status  IN ('OPEN', 'FULFILLED', 'CLOSED', 'EXPIRED'))
);
CREATE INDEX idx_request_status ON blood_request (status, bg_id);
-- the same patient cannot have two open requests for the same blood group at one hospital
CREATE UNIQUE INDEX one_open_request ON blood_request (hospital_id, patient_name, bg_id) WHERE (status = 'OPEN');

CREATE TABLE request_pledge (              -- M:N DONOR - BLOOD_REQUEST
    request_id    INT NOT NULL,
    donor_id      INT NOT NULL,
    status        VARCHAR(10) NOT NULL DEFAULT 'CONTACTED',
    contacted_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at  TIMESTAMP,
    donated_at    TIMESTAMP,
    PRIMARY KEY (request_id, donor_id),
    FOREIGN KEY (request_id) REFERENCES blood_request(request_id) ON DELETE CASCADE,
    FOREIGN KEY (donor_id)   REFERENCES donor(donor_id),
    CHECK (status IN ('CONTACTED', 'PLEDGED', 'DONATED', 'DECLINED')),
    CHECK (status <> 'DONATED' OR donated_at IS NOT NULL)
);

-- ---------- 20-22 : support tables for the website ----------
CREATE TABLE notification (                -- in-app messages for club members
    notification_id SERIAL PRIMARY KEY,
    member_id   INT NOT NULL,
    kind        VARCHAR(30)  NOT NULL,
    message     VARCHAR(300) NOT NULL,
    link        VARCHAR(100),
    ref_id      INT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at     TIMESTAMP,
    FOREIGN KEY (member_id) REFERENCES member(member_id)
);
CREATE INDEX idx_notification_member ON notification (member_id, read_at);

CREATE TABLE donor_reminder (              -- outgoing SMS / e-mail queue for donors
    reminder_id  SERIAL PRIMARY KEY,
    donor_id     INT NOT NULL,
    kind         VARCHAR(20)  NOT NULL,
    message      VARCHAR(300) NOT NULL,
    channel      VARCHAR(10)  NOT NULL DEFAULT 'SMS',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at      TIMESTAMP,
    FOREIGN KEY (donor_id) REFERENCES donor(donor_id),
    CHECK (kind IN ('ELIGIBLE_AGAIN', 'DRIVE_REMINDER', 'DRIVE_CANCELLED', 'DEFERRAL_RETURN', 'REQUEST_ALERT', 'THANK_YOU')),
    CHECK (channel IN ('SMS', 'EMAIL', 'WHATSAPP'))
);
CREATE INDEX idx_reminder_donor ON donor_reminder (donor_id, sent_at);
CREATE INDEX idx_reminder_pending ON donor_reminder (created_at) WHERE (sent_at IS NULL);   -- the send queue

CREATE TABLE activity_log (
    log_id     SERIAL PRIMARY KEY,
    member_id  INT,
    action     VARCHAR(30) NOT NULL,
    entity     VARCHAR(30),
    entity_id  INT,
    details    TEXT,
    logged_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (member_id) REFERENCES member(member_id)
);
CREATE INDEX idx_activity_member ON activity_log (member_id, logged_at);
