CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS "user" (
    index SERIAL PRIMARY KEY,
    id VARCHAR(50) UNIQUE NOT NULL,
    password TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_history (
    history_id SERIAL PRIMARY KEY,
    die_serial_number VARCHAR(100) NOT NULL,
    stack_count INTEGER NOT NULL DEFAULT 4,
    place_completion_times TIMESTAMP[] NOT NULL DEFAULT '{}',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    status VARCHAR(20) DEFAULT 'START'
);

ALTER TABLE work_history
    ADD COLUMN IF NOT EXISTS stack_count INTEGER NOT NULL DEFAULT 4;

ALTER TABLE work_history
    ADD COLUMN IF NOT EXISTS place_completion_times TIMESTAMP[]
    NOT NULL DEFAULT '{}';

UPDATE work_history
SET stack_count = substring(
    die_serial_number FROM '^HBM-([0-9]{1,2})L-'
)::INTEGER
WHERE stack_count = 4
  AND die_serial_number ~ '^HBM-([0-9]{1,2})L-'
  AND substring(
      die_serial_number FROM '^HBM-([0-9]{1,2})L-'
  )::INTEGER BETWEEN 4 AND 16;

CREATE TABLE IF NOT EXISTS user_logs (
    log_id BIGSERIAL PRIMARY KEY,
    user_index INT REFERENCES "user"(index) ON DELETE CASCADE,
    action_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS robot_error_logs (
    log_id SERIAL PRIMARY KEY,
    error_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_level VARCHAR(20) NOT NULL, -- WARN, FATAL
    error_code VARCHAR(50),
    detail TEXT,
    history_id INT REFERENCES work_history(history_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vision_align_logs (
    align_id SERIAL PRIMARY KEY,
    history_id INT REFERENCES work_history(history_id) ON DELETE CASCADE,
    process_step VARCHAR(20) NOT NULL, -- PICK, PLACE
    camera_type VARCHAR(50) NOT NULL, -- MACRO, MICRO_TL 등
    offset_x FLOAT DEFAULT 0.0,
    offset_y FLOAT DEFAULT 0.0,
    offset_theta FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_work_history_start_time
    ON work_history(start_time DESC);

CREATE INDEX IF NOT EXISTS idx_work_history_archive_cutoff
    ON work_history ((COALESCE(end_time, start_time)))
    WHERE status IN ('DONE', 'FAIL', 'STOP');

CREATE INDEX IF NOT EXISTS idx_robot_error_logs_error_time
    ON robot_error_logs(error_time DESC);

CREATE INDEX IF NOT EXISTS idx_robot_error_logs_history_id
    ON robot_error_logs(history_id);

CREATE INDEX IF NOT EXISTS idx_vision_align_logs_created_at
    ON vision_align_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vision_align_logs_history_id
    ON vision_align_logs(history_id);
"""
